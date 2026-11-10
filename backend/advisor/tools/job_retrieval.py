import re
import asyncio
import hashlib
import heapq
import os
from pathlib import Path
from functools import lru_cache

import httpx

from ..config import JobRAGConfig, get_job_rag_config
from ..runtime import LightRAGStartupError, ensure_lightrag
from ..schemas.job import JobAnalysisInput, JobSource


class JobRetrievalError(RuntimeError):
    """可安全展示给调用方的检索错误，不携带密钥或服务器原始错误正文。"""


@lru_cache(maxsize=16)
def _local_candidates(path_text, modified, target, question, limit):
    """Bounded lexical recall from the same original JD export; never classifies a requirement."""
    from artifacts.research.job_graph import iter_job_documents

    target = re.sub(r"工程师|实习生|开发|方向|高级|资深|招聘|算法|[（）()、，,与和]", " ", target)
    terms = list(dict.fromkeys(term.casefold() for term in re.findall(r"[A-Za-z][A-Za-z0-9.+-]*|[\u4e00-\u9fff]{2,}", target)))
    if not terms:
        return []
    best = []
    for document in iter_job_documents(Path(path_text)):
        content = document.text
        title = content.splitlines()[0].partition("：")[2].casefold()
        body = content.casefold()
        title_hits = sum(term in title for term in terms)
        body_hits = sum(term in body for term in terms)
        if not title_hits and body_hits < min(2, len(terms)):
            continue
        # A specific title match dominates incidental mentions in unrelated descriptions.
        score = title_hits * 12 + body_hits
        candidate = (score, -document.index, document.index, content, document.document_id)
        if len(best) < limit:
            heapq.heappush(best, candidate)
        elif candidate[:2] > best[0][:2]:
            heapq.heapreplace(best, candidate)
    return [{"chunk_id": "local-jd-" + hashlib.sha256(content.encode("utf-8")).hexdigest()[:32],
             "file_path": Path(path_text).as_posix() + f"#record={record}", "reference_id": "local_export",
             "content": f"招聘记录内部键：{identifier}\n{content}"}
            for _, _, record, content, identifier in sorted(best, reverse=True)]


def local_job_candidates(request, limit=3):
    path = Path(os.environ.get("JOB_JD_SOURCE_PATH") or Path(__file__).resolve().parents[3] / "job_descriptions.txt")
    if not path.is_file():
        return []
    try:
        return _local_candidates(str(path.resolve()), path.stat().st_mtime_ns, request.target_role, request.question, limit)
    except (OSError, ValueError):
        # An unavailable local export does not discard valid graph results.
        return []


class LightRAGJobRetriever:
    def __init__(self, settings: JobRAGConfig | None = None, *, transport=None):
        self.settings = settings or get_job_rag_config()
        self.transport = transport

    async def retrieve(self, request: JobAnalysisInput) -> dict:
        headers = {"X-API-Key": self.settings.api_key} if self.settings.api_key else {}
        try:
            async with httpx.AsyncClient(
                base_url=self.settings.base_url + "/", headers=headers,
                timeout=self.settings.timeout, trust_env=False, transport=self.transport,
            ) as client:
                # 放在检索入口：直接在其他 Python 代码里调用 Agent 也能自动启动。
                await ensure_lightrag(client, self.settings)
                response = await client.post("query/data", json={
                    "query": request.retrieval_query(), "mode": request.mode,
                    "top_k": request.top_k, "chunk_top_k": request.chunk_top_k,
                    "max_entity_tokens": 2000, "max_relation_tokens": 2000,
                    "max_total_tokens": 12000, "enable_rerank": False,
                    "include_references": True,
                })
                response.raise_for_status()
                raw = response.json()
            no_results = (
                raw.get("status") == "failure"
                and raw.get("metadata", {}).get("failure_reason") == "no_results"
            )
            if raw.get("status") != "success" and not no_results:
                raise JobRetrievalError("LightRAG 未成功完成检索，请查看 LightRAG 服务日志")
            data = raw["data"]
            sources, seen = [], set()
            for chunk in data.get("chunks", []):
                if not chunk.get("content", "").strip():
                    continue
                source = JobSource.model_validate(chunk)
                if source.chunk_id not in seen:
                    seen.add(source.chunk_id)
                    sources.append(source.model_dump())
            # Supplement semantic misses with a few original records, then let the Agent
            # assess actual responsibilities. This is recall, not a relevance verdict.
            local = await asyncio.to_thread(local_job_candidates, request, min(3, request.chunk_top_k))
            graph_paths = {source["file_path"] for source in sources}
            local = [source for source in local if source["file_path"] not in graph_paths]
            sources = [*local, *sources]
            # 限制条数时保留整个 chunk，避免在岗位要求中间硬切文本。
            returned_count = len(sources)
            sources = sources[:request.chunk_top_k]
            record_paths = {
                source["file_path"] for source in sources
                # 后续导入可以使用绝对路径或另一份 TXT，不限定原始文件名。
                if re.fullmatch(r".+\.txt#record=\d+", source["file_path"], flags=re.IGNORECASE)
            }
            return {
                "sources": sources,
                "scope": {
                    "workspace": self.settings.workspace, "mode": request.mode,
                    "chunk_count": len(sources), "retrieved_chunk_count": returned_count,
                    "jd_record_count": len(record_paths),
                    "unidentified_source_count": sum(
                        source["file_path"] not in record_paths for source in sources
                    ),
                    "local_export_candidates": sum(source["reference_id"] == "local_export" for source in sources),
                    "retrieval_methods": ["lightrag", "bounded_local_export"] if local else ["lightrag"],
                    "entity_count": len(data.get("entities", [])),
                    "relationship_count": len(data.get("relationships", [])),
                    "description": "仅本次检索样本；JD 数按 record 来源去重，不代表全库或招聘市场统计。",
                    "completeness": "保留接口返回的 chunk；是否覆盖某条完整 JD 取决于导入时的分块方式。",
                },
            }
        except JobRetrievalError:
            raise
        except LightRAGStartupError as error:
            raise JobRetrievalError(str(error)) from error
        except httpx.HTTPStatusError as error:
            raise JobRetrievalError(f"LightRAG 接口返回 HTTP {error.response.status_code}") from error
        except httpx.TimeoutException as error:
            raise JobRetrievalError("LightRAG 检索超时，请检查服务或调整 LIGHTRAG_TIMEOUT") from error
        except httpx.RequestError as error:
            raise JobRetrievalError("无法连接 LightRAG，请先启动 job_graph.py serve --background") from error
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise JobRetrievalError("LightRAG 返回的数据格式不兼容，请检查 /health 与 /query/data 接口") from error

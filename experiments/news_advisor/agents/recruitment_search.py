import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool
from pydantic import model_validator

from ..prompt.recruitment_search import RECRUITMENT_SEARCH_PROMPT
from ..schemas.recruitment_search import RecruitmentSearchInput, RecruitmentSearchResult
from ..tools.search import read_news_article, search_web
from ..tools.wechat import read_wechat_article, search_wechat_recruitment
from ..utils.evidence import copy_source_quote
from .base import BaseAgent


def _requested_cohort(year: str, request: str) -> bool:
    if re.search(rf"(?<!\d){re.escape(year)}(?!\d)", request):
        return True
    if len(year) == 4:
        return bool(re.search(rf"(?<!\d){year[-2:]}\s*届", request))
    return bool(re.search(rf"(?<!\d)\d{{2}}{year}\s*(?:届|年毕业)", request))


def _record_source(prepared: dict, item: dict, origin: str, read: bool) -> dict | None:
    aliases = [value for value in (item.get("article_id"), item.get("requested_url"), item.get("url"), item.get("resolved_url")) if value]
    if not aliases:
        return None
    source_id = next((prepared["_source_keys"][key] for key in aliases if key in prepared["_source_keys"]), None)
    source_id = source_id or f"S{len(prepared['_sources']) + 1}"
    source = prepared["_sources"].setdefault(source_id, {"source_id": source_id, "origin": origin})
    for key in aliases:
        prepared["_source_keys"][key] = source_id
    values = {
        "url": item.get("resolved_url") or item.get("url"), "title": item.get("title"),
        "publisher": item.get("account") or item.get("source"), "published_at": item.get("published_at"),
        "published_at_source": item.get("published_at_source") or "search_index",
    }
    if source.get("published_at_source") == "article_metadata" and values["published_at_source"] != "article_metadata":
        values.pop("published_at")
        values.pop("published_at_source")
    source.update({key: value for key, value in values.items() if value is not None and value != ""})
    if read or source.get("read_state") not in {"read", "image_only"}:
        read_state = "preview"
        if read:
            read_state = "image_only" if item.get("status") == "image_only" else "read"
        source.update(content=item.get("content", item.get("content_preview", item.get("summary", ""))),
                      read_state=read_state)
    for field in ("limitations", "truncated", "image_count", "image_urls", "links", "url_is_temporary", "publisher_verified", "recruitment_status"):
        if field in item:
            source[field] = item[field]
    return source


def _validate_findings(analysis: RecruitmentSearchResult, prepared: dict) -> None:
    errors = []
    if len(analysis.findings) > prepared["request"]["limit"]:
        errors.append("findings 超出用户指定的 limit")
    if prepared["request"]["days"] is not None and analysis.intent.days != prepared["request"]["days"]:
        errors.append("intent.days 必须保留显式传入的时间范围")
    user_request = "\n".join([
        prepared["request"]["request"],
        *(item["answer"] for item in prepared["request"]["clarifications"]),
    ])
    for cohort in analysis.intent.graduation_cohorts:
        years = re.findall(r"(?<!\d)\d{2,4}(?!\d)", cohort)
        if years and not all(_requested_cohort(year, user_request) for year in years):
            errors.append("用户未指定该毕业届别，intent.graduation_cohorts 应留空；文章中的届别只写在结果说明中")
    seen = set()
    for finding in analysis.findings:
        source = prepared["_sources"].get(finding.source_id)
        if not source:
            errors.append(f"来源不存在：{finding.source_id}")
            continue
        if finding.source_id in seen:
            errors.append(f"同一来源重复推荐：{finding.source_id}")
        seen.add(finding.source_id)
        if source["read_state"] not in {"read", "image_only"}:
            errors.append(f"{finding.source_id} 尚未读取原文，请先调用读取工具")
        original = source.get("title", "") + "\n" + source.get("content", "")
        for index, quote in enumerate(finding.evidence_quotes):
            copied = copy_source_quote(quote, original)
            if copied is None:
                errors.append(f"{finding.source_id} 的引文不是原文：{quote!r}")
            else:
                finding.evidence_quotes[index] = copied
        if finding.match_status == "matches_request":
            if source["read_state"] == "image_only":
                errors.append(f"{finding.source_id} 仅有图片，需标为 needs_confirmation")
            if analysis.intent.days is not None:
                published = source.get("published_at")
                if source.get("published_at_source") != "article_metadata" or not published:
                    errors.append(f"{finding.source_id} 日期未从原文核实，需标为 needs_confirmation")
                else:
                    instant = datetime.fromisoformat(published)
                    now = datetime.fromisoformat(prepared["analysis_date"])
                    if instant.tzinfo is None or not now - timedelta(days=analysis.intent.days) <= instant <= now + timedelta(minutes=5):
                        errors.append(f"{finding.source_id} 不在请求的时间窗口内")
    runs = prepared["_tool_runs"]
    if analysis.outcome not in {"needs_clarification"} and not runs:
        errors.append("尚未调用真实工具，不能生成搜索结论")
    if analysis.outcome == "no_match" and not any(run["status"] in {"ok", "empty", "partial", "image_only"} for run in runs):
        errors.append("工具全部访问失败，应使用 unavailable，不应声称没有匹配信息")
    if analysis.outcome == "no_match":
        read_any = any(source["read_state"] in {"read", "image_only"} for source in prepared["_sources"].values())
        empty_search = any(run["tool"].startswith("search_") and run["status"] == "empty" for run in runs)
        if prepared["_budget_exhausted"] or not (read_any or empty_search):
            errors.append("候选原文尚未核实或工具预算耗尽，应继续读取或使用 unavailable，不能当作没有匹配信息")
    if errors:
        raise ValueError("；".join(errors))


class RecruitmentSearchAgent(BaseAgent):
    """输入 request 自然语言需求；默认只搜索公众号，可选择 web 或 all。"""

    name = "recruitment_search"
    system_prompt = RECRUITMENT_SEARCH_PROMPT

    def __init__(self, model, *, use_tools=True, max_model_calls=5, max_tool_calls=8):
        super().__init__(model, use_tools=use_tools, max_model_calls=max_model_calls)
        if not 1 <= max_tool_calls <= 20:
            raise ValueError("max_tool_calls 必须为 1—20")
        self.max_tool_calls = max_tool_calls

    def prepare(self, payload: dict) -> dict:
        return {
            "request": RecruitmentSearchInput.model_validate(payload).model_dump(),
            "analysis_date": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
            "default_days": 30, "max_tool_calls": self.max_tool_calls,
            "_sources": {}, "_source_keys": {}, "_tool_runs": [], "_budget_exhausted": False,
        }

    def make_inputs(self, prepared: dict):
        return super().make_inputs({key: value for key, value in prepared.items() if not key.startswith("_")})

    def get_tools(self, prepared: dict) -> list:
        channel = prepared["request"]["channel"]
        tools = []
        if channel in {"wechat", "all"}:
            tools.extend([search_wechat_recruitment, read_wechat_article])
        if channel in {"web", "all"}:
            tools.extend([search_web, read_news_article])

        def track(raw_tool):
            async def run(config: RunnableConfig, **arguments):
                if len(prepared["_tool_runs"]) >= self.max_tool_calls:
                    prepared["_budget_exhausted"] = True
                    return {"status": "execution_limit", "error": "工具调用预算已用尽，请基于已有证据输出并说明限制"}
                arguments = raw_tool.args_schema.model_validate(arguments).model_dump()
                if raw_tool.name.startswith("search_"):
                    arguments["limit"] = min(arguments.get("limit", 5), prepared["request"]["limit"], 5)
                if raw_tool.name == "read_wechat_article":
                    arguments["max_chars"] = min(arguments.get("max_chars", 16000), 16000)
                if raw_tool.name == "search_wechat_recruitment" and prepared["request"]["days"] is not None:
                    arguments["days"] = prepared["request"]["days"]
                if raw_tool.name == "search_wechat_recruitment" and arguments.get("company") == arguments.get("query"):
                    arguments["company"] = ""  # 企业条件已在 query 内，避免重复关键词压缩召回。
                record = {"tool": raw_tool.name, "arguments": arguments, "status": "running"}
                prepared["_tool_runs"].append(record)
                if raw_tool.name.startswith("search_"):
                    years = re.findall(r"(?<!\d)(\d{2,4})\s*届", arguments.get("query", ""))
                    user_request = "\n".join([
                        prepared["request"]["request"],
                        *(item["answer"] for item in prepared["request"]["clarifications"]),
                    ])
                    if any(not _requested_cohort(year, user_request) for year in years):
                        record.update(status="invalid_scope", error="用户没有指定该毕业届别，不应自行加上届别过滤；请简化查询")
                        return {**record, "sources": []}
                try:
                    result = await raw_tool.ainvoke(arguments, config=config)
                    if not isinstance(result, dict):
                        result = {"status": "error", "error": "工具返回格式错误"}
                except Exception as error:
                    result = {"status": "error", "error": f"工具调用失败：{type(error).__name__}"}
                record.update(status=result.get("status", "error"), error=result.get("error"))
                read = raw_tool.name in {"read_wechat_article", "read_news_article"}
                origin = "wechat" if "wechat" in raw_tool.name else "web"
                items = ([result] if read and result.get("status") in {"ok", "image_only"} else [] if read
                         else result.get("items", []) + result.get("undated_items", []))
                sources = [_record_source(prepared, item, origin, read) for item in items]
                sources = [source for source in sources if source]
                record["source_ids"] = [source["source_id"] for source in sources]
                return {
                    "status": record["status"], "error": record["error"], "sources": [
                        {key: value for key, value in source.items() if key not in {"image_urls", "links"}}
                        for source in sources
                    ], "failures": result.get("failures", []), "limitations": result.get("limitations", []),
                }

            return StructuredTool.from_function(
                coroutine=run, name=raw_tool.name, args_schema=raw_tool.args_schema,
                description=raw_tool.description + "\n返回真实 source_id；整理结果前请读取原文，再引用该 source_id。本 Agent 单篇最多读取16000字符。",
            )

        return [track(raw_tool) for raw_tool in tools]

    def get_output_schema(self, prepared: dict):
        class GroundedRecruitmentSearch(RecruitmentSearchResult):
            @model_validator(mode="after")
            def verify_sources(self):
                _validate_findings(self, prepared)
                return self

        return GroundedRecruitmentSearch

    async def arun(self, payload: dict, config: RunnableConfig | None = None) -> dict:
        prepared = self.prepare(payload)
        if not self.use_tools:
            return {"agent": self.name, "status": "retrieval_error", "data": {}, "error": "已禁用工具，无法核实招聘信息"}
        result = await self._arun_prepared(prepared, config=config)
        result.update(sources=list(prepared["_sources"].values()), tool_runs=prepared["_tool_runs"])
        if result["status"] == "ok":
            limitations = result["data"]["limitations"]
            limitations.append("仅本次检索与读取结果；近期发文不等于招聘仍开放，公众号身份及用户任职资格未自动核验。")
            if prepared["_budget_exhausted"]:
                limitations.append(f"已达到本轮 {self.max_tool_calls} 次工具调用上限，检索覆盖可能不完整。")
            for run in prepared["_tool_runs"]:
                if run["status"] not in {"ok", "empty", "image_only"}:
                    limitations.append(f"{run['tool']}：{run['status']}；{run.get('error') or '检索或读取不完整'}")
            result["data"]["limitations"] = list(dict.fromkeys(limitations))
        return result

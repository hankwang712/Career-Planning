import re

from langchain_core.runnables import RunnableConfig

from ..prompt.job_analysis import JOB_ANALYSIS_PROMPT
from ..schemas.job import JobAnalysis, JobAnalysisInput
from ..tools.job_retrieval import JobRetrievalError, LightRAGJobRetriever
from .base import BaseAgent


def verify_job_evidence(data: dict, sources: list[dict]) -> list[str]:
    """核对来源及逐字引文；语义是否充分支持结论仍需人工/后续评估。"""
    normalize = lambda text: re.sub(r"\s+", "", text)
    originals = {source["chunk_id"]: normalize(source["content"]) for source in sources}
    errors = []
    analysis = JobAnalysis.model_validate(data)
    for group in (analysis.findings, analysis.related_roles):
        for item in group:
            for evidence in item.evidence:
                original = originals.get(evidence.chunk_id)
                if original is None:
                    errors.append(f"引用了未检索到的 chunk：{evidence.chunk_id}")
                elif normalize(evidence.quote) not in original:
                    errors.append(f"引文不是对应 chunk 的原文：{evidence.chunk_id}")
    return list(dict.fromkeys(errors))


class JobAnalysisAgent(BaseAgent):
    name = "job_analysis"
    system_prompt = JOB_ANALYSIS_PROMPT

    def __init__(self, model, *, retriever=None, use_tools=True, max_model_calls=5):
        super().__init__(model, use_tools=use_tools, max_model_calls=max_model_calls)
        self.retriever = retriever if retriever is not None else LightRAGJobRetriever()

    def prepare(self, payload: dict) -> dict:
        inputs = dict(payload)
        retrieval = inputs.pop("_retrieval")
        # 模型只需引用短编号，避免复制长哈希时重复或漏字；不改变真实来源。
        model_retrieval = {
            **retrieval,
            "sources": [
                {**source, "chunk_id": f"JD{index}"}
                for index, source in enumerate(retrieval["sources"], 1)
            ],
        }
        return {"request": JobAnalysisInput.model_validate(inputs).model_dump(), "retrieval": model_retrieval}

    def get_output_schema(self, prepared: dict):
        return JobAnalysis

    async def arun(self, payload: dict, config: RunnableConfig | None = None) -> dict:
        # 外部请求不允许直接注入 _retrieval；证据必须来自实际检索。
        request = JobAnalysisInput.model_validate(payload)
        if not self.use_tools:
            return {"agent": self.name, "status": "retrieval_error", "data": {}, "error": "已禁用工具，无法检索 JD"}
        try:
            retrieval = await self.retriever.retrieve(request)
        except JobRetrievalError as error:
            return {"agent": self.name, "status": "retrieval_error", "data": {}, "error": str(error)}
        if not retrieval["sources"]:
            result = self.format_result()
        else:
            result = await super().arun({**request.model_dump(), "_retrieval": retrieval}, config=config)
            if result["status"] == "ok":
                source_ids = {
                    f"JD{index}": source["chunk_id"]
                    for index, source in enumerate(retrieval["sources"], 1)
                }
                for item in result["data"]["findings"] + result["data"]["related_roles"]:
                    for evidence in item["evidence"]:
                        evidence["chunk_id"] = source_ids.get(evidence["chunk_id"], evidence["chunk_id"])
                errors = verify_job_evidence(result["data"], retrieval["sources"])
                if errors:
                    result.update(status="validation_failed", data={}, error="；".join(errors))
        # 保存于本次返回值，不写实例状态，避免并发请求混用证据。
        result.update(sources=retrieval["sources"], scope=retrieval["scope"])
        return result

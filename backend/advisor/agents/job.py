import re
import json

from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import merge_configs
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from pydantic import Field, model_validator, ValidationError

from ..prompt.job_analysis import JOB_ANALYSIS_PROMPT
from ..schemas.job import JobAnalysis, JobAnalysisInput, JobSourceAssessment, JobFinding
from ..tools.job_retrieval import JobRetrievalError, LightRAGJobRetriever
from ..utils.evidence import copy_source_quote
from ..utils.job_grounding import verify_job_grounding, requirement_source_ids, source_location_conflicts, split_mixed_requirements
from ..telemetry import AgentMetrics
from .base import BaseAgent


def verify_job_evidence(data: dict, sources: list[dict], *, require_assessments=False) -> list[str]:
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
                    errors.append(f"引用了未检索到的 chunk：{evidence.chunk_id}，请使用本次 sources 的编号")
                elif normalize(evidence.quote) not in original:
                    errors.append(f"引文不是对应 chunk 的连续原文：{evidence.chunk_id}，错误引文：{evidence.quote!r}；请直接复制该来源的连续片段")
    for item in analysis.source_assessments:
        original = originals.get(item.chunk_id)
        if original is None or normalize(item.quote) not in original:
            errors.append(f"来源相关性判断必须引用对应来源的真实连续职责原文：{item.chunk_id}")
    errors.extend(verify_job_grounding(analysis.model_dump(), sources, require_assessments=require_assessments))
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
        model_retrieval["location_conflicts"] = source_location_conflicts(model_retrieval["sources"])
        return {"request": JobAnalysisInput.model_validate(inputs).model_dump(), "retrieval": model_retrieval}

    def get_output_schema(self, prepared: dict):
        sources = prepared["retrieval"]["sources"]
        originals = {source["chunk_id"]: source["content"] for source in sources}

        class GroundedJobAnalysis(JobAnalysis):
            source_assessments: list[JobSourceAssessment] = Field(min_length=1,
                description="必须逐条覆盖本次所有来源的职责相关性，不能遗漏")
            @model_validator(mode="after")
            def check_quotes(self):
                for item in self.findings + self.related_roles:
                    for evidence in item.evidence:
                        copied = copy_source_quote(evidence.quote, originals.get(evidence.chunk_id, ""))
                        if copied is not None:
                            evidence.quote = copied
                for item in self.source_assessments:
                    copied = copy_source_quote(item.quote, originals.get(item.chunk_id, ""))
                    if copied is not None:
                        item.quote = copied
                self.findings = [JobFinding.model_validate(item) for item in split_mixed_requirements(
                    [item.model_dump() for item in self.findings])]
                errors = verify_job_evidence(self.model_dump(), sources, require_assessments=True)
                if errors:
                    raise ValueError("；".join(errors))
                return self

        # 在结构化输出阶段反馈错误，复用已有调用次数限制，避免校验后直接丢弃整份分析。
        return GroundedJobAnalysis

    async def _arun_prepared(self, prepared, config=None):
        """No tools are needed after retrieval; use explicit JSON repair instead of tool-call loops."""
        schema = self.get_output_schema(prepared)
        metrics = AgentMetrics()
        contract = json.dumps(schema.model_json_schema(mode="validation"), ensure_ascii=False)
        messages = [SystemMessage(content=self.system_prompt + "\n直接返回符合以下Schema的JSON对象，不调用工具或使用Markdown围栏：\n" + contract),
                    HumanMessage(content=json.dumps(prepared, ensure_ascii=False))]
        attempts = min(3, self.max_model_calls)
        result = None
        for attempt in range(1, attempts + 1):
            try:
                response = await self.model.bind(response_format={"type": "json_object"}).ainvoke(
                    messages, config=merge_configs(config, {"callbacks": [metrics]}))
            except Exception as error:
                result = self.format_result(error=error)
                break
            content = response.content
            if isinstance(content, list):
                content = "".join(block if isinstance(block, str) else block.get("text", "") for block in content if isinstance(block, (str, dict)))
            elif not isinstance(content, str):
                content = ""
            fenced = re.fullmatch(r"\s*```(?:json)?\s*([\s\S]*?)\s*```\s*", content)
            if fenced:
                content = fenced[1]
            if (response.response_metadata or {}).get("finish_reason") == "length":
                detail = "输出被截断。请精简条目，保留每个来源的相关性审查与全部必填字段。"
            else:
                try:
                    draft = schema.model_validate_json(content)
                except ValidationError as error:
                    detail = "；".join(str(item["msg"]) for item in error.errors(include_input=False, include_url=False, include_context=False)[:6])
                else:
                    result = self.format_result(draft)
                    break
            result = {"agent": self.name, "status": "validation_failed", "data": {}, "error": detail}
            if attempt < attempts:
                messages.extend([AIMessage(content=content), HumanMessage(content="请修正下列校验问题后返回完整JSON，保留原文限定和证据，不以邻近岗位补造门槛：\n" + detail)])
        result["execution"] = {**metrics.summary(), "output_mode": "validated_json", "attempts": attempt,
                               "model": getattr(self.model, "model_name", None) or getattr(self.model, "model", None)}
        return result

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
                for item in result["data"].get("source_assessments", []):
                    item["chunk_id"] = source_ids.get(item["chunk_id"], item["chunk_id"])
                errors = verify_job_evidence(result["data"], retrieval["sources"], require_assessments=True)
                if errors:
                    result.update(status="validation_failed", rejected_data=result["data"], data={}, error="；".join(errors))
        # 保存于本次返回值，不写实例状态，避免并发请求混用证据。
        result.update(sources=retrieval["sources"], scope=retrieval["scope"])
        if result["status"] == "ok":
            usable = requirement_source_ids(result["data"])
            result["scope"].update(requirement_source_ids=usable,
                                  relevant_requirement_source_count=len(usable),
                                  evidence_status="available" if usable else "insufficient_related_evidence")
            conflicts = source_location_conflicts(retrieval["sources"])
            result["scope"]["location_conflicts"] = conflicts
            for conflict in conflicts:
                note = (f"来源城市元数据为{conflict['metadata_city']}，但岗位正文明确写“{conflict['quote']}”；"
                        "地点存在冲突，按具体岗位向招聘方核实，不能统一视为同一城市岗位。")
                if note not in result["data"]["limitations"]:
                    result["data"]["limitations"].append(note)
            relevant = [source for source in retrieval["sources"] if source["chunk_id"] in usable]
            if relevant:
                companies = list(dict.fromkeys(match[1].strip() for source in relevant
                    if (match := re.search(r"^企业[：:]\s*([^\n]+)", source["content"], re.M))))
                note = (f"本次核心要求仅由{len(relevant)}条相关样本支持"
                        + ("（" + "、".join(companies) + "）" if companies else "")
                        + "；其中的学历、经验和行业场景条件不能推广为整个目标方向的统一门槛。")
                result["data"]["limitations"].append(note)
                if all("自动驾驶" in source["content"] for source in relevant) and "自动驾驶" not in request.target_role:
                    result["data"]["limitations"].append(
                        "本次直接相关样本集中在自动驾驶场景，不能据此覆盖其他行业的同方向岗位或判断整个方向的进入资格。")
        return result

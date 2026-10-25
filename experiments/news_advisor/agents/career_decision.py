import re
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.runnables import RunnableConfig
from pydantic import ValidationError, model_validator

from ..prompt.career_decision import CAREER_DECISION_PROMPT
from ..schemas.career_decision import CareerDecision, CareerDecisionInput, CareerTarget
from ..schemas.job import JobAnalysis, JobSource
from ..utils.evidence import copy_source_quote
from ..utils.dates import resume_date_context
from .base import BaseAgent


def _prepare_target(target: CareerTarget, index: int) -> tuple[dict, list[dict]]:
    """复用上游数据结构，隔离各目标的来源编号；不重复验证上游分析引文。"""
    result = target.job_analysis
    job = JobAnalysis.model_validate(result.get("data")).model_dump()
    originals = [JobSource.model_validate(source) for source in result["sources"]]
    source_map = {source.chunk_id: f"T{index}JD{number}" for number, source in enumerate(originals, 1)}
    if len(source_map) != len(originals):
        raise ValueError(f"目标 {target.target_id} 的岗位来源 chunk_id 重复")
    if target.target_type == "job":
        paths = {source.file_path for source in originals if source.file_path != "unknown_source"}
        if len(paths) > 1:
            raise ValueError(f"目标 {target.target_id} 包含多条岗位来源，请拆分或使用 direction")
    for finding in job["findings"] + job["related_roles"]:
        for evidence in finding["evidence"]:
            if evidence["chunk_id"] not in source_map:
                raise ValueError(f"目标 {target.target_id} 引用了不存在的岗位来源")
            evidence["chunk_id"] = source_map[evidence["chunk_id"]]
    sources = [{
        "source_id": source_map[source.chunk_id], "kind": "job", "target_id": target.target_id,
        "content": source.content, "chunk_id": source.chunk_id, "file_path": source.file_path,
    } for source in originals]
    return {
        "target_id": target.target_id, "title": target.title, "target_type": target.target_type,
        "job_analysis": job, "source_ids": list(source_map.values()),
    }, sources


def verify_career_decision(data: dict, prepared: dict) -> list[str]:
    """只检查引用、关联和具体岗位的硬条件；不替模型决定能力取舍。"""
    analysis = CareerDecision.model_validate(data)
    errors = []
    sources = {source["source_id"]: source for source in prepared["sources"]}
    originals = {key: re.sub(r"\s+", " ", source["content"]).strip() for key, source in sources.items()}
    targets = {target["target_id"]: target for target in prepared["targets"]}
    decisions = {item.target_id: item.decision for item in analysis.assessments}
    if len(decisions) != len(analysis.assessments) or set(decisions) != set(targets):
        errors.append("assessments 必须各一次覆盖全部可用 target_id")

    checks = {}
    for assessment in analysis.assessments:
        for check in assessment.checks:
            if check.check_id in checks:
                errors.append(f"check_id 重复：{check.check_id}")
            checks[check.check_id] = assessment.target_id
            for side, citations in (("job", check.job_evidence), ("candidate", check.candidate_evidence)):
                for citation in citations:
                    source = sources.get(citation.source_id)
                    if source is None:
                        errors.append(f"引用了不存在的 source_id：{citation.source_id}")
                        continue
                    if side == "job":
                        valid = source["kind"] == "job" and source.get("target_id") == assessment.target_id
                    else:
                        valid = source["kind"] in {"resume", "additional_evidence", "preferences"}
                    if not valid:
                        errors.append(f"{assessment.target_id}/{check.check_id} 的证据来源归属错误：{citation.source_id}")
                    if re.sub(r"\s+", " ", citation.quote).strip() not in originals[citation.source_id]:
                        prefix = copy_source_quote(citation.quote[:12], source["content"])
                        offset = source["content"].find(prefix) if prefix else -1
                        context = source["content"][offset:offset + 350] if offset >= 0 else "请重新定位该来源"
                        errors.append(f"{assessment.target_id}/{check.check_id} 的引文不是 {citation.source_id} 的连续原文，错误引文：{citation.quote!r}；请直接复制。原文上下文：{context!r}")

        if targets.get(assessment.target_id, {}).get("target_type") == "job":
            hard = [check for check in assessment.checks
                    if check.kind == "hard_condition" and check.importance == "required"]
            if any(check.status == "confirmed_gap" for check in hard):
                if assessment.decision != "not_recommended":
                    errors.append(f"目标 {assessment.target_id} 有明确硬条件冲突，当前不应推荐")
            elif any(check.status != "supported" for check in hard) and assessment.decision == "recommended":
                errors.append(f"目标 {assessment.target_id} 有待确认的硬条件，应保留条件性结论")

    for action in analysis.next_actions:
        if checks.get(action.check_id) != action.target_id:
            errors.append(f"行动未关联同一目标下的有效 check：{action.check_id}")
        elif action.kind == "apply" and decisions[action.target_id] in {"not_recommended", "insufficient_information"}:
            errors.append(f"目标 {action.target_id} 当前结论不支持投递行动")
    return list(dict.fromkeys(errors))


class CareerDecisionAgent(BaseAgent):
    """接收学生原文和 1—5 个目标的岗位 Agent 结果，不重复读取文件或检索岗位。"""

    name = "career_decision"
    system_prompt = CAREER_DECISION_PROMPT

    def prepare(self, payload: dict) -> dict:
        request = CareerDecisionInput.model_validate(payload)
        analysis_date = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        sources = [
            {"source_id": source_id, "kind": kind, "content": content}
            for source_id, kind, content in (
                ("R1", "resume", request.raw_resume),
                ("U1", "additional_evidence", request.additional_evidence),
                ("P1", "preferences", request.preferences),
            ) if content
        ]
        targets, limitations = [], []
        document = request.resume_analysis.get("document") or {}
        if document.get("status") == "partial":
            limitations.append("简历仅部分读取成功，未读取内容不能用于否定学生能力。")
        limitations.extend(document.get("warnings") or [])
        if request.resume_analysis and request.resume_analysis.get("status") != "ok":
            limitations.append("简历 Agent 未成功完成诊断，当前仅依据提供的学生原文判断。")

        for index, target in enumerate(request.targets, 1):
            result = target.job_analysis
            if result.get("status") != "ok" or not result.get("sources"):
                limitations.append(f"目标 {target.target_id} 的岗位分析未成功或缺少原文，本次不形成匹配结论。")
                continue
            prepared_target, job_sources = _prepare_target(target, index)
            targets.append(prepared_target)
            sources.extend(job_sources)
            limitations.append(f"目标 {target.target_id} 仅依据本次岗位样本，不代表整个方向或当前仍在招聘。")
            scope = result.get("scope") or {}
            # 上游模型的局限可能只适用于岗位分析阶段；保留在 job_analysis 中供复核，
            # 不将“该阶段未接收简历”等说明直接升级为本次决策的事实性限制。
            details = [
                scope[field] for field in ("description", "completeness") if scope.get(field)
            ]
            limitations.extend(f"目标 {target.target_id}：{detail}" for detail in details)
        return {
            "analysis_date": analysis_date.isoformat(), "date_context": resume_date_context(request.raw_resume, analysis_date),
            "question": request.question, "sources": sources, "targets": targets,
            # 简历质量诊断不是能力事实来源；隔离其未经验证的推断，避免错误意见被下游复述。
            "resume_analysis": {"status": request.resume_analysis.get("status"), "document": document},
            "input_limitations": list(dict.fromkeys(limitations)),
        }

    def should_run(self, prepared: dict) -> bool:
        return bool(prepared["targets"]) and any(
            source["kind"] in {"resume", "additional_evidence"} for source in prepared["sources"]
        )

    def get_output_schema(self, prepared: dict):
        originals = {source["source_id"]: source["content"] for source in prepared["sources"]}

        class GroundedCareerDecision(CareerDecision):
            @model_validator(mode="after")
            def check_evidence(self):
                for assessment in self.assessments:
                    for check in assessment.checks:
                        for evidence in check.job_evidence + check.candidate_evidence:
                            copied = copy_source_quote(evidence.quote, originals.get(evidence.source_id, ""))
                            if copied is not None:
                                evidence.quote = copied
                errors = verify_career_decision(self.model_dump(), prepared)
                if errors:
                    raise ValueError("；".join(errors))
                return self

        return GroundedCareerDecision

    async def arun(self, payload: dict, config: RunnableConfig | None = None) -> dict:
        prepared = self.prepare(payload)
        result = await self._arun_prepared(prepared, config=config)
        result.update(sources=prepared["sources"], input_limitations=prepared["input_limitations"])
        if result["status"] == "ok":
            try:
                errors = verify_career_decision(result["data"], prepared)
            except ValidationError as error:
                errors = [str(error)]
            if errors:
                result.update(status="validation_failed", data={}, error="；".join(errors))
            else:
                result["data"]["limitations"] = list(dict.fromkeys(
                    prepared["input_limitations"] + result["data"].get("limitations", [])
                ))
        return result

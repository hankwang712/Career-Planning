import re
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.runnables import RunnableConfig
from pydantic import ValidationError, model_validator

from ..prompt.career_decision import CAREER_DECISION_PROMPT
from ..schemas.career_decision import CareerDecision, CareerDecisionInput, CareerTarget
from ..schemas.job import JobAnalysis, JobSource
from ..utils.evidence import copy_source_quote
from ..utils.dates import education_timeline_context, resume_date_context, verify_education_timeline_claims
from .base import BaseAgent


def recruitment_context(result: dict) -> dict:
    """只传递已读取来源中的真实引文，不将招聘线索混入岗位/学生事实。"""
    status = result.get("status", "skipped")
    data = result.get("data") or {}
    context = {"status": status, "outcome": data.get("outcome"), "findings": [], "limitations": []}
    if status == "skipped":
        return context
    context["limitations"].append("招聘搜索仅提供核实线索，不证明岗位仍开放或用户符合任职条件。")
    if status != "ok":
        context["limitations"].append("招聘搜索未提供可用结果，不能据此判断没有招聘机会。")
        return context
    sources = {source["source_id"]: source for source in result.get("sources", [])
               if source.get("source_id") and source.get("read_state") == "read"}
    omitted = False
    for finding in data.get("findings", []):
        source = sources.get(finding.get("source_id"))
        if source is None:
            omitted = True
            continue
        original = str(source.get("title", "")) + "\n" + str(source.get("content", ""))
        quotes = [copy_source_quote(quote, original) for quote in finding.get("evidence_quotes", [])]
        if not quotes or any(quote is None for quote in quotes):
            omitted = True
            continue
        context["findings"].append({
            "reference": "search:" + source["source_id"], "title": source.get("title", ""),
            "url": source.get("url", ""), "published_at": source.get("published_at"),
            "match_status": finding.get("match_status", "needs_confirmation"),
            "evidence_quotes": quotes, "unverified_conditions": finding.get("unverified_conditions", []),
        })
    if omitted:
        context["limitations"].append("部分招聘线索只有摘要、图片或引文无法核对，未作为决策材料。")
    context["limitations"].extend(data.get("limitations", []))
    return context


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
    errors = verify_education_timeline_claims(data, "\n".join(
        source["content"] for source in prepared["sources"] if source["kind"] == "resume"))
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
    for request in analysis.evidence_requests:
        if request.target_id not in targets:
            errors.append(f"补查请求引用了不可用的 target_id：{request.target_id}")
    return list(dict.fromkeys(errors))


class CareerDecisionAgent(BaseAgent):
    """接收学生原文和 1—5 个目标的岗位 Agent 结果，不重复读取文件或检索岗位。"""

    name = "career_decision"
    system_prompt = CAREER_DECISION_PROMPT

    @staticmethod
    def prepare(payload: dict) -> dict:
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
        sources.extend({
            "source_id": f"U{index + 2}", "kind": "additional_evidence",
            "content": item.answer, "question": item.question,
        } for index, item in enumerate(request.clarifications))
        targets, limitations = [], []
        document = request.resume_analysis.get("document") or {}
        if document.get("status") == "partial":
            limitations.append("简历仅部分读取成功，未读取内容不能用于否定学生能力。")
        limitations.extend(document.get("warnings") or [])
        if request.resume_analysis and request.resume_analysis.get("status") != "ok":
            limitations.append("简历 Agent 未成功完成诊断，当前仅依据提供的学生原文判断。")
        recruitment = recruitment_context(request.recruitment_search)
        limitations.extend(recruitment["limitations"])
        for feedback in request.evidence_feedback:
            if feedback.outcome != "added":
                outcome = "未取得新证据" if feedback.outcome == "no_new_evidence" else "暂不可用"
                limitations.append(f"目标 {feedback.target_id} 的岗位补查{outcome}，相关条件仍需核实：{feedback.question}")

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
            "education_timeline": education_timeline_context(request.raw_resume),
            "question": request.question, "sources": sources, "targets": targets,
            "recruitment_context": recruitment,
            "evidence_rounds_remaining": request.evidence_rounds_remaining,
            "evidence_feedback": [item.model_dump() for item in request.evidence_feedback],
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

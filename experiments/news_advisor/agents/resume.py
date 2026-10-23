"""简历内容诊断；有明确意向时增加方向分析，有 JD 时才逐项匹配。"""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import AliasChoices, ConfigDict, Field

from ..prompt.resume_analysis import RESUME_ANALYSIS_PROMPT
from .base import BaseAgent
from .resume_schema import JobAnalysis, Record, ResumeReview, RoleAnalysis


class ResumeInput(Record):
    # 文档读取由 tools.document.read_document 负责，将其 markdown 作为 raw_resume 传入。
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)

    raw_resume: str = ""
    target_role: str = ""
    job_description: str = ""
    candidate_level: str = ""
    structured_resume: dict | None = None
    additional_evidence: str = Field(
        default="", validation_alias=AliasChoices("additional_evidence", "project_evidence"),
    )
    input_warnings: list[str] = Field(default_factory=list)


OUTPUT_SCHEMAS = {
    "resume_review": ResumeReview,
    "role_alignment": RoleAnalysis,
    "job_match": JobAnalysis,
}
UNSPECIFIED = {"无", "暂无", "未定", "待定", "不限", "不确定", "都可以", "无明确意向", "未提供", "none", "null"}


def explicit_resume_role(raw_resume: str) -> str:
    """只读取明确标注的求职意向，不从项目技术栈推断用户意愿。"""
    for line in raw_resume.splitlines():
        line = re.sub(r"^\s*(?:#{1,6}\s*|[-*]\s+)", "", line).replace("**", "").strip()
        match = re.fullmatch(r"(?:求职意向|意向岗位|目标岗位|应聘岗位|应聘职位|求职岗位)\s*[:：]\s*(.+)", line)
        if match:
            return match[1].strip()
    return ""


class ResumeAnalysisAgent(BaseAgent):
    """继承 BaseAgent 的异步调用、调用次数限制和统一结果封装。

    用法：await ResumeAnalysisAgent(model).arun({"raw_resume": markdown, ...})。
    可选输入见 ResumeInput；additional_evidence 是补充的真实经历事实，需注明归属。
    兼容原输入名 project_evidence；输出 experiences 包含实习、课程、科研、项目和活动等经历。
    read_document 返回 partial 时，应同时传入 input_warnings，避免把读取缺失当成简历遗漏。
    不进行外部岗位检索，也不根据关键词数量推算能力或录用概率。
    """

    name = "resume_analysis"
    system_prompt = RESUME_ANALYSIS_PROMPT

    def prepare(self, payload: dict) -> dict:
        prepared = ResumeInput.model_validate(payload).model_dump()
        role = prepared["target_role"] or explicit_resume_role(prepared["raw_resume"])
        if role.lower() in UNSPECIFIED:
            role = ""
        prepared["target_role"] = role
        prepared["mode"] = (
            "job_match" if prepared["job_description"] else
            "role_alignment" if role else "resume_review"
        )
        prepared["analysis_date"] = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        return prepared

    def should_run(self, prepared: dict) -> bool:
        # 只有岗位或补充材料而没有简历正文时，不让模型虚构一份诊断。
        return bool(prepared["raw_resume"])

    def get_output_schema(self, prepared: dict):
        return OUTPUT_SCHEMAS[prepared["mode"]]

    def validate_result(self, draft, prepared: dict):
        if draft is None:
            return None
        schema = self.get_output_schema(prepared)
        # 第二次校验带入原始输入，验证所有来源引用。请求上下文不保存在实例上，支持并发复用。
        return schema.model_validate(
            draft.model_dump(exclude_computed_fields=True), context=prepared,
        )

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.runnables import RunnableConfig

from ..prompt.resume_analysis import RESUME_ANALYSIS_PROMPT
from ..resume_rubric import DEFAULT_EXPERIENCE_WEIGHTS, EXPERIENCE_WEIGHTS, RESUME_WEIGHTS
from ..schemas.resume import ResumeAnalysis, ResumeInput
from ..tools.document import read_document
from ..utils.dates import resume_date_context
from .base import BaseAgent


UNSPECIFIED = {"无", "暂无", "未定", "待定", "不限", "不确定", "都可以", "无明确意向", "未提供", "none", "null"}


def explicit_resume_role(raw_resume: str) -> str:
    """只读取明确标注的求职意向，不从项目技术栈推断用户意愿。"""
    lines = [
        re.sub(r"^\s*(?:#{1,6}\s*|[-*]\s+)", "", line).replace("**", "").strip()
        for line in raw_resume.splitlines() if line.strip()
    ]
    section_titles = {"教育经历", "教育背景", "工作经历", "实习经历", "项目经历", "科研成果", "技能能力", "个人信息"}
    for index, line in enumerate(lines):
        match = re.fullmatch(r"(?:求职意向|意向岗位|目标岗位|应聘岗位|应聘职位|求职岗位)(?:\s*[:：]\s*(.*))?", line)
        if match:
            if match[1]:
                return match[1].strip()
            # PDF/OCR 常将“求职意向”标题和具体岗位分在两行。
            if index + 1 < len(lines) and lines[index + 1] not in section_titles:
                return lines[index + 1]
    return ""


class ResumeAnalysisAgent(BaseAgent):
    """文件输入先调用 read_document，再沿用 BaseAgent 执行分析。

    传 file_path 自动读取为 Markdown；也可直接传 raw_resume，二者择一。
    可选输入见 ResumeInput；additional_evidence 是补充的真实经历事实，需注明归属。
    只执行简历质量诊断；意向岗位及 JD 用于确定内容重点，不执行岗位匹配。
    读取警告自动送入分析，document 返回读取状态和页数信息。
    不进行外部岗位检索，也不根据关键词数量推算能力或录用概率。
    """

    name = "resume_analysis"
    system_prompt = RESUME_ANALYSIS_PROMPT

    def document_error(self, message: str, document: dict | None = None) -> dict:
        return {
            "agent": self.name, "status": "document_error",
            "data": {}, "error": message, "document": document or {},
        }

    async def arun(self, payload: dict, config: RunnableConfig | None = None) -> dict:
        request = ResumeInput.model_validate(payload)
        if not request.file_path:
            result = await super().arun(request.model_dump(), config=config)
            if request.document:
                result["document"] = request.document
            return result
        if not self.use_tools:
            return self.document_error("已禁用工具，无法读取简历文件")

        try:
            document = await read_document.ainvoke(
                {"file_path": request.file_path, "max_pages": request.max_pages},
                config=config,
            )
        except Exception as error:
            return self.document_error(f"文档工具调用失败：{type(error).__name__}")

        metadata = {
            key: document[key] for key in
            ("file_path", "status", "warnings", "processed_pages", "total_pages")
            if key in document
        }
        markdown = document.get("markdown", "").strip()
        if document.get("status") not in {"ok", "partial"} or not markdown:
            return self.document_error(document.get("error") or "文档未返回有效正文", metadata)

        warnings = list(document.get("warnings", []))
        if document["status"] == "partial":
            warnings.append("简历仅部分读取成功，分析仅覆盖已读取内容")
        metadata["warnings"] = list(dict.fromkeys(warnings))
        # 读取完成后，根据实际正文确定分析重点。
        inputs = request.model_dump()
        inputs.update(
            file_path="", raw_resume=markdown,
            _document=metadata,
        )
        result = await super().arun(inputs, config=config)
        result["document"] = metadata
        return result

    def prepare(self, payload: dict) -> dict:
        inputs = dict(payload)
        document = inputs.pop("_document", inputs.get("document", {}))
        prepared = ResumeInput.model_validate(inputs).model_dump()
        role = prepared["target_role"] or explicit_resume_role(prepared["raw_resume"])
        if role.lower() in UNSPECIFIED:
            role = ""
        prepared["target_role"] = role
        prepared["document"] = document
        prepared["additional_evidence"] = "\n".join(filter(None, [
            prepared["additional_evidence"],
            *(item["answer"] for item in prepared["clarifications"]),
        ]))
        prepared["rubrics"] = {
            "resume": RESUME_WEIGHTS,
            "experiences": EXPERIENCE_WEIGHTS,
            "default_experience": DEFAULT_EXPERIENCE_WEIGHTS,
        }
        analysis_date = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        prepared["analysis_date"] = analysis_date.isoformat()
        prepared["date_context"] = resume_date_context(prepared["raw_resume"], analysis_date)
        return prepared

    def should_run(self, prepared: dict) -> bool:
        # 只有岗位或补充材料而没有简历正文时，不让模型虚构一份诊断。
        return bool(prepared["raw_resume"])

    def get_output_schema(self, prepared: dict):
        return ResumeAnalysis


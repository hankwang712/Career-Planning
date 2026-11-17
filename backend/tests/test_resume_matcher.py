"""简历与岗位文本的结构化、Markdown 安全转换，以及简历文件读取的容错。"""
import pytest

from services.resume import matcher

JOB_TEXT = """高级Python后端工程师
公司：星河科技
工作地点：上海
岗位职责：
1. 负责后端服务设计与开发
2. 优化数据库性能
任职要求：
- 3年以上Python经验，熟悉Django、Flask
- 熟悉MySQL、Redis
"""


def test_job_text_is_structured():
    job = matcher.build_job_payload_from_text(JOB_TEXT)
    assert job["jobTitle"] == "高级Python后端工程师"
    assert job["companyProfile"]["companyName"] == "星河科技"
    assert job["location"]["city"] == "上海"
    assert job["keyResponsibilities"] and job["qualifications"]
    keywords = " ".join(map(str, job["extractedKeywords"]))
    assert "Python" in keywords


@pytest.mark.parametrize("text", ["", "   ", "\n\n", None])
def test_empty_job_text_yields_an_empty_payload(text):
    assert matcher.build_job_payload_from_text(text) == {}


def test_markdown_conversion_escapes_scripts_and_unsafe_links():
    html = matcher.markdown_to_safe_html("# 标题\n\n<script>alert(1)</script> **粗体** [点我](javascript:alert(1))")
    assert "<script" not in html
    assert "<h2>" in html and "<strong>" in html
    assert 'href="javascript' not in html.lower()


def test_markdown_conversion_handles_lists_and_empty_input():
    assert "career-list-empty" in matcher.markdown_to_safe_html("")  # 空内容显示占位提示，而不是空白
    html = matcher.markdown_to_safe_html("- 一\n- 二")
    assert html.count("<li>") == 2


def test_markdown_code_blocks_are_escaped():
    html = matcher.markdown_to_safe_html("```\n<b>x</b>\n```")
    assert "&lt;b&gt;" in html and "<b>x</b>" not in html


def test_structured_resume_normalization_tolerates_garbage():
    for payload in (None, {}, {"candidate": "不是字典"}, {"skills": "不是列表"}):
        result = matcher.normalize_structured_resume(payload)
        assert isinstance(result, dict)


def test_structured_job_normalization_tolerates_garbage():
    for payload in (None, {}, {"jobTitle": 123}):
        assert isinstance(matcher.normalize_structured_job(payload), dict)


def test_matcher_state_reports_matched_and_missing_keywords():
    resume = matcher.normalize_structured_resume({
        "candidateName": "张三",
        "skills": {"technicalSkills": ["Python", "Django", "MySQL"]},
        "workExperience": [{"company": "示例公司", "role": "后端开发", "description": "使用 Django 开发接口"}],
    })
    job = matcher.normalize_structured_job(matcher.build_job_payload_from_text(JOB_TEXT))
    state = matcher.build_matcher_state(resume, job, "## 分析\n匹配度较高", JOB_TEXT)
    assert isinstance(state, dict) and state


def test_resume_text_payload_reads_docx(tmp_path):
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_paragraph("张三")
    document.add_paragraph("熟悉 Python 与 Django，负责过订单系统后端开发。")
    path = tmp_path / "resume.docx"
    document.save(path)
    payload = matcher.build_resume_text_payload(str(path), lambda *a: [], lambda *a: False, lambda *a: [])
    assert "Python" in payload["plain_text"]
    assert payload["analysis_meta"]["file_type"] == "docx" and payload["analysis_meta"]["ocr_used"] is False


def test_pdf_resume_falls_back_to_ocr_only_when_text_is_missing(tmp_path):
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"%PDF-1.4")
    ocr_calls = []

    def ocr(*args):
        ocr_calls.append(args)
        return [{"page_no": 1, "source": "ocr:chi_sim", "text": "扫描件识别出的简历正文，包含 Python 经验。"}]

    payload = matcher.build_resume_text_payload(str(path), lambda p: [], lambda pages: not pages, ocr)
    assert ocr_calls and payload["analysis_meta"]["ocr_used"] is True
    assert "扫描件" in payload["plain_text"]

    ocr_calls.clear()
    text_pages = [{"page_no": 1, "source": "pypdf", "text": "文字版简历正文，熟悉 Django 与 MySQL，有三年后端经验。"}]
    payload = matcher.build_resume_text_payload(str(path), lambda p: text_pages, lambda pages: not pages, ocr)
    assert not ocr_calls and payload["analysis_meta"]["ocr_used"] is False


def test_resume_text_payload_rejects_unsupported_files(tmp_path):
    path = tmp_path / "resume.exe"
    path.write_bytes(b"MZ")
    with pytest.raises(ValueError, match="PDF 或 DOCX"):
        matcher.build_resume_text_payload(str(path), lambda *a: [], lambda *a: False, lambda *a: [])

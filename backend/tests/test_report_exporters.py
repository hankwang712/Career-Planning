"""报告导出：Markdown 规整、HTML 渲染，以及 Word / PDF 真的能生成可打开的文件。"""
import io
import sys
import zipfile

import pytest

from services.report import exporters

MARKDOWN = "# 职业发展报告\n\n## 方向建议\n\n| 岗位 | 匹配度 |\n|---|---|\n| 后端工程师 | 高 |\n\n- 补强系统设计\n- 准备项目讲述\n"


@pytest.mark.parametrize("raw,expected", [("a<br>b<br/>c<BR />d", "a\nb\nc\nd"), ("没有换行标签", "没有换行标签"), ("", "")])
def test_br_tags_become_newlines(raw, expected):
    assert exporters.normalize_br_tags_in_markdown(raw) == expected


def test_html_export_contains_title_table_and_list():
    html = exporters.render_markdown_export_html(MARKDOWN, title="我的报告")
    assert "<title>我的报告" in html
    assert "<table" in html and "后端工程师" in html
    assert html.count("<li>") == 2


def test_html_export_does_not_let_scripts_through():
    html = exporters.render_markdown_export_html("正文 <script>alert(1)</script>", title="t")
    assert "<script>alert(1)</script>" not in html


def test_docx_export_is_a_valid_word_document():
    data = exporters.export_markdown_to_docx_bytes(MARKDOWN)
    assert data[:2] == b"PK"
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert "word/document.xml" in archive.namelist()
        xml = archive.read("word/document.xml").decode("utf-8")
    assert "职业发展报告" in xml and "后端工程师" in xml


def test_docx_export_can_be_reopened():
    docx = pytest.importorskip("docx")
    document = docx.Document(io.BytesIO(exporters.export_markdown_to_docx_bytes(MARKDOWN)))
    assert any("方向建议" in paragraph.text for paragraph in document.paragraphs)
    assert len(document.tables) == 1


def test_pdf_export_produces_a_pdf():
    data = exporters.export_markdown_to_pdf_bytes(MARKDOWN, title="我的报告")
    assert data.startswith(b"%PDF-") and len(data) > 1000


def test_report_markdown_rendering_skips_empty_sections():
    report = {"sections": {"summary": {"title": "概览", "content": "内容"}}}
    rendered = exporters.render_report_markdown(report)
    assert isinstance(rendered, str)


# ---------- Word 导出的兜底：没有 docx_mcp 时仍然能导出 ----------

RICH_MARKDOWN = """# 职业发展报告

## 核心结论

适合走**后端工程**方向，详见 [官网](https://example.com) 和 [危险链接](javascript:alert(1))。

### 行动计划

1. 补强系统设计
2. 准备项目讲述

- 要点一
  - 子要点

| 岗位 | 匹配度 |
|---|---|
| 后端工程师 | 高 |

> 引用说明

## 简历诊断

问题：简历缺少量化结果。

```
print("code")
```
"""


@pytest.fixture()
def without_docx_mcp(monkeypatch):
    monkeypatch.setattr(exporters, "_resolve_docx_python", lambda conda_env: None)


def open_docx(data):
    docx = pytest.importorskip("docx")
    return docx.Document(io.BytesIO(data))


def test_word_export_works_without_docx_mcp(without_docx_mcp):
    document = open_docx(exporters.export_markdown_to_docx_bytes(RICH_MARKDOWN))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "职业发展报告" in text and "补强系统设计" in text and "print(" in text
    assert len(document.tables) == 1
    assert [cell.text for cell in document.tables[0].rows[1].cells] == ["后端工程师", "高"]


def test_fallback_maps_markdown_structure_to_word_styles(without_docx_mcp):
    document = open_docx(exporters.export_markdown_to_docx_bytes(RICH_MARKDOWN))

    def style_of(fragment):
        # 导出前会给章节标题自动编号，所以按片段匹配
        return next(p.style.name for p in document.paragraphs if fragment in p.text)

    assert style_of("职业发展报告") == "Title"     # 版式处理把首个标题升为文档标题
    assert style_of("核心结论") == "Heading 1"     # 二级标题在报告里是章节标题
    assert style_of("行动计划") == "Heading 2"
    assert style_of("补强系统设计").startswith("List Number")
    assert style_of("要点一").startswith("List Bullet")


def test_fallback_keeps_inline_formatting_and_only_safe_links(without_docx_mcp):
    data = exporters.export_markdown_to_docx_bytes(RICH_MARKDOWN)
    document = open_docx(data)
    bold = [run.text for paragraph in document.paragraphs for run in paragraph.runs if run.bold]
    assert "后端工程" in bold
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        relations = archive.read("word/_rels/document.xml.rels").decode("utf-8")
        xml = archive.read("word/document.xml").decode("utf-8")
    assert "https://example.com" in relations
    assert "javascript:" not in relations and "javascript:" not in xml
    assert "危险链接" in xml  # 不安全链接只保留文字


def test_fallback_applies_the_report_layout(without_docx_mcp):
    document = open_docx(exporters.export_markdown_to_docx_bytes(RICH_MARKDOWN))
    note = next(paragraph for paragraph in document.paragraphs if paragraph.text.startswith("问题："))
    assert 'w:fill="FFF4F1"' in note._p.xml  # 提示块底色来自 docx_layout


def test_fallback_survives_empty_and_odd_input(without_docx_mcp):
    for text in ("", "只有一段文字", "| 不完整的表格 |", "```\n没有结束的代码块"):
        assert exporters.export_markdown_to_docx_bytes(text)[:2] == b"PK"


def test_fallback_embeds_only_local_images_from_the_export_directory(tmp_path):
    from PIL import Image
    from services.report.docx_fallback import convert_markdown_to_docx

    Image.new("RGB", (40, 20), "red").save(tmp_path / "chart.png")
    outside = tmp_path.parent / "outside.png"
    Image.new("RGB", (40, 20), "blue").save(outside)
    target = tmp_path / "out.docx"
    convert_markdown_to_docx(f"![图](./chart.png)\n\n![越界](../{outside.name})\n\n![远程](https://example.com/a.png)", target, base_dir=tmp_path)
    document = open_docx(target.read_bytes())
    assert len(document.inline_shapes) == 1
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "[图片：越界]" in text and "[图片：远程]" in text


def test_external_converter_failure_falls_back_instead_of_failing(monkeypatch):
    """docx_mcp 解释器存在但转换失败（例如缺包）时，导出仍然成功。"""
    monkeypatch.setattr(exporters, "_resolve_docx_python", lambda conda_env: sys.executable)  # 没有 docx_mcp
    document = open_docx(exporters.export_markdown_to_docx_bytes(RICH_MARKDOWN))
    assert len(document.tables) == 1

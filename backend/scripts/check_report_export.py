"""Offline PDF generation and authenticated download regression checks."""
from copy import deepcopy
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pymupdf as fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.report import exporters

with contextlib.redirect_stderr(io.StringIO()):
    import server


MARKDOWN = """# 职业规划报告

## 岗位证据与行动

保留**原文证据**，核实 Python 项目贡献。

| 任务 | 验收标准 |
| --- | --- |
| 完善 API | 独立运行并演示 |

- 核实岗位要求
- 保存项目证据

```python
print('project evidence')
```
"""


def pdf_text(data):
    with fitz.open(stream=data, filetype="pdf") as document:
        return "\n".join(page.get_text() for page in document)


class PdfChecks(unittest.TestCase):
    def test_chinese_tables_and_code_export_without_office_or_subprocess(self):
        with patch.object(exporters.subprocess, "run", side_effect=AssertionError("PDF must not launch Office")):
            data = exporters.export_markdown_to_pdf_bytes(MARKDOWN)
        self.assertTrue(data.startswith(b"%PDF-"))
        text = pdf_text(data)
        for value in ("职业规划报告", "原文证据", "独立运行并演示", "project evidence"):
            self.assertIn(value, text)
        self.assertNotIn("| ---", text)
        self.assertNotIn("**", text)

    def test_long_report_reaches_final_section_across_pages(self):
        markdown = "# 分页报告\n\n" + "\n\n".join(
            f"## 阶段 {index}\n\n" + "记录项目贡献、原始证据与下一步任务。" * 15 for index in range(40))
        markdown += "\n\n最终验收标记 END-OF-REPORT"
        data = exporters.export_markdown_to_pdf_bytes(markdown)
        with fitz.open(stream=data, filetype="pdf") as document:
            self.assertGreater(len(document), 1)
            self.assertLess(len(document), 200)
            self.assertIn("END-OF-REPORT", document[-1].get_text())

    def test_empty_report_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "正文为空"):
            exporters.export_markdown_to_pdf_bytes(" \n")

    def test_utf8_child_error_is_readable_instead_of_failing_gbk_decode(self):
        run = exporters.subprocess.run
        def child(command, **kwargs):
            # Emit the bytes which broke Windows' default GBK reader, without invoking Office.
            code = "import sys; sys.stderr.buffer.write(bytes.fromhex('e68aa5e5918ae8bdace68da2e5a4b1e8b4a5')); sys.exit(1)"
            return run([sys.executable, "-c", code], **kwargs)
        with patch.object(exporters, "_resolve_docx_python", return_value=sys.executable), \
                patch.object(exporters.subprocess, "run", side_effect=child):
            with self.assertRaisesRegex(RuntimeError, "报告转换失败"):
                exporters.export_markdown_to_docx_bytes("# Synthetic report")

    def test_local_report_image_is_embedded(self):
        with tempfile.TemporaryDirectory() as directory:
            image_dir = Path(directory)
            pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 40), False)
            pixmap.clear_with(180)
            pixmap.save(str(image_dir / "evidence.png"))
            with patch.object(exporters, "REPORT_IMAGE_DIR", image_dir):
                data = exporters.export_markdown_to_pdf_bytes("# 图文报告\n\n![项目证据](/static/img/report/evidence.png)")
            with fitz.open(stream=data, filetype="pdf") as document:
                self.assertEqual(len(document[0].get_images()), 1)

    def test_unplaceable_content_stops_instead_of_creating_endless_pages(self):
        with patch.object(fitz, "Story") as story:
            story.return_value.place.return_value = (1, fitz.Rect())
            with self.assertRaisesRegex(ValueError, "无法分页"):
                exporters.export_markdown_to_pdf_bytes(MARKDOWN)
            self.assertEqual(story.return_value.place.call_count, 1)

    def test_html_is_sanitized_and_images_cannot_read_arbitrary_paths(self):
        html = exporters.render_markdown_export_html(
            '<script>alert(1)</script>\n\n![private](file:///private.txt)\n\n'
            '![remote](https://example.invalid/image.png)\n\n'
            '<img src="/static/img/report/../../private.png" onerror="alert(1)">\n\n'
            '| 任务 | 结果 |\n| --- | --- |\n| 核实 | 完成 |')
        self.assertNotIn("<script", html)
        self.assertNotIn("onerror", html)
        self.assertNotIn('src="file:', html)
        self.assertNotIn('src="https:', html)
        self.assertNotIn('src="/static/img/report/../', html)
        self.assertIn("<table>", html)


class ExportApiChecks(unittest.TestCase):
    def setUp(self):
        self.owner = "export-check"
        self.bundle = {"meta": {"report_id": "report-export-check", "title": "职业规划报告",
                                 "generated_at": "2026-11-07 12:00:00", "version": "1"},
                       "report_document": {"markdown": MARKDOWN}}
        self.patches = [
            patch.object(server._auth, "current_user", lambda: {"username": self.owner} if self.owner else None),
            patch.object(server, "_read_career_report_bundle_by_id", lambda owner, report_id: deepcopy(self.bundle)),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.client = server.app.test_client()

    def test_pdf_download_has_valid_content_and_unicode_filename(self):
        response = self.client.get("/api/career-report/export?format=pdf&report_id=report-export-check")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertEqual(response.headers["X-Report-PDF-Engine"], "pymupdf")
        self.assertIn("attachment;", response.headers["Content-Disposition"])
        self.assertIn("filename*=UTF-8", response.headers["Content-Disposition"])
        self.assertIn("职业规划报告", pdf_text(response.data))

    def test_saved_edit_exports_its_own_text(self):
        with patch.object(server, "_read_career_report_snapshot", return_value={"snapshot_id": "edit-1"}), \
                patch.object(server, "_normalize_career_report_snapshot", return_value={"title": "编辑版本", "markdown": "# 编辑版本\n\n已保存的修改内容"}):
            response = self.client.get("/api/career-report/export?format=pdf&snapshot_id=edit-1")
        self.assertEqual(response.status_code, 200)
        self.assertIn("已保存的修改内容", pdf_text(response.data))
        self.assertNotIn("原文证据", pdf_text(response.data))

    def test_missing_report_and_expired_login_are_errors(self):
        self.bundle = None
        self.assertEqual(self.client.get("/api/career-report/export?format=pdf").status_code, 404)
        self.owner = None
        self.assertEqual(self.client.get("/api/career-report/export?format=pdf").status_code, 401)

    def test_generation_failure_returns_json_instead_of_invalid_pdf(self):
        with patch.object(server, "export_markdown_to_pdf_bytes", side_effect=ValueError("无法分页，请精简内容")), \
                self.assertLogs(server.app.logger, level="ERROR"):
            response = self.client.get("/api/career-report/export?format=pdf")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.mimetype, "application/json")
        self.assertIn("无法分页", response.json["message"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

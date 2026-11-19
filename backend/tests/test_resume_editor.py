from io import BytesIO
import json
from zipfile import ZipFile

import pymupdf as fitz
from PIL import Image

from services.resume import editor_document, pipeline


def test_rewrite_creates_only_a_temporary_copy_and_rejects_unsupported_claims(make_account, monkeypatch, tmp_path):
    from services.resume import rewrite

    account = make_account("resume-rewrite")
    route = "/api/resume-editor"
    skill_file = tmp_path / "resume_rewrite.md"
    skill_text = "# 改写规则\n\n使用 <FINAL_RESUME> 输出定稿。\n"
    skill_file.write_text(skill_text, encoding="utf-8", newline="\n")
    monkeypatch.setenv("RESUME_REWRITE_SKILL_PATH", str(skill_file))
    original = {"title": "基础简历", "style": "blue", "contact": {"name": "林晓", "email": "private@example.com"}, "sections": [
        {"title": "工作经历", "content": "### 订单开发组 2025.03\n- 使用 Python 编写订单脚本，整理对账记录\n- 配合维护已有接口并处理常见数据问题"},
        {"title": "教育经历", "content": "示例大学 | 本科 | 2022–2026"},
        {"title": "项目经历", "content": "论坛维护 | 维护成员 | 2023.06\n- 整理社区讨论与使用反馈"},
        {"title": "专业技能", "content": "Python、数据处理"},
    ]}
    saved = account.post(route + "/drafts", json=original).get_json()
    default = account.get(route + "/rewrite/settings").get_json()
    assert default["settings"]["skill"] == "resume_rewrite"
    assert default["skills"][0]["name"] == "简历改写"
    assert default["prompt"] == skill_text
    monkeypatch.setattr(rewrite.llm_env, "chat_runtime", lambda: ("https://model.invalid", "mock-key", "mock"))

    def model(*args, **kwargs):
        raw = args[3][0]["content"]
        assert "private@example.com" not in raw and "林晓" not in raw
        assert args[4] == skill_text
        assert "### 论坛维护 | 维护成员 | 2023.06" in raw
        return """<THINKING>仅用于测试过滤的文本</THINKING>
<FINAL_RESUME>
## 🏢 工作经历
### 订单开发组 2025.03
- 用 **Python** 编写订单脚本，整理对账记录
- 维护已有接口，处理常见数据问题
## 🚀 项目经历
## 🛠️ 核心技能
- 主导 Kubernetes 部署，效率提升 90%
## 🎓 教育背景
- 无关学校
</FINAL_RESUME>"""

    monkeypatch.setattr(rewrite, "call_markdown_chat", model)
    result = account.post(route + "/rewrite", json={"document": saved["document"], "job": {
        "title": "数据工程师", "description": "使用 Python 搭建订单数据管道",
    }}).get_json()
    assert [change["section"] for change in result["changes"]] == ["工作经历", "项目经历"]
    assert result["document"]["contact"] == saved["document"]["contact"]
    assert result["document"]["style"] == "blue"
    assert result["document"]["sections"][1] == saved["document"]["sections"][1]
    assert result["document"]["sections"][2]["content"] == ""
    assert result["document"]["sections"][3] == saved["document"]["sections"][3]
    assert "**Python**" in result["document"]["sections"][0]["content"]
    assert "THINKING" not in json.dumps(result)
    assert len(account.get(route + "/drafts").get_json()["drafts"]) == 1
    assert account.get(route + "/drafts/" + saved["id"]).get_json() == saved
    copied = account.post(route + "/drafts", json=result["document"]).get_json()
    assert copied["id"] != saved["id"]


def test_imported_resume_skill_is_account_scoped_and_selected(make_account, monkeypatch, tmp_path):
    from services.resume import rewrite

    owner = make_account("resume-skill")
    other = make_account("resume-skill-other")
    route = "/api/resume-editor/rewrite"
    path = tmp_path / "SKILL.md"
    path.write_text("---\nname: 精简条目\n---\n写明行为和结果。", encoding="utf-8")
    assert owner.post(route + "/skills", data={"location": str(path.parent)},
                      environ_overrides={"REMOTE_ADDR": "192.0.2.30"}).status_code == 403
    response = owner.post(route + "/skills", data={"location": str(path.parent)})
    settings = response.get_json()
    assert response.status_code == 200 and settings["skills"][1]["name"] == "精简条目"
    assert settings["settings"]["skill"] == settings["skills"][1]["id"]
    assert other.post(route + "/settings", json=settings["settings"]).status_code == 400
    assert owner.post(route + "/skills", data={"location": "https://example.com/SKILL.md"}).status_code == 400
    assert rewrite.github_request("https://github.com/org/repo/tree/main/skills/resume") == (
        "https://api.github.com/repos/org/repo/contents/skills/resume/SKILL.md", {"ref": "main"}, True,
    )
    monkeypatch.setattr(rewrite, "read_github", lambda _: b"---\nname: GitHub skill\n---\nUse concise lists.")
    result = owner.post(route + "/skills", data={"location": "https://github.com/org/repo"}).get_json()
    assert result["prompt"] == "Use concise lists."
    assert any(skill["id"] == result["settings"]["skill"] and skill["origin"] == "GitHub" for skill in result["skills"])
    uploaded = owner.post(route + "/skills", data={"skill_file": (BytesIO(b"Prefer short bullets."), "SKILL.md")}).get_json()
    assert uploaded["prompt"] == "Prefer short bullets."


def upload_text(account, text, ai="0"):
    return account.post("/api/resume-editor/import", data={"source": "text", "text": text, "use_ai": ai})


def test_import_classifies_sections_without_rewriting_text(make_account, monkeypatch):
    account = make_account("resume-import")
    monkeypatch.setattr(editor_document.llm_env, "chat_runtime", lambda: ("https://test.invalid", "key", "model"))
    sent = []

    def classify(*args, **kwargs):
        text = args[3][0]["content"]
        sent.append(text)
        return {"1": "项目经历", "2": "不存在的分区", "0": "个人总结"}

    monkeypatch.setattr(editor_document, "call_structured_chat", classify)
    response = upload_text(account, "姓名：韩青\n邮箱：private@example.com\n## 工作经验\n实现订单管理\n"
                           "## 实战案例\n为韩青完成迁移，咨询 13800138000\n## 证书\n普通话证书", "1")
    assert response.status_code == 200
    doc = response.get_json()["document"]
    assert doc["contact"]["email"] == "private@example.com"
    assert doc["sections"] == [
        {"title": "工作经历", "content": "实现订单管理"},
        {"title": "项目经历", "content": "为韩青完成迁移，咨询 13800138000"},
        {"title": "证书", "content": "普通话证书"},
    ]
    assert len(sent) == 1 and all(secret not in sent[0] for secret in ("韩青", "13800138000", "private@example.com"))
    assert account.get("/api/resume-editor/drafts").get_json() == {"drafts": []}


def test_scanned_image_uses_existing_ocr(make_account, monkeypatch):
    account = make_account("resume-scan")
    monkeypatch.setattr(pipeline, "_resolve_resume_ocr_lang", lambda: "chi_sim+eng")
    monkeypatch.setattr(pipeline, "_run_resume_ocr", lambda image, lang, *, keep_lines: "## 教育背景\n计算机科学")
    source = BytesIO()
    Image.new("RGB", (30, 30), "white").save(source, "PNG")
    source.seek(0)
    result = account.post("/api/resume-editor/import", data={"source": "file", "file": (source, "scan.png")})
    assert result.status_code == 200
    assert result.get_json()["ocr_used"]
    assert result.get_json()["document"]["sections"] == [{"title": "教育经历", "content": "计算机科学"}]


def test_current_source_pdf_import_preserves_headings(make_account, monkeypatch):
    account = make_account("resume-current")
    other = make_account("resume-no-file")
    with fitz.open() as source:
        page = source.new_page()
        page.insert_text((35, 45), "Work Experience\nImplemented a service API and maintained integration tests.")
        pdf = source.tobytes()
    monkeypatch.setattr(pipeline, "_ocr_pdf_pages", lambda *_args, **_kwargs: [])
    uploaded = account.post("/api/resume/upload", data={"file": (BytesIO(pdf), "existing.pdf")})
    assert uploaded.status_code == 200
    path = "/api/resume-editor/import"
    assert other.post(path, data={"source": "current"}).status_code == 400
    result = account.post(path, data={"source": "current"})
    assert result.status_code == 200
    assert result.get_json()["document"]["sections"] == [
        {"title": "工作经历", "content": "Implemented a service API and maintained integration tests."}
    ]


def test_saved_resume_is_editable_and_private(make_account):
    owner = make_account("resume-owner")
    stranger = make_account("resume-other")
    base = "/api/resume-editor/drafts"
    document = upload_text(owner, "## 工作经验\n编写接口").get_json()["document"]
    assert owner.client.post(base, json=document).status_code == 403
    created = owner.post(base, json=document)
    assert created.status_code == 201
    saved = created.get_json()
    path = f"{base}/{saved['id']}"
    assert stranger.get(path).status_code == 404
    assert stranger.put(path, json={"document": document, "revision": 1}).status_code == 404
    document["title"] = "后端求职简历"
    assert owner.put(path, json={"document": document, "revision": 1}).status_code == 200
    assert owner.put(path, json={"document": document, "revision": 1}).status_code == 409
    assert owner.get(path).get_json()["document"] == document
    assert owner.delete(path, json={"revision": 2}).status_code == 200


def test_export_keeps_chinese_text_and_matches_preview_pages(make_account):
    user = make_account("resume-export")
    doc = upload_text(user, "姓名：林晓\n## 工作经验\n负责自动化交付").get_json()["document"]
    root = "/api/resume-editor/render/"
    pdf = user.post(root + "pdf", json=doc)
    assert pdf.mimetype == "application/pdf"
    with fitz.open(stream=pdf.data, filetype="pdf") as pages:
        assert len(pages) == 1
        assert "林晓" in pages[0].get_text()
        assert "负责自动化交付" in pages[0].get_text()
    assert user.post(root + "image", json=doc).mimetype == "image/png"

    doc["sections"][0]["content"] = "\n".join(f"- 第 {index} 条工作记录" for index in range(125))
    preview = user.post(root + "auto", json=doc).get_json()
    assert preview["page_count"] == len(preview["images"]) > 1
    doc["layout"] = preview["layout"]
    images = user.post(root + "image", json=doc)
    assert images.mimetype == "application/zip"
    with ZipFile(BytesIO(images.data)) as pages:
        assert len(pages.namelist()) == preview["page_count"]
        assert pages.read("resume-01.png").startswith(b"\x89PNG")


def test_template_aligns_project_metadata_and_renders_markdown(make_account):
    account = make_account("resume-template")
    doc = {
        "contact": {"name": "林晓"},
        "extras": [{"label": "GitHub", "value": "demo-account"}],
        "sections": [{
            "title": "项目经历",
            "content": "WorkBench | Engineer | 2026\n- **Result:** [Repository](https://example.com/project)",
        }],
    }
    assert account.post("/api/resume-editor/drafts", json=doc).get_json()["document"]["extras"] == doc["extras"]
    response = account.post("/api/resume-editor/render/pdf", json=doc)
    assert response.status_code == 200
    with fitz.open(stream=response.data, filetype="pdf") as pdf:
        page = pdf[0]
        points = {word[4]: word[0] for word in page.get_text("words")}
        assert points["WorkBench"] < 60 and points["Engineer"] > 355 and points["2026"] > 515
        assert "**Result" not in page.get_text() and "demo-account" in page.get_text()
        assert any(link.get("uri") == "https://example.com/project" for link in page.get_links())


def test_pdf_import_uses_header_and_table_geometry_instead_of_flat_text(make_account):
    from pathlib import Path

    from services.user_state import _save_user_state, _user_upload_dir

    account = make_account("resume-pdf-layout")
    photo = BytesIO()
    Image.new("RGB", (45, 65), "#5591a2").save(photo, "JPEG")
    with fitz.open() as pdf:
        page = pdf.new_page(width=595, height=842)
        page.insert_text((275, 48), "Demo", fontsize=24)
        page.insert_text((36, 37), "求职意向", fontname="china-s")
        page.insert_text((36, 56), "AI Engineer")
        page.insert_text((36, 90), "13800138000")
        page.insert_text((207, 90), "resume@example.com")
        page.insert_image(fitz.Rect(513, 22, 558, 87), stream=photo.getvalue())
        page.insert_text((36, 112), "教育经历", fontname="china-s")
        page.insert_text((36, 130), "Demo University")
        page.insert_text((224, 130), "Computer Science")
        page.insert_text((490, 131), "2023-2027")
        page.insert_text((36, 160), "科研与项目经历", fontname="china-s")
        page.insert_text((36, 180), "Workshop")
        page.insert_text((392, 180), "Developer")
        page.insert_text((490, 181), "2025-2026")
        page.insert_text((36, 200), "Completed the project.")
        page.insert_text((36, 235), "技能能力", fontname="china-s")
        page.insert_text((36, 254), "Python")
        raw = pdf.tobytes()
    source = account.post("/api/resume-editor/import", data={"source": "file", "file": (BytesIO(raw), "sample.pdf")})
    assert source.status_code == 200
    doc = source.get_json()["document"]
    assert doc["contact"] == {"name": "Demo", "target": "AI Engineer", "phone": "13800138000", "email": "resume@example.com"}
    assert doc["photo"]
    assert [part["title"] for part in doc["sections"]] == ["教育经历", "项目经历", "专业技能"]
    assert "Demo University | Computer Science | 2023-2027" in doc["sections"][0]["content"]
    assert "Workshop | Developer | 2025-2026" in doc["sections"][1]["content"]
    path = Path(_user_upload_dir(account.email)) / "sample.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    _save_user_state(account.email, {"resume_profile": {"file_name": "sample.pdf", "storage_path": str(path)}})
    assert account.get("/api/career-report/resume-source").get_json()["source"]["targets"] == ["AI Engineer"]
    result = account.post("/api/resume-editor/render/pdf", json=doc)
    with fitz.open(stream=result.data, filetype="pdf") as pdf:
        assert len(pdf) == 1 and pdf[0].get_images()
        assert "resume@example.com" in pdf[0].get_text()

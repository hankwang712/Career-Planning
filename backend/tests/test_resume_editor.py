from io import BytesIO
from zipfile import ZipFile

import pymupdf as fitz
from PIL import Image

from services.resume import editor_document, pipeline


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
    result = account.post("/api/resume-editor/render/pdf", json=doc)
    with fitz.open(stream=result.data, filetype="pdf") as pdf:
        assert len(pdf) == 1 and pdf[0].get_images()
        assert "resume@example.com" in pdf[0].get_text()

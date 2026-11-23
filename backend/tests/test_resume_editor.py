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
    imported = next(skill for skill in settings["skills"] if skill["name"] == "精简条目")
    assert response.status_code == 200 and imported["builtin"] is False
    assert settings["settings"]["skill"] == imported["id"]
    assert owner.delete(route + "/skills/preset_tech_dense").status_code == 400
    after_del = owner.delete(route + "/skills/" + imported["id"])
    assert after_del.status_code == 200 and after_del.get_json()["settings"]["skill"] == "resume_rewrite"
    response = owner.post(route + "/skills", data={"location": str(path.parent)})
    settings = response.get_json()
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
    word = user.post(root + "docx", json=doc)
    assert word.status_code == 200
    assert word.mimetype == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    with ZipFile(BytesIO(word.data)) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
        assert "林晓" in xml and "负责自动化交付" in xml

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


def test_work_experience_entries_render_as_aligned_tables(make_account):
    account = make_account("resume-work-entry")
    doc = {
        "contact": {"name": "林晓"},
        "sections": [{
            "title": "工作经历",
            "content": "Acme Corp | Data Intern | 2025.03–2025.09\n- 整理订单数据\n\nBeta LLC | Backend Intern | 2024.06–2024.12\n- 维护接口",
        }],
    }
    response = account.post("/api/resume-editor/render/pdf", json=doc)
    assert response.status_code == 200
    with fitz.open(stream=response.data, filetype="pdf") as pdf:
        words = pdf[0].get_text("words")
        points = {word[4]: word[0] for word in words}
        assert points["Acme"] < 60 and points["Intern"] > 250
        assert any(word[4].startswith("2025.03") and word[0] > 450 for word in words)
        assert "整理订单数据" in pdf[0].get_text() and "维护接口" in pdf[0].get_text()


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


def test_skill_html_render_sanitizes_scripts_and_injects_photo(make_account, monkeypatch, tmp_path):
    from services.resume import rewrite

    account = make_account("resume-skill-html")
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text("# 视觉风格\n使用蓝色标题与浅色经历条。", encoding="utf-8")
    monkeypatch.setenv("RESUME_REWRITE_SKILL_PATH", str(skill_file))
    monkeypatch.setattr(rewrite.llm_env, "chat_runtime", lambda: ("https://model.invalid", "k", "m"))
    monkeypatch.setattr(
        rewrite,
        "call_markdown_chat",
        lambda *a, **k: (
            "```html\n<!doctype html><html><head><style>body{color:#111;}</style></head>"
            "<body onclick=\"alert(1)\"><script>alert(1)</script>"
            "<img src=\"{{PHOTO_DATA_URI}}\"><a href=\"javascript:evil()\">x</a>"
            "<h1>林晓</h1></body></html>\n```"
        ),
    )
    photo = BytesIO()
    Image.new("RGB", (45, 65), "#336699").save(photo, "JPEG")
    import base64
    doc = {
        "title": "技术履历",
        "contact": {"name": "林晓"},
        "photo": base64.b64encode(photo.getvalue()).decode("ascii"),
        "sections": [{"title": "项目经历", "content": "Demo | Owner | 2026\n- 实现核心模块"}],
    }
    resp = account.post("/api/resume-editor/render/skill-html", json={"document": doc})
    assert resp.status_code == 200
    html = resp.get_json()["html"]
    assert "<script" not in html.lower() and "onclick" not in html.lower() and "javascript:" not in html.lower()
    assert "data:image/jpeg;base64," in html and "@media print" in html
    docx_resp = account.post("/api/resume-editor/render/skill-docx", json={"html": html, "title": "技术履历"})
    assert docx_resp.status_code == 200
    assert docx_resp.mimetype == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    with ZipFile(BytesIO(docx_resp.data)) as archive:
        assert "林晓" in archive.read("word/document.xml").decode("utf-8")


def test_personalization_features_appearance_occupancy_polish_and_default(make_account, monkeypatch):
    import base64
    from services.resume import rewrite

    account = make_account("resume-personalize")
    photo = BytesIO()
    Image.new("RGB", (45, 65), "#224466").save(photo, "JPEG")
    photo_b64 = base64.b64encode(photo.getvalue()).decode("ascii")
    doc1 = {
        "title": "版本A", "style": "blue", "layout": "compact", "show_photo": False, "photo": photo_b64,
        "contact": {"name": "林晓"},
        "sections": [{"title": "项目经历", "content": "引擎 | 负责人 | 2025\n- 召回率提升 15%"}],
    }
    doc2 = {"title": "版本B", "contact": {"name": "林晓"}, "sections": [{"title": "专业技能", "content": "Python"}]}
    d1 = account.post("/api/resume-editor/drafts", json=doc1).get_json()
    d2 = account.post("/api/resume-editor/drafts", json=doc2).get_json()
    assert d1["document"]["show_photo"] is False
    # Hidden photo should not render in PDF
    pdf_resp = account.post("/api/resume-editor/render/pdf", json=d1["document"])
    with fitz.open(stream=pdf_resp.data, filetype="pdf") as pdf:
        assert not pdf[0].get_images()
    # Preview returns occupancy metrics
    prev = account.post("/api/resume-editor/render/preview", json=d1["document"]).get_json()
    assert prev["page_count"] == 1 and 0 < prev["fill_percent"] <= 100 and prev["overflow_lines"] == 0
    # Set default moves d1 to top of drafts list
    assert account.post(f"/api/resume-editor/drafts/{d1['id']}/set-default").status_code == 200
    assert account.get("/api/resume-editor/drafts").get_json()["drafts"][0]["id"] == d1["id"]
    # Polish entry works and guards against fabricated numbers
    monkeypatch.setattr(rewrite.llm_env, "chat_runtime", lambda: ("https://model.invalid", "k", "m"))
    monkeypatch.setattr(rewrite, "call_markdown_chat", lambda *a, **k: "- **核心模块：**优化检索链路，召回率提升 15%")
    ok = account.post("/api/resume-editor/polish-entry", json={
        "section": "项目经历", "name": "引擎", "role": "负责人", "content": "- 召回率提升 15%", "action": "star",
    })
    assert ok.status_code == 200 and "15%" in ok.get_json()["content"]
    monkeypatch.setattr(rewrite, "call_markdown_chat", lambda *a, **k: "- 召回率提升 99%")
    bad = account.post("/api/resume-editor/polish-entry", json={
        "section": "项目经历", "name": "引擎", "role": "负责人", "content": "- 召回率提升 15%", "action": "shorten",
    })
    assert bad.status_code == 502


def test_adaptive_font_scale_and_github_icon_links(make_account):
    account = make_account("resume-scale-gh")
    doc = {
        "title": "精简简历",
        "contact": {"name": "林晓", "target": "AI Agent 系统开发实习 | 多智能体与 RAG 开发"},
        "extras": [{"label": "GitHub", "value": "https://github.com/hankwang712"}],
        "sections": [
            {"title": "教育经历", "content": "北京邮电大学 | 计算机技术 | 2027.09 入学\n- GPA 4.71/5.00"},
            {"title": "项目经历", "content": "智航平台 [项目链接](https://github.com/hankwang712/Career-Planning) | 核心开发 | 2026.01–2026.06\n- 负责多智能体编排与混合检索落地。\n- 优化召回率提升 24%。"},
            {"title": "专业技能", "content": "- Python、LangGraph、FastAPI、SQLite"},
        ],
    }
    auto = account.post("/api/resume-editor/render/auto", json=doc).get_json()
    assert auto["page_count"] == 1
    assert auto["font_scale"] > 1.0
    doc["font_scale"] = auto["font_scale"]
    pdf_resp = account.post("/api/resume-editor/render/pdf", json=doc)
    assert pdf_resp.status_code == 200
    with fitz.open(stream=pdf_resp.data, filetype="pdf") as pdf:
        assert len(pdf) == 1
        uris = {link.get("uri") for link in pdf[0].get_links()}
        assert "https://github.com/hankwang712" in uris
        assert "https://github.com/hankwang712/Career-Planning" in uris
        # Both GitHub links should embed the inline Octocat icon image
        assert len(pdf[0].get_images()) >= 1
    # Word export must explicitly write fixed tblLayout and proportional gridCol widths so WPS/Word don't split 33/33/33
    docx_resp = account.post("/api/resume-editor/render/docx", json=doc)
    assert docx_resp.status_code == 200
    with ZipFile(BytesIO(docx_resp.data)) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
        assert 'w:tblLayout w:type="fixed"' in xml
        assert "智航平台" in xml


def test_privacy_shield_audit_backup_diagnostics_grill_and_jd_report(make_account):
    from services import db_backup, llm_audit, privacy_shield

    # 1. Privacy shield masks & restores phone/email/name
    raw = "我是王帅，手机 13800138000，邮箱 demo@example.com。"
    masked, pii_map = privacy_shield.mask_pii(raw, extra_names=("王帅",))
    assert "13800138000" not in masked and "demo@example.com" not in masked and "王帅" not in masked
    assert privacy_shield.unmask_pii(masked, pii_map) == raw

    # 2. LLM audit ledger records and summarizes
    llm_audit.record_usage("test-model", prompt_tokens=120, completion_tokens=80, latency_ms=420, ok=True, feature="unit_test")
    summary = llm_audit.usage_summary(days=7)
    assert summary["today"]["calls"] >= 1 and summary["today"]["total_tokens"] >= 200

    # 3. Rolling SQLite backup works
    bk = db_backup.create_rolling_backup(force=True, max_keep=3)
    assert bk["ok"] is True and bk["count"] >= 1

    # 4. System diagnostics + Grill-me + JD heatmap endpoints
    account = make_account("resume-insights")
    diag = account.get("/api/system-settings/diagnostics")
    assert diag.status_code == 200
    assert any(c["key"] == "privacy_shield" and c["ok"] for c in diag.get_json()["checks"])

    g1 = account.post("/api/resume-editor/grill", json={
        "section": "项目经历", "name": "智能体平台", "role": "负责人",
        "content": "- 基于 LangGraph 实现多智能体协同，召回率提升 20%。",
    })
    assert g1.status_code == 200 and g1.get_json()["question"]
    g2 = account.post("/api/resume-editor/grill", json={
        "section": "项目经历", "name": "智能体平台", "role": "负责人",
        "content": "- 基于 LangGraph 实现多智能体协同，召回率提升 20%。",
        "history": [{"q": g1.get_json()["question"], "a": "我们在 500 条测试集上对比了单向量检索 Baseline。"}],
        "synthesize": True,
    })
    assert g2.status_code == 200 and "500" in g2.get_json()["improved_content"]

    jd_rep = account.post("/api/resume-editor/jd-report", json={
        "document": {"contact": {"name": "林晓"}, "sections": [{"title": "专业技能", "content": "Python, LangGraph"}]}
    })
    assert jd_rep.status_code == 200 and "skills" in jd_rep.get_json()

"""Resume workshop API. Drafts and source documents remain scoped to their owner."""
import base64
import io
import json
import logging
import time
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import BadZipFile, ZipFile, ZIP_DEFLATED

import pymupdf as fitz
from PIL import Image, ImageOps, UnidentifiedImageError
from docx.opc.exceptions import PackageNotFoundError
from flask import Blueprint, jsonify, redirect, render_template, request, send_file, url_for
from lxml.etree import XMLSyntaxError

from backend.advisor.utils.resume_grounding import explicit_resume_role
from services import db, llm_env
from services.user_state import _current_user, _load_user_state, _login_required, _owned_resume_storage_path
from . import pipeline, rewrite
from .editor_document import CONTACT, MAX_SECTIONS, MAX_TEXT, SECTIONS, choose_layout, clean_document, parse_resume, render_resume
from .editor_pdf import read_layout, read_page_target
from .matcher import _extract_docx_text

blueprint = Blueprint("resume_editor", __name__)
logger = logging.getLogger(__name__)
UPLOAD_LIMIT = pipeline.RESUME_MAX_FILE_SIZE
IMAGE_EXTENSIONS = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}


@blueprint.get("/user-center/resumes")
def index():
    if not (user := _current_user()):
        return redirect(url_for("site.index"))
    state = _load_user_state(user["username"]).get("resume_profile") or {}
    path = _owned_resume_storage_path(user["username"], state.get("storage_path") or "")
    has_source = bool(path and Path(path).is_file())
    return render_template("resume_editor.html", contact=CONTACT, sections=list(SECTIONS),
                           has_source=has_source, ai_configured=llm_env.chat_configured(),
                           max_sections=MAX_SECTIONS)


def rewrite_state(conn, owner, preview_skill=None):
    settings = rewrite.options(conn, owner)
    try:
        prompt = rewrite.instructions(conn, owner, preview_skill or settings["skill"])
    except ValueError as error:
        return jsonify(message=str(error)), 400
    response = jsonify(settings=settings, skills=rewrite.skills(conn, owner), prompt=prompt)
    response.headers["Cache-Control"] = "no-store"
    return response


@blueprint.route("/api/resume-editor/rewrite/settings", methods=["GET", "POST"])
@_login_required
def rewrite_settings():
    owner = _current_user()["username"]
    conn = db._get_conn()
    if request.method == "POST":
        try:
            with conn:
                rewrite.save_options(conn, owner, request.get_json(silent=True))
        except ValueError as error:
            return jsonify(message=str(error)), 400
    return rewrite_state(conn, owner, request.args.get("skill"))


@blueprint.post("/api/resume-editor/rewrite/skills")
@_login_required
def rewrite_skill_import():
    from services.recruitment import local_desktop_request

    owner = _current_user()["username"]
    conn = db._get_conn()
    file = request.files.get("skill_file")
    location = request.form.get("location", "").strip()
    if bool(file) == bool(location) or len(location) > 2048:
        return jsonify(message="选择一个 Markdown 文件，或填写 GitHub 链接或本机路径。"), 400
    try:
        if file:
            filename = Path(file.filename or "").name
            if Path(filename).suffix.lower() != ".md":
                raise ValueError("请上传 Markdown Skill 文件。")
            origin, data = "上传", file.stream.read(rewrite.MAX_SKILL + 1)
        elif "://" in location:
            origin, data, filename = "GitHub", rewrite.read_github(location), location.rstrip("/").rsplit("/", 1)[-1]
        else:
            if not local_desktop_request():
                return jsonify(message="本机路径导入需从本机地址访问，也可以上传 Markdown 文件。"), 403
            origin = "本机路径"
            data, filename = rewrite.read_local(location)
        with conn:
            rewrite.import_skill(conn, owner, data, filename, origin)
    except (ValueError, OSError) as error:
        return jsonify(message=str(error) if isinstance(error, ValueError) else "暂时无法读取 Skill 文件。"), 400
    return rewrite_state(conn, owner)


@blueprint.post("/api/resume-editor/rewrite")
@_login_required
def rewrite_resume():
    payload = request.get_json(silent=True)
    job = payload.get("job") if isinstance(payload, dict) else None
    if not isinstance(job, dict) or not all(isinstance(job.get(key), str) and "\x00" not in job[key]
                                          for key in ("title", "description")):
        return jsonify(message="请填写目标岗位和岗位描述。"), 400
    job_title, description = job["title"].strip(), job["description"].strip()
    if not job_title or len(job_title) > 120 or not description or len(description) > 12000:
        return jsonify(message="请填写目标岗位和岗位描述（最多 12,000 字符）。"), 400
    owner = _current_user()["username"]
    conn = db._get_conn()
    settings = rewrite.options(conn, owner)
    try:
        skill = rewrite.instructions(conn, owner, settings["skill"])
    except ValueError as error:
        return jsonify(message=str(error)), 400
    if not skill:
        return jsonify(message="请先选择有效的改写 Skill。"), 400
    if not rewrite.SLOTS.acquire(blocking=False):
        return jsonify(message="当前改写任务较多，请稍后重试。"), 429
    try:
        document = clean_document(payload.get("document"))
        try:
            result, changes = rewrite.generate(document, {"title": job_title, "description": description},
                                               skill, full=settings["skill"] == rewrite.DEFAULT_ID)
        except rewrite.RewriteInputError:
            raise
        except Exception:
            logger.warning("Resume rewrite could not complete")
            return jsonify(message="模型调用或结果校验失败，请检查配置后重试。"), 502
    except ValueError as error:
        return jsonify(message=str(error)), 400
    finally:
        rewrite.SLOTS.release()
    response = jsonify(document=result, changes=changes)
    response.headers["Cache-Control"] = "no-store"
    return response


@blueprint.route("/api/resume-editor/drafts", methods=["GET", "POST"])
@_login_required
def drafts():
    owner = _current_user()["username"]
    conn = db._get_conn()
    if request.method == "GET":
        rows = conn.execute("SELECT id, title, updated_at FROM resume_drafts WHERE owner=? ORDER BY updated_at DESC",
                            (owner,))
        return jsonify(drafts=[dict(row) for row in rows])
    try:
        document = clean_document(request.get_json(silent=True))
    except ValueError as exc:
        return jsonify(message=str(exc)), 400
    identifier, now = uuid.uuid4().hex, time.time()
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        count = conn.execute("SELECT count(*) FROM resume_drafts WHERE owner=?", (owner,)).fetchone()[0]
        if count >= 30:
            return jsonify(message="已达到 30 份简历上限，请删除不用的草稿。"), 409
        conn.execute("INSERT INTO resume_drafts VALUES (?, ?, ?, ?, ?, ?)",
                     (identifier, owner, document["title"], json.dumps(document, ensure_ascii=False), now, 1))
    return jsonify(id=identifier, revision=1, document=document), 201


@blueprint.route("/api/resume-editor/drafts/<identifier>", methods=["GET", "PUT", "DELETE"])
@_login_required
def draft(identifier):
    owner = _current_user()["username"]
    conn = db._get_conn()
    record = conn.execute("SELECT document, revision FROM resume_drafts WHERE owner=? AND id=?",
                          (owner, identifier)).fetchone()
    if not record:
        return jsonify(message="找不到这份简历。"), 404
    if request.method == "GET":
        return jsonify(id=identifier, revision=record["revision"], document=json.loads(record["document"]))
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or type(payload.get("revision")) is not int:
        return jsonify(message="简历版本号无效，请重新打开。"), 400
    revision = payload["revision"]
    if request.method == "DELETE":
        with conn:
            result = conn.execute("DELETE FROM resume_drafts WHERE owner=? AND id=? AND revision=?",
                                  (owner, identifier, revision))
        if not result.rowcount:
            return jsonify(message="这份简历在其他页面修改过，请重新打开。"), 409
        return jsonify(deleted=True)
    try:
        document = clean_document(payload.get("document"))
    except ValueError as exc:
        return jsonify(message=str(exc)), 400
    with conn:
        result = conn.execute(
            "UPDATE resume_drafts SET title=?, document=?, updated_at=?, revision=revision+1 "
            "WHERE owner=? AND id=? AND revision=?",
            (document["title"], json.dumps(document, ensure_ascii=False), time.time(), owner, identifier, revision),
        )
    if not result.rowcount:
        return jsonify(message="这份简历在其他页面修改过。请复制当前内容或重新打开后再保存。"), 409
    return jsonify(id=identifier, revision=revision + 1, document=document)


def extract_source(path):
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        with Image.open(path) as image:
            if image.format != IMAGE_EXTENSIONS[suffix] or image.width * image.height > 20_000_000:
                raise ValueError("请上传有效的 PNG、JPEG 或 WebP 图片，像素数不超过 2000 万。")
            lang = pipeline._resolve_resume_ocr_lang()
            if not lang:
                raise ValueError("当前服务没有可用的 OCR 语言包。")
            text = pipeline._run_resume_ocr(ImageOps.exif_transpose(image).convert("RGB"), lang, keep_lines=True)
        return text, True
    if suffix == ".docx":
        with ZipFile(path) as archive:
            if sum(item.file_size for item in archive.infolist()) > 64 * 1024 * 1024:
                raise ValueError("Word 文件解压后的内容过大。")
        try:
            return "\n\n".join(_extract_docx_text(path)), False
        except (KeyError, PackageNotFoundError, XMLSyntaxError) as error:
            raise ValueError("无法读取 Word 内容，请检查 DOCX 文件。") from error
    if suffix != ".pdf":
        raise ValueError("请选择 PDF、DOCX、PNG、JPEG 或 WebP 简历。")
    with fitz.open(path) as source:
        if not source.is_pdf or source.needs_pass:
            raise ValueError("请选择未加密的 PDF 简历。")
        if len(source) > pipeline.RESUME_MAX_PAGES:
            raise ValueError(f"请将简历控制在 {pipeline.RESUME_MAX_PAGES} 页内。")
        text_pages = {index: page.get_text(sort=True).strip() for index, page in enumerate(source, 1)}
    candidates = {index for index, text in text_pages.items()
                  if len(text) < 32 or pipeline._resume_text_meaningful_ratio(text) < 0.42}
    if not candidates:
        return "\n\n".join(text_pages.values()), False
    used_ocr = False
    for result in pipeline._ocr_pdf_pages(path, keep_lines=True, page_numbers=candidates):
        index = result["page_no"]
        if pipeline._resume_text_quality_score(result["text"]) > pipeline._resume_text_quality_score(text_pages[index]):
            text_pages[index] = result["text"]
            used_ocr = True
    return "\n\n".join(text_pages.values()), used_ocr


def extract_for_editor(path):
    if path.suffix.lower() == ".pdf":
        with fitz.open(path) as source:
            if source.is_pdf and not source.needs_pass and len(source) <= pipeline.RESUME_MAX_PAGES:
                structured = read_layout(source)
                if structured:
                    text, header = structured
                    return text, False, header
    text, ocr = extract_source(path)
    return text, ocr, {}


def read_source_target(path, cached_text):
    """Read the goal from an existing upload without rerunning OCR or AI."""
    target = explicit_resume_role(cached_text)
    if not path:
        return target
    path = Path(path)
    try:
        if path.suffix.lower() == ".pdf":
            with fitz.open(path) as source:
                if source.is_pdf and not source.needs_pass and len(source):
                    page = source[0]
                    return read_page_target(page) or target or explicit_resume_role(page.get_text(sort=True))
        if path.suffix.lower() == ".docx" and not target:
            text, _ = extract_source(path)
            return explicit_resume_role(text)
    except (BadZipFile, OSError, RuntimeError, ValueError):
        pass
    return target


@blueprint.post("/api/resume-editor/import")
@_login_required
def import_source():
    owner = _current_user()["username"]
    try:
        kind = request.form.get("source")
        header = {}
        if kind == "text":
            text, ocr = request.form.get("text", ""), False
        elif kind == "current":
            profile = _load_user_state(owner).get("resume_profile") or {}
            path = _owned_resume_storage_path(owner, profile.get("storage_path") or "")
            if not path or not Path(path).is_file():
                raise ValueError("没有找到当前上传的简历。")
            text, ocr, header = extract_for_editor(Path(path))
        elif kind == "file":
            file = request.files.get("file")
            suffix = Path(file.filename or "").suffix.lower() if file else ""
            if suffix not in {".pdf", ".docx", *IMAGE_EXTENSIONS}:
                raise ValueError("请选择 PDF、DOCX、PNG、JPEG 或 WebP 简历。")
            data = file.stream.read(UPLOAD_LIMIT + 1)
            if not 0 < len(data) <= UPLOAD_LIMIT:
                raise ValueError("简历文件须小于 12 MB 且不能为空。")
            with TemporaryDirectory(prefix="career-resume-") as directory:
                path = Path(directory) / ("resume" + suffix)
                path.write_bytes(data)
                text, ocr, header = extract_for_editor(path)
        else:
            raise ValueError("请选择简历来源。")
        text = str(text or "").strip().replace("\x00", "")
        if not text:
            raise ValueError("没有识别到文字。请检查扫描清晰度，或粘贴简历文本。")
        if len(text) > MAX_TEXT:
            raise ValueError("识别到的文本超过 24,000 字符，请精简后再导入。")
        document, warning = parse_resume(text, use_ai=request.form.get("use_ai") == "1", header=header)
    except ValueError as exc:
        return jsonify(message=str(exc)), 400
    except (BadZipFile, UnidentifiedImageError, Image.DecompressionBombError, OSError, RuntimeError):
        return jsonify(message="无法读取简历，请检查文件类型和内容。"), 400
    # Import only stages edits in the browser. The uploaded source and saved drafts are not replaced.
    return jsonify(document=document, warning=warning, ocr_used=ocr)


@blueprint.post("/api/resume-editor/render/<mode>")
@_login_required
def render(mode):
    if mode not in {"auto", "preview", "pdf", "image"}:
        return jsonify(message="不支持的导出类型。"), 404
    try:
        document = clean_document(request.get_json(silent=True))
        if not (any(document["contact"].values()) or any(item["value"] for item in document.get("extras", []))
                or any(part["content"] for part in document["sections"])):
            raise ValueError("请先填写或导入简历内容。")
        if mode == "auto":
            layout, pdf, count = choose_layout(document)
        else:
            layout = document["layout"]
            pdf, count = render_resume(document)
    except (ValueError, RuntimeError) as exc:
        return jsonify(message=str(exc) if isinstance(exc, ValueError) else "排版失败，请检查简历内容。"), 400

    if mode == "pdf":
        return send_file(io.BytesIO(pdf), mimetype="application/pdf", as_attachment=True, download_name="resume.pdf")
    with fitz.open(stream=pdf, filetype="pdf") as pages:
        if mode == "image":
            if count == 1:
                return send_file(io.BytesIO(pages[0].get_pixmap(dpi=170).tobytes("png")), mimetype="image/png",
                                 as_attachment=True, download_name="resume.png")
            result = io.BytesIO()
            with ZipFile(result, "w", ZIP_DEFLATED) as archive:
                for number, page in enumerate(pages, 1):
                    archive.writestr(f"resume-{number:02d}.png", page.get_pixmap(dpi=170).tobytes("png"))
            result.seek(0)
            return send_file(result, mimetype="application/zip", as_attachment=True, download_name="resume-images.zip")
        images = [base64.b64encode(page.get_pixmap(dpi=100).tobytes("png")).decode("ascii") for page in pages]
    return jsonify(layout=layout, page_count=count, images=images)

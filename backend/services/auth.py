import base64
import hashlib
import hmac
import io
import os
import re
import secrets
import sqlite3
import time

from flask import Blueprint, current_app, g, jsonify, request, session
from PIL import Image, ImageDraw, ImageFont
from werkzeug.security import check_password_hash, generate_password_hash

from . import db


blueprint = Blueprint("auth", __name__, url_prefix="/api/auth")
CAPTCHA_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
DUMMY_PASSWORD_HASH = generate_password_hash(secrets.token_urlsafe(32))


class AuthError(Exception):
    def __init__(self, message, status=400, retry_after=None):
        self.message = message
        self.status = status
        self.retry_after = retry_after


def digest(value):
    return hmac.new(str(current_app.secret_key).encode(), value.encode(), hashlib.sha256).hexdigest()


def normalize_email(value):
    if not isinstance(value, str) or len(value) > 254 or value != value.strip():
        raise AuthError("请输入有效的邮箱地址。")
    parts = value.rsplit("@", 1)
    if len(parts) != 2:
        raise AuthError("请输入有效的邮箱地址。")
    local, domain = parts
    try:
        domain = domain.encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise AuthError("请输入有效的邮箱地址。") from None
    labels = domain.split(".")
    if (
        not 1 <= len(local) <= 64
        or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+", local)
        or local.startswith(".") or local.endswith(".") or ".." in local
        or len(labels) < 2 or len(labels[-1]) < 2
        or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels)
        or len(local + "@" + domain) > 254
    ):
        raise AuthError("请输入有效的邮箱地址。")
    return f"{local.lower()}@{domain}"


def validate_password(password):
    if not isinstance(password, str) or not password:
        raise AuthError("请输入密码。")


def payload():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise AuthError("请求必须是有效的 JSON 对象。")
    return data


def field(data, name, maximum=254):
    value = data.get(name, "")
    if not isinstance(value, str) or (maximum is not None and len(value) > maximum):
        raise AuthError("提交的字段格式或长度不正确。")
    return value


def rate_limit(scope, identifier, limit, window):
    now = time.time()
    bucket = digest(f"{scope}:{identifier}")
    conn = db._get_conn()
    with conn:
        conn.execute("""
            INSERT INTO auth_rate_limits VALUES (?, ?, 1)
            ON CONFLICT(bucket) DO UPDATE SET
                attempts = CASE WHEN started_at <= ? THEN 1 ELSE attempts + 1 END,
                started_at = CASE WHEN started_at <= ? THEN excluded.started_at ELSE started_at END
        """, (bucket, now, now - window, now - window))
        record = conn.execute("SELECT * FROM auth_rate_limits WHERE bucket = ?", (bucket,)).fetchone()
    if record["attempts"] > limit:
        retry_after = max(1, int(record["started_at"] + window - now) + 1)
        raise AuthError("尝试次数过多，请稍后再试。", 429, retry_after)
    return bucket


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def public_user(user):
    return {**{name: user[name] for name in ("username", "display_name", "role")}, "can_manage_configs": user["role"] == "super_admin"}


def current_user():
    if "auth_user" in g:
        return g.auth_user
    token = session.get("auth_token")
    user = None
    if isinstance(token, str):
        record = db._get_conn().execute("""
            SELECT users.* FROM auth_sessions JOIN users USING(username)
            WHERE token_hash = ? AND expires_at > ? AND users.disabled = 0
        """, (digest(token), time.time())).fetchone()
        if record:
            user = dict(record)
    g.auth_user = user
    return user


def start_session(user):
    conn = db._get_conn()
    now = time.time()
    with conn:
        verified = conn.execute("""
            UPDATE users SET last_login_at = ?
            WHERE username = ? AND password_hash = ? AND disabled = 0
            RETURNING username
        """, (now, user["username"], user["password_hash"])).fetchone()
        if not verified:
            raise AuthError("账户信息已变更，请重新登录。", 401)
        if session.get("auth_token"):
            conn.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (digest(session["auth_token"]),))
        session.clear()
        session.permanent = True
        session["auth_token"] = secrets.token_urlsafe(32)
        session["username"] = user["username"]
        conn.execute("INSERT INTO auth_sessions VALUES (?, ?, ?, ?)", (
            digest(session["auth_token"]), user["username"], now,
            now + current_app.permanent_session_lifetime.total_seconds(),
        ))
    g.auth_user = user


def captcha_image(answer):
    image = Image.new("RGB", (210, 72), "#f2f7fb")
    drawing = ImageDraw.Draw(image)
    font = None
    for name in ("DejaVuSans.ttf", "arial.ttf"):
        try:
            font = ImageFont.truetype(name, 35)
            break
        except OSError:
            continue
    font = font or ImageFont.load_default(size=35)
    for position, character in enumerate(answer):
        glyph = Image.new("RGBA", (45, 60))
        ImageDraw.Draw(glyph).text((3, 3), character, font=font, fill=(25, 60 + secrets.randbelow(65), 120, 255))
        glyph = glyph.rotate(secrets.randbelow(31) - 15, resample=Image.Resampling.BICUBIC)
        image.paste(glyph, (8 + position * 39, secrets.randbelow(9) + 3), glyph)
    for noise_index in range(70):
        drawing.point((secrets.randbelow(210), secrets.randbelow(72)), fill="#809ab4")
    for line_index in range(3):
        drawing.line([(0, secrets.randbelow(72)), (210, secrets.randbelow(72))], fill="#99b3c9", width=1)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def verify_captcha(data, purpose):
    challenge_id = field(data, "captcha_id", 100)
    answer = field(data, "captcha_answer", 10).strip().upper()
    owner = session.get("captcha_owner", "")
    conn = db._get_conn()
    with conn:
        challenge = conn.execute("""
            DELETE FROM auth_challenges WHERE id = ? AND owner_hash = ? AND purpose = ?
            RETURNING answer_hash, expires_at
        """, (challenge_id, digest(owner), purpose)).fetchone()
    if not challenge or challenge["expires_at"] <= time.time() or not hmac.compare_digest(challenge["answer_hash"], digest(answer)):
        raise AuthError("验证码错误或已过期，请刷新后重新输入。")


@blueprint.get("/security")
def security():
    session.setdefault("captcha_owner", secrets.token_urlsafe(32))
    return jsonify(csrf_token=csrf_token())


@blueprint.get("/challenge")
def challenge():
    purpose = request.args.get("purpose", "login")
    if purpose not in {"login", "register"}:
        raise AuthError("未知的验证场景。")
    rate_limit("challenge", request.remote_addr or "unknown", 90, 600)
    session.setdefault("captcha_owner", secrets.token_urlsafe(32))
    owner_hash = digest(session["captcha_owner"])
    answer = "".join(secrets.choice(CAPTCHA_ALPHABET) for character_index in range(5))
    challenge_id = secrets.token_urlsafe(24)
    conn = db._get_conn()
    with conn:
        conn.execute("DELETE FROM auth_challenges WHERE expires_at <= ? OR (owner_hash = ? AND purpose = ?)", (time.time(), owner_hash, purpose))
        conn.execute("INSERT INTO auth_challenges VALUES (?, ?, ?, ?, ?)", (challenge_id, owner_hash, purpose, digest(answer), time.time() + 180))
    return jsonify(id=challenge_id, image=captcha_image(answer), expires_in=180)


@blueprint.post("/login")
def login():
    rate_limit("login_ip", request.remote_addr or "unknown", 30, 600)
    data = payload()
    identifier = field(data, "username").strip()
    identifier = identifier.lower() if "@" in identifier else identifier
    password = field(data, "password", None)
    if not identifier or not password:
        raise AuthError("请输入账号和密码。")
    verify_captcha(data, "login")
    account_bucket = rate_limit("login_account", identifier, 8, 900)
    user = db._get_conn().execute("SELECT * FROM users WHERE username = ?", (identifier,)).fetchone()
    password_matches = check_password_hash(user["password_hash"] if user else DUMMY_PASSWORD_HASH, password)
    if not user or not password_matches or user["disabled"]:
        raise AuthError("账号或密码错误，请检查后重试。", 401)
    with db._get_conn() as conn:
        conn.execute("DELETE FROM auth_rate_limits WHERE bucket = ?", (account_bucket,))
    user = dict(user)
    start_session(user)
    return jsonify(message="登录成功", user=public_user(user))


@blueprint.post("/register")
def register():
    rate_limit("register_ip", request.remote_addr or "unknown", 10, 3600)
    data = payload()
    email = normalize_email(field(data, "email").strip())
    password = field(data, "password", None)
    confirm_password = field(data, "confirm_password", None)
    validate_password(password)
    if not confirm_password or password != confirm_password:
        raise AuthError("两次输入的密码不一致。")
    display_name = field(data, "display_name", 48).strip() or email.split("@")[0][:48]
    if any(ord(character) < 32 for character in display_name):
        raise AuthError("昵称包含无效字符。")
    verify_captcha(data, "register")
    user = {"username": email, "password_hash": generate_password_hash(password), "role": "user", "display_name": display_name}
    try:
        with db._get_conn() as conn:
            conn.execute("INSERT INTO users (username, password_hash, role, display_name, created_at) VALUES (?, ?, ?, ?, ?)",
                         (email, user["password_hash"], "user", display_name, time.time()))
    except sqlite3.IntegrityError:
        raise AuthError("无法使用此邮箱创建账户，请尝试登录或使用其他邮箱。", 409) from None
    start_session(user)
    return jsonify(message="注册成功", user=public_user(user)), 201


@blueprint.post("/logout")
def logout():
    token = session.get("auth_token")
    if token:
        with db._get_conn() as conn:
            conn.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (digest(token),))
    session.clear()
    g.auth_user = None
    return jsonify(message="已退出登录。")


@blueprint.put("/password")
def change_password():
    user = current_user()
    if not user:
        raise AuthError("请先登录。", 401)
    rate_limit("password", user["username"], 8, 900)
    data = payload()
    old_password = field(data, "current_password", None)
    new_password = field(data, "new_password", None)
    confirm_password = field(data, "confirm_password", None)
    validate_password(new_password)
    if new_password != confirm_password:
        raise AuthError("两次输入的新密码不一致。")
    if not check_password_hash(user["password_hash"], old_password):
        raise AuthError("当前密码不正确。")
    new_hash = generate_password_hash(new_password)
    with db._get_conn() as conn:
        changed = conn.execute("UPDATE users SET password_hash = ? WHERE username = ? AND password_hash = ?", (new_hash, user["username"], user["password_hash"]))
        if changed.rowcount != 1:
            raise AuthError("账户信息已变更，请重新登录。", 401)
        conn.execute("DELETE FROM auth_sessions WHERE username = ?", (user["username"],))
    user["password_hash"] = new_hash
    start_session(user)
    return jsonify(message="密码已更新，其他设备的登录已失效。")


def init_app(app):
    conn = db._get_conn()
    with conn:
        conn.execute("INSERT OR IGNORE INTO auth_settings VALUES ('session_secret', ?)", (secrets.token_hex(32),))
    app.secret_key = os.environ.get("APP_SECRET_KEY") or os.environ.get("SECRET_KEY") or conn.execute("SELECT value FROM auth_settings WHERE name = 'session_secret'").fetchone()[0]
    with conn:
        conn.execute("DELETE FROM auth_sessions WHERE expires_at <= ?", (time.time(),))
        conn.execute("DELETE FROM auth_rate_limits WHERE started_at < ?", (time.time() - 86400,))
        checked = conn.execute("SELECT 1 FROM auth_settings WHERE name = 'demo_accounts_disabled'").fetchone()
        if not checked:
            for username in ("system", "23030134", "24110403", "24030115", "24151007"):
                user = db.find_user(username)
                if user and check_password_hash(user["password_hash"], "123456"):
                    conn.execute("UPDATE users SET disabled = 1 WHERE username = ?", (username,))
            conn.execute("INSERT INTO auth_settings VALUES ('demo_accounts_disabled', '1')")

    @app.before_request
    def protect_auth_requests():
        if request.path.startswith(("/api/auth/", "/api/career-profile", "/api/job-market")) and request.method in {"POST", "PUT", "DELETE", "PATCH"}:
            limit = 65536 if request.path.startswith(("/api/career-profile", "/api/job-market")) else 16384
            if request.content_length and request.content_length > limit:
                raise AuthError("提交的内容过大。", 413)
            expected = session.get("csrf_token")
            supplied = request.headers.get("X-CSRF-Token", "")
            if not isinstance(expected, str) or not hmac.compare_digest(expected.encode(), supplied.encode()):
                raise AuthError("安全校验已过期，请刷新页面后重试。", 403)

    @app.after_request
    def protect_auth_responses(response):
        private_prefixes = ("/api/auth/", "/api/user-state/", "/api/resume/", "/api/career-report/", "/api/career-profile", "/api/job-market",
                            "/api/profile-portrait", "/api/account", "/api/community-feed", "/app_data/")
        if request.path.startswith(private_prefixes):
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.vary.add("Cookie")
            user = current_user()
            if user:
                from urllib.parse import quote
                response.headers["X-Workspace-Owner"] = quote(user["username"], safe="")
                response.headers["Access-Control-Expose-Headers"] = "X-Workspace-Owner"
        return response

    @app.errorhandler(AuthError)
    def auth_error(error):
        response = jsonify(message=error.message)
        response.status_code = error.status
        if error.retry_after:
            response.headers["Retry-After"] = str(error.retry_after)
        return response

    app.register_blueprint(blueprint)

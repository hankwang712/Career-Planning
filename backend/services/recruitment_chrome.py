"""Read recruitment results in a new tab of an explicitly enabled local Chrome bridge."""

from contextlib import contextmanager
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
from threading import Lock
from time import monotonic, sleep
from urllib.parse import parse_qs, urlsplit

import httpx

from .recruitment_sources import (
    JOB51_APPLY_FILTER, JOB51_WORK_TYPES, SOURCES, cards, platform_url, search_url,
)


logger = logging.getLogger(__name__)
BRIDGE_URL = "http://127.0.0.1:3456"
CHROME_AUTHORIZATION_URL = "chrome://inspect/#remote-debugging"
_authorization_lock = Lock()
_authorization_opened_at = float("-inf")
TAB_ID = re.compile(r"[0-9a-fA-F]{32}")
CHROME_SOURCES = {
    "boss": ("www.zhipin.com", "/web/geek/jobs"),
    "51job": ("we.51job.com", "/pc/search"),
    "zhilian": ("xiaoyuan.zhaopin.com", "/search/index"),
    "xiaohongshu": ("www.xiaohongshu.com", "/search_result"),
}
LOGIN_WAIT_SECONDS = 120
LOGIN_URLS = {
    "boss": "https://www.zhipin.com/web/user/?ka=header-login",
    "51job": "https://login.51job.com/",
    "zhilian": "https://www.zhaopin.com/jobs/",
    "xiaohongshu": "https://www.xiaohongshu.com/explore",
}
LOGIN_HOSTS = {"passport.zhipin.com", "passport.zhaopin.com", "login.51job.com", "passport.51job.com"}
SESSION_URLS = {**LOGIN_URLS, **{source: SOURCES[source][1] for source in ("boss", "51job")}}
ZHILIAN_LOGIN = r"""(() => {
    if (!['https://www.zhaopin.com', 'https://xiaoyuan.zhaopin.com'].includes(location.origin)) return 'unknown';
    const visible = el => Boolean(el?.getClientRects?.().length);
    const label = (node) => (node.textContent || '').trim().replace(/\s+/g, '');
    const visitor = document.querySelector('.home-header__c-no-login, .c-login__top__no-login, .xy-header__login');
    if (visible(visitor)) return 'not_logged_in';
    const header = document.querySelector('.home-header__right, .c-login__top, header, [class*="header"]');
    const controls = Array.from(header?.querySelectorAll('a, button, [role="button"], span') || []);
    if (controls.some(node => visible(node) && ['登录', '登录/注册', '登录／注册'].includes(label(node))))
        return 'not_logged_in';
    const account = document.querySelector('.c-login__top__name, .c-login__top__img, .home-header__c-login, .user-info, .user-name, .user-avatar, [class*="user-name"], [class*="avatar"]');
    if (visible(account)) return 'ready';
    if (controls.some(node => visible(node) && ['退出', '退出登录', '个人中心', '我的简历', '消息'].includes(label(node)))) return 'ready';
    if (location.origin === 'https://xiaoyuan.zhaopin.com' && document.querySelectorAll("a[href*='/job/'], a[href*='/jobdetail/'], .job-card, .fn-job-item, .job-item").length > 0)
        return 'ready';
    return 'unknown';
})()"""
BOSS_LOGIN = r"""(() => {
    if (location.origin !== 'https://www.zhipin.com') return 'unknown';
    const visible = el => Boolean(el?.getClientRects?.().length);
    const clean = el => (el?.innerText || el?.textContent || '').trim().replace(/\s+/g, '');
    if (visible(document.querySelector('.btn-sign, .header-login-btn, .login-dialog-wrapper, .sign-form-wrapper')))
        return 'not_logged_in';
    const header = document.querySelector('#header, header, .header-inner, .user-nav');
    const controls = Array.from(header?.querySelectorAll('a, button') || []);
    if (controls.some(el => visible(el) && /^(登录|注册|登录\/注册|登录／注册)$/.test(clean(el))))
        return 'not_logged_in';
    if (Array.from(document.querySelectorAll('a, button')).some(el => visible(el) && clean(el) === '登录查看完整内容'))
        return 'not_logged_in';
    if (visible(document.querySelector('.nav-figure, .user-nav .nav-figure img, .user-nav .label-text, .nav-chat, a[href*="/web/geek/chat"], a[href*="/web/geek/resume"]')))
        return 'ready';
    return 'unknown';
})()"""
JOB51_LOGIN = r"""(() => {
    if (!['https://we.51job.com', 'https://jobs.51job.com'].includes(location.origin)) return 'unknown';
    const visible = el => Boolean(el?.getClientRects?.().length);
    const clean = el => (el?.innerText || el?.textContent || '').trim().replace(/\s+/g, '');
    if (Array.from(document.querySelectorAll('header a, header button, .top-nav a, .header a, a, button')).some(
        el => visible(el) && ['登录/注册', '登录／注册', '登录'].includes(clean(el))))
        return 'not_logged_in';
    if (visible(document.querySelector('.user-info, .header-avatar, .uname, a[href*="my.51job.com"]')))
        return 'ready';
    return 'unknown';
})()"""
XHS_LOGIN = r"""(() => {
    if (location.origin !== 'https://www.xiaohongshu.com') return 'unknown';
    const visible = el => Boolean(el?.getClientRects?.().length);
    const clean = el => (el?.innerText || el?.textContent || '').trim().replace(/\s+/g, '');
    if (visible(document.querySelector('button.login-btn, .login-container .qrcode, .login-modal')))
        return 'not_logged_in';
    if (Array.from(document.querySelectorAll('.side-bar button, .side-bar a, header button, header a')).some(
        el => visible(el) && ['登录', '登录/注册'].includes(clean(el))))
        return 'not_logged_in';
    if (visible(document.querySelector('a.link-wrapper[href^="/user/profile"], .user-avatar, .side-bar-user')))
        return 'ready';
    return 'unknown';
})()"""
SNAPSHOT = """JSON.stringify({
    url: location.origin + location.pathname + location.search,
    title: document.title,
    verification: !!document.querySelector('#nc_1_n1z')?.getClientRects().length,
    zhilianLogin: """ + ZHILIAN_LOGIN + """,
    bossLogin: """ + BOSS_LOGIN + """,
    job51Login: """ + JOB51_LOGIN + """,
    xhsLogin: """ + XHS_LOGIN + """
})"""
SESSION_FIELDS = {"boss": "bossLogin", "51job": "job51Login", "zhilian": "zhilianLogin", "xiaohongshu": "xhsLogin"}
SESSION_LABELS = {
    "ready": "已登录",
    "not_logged_in": "未登录",
    "verification_required": "需要安全验证",
    "unknown": "未能确认",
    "unavailable": "检查失败",
    "authorization_required": "等待 Chrome 授权",
    "authorization_required_manual": "需要 Chrome 授权",
    "bridge_unavailable": "本机 Chrome 连接未启动",
}
SESSION_MESSAGES = {
    "ready": "当前 Chrome 已登录，可以采集。",
    "not_logged_in": "请在用于采集的 Chrome 登录后重试。",
    "verification_required": "请在官网完成验证后重试。",
    "unknown": "请在官网确认登录后重试。",
    "unavailable": "暂时无法读取招聘页面，请稍后重试。",
    "authorization_required": "已打开 Chrome 授权页。请允许远程调试，如 Chrome 提示确认连接，也请确认。完成后再点「检查登录」。",
    "authorization_required_manual": "请在 Chrome 地址栏打开 chrome://inspect/#remote-debugging，允许远程调试后重试。",
    "bridge_unavailable": "启动本机 Chrome 连接服务后再检查登录。",
}


def use_local_chrome():
    configured = os.getenv("CAREER_RECRUITMENT_USE_LOCAL_CHROME", os.getenv("CAREER_BOSS_USE_LOCAL_CHROME", ""))
    return configured.strip().lower() in {"1", "true"}


def find_chrome_executable():
    for name in ("chrome.exe", "google-chrome", "google-chrome-stable", "chromium"):
        if executable := shutil.which(name):
            return executable
    for name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        if root := os.getenv(name):
            executable = Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe"
            if executable.is_file():
                return str(executable)
    executable = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    return str(executable) if executable.is_file() else None


def open_chrome_authorization():
    global _authorization_opened_at
    with _authorization_lock:
        # A parallel check of all platforms should open only one authorization page.
        if monotonic() - _authorization_opened_at < 10:
            return True
        executable = find_chrome_executable()
        if not executable:
            return False
        try:
            subprocess.Popen(
                [executable, CHROME_AUTHORIZATION_URL],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except OSError:
            logger.warning("Could not open the Chrome authorization page")
            return False
        _authorization_opened_at = monotonic()
        return True


class ChromeTab:
    def __init__(self, client, identifier, source):
        self.client = client
        self.identifier = identifier
        self.url = ""
        self.source = source
        self.host, self.path = CHROME_SOURCES[source]

    def read(self, expression, *, timeout=15):
        response = self.client.post("/eval", params={"target": self.identifier}, content=expression, timeout=timeout)
        response.raise_for_status()
        return json.loads(response.json()["value"])

    def navigate(self, url, timeout):
        response = self.client.get("/navigate", params={"target": self.identifier, "url": url}, timeout=timeout)
        response.raise_for_status()

    def evaluate(self, script, options):
        arguments = json.dumps(options, ensure_ascii=True)
        login_check = f"&& {ZHILIAN_LOGIN} === 'ready' " if self.source == "zhilian" else ""
        return self.read(f"JSON.stringify(location.origin === 'https://{self.host}' "
                         f"&& location.pathname.replace(/\\/$/, '') === '{self.path}' "
                         f"{login_check}"
                         f"? ({script})({arguments}) : [])")


@contextmanager
def open_chrome_tab(source, target_url):
    with httpx.Client(base_url=BRIDGE_URL, timeout=15, trust_env=False) as client:
        health = client.get("/health", timeout=3)
        health.raise_for_status()
        # The bridge connects lazily on /new, so an idle /health is not a failed connection.
        connected = health.json().get("connected") is True
        # Get the owned tab ID first; a slow site must not leave an untracked tab behind.
        response = client.get("/new", params={"url": "about:blank"})
        if response.status_code == 500 and not connected:
            yield None
            return
        response.raise_for_status()
        identifier = str(response.json().get("targetId") or "")
        if not TAB_ID.fullmatch(identifier):
            raise ValueError("Chrome bridge returned an invalid tab ID")
        tab = ChromeTab(client, identifier, source)
        try:
            try:
                tab.navigate(target_url, timeout=20)
            except httpx.TimeoutException:
                pass
            yield tab
        finally:
            try:
                client.get("/close", params={"target": identifier}, timeout=3).raise_for_status()
            except httpx.HTTPError:
                logger.warning("Could not close the owned recruitment search tab")


def is_verification(snapshot):
    return snapshot["verification"] or any(word in snapshot["title"].lower() for word in (
        "安全验证", "安全限制", "请稍候", "security verification",
    ))


def platform_session(source, snapshot):
    url = snapshot["url"]
    if not url.startswith("https://") or not platform_url(source, url):
        return "unknown"
    if is_verification(snapshot):
        return "verification_required"
    address = urlsplit(url)
    if address.hostname in LOGIN_HOSTS or "请登录" in snapshot["title"]:
        return "not_logged_in"
    state = snapshot.get(SESSION_FIELDS[source])
    return state if state in ("ready", "not_logged_in") else "unknown"


def check_platform_login(source):
    try:
        with open_chrome_tab(source, SESSION_URLS[source]) as tab:
            if tab is None:
                return "authorization_required" if open_chrome_authorization() else "authorization_required_manual"
            deadline = monotonic() + 8
            while monotonic() < deadline:
                try:
                    state = platform_session(source, tab.read(SNAPSHOT, timeout=min(3, deadline - monotonic())))
                except httpx.TimeoutException:
                    continue
                except httpx.HTTPStatusError as error:
                    if error.response.status_code != 400:
                        raise
                    state = "unknown"
                if state != "unknown":
                    return state
                sleep(max(0, min(1, deadline - monotonic())))
            return "unknown"
    except (httpx.ConnectError, httpx.ConnectTimeout):
        return "bridge_unavailable"
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return "unavailable"


DRAFT_PLATFORM_CONFIG = {
    "boss": {
        "label": "BOSS 直聘",
        "prefixes": ("https://www.zhipin.com/",),
        "chat_btn_selectors": "a.btn-startchat, button.btn-startchat, .btn-startchat, .op-btn-chat, a[ka*='chat']",
        "chat_btn_pattern": r"(立即沟通|继续沟通|去沟通)",
        "input_selectors": [
            "#chat-input",
            ".chat-input[contenteditable=\"true\"]",
            ".input-area [contenteditable=\"true\"]",
            ".chat-conversation [contenteditable=\"true\"]",
            "textarea.input-area",
            "textarea.chat-input",
        ],
    },
    "zhilian": {
        "label": "智联招聘",
        "prefixes": ("https://www.zhaopin.com/", "https://xiaoyuan.zhaopin.com/", "https://jobs.zhaopin.com/"),
        "chat_btn_selectors": "button, a, [role='button']",
        "chat_btn_pattern": r"^(立即沟通|和TA聊聊|聊一聊|在线沟通|继续沟通)$",
        "input_selectors": [
            ".im-input [contenteditable=\"true\"]",
            ".chat-input [contenteditable=\"true\"]",
            ".msg-input [contenteditable=\"true\"]",
            "textarea[class*='chat']",
            "textarea[class*='im-input']",
            "textarea[placeholder*='输入']",
            "textarea[placeholder*='沟通']",
        ],
    },
    "51job": {
        "label": "前程无忧",
        "prefixes": ("https://jobs.51job.com/", "https://we.51job.com/", "https://search.51job.com/"),
        "chat_btn_selectors": "button, a, [role='button']",
        "chat_btn_pattern": r"^(立即沟通|聊一聊|和TA聊|在线沟通|继续沟通)$",
        "input_selectors": [
            ".chat-input [contenteditable=\"true\"]",
            ".im-editor [contenteditable=\"true\"]",
            "textarea.chat-input",
            "textarea[class*='chat']",
            "textarea[placeholder*='回复']",
            "textarea[placeholder*='输入']",
        ],
    },
}


def open_platform_draft_chat(source, job_url, greeting_text):
    """Open a BOSS/Zhilian/51job posting in local Chrome, enter chat, and fill greeting as a DRAFT (NEVER send)."""
    cfg = DRAFT_PLATFORM_CONFIG.get(str(source or "").strip())
    if not cfg:
        return {"ok": False, "status": "unsupported_source", "message": "目前填入草稿仅支持 BOSS 直聘、智联招聘与前程无忧。"}
    url = str(job_url or "").strip()
    greeting = str(greeting_text or "").strip()
    if not any(url.startswith(prefix) for prefix in cfg["prefixes"]):
        return {"ok": False, "status": "invalid_url", "message": f"岗位链接不属于 {cfg['label']}。"}
    if not greeting:
        return {"ok": False, "status": "empty_greeting", "message": "该岗位尚未生成打招呼语，请先生成后再填入草稿。"}

    input_selectors_json = json.dumps(cfg["input_selectors"], ensure_ascii=True)
    btn_selectors_json = json.dumps(cfg["chat_btn_selectors"], ensure_ascii=True)
    btn_pattern_json = json.dumps(cfg["chat_btn_pattern"], ensure_ascii=True)

    click_chat_js = (
        "JSON.stringify((() => {"
        "const visible = el => Boolean(el && el.getClientRects && el.getClientRects().length);"
        f"const inputSels = {input_selectors_json};"
        "for (const sel of inputSels) { const el = document.querySelector(sel); if (visible(el)) return { state: 'chat_ready', url: location.href }; }"
        f"const re = new RegExp({btn_pattern_json});"
        f"const btns = Array.from(document.querySelectorAll({btn_selectors_json}));"
        "const btn = btns.find(el => visible(el) && re.test((el.innerText || el.textContent || '').trim().replace(/\\s+/g, '')));"
        "if (btn) {"
        "  const label = (btn.innerText || btn.textContent || '').trim();"
        "  btn.click();"
        "  return { state: 'clicked_chat', label, url: location.href };"
        "}"
        "return { state: 'waiting', url: location.href };"
        "})())"
    )

    fill_draft_js = (
        "JSON.stringify((() => {"
        f"const text = {json.dumps(greeting, ensure_ascii=True)};"
        "const visible = el => Boolean(el && el.getClientRects && el.getClientRects().length);"
        f"const selectors = {input_selectors_json};"
        "let box = null;"
        "for (const sel of selectors) { const el = document.querySelector(sel); if (visible(el)) { box = el; break; } }"
        "if (!box) return { filled: false, url: location.href };"
        "box.focus();"
        "if (box.tagName === 'TEXTAREA' || box.tagName === 'INPUT') {"
        "  box.value = text;"
        "  box.dispatchEvent(new Event('input', { bubbles: true }));"
        "  box.dispatchEvent(new Event('change', { bubbles: true }));"
        "} else {"
        "  const sel = window.getSelection();"
        "  const range = document.createRange();"
        "  range.selectNodeContents(box);"
        "  sel.removeAllRanges();"
        "  sel.addRange(range);"
        "  const ok = document.execCommand && document.execCommand('insertText', false, text);"
        "  if (!ok || !(box.innerText || '').trim()) { box.innerText = text; }"
        "  box.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: text }));"
        "}"
        "return { filled: true, length: (box.value || box.innerText || '').length, url: location.href };"
        "})())"
    )

    label = cfg["label"]
    try:
        with httpx.Client(base_url=BRIDGE_URL, timeout=15, trust_env=False) as client:
            health = client.get("/health", timeout=3)
            health.raise_for_status()
            connected = health.json().get("connected") is True
            response = client.get("/new", params={"url": "about:blank"})
            if response.status_code == 500 and not connected:
                return {"ok": False, "status": "authorization_required",
                        "message": "本机 Chrome 尚未授权远程调试，请先打开 chrome://inspect/#remote-debugging 允许调试。"}
            response.raise_for_status()
            identifier = str(response.json().get("targetId") or "")
            if not TAB_ID.fullmatch(identifier):
                return {"ok": False, "status": "unavailable", "message": "Chrome 桥接返回了无效标签页 ID。"}
            tab = ChromeTab(client, identifier, source)
            # Keep tab open intentionally so user can review & press Enter in Chrome!
            try:
                tab.navigate(url, timeout=20)
            except httpx.TimeoutException:
                pass

            clicked = False
            deadline = monotonic() + 14
            while monotonic() < deadline:
                try:
                    snap = tab.read(SNAPSHOT, timeout=4)
                except (httpx.HTTPError, ValueError):
                    sleep(0.6)
                    continue
                if is_verification(snap):
                    return {"ok": False, "status": "verification_required",
                            "message": f"{label}触发了安全验证，请在打开的 Chrome 标签页手动完成验证后重试。",
                            "url": snap.get("url") or url}
                login_state = platform_session(source, snap)
                if login_state == "not_logged_in":
                    return {"ok": False, "status": "not_logged_in",
                            "message": f"本机 Chrome 尚未登录{label}，请在打开的标签页登录后重试。",
                            "url": snap.get("url") or url}
                if not clicked:
                    res = tab.read(click_chat_js, timeout=4)
                    if res.get("state") == "chat_ready":
                        clicked = True
                    elif res.get("state") == "clicked_chat":
                        clicked = True
                        sleep(1.2)
                        continue
                    else:
                        sleep(0.7)
                        continue
                fill_res = tab.read(fill_draft_js, timeout=4)
                if fill_res.get("filled"):
                    return {
                        "ok": True,
                        "status": "draft_filled",
                        "message": f"已在{label}聊天框填入 {fill_res.get('length', len(greeting))} 字草稿（未发送）。请切换到 Chrome 核对并按 Enter 发送。",
                        "url": fill_res.get("url") or url,
                    }
                sleep(0.7)

            return {
                "ok": False,
                "status": "opened_chat_manual_paste",
                "message": f"已在 Chrome 打开{label}岗位页面（未发送），未自动定位到聊天输入框；已保留标签页，可手动点开聊天框粘贴打招呼语。",
                "url": url,
            }
    except (httpx.ConnectError, httpx.ConnectTimeout):
        return {"ok": False, "status": "bridge_unavailable",
                "message": "本机 Chrome 桥接服务未启动（127.0.0.1:3456），请确认已开启本地 Chrome 模式。"}
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        return {"ok": False, "status": "unavailable", "message": f"连接本机 Chrome 失败：{type(exc).__name__}"}


def open_boss_draft_chat(job_url, greeting_text):
    return open_platform_draft_chat("boss", job_url, greeting_text)


def read_zhilian_detail(url):
    parsed = urlsplit(url)
    expected_origin = f"{parsed.scheme}://{parsed.netloc}"
    expected_path = parsed.path.rstrip("/")
    expression = (
        f"JSON.stringify(location.origin === {json.dumps(expected_origin)} "
        f"&& location.pathname.replace(/\\/$/, '') === {json.dumps(expected_path)} "
        f"&& {ZHILIAN_LOGIN} === 'ready' "
        "? document.querySelector('.describtion-card__detail-content, .description-card__detail-content, .job-detail__content, .job-content')"
        "?.innerText.trim().slice(0, 12000) || '' : '')"
    )
    try:
        with open_chrome_tab("zhilian", url) as tab:
            if tab is None:
                return "unavailable", ""
            deadline = monotonic() + 8
            state = "unknown"
            while monotonic() < deadline:
                snapshot = tab.read(SNAPSHOT)
                state = platform_session("zhilian", snapshot)
                if state in {"not_logged_in", "verification_required"}:
                    return state, ""
                if state == "ready":
                    text = tab.read(expression)
                    if text:
                        return "ready", text
                sleep(1)
            return ("no_detail" if state == "ready" else "unknown"), ""
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return "unavailable", ""


def read_boss_detail(url):
    expected_path = urlsplit(url).path.rstrip("/")
    expression = (
        "JSON.stringify(location.origin === 'https://www.zhipin.com' "
        f"&& location.pathname.replace(/\\/$/, '') === {json.dumps(expected_path)} "
        f"&& {BOSS_LOGIN} === 'ready' ? {{"
        "description: (document.querySelector('.job-sec-text, .job-detail-section .text, [class*=\"job-sec-text\"]')?.innerText || '').trim().slice(0, 12000), "
        "salary: (document.querySelector('.job-primary .info-primary .salary, .info-primary .salary, .salary')?.innerText || '').trim().slice(0, 120)"
        "} : null)"
    )
    try:
        with open_chrome_tab("boss", url) as tab:
            if tab is None:
                return "unavailable", "", ""
            deadline = monotonic() + 8
            state = "unknown"
            while monotonic() < deadline:
                snapshot = tab.read(SNAPSHOT)
                state = platform_session("boss", snapshot)
                if state in {"not_logged_in", "verification_required"}:
                    return state, "", ""
                if state == "ready":
                    data = tab.read(expression)
                    if isinstance(data, dict) and data.get("description"):
                        salary = str(data.get("salary") or "").strip()
                        if "*" in salary:
                            salary = ""
                        return "ready", str(data["description"]).strip(), salary
                sleep(1)
            return ("no_detail" if state == "ready" else "unknown"), "", ""
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return "unavailable", "", ""


def read_51job_detail(url):
    parsed = urlsplit(url)
    expected_origin = f"{parsed.scheme}://{parsed.netloc}"
    expected_path = parsed.path.rstrip("/")
    expression = (
        f"JSON.stringify(location.origin === {json.dumps(expected_origin)} "
        f"&& location.pathname.replace(/\\/$/, '') === {json.dumps(expected_path)} ? {{"
        "description: (document.querySelector('.bmsg.job_msg, .job_msg, .job-detail-content, .job-detail, [class*=\"job_msg\"]')?.innerText || '').trim().slice(0, 12000), "
        "salary: (document.querySelector('.cn strong, .job-salary, .sal')?.innerText || '').trim().slice(0, 120)"
        "} : null)"
    )
    try:
        with open_chrome_tab("51job", url) as tab:
            if tab is None:
                return "unavailable", "", ""
            deadline = monotonic() + 8
            while monotonic() < deadline:
                snapshot = tab.read(SNAPSHOT)
                state = platform_session("51job", snapshot)
                if state == "verification_required":
                    return state, "", ""
                data = tab.read(expression)
                if isinstance(data, dict) and data.get("description"):
                    return "ready", str(data["description"]).strip(), str(data.get("salary") or "").strip()
                sleep(1)
            return "no_detail", "", ""
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return "unavailable", "", ""


def read_xiaohongshu_detail(url):
    note_id = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    expression = (
        "JSON.stringify(location.origin === 'https://www.xiaohongshu.com' "
        "&& /^\\/(explore|search_result)\\//.test(location.pathname) "
        f"&& location.pathname.replace(/\\/$/, '').split('/').at(-1) === {json.dumps(note_id)} ? ("
        "[document.querySelector('#detail-title, .note-content .title')?.innerText?.trim(), "
        "document.querySelector('#detail-desc, .note-scroller .desc, .note-text, [class*=\"note-desc\"]')?.innerText?.trim()]"
        ".filter(Boolean).join('\\n').slice(0, 12000)) : '')"
    )
    try:
        with open_chrome_tab("xiaohongshu", url) as tab:
            if tab is None:
                return "unavailable", "", ""
            deadline = monotonic() + 8
            while monotonic() < deadline:
                snapshot = tab.read(SNAPSHOT)
                state = platform_session("xiaohongshu", snapshot)
                if state in {"not_logged_in", "verification_required"}:
                    return state, "", ""
                text = tab.read(expression)
                if text:
                    return "ready", str(text).strip(), ""
                sleep(1)
            return "no_detail", "", ""
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return "unavailable", "", ""


def read_platform_detail(source, url):
    if source == "zhilian":
        state, text = read_zhilian_detail(url)
        return state, text, ""
    if source == "boss":
        return read_boss_detail(url)
    if source == "51job":
        return read_51job_detail(url)
    if source == "xiaohongshu":
        return read_xiaohongshu_detail(url)
    return "no_detail", "", ""


def read_xiaohongshu_images(url):
    note_id = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    expression = r"""JSON.stringify(location.origin === 'https://www.xiaohongshu.com'
        && /^\/(explore|search_result)\//.test(location.pathname)
        && location.pathname.replace(/\/$/, '').split('/').at(-1) === """ + json.dumps(note_id) + r"""
        ? Array.from(document.querySelectorAll('.note-slider img, .note-content .swiper img, .note-container .swiper img'))
            .map(img => img.currentSrc || img.src).filter(Boolean).slice(0, 16)
        : [])"""
    with open_chrome_tab("xiaohongshu", url) as tab:
        if tab is None:
            return []
        deadline = monotonic() + 7
        while monotonic() < deadline:
            images = []
            for image in tab.read(expression, timeout=3):
                address = urlsplit(image)
                host = address.hostname or ""
                if (address.scheme == "https" and not address.username and not address.password and address.port in (None, 443)
                        and any(host == domain or host.endswith("." + domain) for domain in ("xhscdn.com", "xhsimg.com"))
                        and len(image) <= 2048 and image not in images):
                    images.append(image)
            if images:
                return images[:8]
            sleep(1)
    return []


def collect_in_chrome(source, keyword, city, limit, update, profile="general"):
    update("opening", "正在打开已授权的本机 Chrome 搜索标签页。")
    target_url = search_url(source, keyword, city, profile)
    expected = parse_qs(urlsplit(target_url).query)
    job51_label = JOB51_WORK_TYPES.get(profile) if source == "51job" else None
    job51_filter_done = not job51_label
    job51_filter_deadline = None
    deadline = monotonic() + LOGIN_WAIT_SECONDS
    try:
        with open_chrome_tab(source, target_url) as tab:
            if tab is None:
                return "unavailable", "本机 Chrome 桥尚未连接，请确认 Chrome 调试授权已开启。", []
            last_state = None
            opened_login = False
            returned_to_search = False
            while monotonic() < deadline:
                try:
                    snapshot = tab.read(SNAPSHOT, timeout=max(0.1, min(5, deadline - monotonic())))
                except httpx.TimeoutException:
                    continue
                except httpx.HTTPStatusError as error:
                    if error.response.status_code == 400:
                        sleep(1)
                        continue
                    raise
                state = platform_session(source, snapshot)
                tab.url = snapshot["url"]
                address = urlsplit(tab.url)
                same_search = (
                    platform_url(source, tab.url)
                    and address.hostname == tab.host
                    and address.path.rstrip("/") == tab.path
                    and all(parse_qs(address.query).get(key) == value for key, value in expected.items())
                )
                if same_search and state == "ready":
                    if not job51_filter_done:
                        now = monotonic()
                        if job51_filter_deadline is None:
                            job51_filter_deadline = now + 4
                        filter_state = tab.read(
                            f"JSON.stringify(({JOB51_APPLY_FILTER})({json.dumps(job51_label)}))",
                            timeout=max(0.1, min(3, deadline - now)),
                        )
                        if filter_state == "clicked":
                            job51_filter_done = True
                            sleep(max(0, min(1.5, deadline - monotonic())))
                            continue
                        if filter_state == "applied" or monotonic() >= job51_filter_deadline:
                            job51_filter_done = True
                        else:
                            sleep(max(0, min(0.6, deadline - monotonic())))
                            continue
                    rows = cards(tab, source, limit)
                    if rows:
                        return "succeeded", f"从本机 Chrome 读取 {len(rows)} 条岗位。", rows
                remaining = deadline - monotonic()
                if state != last_state:
                    if state == "ready":
                        update("running", f"{SOURCES[source][0]} 已登录，正在读取搜索结果。")
                    else:
                        update("waiting_user", f"请在 Chrome 的{SOURCES[source][0]}标签页完成登录或验证，最多等待 2 分钟。")
                    last_state = state
                if remaining > 2 and state == "not_logged_in" and not opened_login and source in {"boss", "51job"}:
                    opened_login = True
                    try:
                        tab.navigate(LOGIN_URLS[source], timeout=min(12, remaining))
                    except httpx.TimeoutException:
                        pass
                elif remaining > 2 and state == "ready" and not same_search and not returned_to_search:
                    returned_to_search = True
                    try:
                        tab.navigate(target_url, timeout=min(12, remaining))
                    except httpx.TimeoutException:
                        pass
                sleep(max(0, min(1, deadline - monotonic())))
            if last_state == "ready":
                return "empty", "登录已通过，本轮没有读取到可用结果。", []
            return "login_timeout", f"{SOURCES[source][0]} 在 2 分钟内未完成登录或验证，本轮暂不可用。", []
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        logger.exception("Local Chrome connector could not read the recruitment search")
        return "unavailable", "无法读取本机 Chrome，请确认浏览器已打开并已授权本机连接。", []

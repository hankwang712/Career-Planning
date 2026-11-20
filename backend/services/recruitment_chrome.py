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

from .recruitment_sources import SOURCES, cards, platform_url, search_url


logger = logging.getLogger(__name__)
BRIDGE_URL = "http://127.0.0.1:3456"
CHROME_AUTHORIZATION_URL = "chrome://inspect/#remote-debugging"
_authorization_lock = Lock()
_authorization_opened_at = float("-inf")
TAB_ID = re.compile(r"[0-9a-fA-F]{32}")
CHROME_SOURCES = {
    "boss": ("www.zhipin.com", "/web/geek/jobs"),
    "51job": ("we.51job.com", "/pc/search"),
    "zhilian": ("www.zhaopin.com", "/jobs"),
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
    if (location.origin !== 'https://www.zhaopin.com') return 'unknown';
    const visitor = document.querySelector('.home-header__c-no-login, .c-login__top__no-login');
    if (visitor?.getClientRects().length) return 'not_logged_in';
    const account = document.querySelector('.c-login__top__name, .c-login__top__img, .home-header__c-login');
    if (account?.getClientRects().length) return 'ready';
    const header = document.querySelector('.home-header__right, .c-login__top, header');
    const controls = Array.from(header?.querySelectorAll('a, button, [role="button"]') || []);
    const label = (node) => node.textContent.trim().replace(/\s+/g, '');
    if (controls.some(node => ['退出', '退出登录'].includes(label(node)))) return 'ready';
    if (controls.some(node => ['登录', '登录/注册', '登录／注册'].includes(label(node)) && node.getClientRects().length))
        return 'not_logged_in';
    return 'unknown';
})()"""
SNAPSHOT = """JSON.stringify({
    url: location.origin + location.pathname + location.search,
    title: document.title,
    verification: !!document.querySelector('#nc_1_n1z')?.getClientRects().length,
    zhilianLogin: """ + ZHILIAN_LOGIN + """,
    bossLogin: document.querySelector('.btn-sign')?.getClientRects().length ? 'not_logged_in'
        : document.querySelector('.user-nav')?.getClientRects().length ? 'ready' : 'unknown',
    job51Login: document.querySelector('.user-info, .header-avatar')?.getClientRects().length ? 'ready'
        : Array.from(document.querySelectorAll('a, button')).some(el =>
            el.getClientRects().length && ['登录/注册', '登录／注册', '登录'].includes(el.innerText.trim()))
            ? 'not_logged_in' : 'unknown',
    xhsLogin: document.querySelector('button.login-btn, .login-container .qrcode')?.getClientRects().length ? 'not_logged_in'
        : document.querySelector('a.link-wrapper[href^="/user/profile"], .user-avatar, .side-bar-user')?.getClientRects().length
            ? 'ready' : 'unknown'
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


def read_zhilian_detail(url):
    expected_path = urlsplit(url).path.rstrip("/")
    expression = (
        "JSON.stringify(location.origin === 'https://www.zhaopin.com' "
        f"&& location.pathname.replace(/\\/$/, '') === {json.dumps(expected_path)} "
        f"&& {ZHILIAN_LOGIN} === 'ready' "
        "? document.querySelector('.describtion-card__detail-content, .description-card__detail-content')"
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


def collect_in_chrome(source, keyword, city, limit, update):
    update("opening", "正在打开已授权的本机 Chrome 搜索标签页。")
    target_url = search_url(source, keyword, city)
    expected = parse_qs(urlsplit(target_url).query)
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

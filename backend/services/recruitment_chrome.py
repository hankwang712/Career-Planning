"""Read recruitment results in a new tab of an explicitly enabled local Chrome bridge."""

from contextlib import contextmanager
import json
import logging
import os
import re
from time import monotonic, sleep
from urllib.parse import parse_qs, urlsplit

import httpx

from .recruitment_sources import SOURCES, cards, platform_url, search_url


logger = logging.getLogger(__name__)
BRIDGE_URL = "http://127.0.0.1:3456"
TAB_ID = re.compile(r"[0-9a-fA-F]{32}")
CHROME_SOURCES = {"boss": ("www.zhipin.com", "/web/geek/jobs"), "zhilian": ("www.zhaopin.com", "/jobs")}
ZHILIAN_LOGIN_URL = "https://www.zhaopin.com/jobs/"
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
    zhilianLogin: """ + ZHILIAN_LOGIN + """
})"""
ZHILIAN_LOGIN_MESSAGES = {
    "ready": "智联已登录，可以开始采集。",
    "not_logged_in": "尚未登录智联。请在当前 Chrome 登录官网，再检查。",
    "verification_required": "智联需要安全验证。请在官网完成验证，再检查。",
    "unknown": "暂未确认智联登录状态。请先在官网确认登录，再检查。",
    "unavailable": "无法连接本机 Chrome，请确认 Chrome 已打开并授权本机连接。",
}


def use_local_chrome():
    configured = os.getenv("CAREER_RECRUITMENT_USE_LOCAL_CHROME", os.getenv("CAREER_BOSS_USE_LOCAL_CHROME", ""))
    return configured.strip().lower() in {"1", "true"}


class ChromeTab:
    def __init__(self, client, identifier, source):
        self.client = client
        self.identifier = identifier
        self.url = ""
        self.source = source
        self.host, self.path = CHROME_SOURCES[source]

    def read(self, expression):
        response = self.client.post("/eval", params={"target": self.identifier}, content=expression)
        response.raise_for_status()
        return json.loads(response.json()["value"])

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
        if health.json().get("connected") is not True:
            yield None
            return
        response = client.get("/new", params={"url": target_url})
        response.raise_for_status()
        identifier = str(response.json().get("targetId") or "")
        if not TAB_ID.fullmatch(identifier):
            yield None
            return
        try:
            yield ChromeTab(client, identifier, source)
        finally:
            try:
                client.get("/close", params={"target": identifier}, timeout=3).raise_for_status()
            except httpx.HTTPError:
                logger.warning("Could not close the owned recruitment search tab")


def is_verification(snapshot):
    return snapshot["verification"] or any(word in snapshot["title"].lower() for word in (
        "安全验证", "安全限制", "请稍候", "security verification",
    ))


def zhilian_session(snapshot):
    if is_verification(snapshot):
        return "verification_required"
    if urlsplit(snapshot["url"]).hostname == "passport.zhaopin.com":
        return "not_logged_in"
    return snapshot.get("zhilianLogin", "unknown")


def check_zhilian_login():
    try:
        with open_chrome_tab("zhilian", ZHILIAN_LOGIN_URL) as tab:
            if tab is None:
                return "unavailable"
            deadline = monotonic() + 8
            while monotonic() < deadline:
                state = zhilian_session(tab.read(SNAPSHOT))
                if state != "unknown":
                    return state
                sleep(1)
            return "unknown"
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
                state = zhilian_session(snapshot)
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


def collect_in_chrome(source, keyword, city, limit, update):
    update("opening", "正在打开已授权的本机 Chrome 搜索标签页。")
    target_url = search_url(source, keyword, city)
    expected = parse_qs(urlsplit(target_url).query)
    try:
        with open_chrome_tab(source, target_url) as tab:
            if tab is None:
                return "unavailable", "本机 Chrome 桥尚未连接，请确认 Chrome 调试授权已开启。", []
            deadline = monotonic() + (20 if source == "zhilian" else 100)
            login_observed = source != "zhilian"
            waiting = False
            while monotonic() < deadline:
                try:
                    snapshot = tab.read(SNAPSHOT)
                except httpx.HTTPStatusError as error:
                    if error.response.status_code == 400:
                        sleep(1)
                        continue
                    raise
                if source == "zhilian":
                    state = zhilian_session(snapshot)
                    if state in {"not_logged_in", "verification_required"}:
                        return "login_required", ZHILIAN_LOGIN_MESSAGES[state], []
                    login_observed = state == "ready"
                tab.url = snapshot["url"]
                address = urlsplit(tab.url)
                same_search = (
                    platform_url(source, tab.url)
                    and address.hostname == tab.host
                    and address.path.rstrip("/") == tab.path
                    and all(parse_qs(address.query).get(key) == value for key, value in expected.items())
                )
                gated = is_verification(snapshot) or "请登录" in snapshot["title"]
                if same_search and not gated and login_observed:
                    rows = cards(tab, source, limit)
                    if rows:
                        return "succeeded", f"从本机 Chrome 读取 {len(rows)} 条岗位。", rows
                if not waiting:
                    update("waiting_user", f"正在等待 {SOURCES[source][0]} 搜索结果。")
                    waiting = True
                sleep(1)
            if not login_observed:
                return "login_required", ZHILIAN_LOGIN_MESSAGES["unknown"], []
            return "blocked", "Chrome 搜索标签页在等待时限内未显示匹配的岗位。", []
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        logger.exception("Local Chrome connector could not read the recruitment search")
        return "unavailable", "无法读取本机 Chrome，请确认浏览器已打开并已授权本机连接。", []

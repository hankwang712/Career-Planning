"""Read BOSS results in a new tab of an explicitly enabled local Chrome bridge."""

import json
import logging
import os
import re
from time import monotonic, sleep
from urllib.parse import parse_qs, urlsplit

import httpx

from .recruitment_sources import cards, platform_url, search_url


logger = logging.getLogger(__name__)
BRIDGE_URL = "http://127.0.0.1:3456"
TAB_ID = re.compile(r"[0-9a-fA-F]{32}")
SNAPSHOT = """JSON.stringify({
    url: location.origin + location.pathname + location.search,
    title: document.title,
    verification: !!document.querySelector('#nc_1_n1z')?.getClientRects().length
})"""


def use_local_chrome():
    return os.getenv("CAREER_BOSS_USE_LOCAL_CHROME", "").strip().lower() in {"1", "true"}


class ChromeTab:
    def __init__(self, client, identifier):
        self.client = client
        self.identifier = identifier
        self.url = ""

    def read(self, expression):
        response = self.client.post("/eval", params={"target": self.identifier}, content=expression)
        response.raise_for_status()
        return json.loads(response.json()["value"])

    def evaluate(self, script, options):
        arguments = json.dumps(options, ensure_ascii=True)
        return self.read("JSON.stringify(location.origin === 'https://www.zhipin.com' "
                         "&& location.pathname === '/web/geek/jobs' "
                         f"? ({script})({arguments}) : [])")


def collect_boss_in_chrome(keyword, city, limit, update):
    update("opening", "正在打开已授权的本机 Chrome 搜索标签页。")
    target_url = search_url("boss", keyword, city)
    expected = parse_qs(urlsplit(target_url).query)
    try:
        with httpx.Client(base_url=BRIDGE_URL, timeout=15, trust_env=False) as client:
            health = client.get("/health", timeout=3)
            health.raise_for_status()
            if health.json().get("connected") is not True:
                return "unavailable", "本机 Chrome 桥尚未连接，请确认 Chrome 调试授权已开启。", []
            response = client.get("/new", params={"url": target_url})
            response.raise_for_status()
            identifier = str(response.json().get("targetId") or "")
            if not TAB_ID.fullmatch(identifier):
                return "unavailable", "未能建立 Chrome 搜索标签页。", []
            tab = ChromeTab(client, identifier)
            try:
                deadline = monotonic() + 100
                waiting = False
                while monotonic() < deadline:
                    try:
                        snapshot = tab.read(SNAPSHOT)
                    except httpx.HTTPStatusError as error:
                        if error.response.status_code == 400:
                            sleep(1)
                            continue
                        raise
                    tab.url = snapshot["url"]
                    address = urlsplit(tab.url)
                    same_search = (
                        platform_url("boss", tab.url)
                        and address.path.rstrip("/") == "/web/geek/jobs"
                        and all(parse_qs(address.query).get(key) == value for key, value in expected.items())
                    )
                    title = snapshot["title"]
                    gated = snapshot["verification"] or any(
                        word in title.lower() for word in ("安全验证", "安全限制", "请稍候", "请登录", "security verification")
                    )
                    if same_search and not gated:
                        rows = cards(tab, "boss", limit)
                        if rows:
                            return "succeeded", f"从已登录的 Chrome 读取 {len(rows)} 条岗位。", rows
                    if not waiting:
                        update("waiting_user", "正在等待 BOSS 搜索结果。如出现验证，请在新开的 BOSS 标签页处理。")
                        waiting = True
                    sleep(1)
                return "blocked", "Chrome 搜索标签页在等待时限内未显示匹配的 BOSS 岗位。", []
            finally:
                try:
                    client.get("/close", params={"target": identifier}, timeout=3).raise_for_status()
                except httpx.HTTPError:
                    logger.warning("Could not close the owned BOSS search tab")
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        logger.exception("Local Chrome connector could not read the BOSS search")
        return "unavailable", "无法读取本机 Chrome，请确认浏览器已打开并已授权本机连接。", []

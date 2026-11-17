"""真实浏览器冒烟：登录后的各页面能加载全部脚本，且没有脚本错误。

需要 Playwright 和 Chromium；不可用时跳过（CI 与本机可用 PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH 指定浏览器）。
测试在本进程里起一个真实的 uvicorn，把测试账号的会话 cookie 交给浏览器，所以走的是和线上一样的页面与脚本。
"""
import os
import socket
import threading
import time

import pytest

playwright_sync = pytest.importorskip("playwright.sync_api")

PAGES = ["/", "/user-center", "/user-center/career-report/polish", "/resume-report", "/test-result", "/test-runner"]

# 页面加载后必须挂在 window 上的函数：其它脚本、内联事件和测试都按这些名字调用。
REQUIRED_GLOBALS = [
    "requestJson", "fetchScopedUserState", "saveScopedUserState", "startCareerReportGeneration",
    "pollCareerReportJob", "openResumeReportModal", "getCareerReportStateSafe", "showSection",
]


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def live_server(server):
    import uvicorn

    port = free_port()
    config = uvicorn.Config(server.asgi_app, host="127.0.0.1", port=port, log_level="warning")
    instance = uvicorn.Server(config)
    thread = threading.Thread(target=instance.run, daemon=True)
    thread.start()
    deadline = time.time() + 20
    while not instance.started and time.time() < deadline:
        time.sleep(0.1)
    assert instance.started, "测试服务器没有启动"
    yield f"http://127.0.0.1:{port}"
    instance.should_exit = True
    thread.join(timeout=10)


@pytest.fixture(scope="module")
def browser():
    with playwright_sync.sync_playwright() as playwright:
        try:
            launched = playwright.chromium.launch(
                headless=True, executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH") or None)
        except Exception as exc:  # 没有安装浏览器
            pytest.skip(f"Chromium 不可用：{str(exc).splitlines()[0]}")
        yield launched
        launched.close()


@pytest.fixture()
def logged_in_page(browser, live_server, make_account):
    account = make_account("browser")
    cookie = account.client.get_cookie("session")
    assert cookie is not None, "测试账号没有会话 cookie"
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    context.add_cookies([{"name": "session", "value": cookie.value, "url": live_server}])
    page = context.new_page()
    # 页面里引用的外部字体、统计等不属于本测试关心的内容。
    page.route("**/*", lambda route: route.abort() if not route.request.url.startswith(live_server) else route.continue_())
    yield page
    context.close()


def collect_errors(page):
    errors = []
    page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))

    def on_console(message):
        # 被测试主动拦截的外部资源会在控制台报 ERR_FAILED，不是页面自身的问题。
        origin = (message.location or {}).get("url", "")
        if message.type == "error" and (not origin or origin.startswith("http://127.0.0.1")):
            errors.append(f"console: {message.text} ({origin})")

    page.on("console", on_console)
    page.on("requestfailed", lambda request: errors.append(f"requestfailed: {request.url}") if request.url.startswith("http://127.0.0.1") else None)
    return errors


@pytest.mark.parametrize("path", PAGES)
def test_page_loads_without_script_errors(logged_in_page, live_server, path):
    errors = collect_errors(logged_in_page)
    response = logged_in_page.goto(live_server + path, wait_until="load")
    assert response.status == 200
    logged_in_page.wait_for_timeout(1500)
    # 服务端 404/500 的资源请求在控制台里表现为 "Failed to load resource"，一并算作错误。
    assert errors == [], f"{path}:\n" + "\n".join(errors)


def test_workspace_exposes_the_functions_other_scripts_call(logged_in_page, live_server):
    errors = collect_errors(logged_in_page)
    logged_in_page.goto(live_server + "/", wait_until="load")
    logged_in_page.wait_for_timeout(1500)
    missing = logged_in_page.evaluate(
        "names => names.filter(name => typeof window[name] !== 'function')", REQUIRED_GLOBALS)
    assert missing == [], f"window 上缺少：{missing}"
    assert errors == [], "\n".join(errors)


def test_user_center_exposes_report_generation(logged_in_page, live_server):
    logged_in_page.goto(live_server + "/user-center", wait_until="load")
    logged_in_page.wait_for_timeout(1500)
    missing = logged_in_page.evaluate(
        "names => names.filter(name => typeof window[name] !== 'function')",
        ["startCareerReportGeneration", "requestJson", "fetchScopedUserState"])
    assert missing == []


def test_switching_sections_works(logged_in_page, live_server):
    errors = collect_errors(logged_in_page)
    logged_in_page.goto(live_server + "/", wait_until="load")
    logged_in_page.wait_for_timeout(1200)
    for section in ("jobs", "profile", "community", "dashboard"):
        logged_in_page.evaluate("section => window.showSection(section)", section)
        logged_in_page.wait_for_timeout(400)
    assert errors == [], "\n".join(errors)

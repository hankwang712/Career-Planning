"""真实浏览器冒烟：登录后的各页面能加载全部脚本，且没有脚本错误。

需要 Playwright 和 Chromium；不可用时跳过（CI 与本机可用 PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH 指定浏览器）。
测试在本进程里起一个真实的 uvicorn，把测试账号的会话 cookie 交给浏览器，所以走的是和线上一样的页面与脚本。
"""
import os
import socket
import threading
import time

import pytest
from services import db, runtime_settings

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


def test_workspace_setup_and_console_in_browser(browser, live_server, make_account, monkeypatch, tmp_path):
    monkeypatch.setattr(runtime_settings, "APP_DATA_DIR", tmp_path)
    account = make_account("setup-browser")
    with db._get_conn() as conn:
        conn.execute("UPDATE users SET role = 'super_admin' WHERE username = ?", (account.email,))
    context = browser.new_context(viewport={"width": 390, "height": 844})
    try:
        cookie = account.client.get_cookie("session")
        context.add_cookies([{"name": "session", "value": cookie.value, "url": live_server}])
        page = context.new_page()
        page.route("**/*", lambda route: route.abort() if not route.request.url.startswith(live_server) else route.continue_())
        errors = collect_errors(page)
        page.goto(live_server)
        guide = page.get_by_role("dialog", name="新手引导")
        guide.wait_for(timeout=8000)
        guide.get_by_role("link", name="去系统配置 →").click()
        page.locator("#AI_CHAT_BASE_URL").fill("https://provider.example/v1")
        page.locator("#AI_CHAT_API_KEY").fill("browser-test-key")
        page.locator("#AI_CHAT_MODEL").fill("test-chat")
        page.get_by_role("button", name="保存配置").click()
        page.get_by_text("对话模型已配置 3/3").wait_for()
        assert page.locator("#AI_CHAT_API_KEY").input_value() == ""
        page.route("**/api/system-settings/test/chat", lambda route: route.fulfill(
            json={"message": "连通性测试通过。", "duration_ms": 12}))
        page.locator("[data-test-group=chat]").click()
        page.get_by_text("连通性测试通过。").wait_for()
        page.get_by_role("link", name="PostgreSQL / pgvector").click()
        page.get_by_text("POSTGRES_PASSWORD", exact=True).wait_for()
        page.get_by_role("button", name="›_ 白盒控制台").click()
        page.locator("[data-console-filter]").fill("PATCH")
        page.locator("[data-console-entries] li").filter(has_text="PATCH /api/system-settings/models").wait_for()
        page.get_by_role("button", name="收起控制台").click()
        assert page.locator("#workspaceConsolePanel").is_hidden()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert errors == [], "\n".join(errors)
    finally:
        context.close()


def test_user_center_exposes_report_generation(logged_in_page, live_server):
    logged_in_page.goto(live_server + "/user-center", wait_until="load")
    logged_in_page.wait_for_timeout(1500)
    missing = logged_in_page.evaluate(
        "names => names.filter(name => typeof window[name] !== 'function')",
        ["startCareerReportGeneration", "requestJson", "fetchScopedUserState"])
    assert missing == []


def test_resume_workshop_import_preview_and_reopen(logged_in_page, live_server):
    page = logged_in_page
    errors = collect_errors(page)
    page.goto(live_server + "/user-center")
    sidebar_width = page.locator(".uc-workspace-sidebar").bounding_box()["width"]
    page.get_by_role("link", name="我的简历").click()
    assert page.locator(".uc-workspace-sidebar").bounding_box()["width"] == sidebar_width
    assert page.get_by_role("link", name="我的简历").get_attribute("aria-current") == "page"
    work = page.get_by_role("button", name="工作经历", exact=True)
    assert work.get_attribute("aria-expanded") == "false"
    work.click()
    assert work.get_attribute("aria-expanded") == "true"
    page.get_by_role("button", name="导入简历").click()
    dialog = page.get_by_role("dialog", name="导入简历")
    dialog.locator("[name=source]").select_option("text")
    dialog.locator("[name=text]").fill("姓名：林晓\n## 工作经验\n开发履历编辑功能。")
    dialog.get_by_role("button", name="识别并填入").click()
    page.get_by_text("已填入，请检查后保存。").wait_for()
    assert page.locator("[data-contact=name]").input_value() == "林晓"
    assert page.locator("[data-section-content]").nth(1).input_value() == "开发履历编辑功能。"
    summary = page.locator(".re-section").first
    summary.locator("[data-section-content]").fill("产品开发")
    summary.locator("[data-section-content]").select_text()
    summary.get_by_role("button", name="粗体").click()
    assert summary.locator("[data-section-content]").input_value() == "**产品开发**"
    page.locator("#resumeQuickField").select_option("GitHub")
    page.get_by_role("textbox", name="字段内容").fill("demo-account")
    page.get_by_role("button", name="智能排版").click()
    preview = page.get_by_role("dialog", name="简历预览")
    preview.get_by_role("img", name="简历第 1 页").wait_for()
    preview.get_by_role("button", name="关闭预览").click()
    page.locator("[name=title]").fill("产品开发简历")
    page.get_by_role("button", name="保存", exact=True).click()
    page.get_by_text("已保存的简历", exact=True).wait_for()
    page.locator("#resumeVersions summary").click()
    page.get_by_role("button", name="产品开发简历").wait_for()
    page.reload()
    page.get_by_text("已保存的简历", exact=True).wait_for()
    assert page.get_by_role("textbox", name="字段内容").input_value() == "demo-account"
    page.locator("[data-contact=name]").fill("林晓更新")
    page.get_by_role("button", name="保存", exact=True).click()
    page.get_by_text("已保存的简历", exact=True).wait_for()
    with page.expect_download() as downloaded:
        page.get_by_role("button", name="导出 PDF").click()
    assert downloaded.value.suggested_filename == "产品开发简历.pdf"
    page.get_by_role("link", name="账户设置").click()
    page.get_by_role("button", name="账户设置").and_(page.locator("[aria-current=page]")).wait_for()
    assert errors == [], "\n".join(errors)


def test_switching_sections_works(logged_in_page, live_server):
    errors = collect_errors(logged_in_page)
    logged_in_page.goto(live_server + "/", wait_until="load")
    logged_in_page.wait_for_timeout(1200)
    for section in ("jobs", "profile", "community", "dashboard"):
        logged_in_page.evaluate("section => window.showSection(section)", section)
        logged_in_page.wait_for_timeout(400)
    assert errors == [], "\n".join(errors)


def test_resume_scores_preserve_unknown_in_actual_page(logged_in_page, live_server):
    errors = collect_errors(logged_in_page)
    logged_in_page.goto(live_server + "/resume-report", wait_until="load")
    result = logged_in_page.evaluate("""() => {
      const profile = {score_method:'canonical_skill_evidence_coverage',
                       capability_scores:{matching:50, execution:null, communication:null}};
      const matcher = {matched_keywords:['Python'], missing_keywords:['Java']};
      const gauge = resumeGaugeCardHtml(profile, matcher, 'job_match', []);
      const metrics = renderResumeReportHeroMetrics(profile, matcher, 'job_match', []);
      return {gauge, metrics, zero:resumeScoreLabel(0), unknown:resumeScoreLabel(null)};
    }""")
    assert "50%" in result["gauge"] and "50%" in result["metrics"]
    assert "待验证" in result["metrics"] and "null%" not in result["metrics"]
    assert result["zero"] == "0%" and result["unknown"] == "待验证"
    assert errors == [], "\n".join(errors)

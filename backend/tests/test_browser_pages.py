"""真实浏览器冒烟：登录后的各页面能加载全部脚本，且没有脚本错误。

需要 Playwright 和 Chromium；不可用时跳过（CI 与本机可用 PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH 指定浏览器）。
测试在本进程里起一个真实的 uvicorn，把测试账号的会话 cookie 交给浏览器，所以走的是和线上一样的页面与脚本。
"""
import os
import socket
import threading
import time
from io import BytesIO

import pymupdf
import pytest
from PIL import Image, ImageDraw
from services import db, runtime_settings

playwright_sync = pytest.importorskip("playwright.sync_api")

PAGES = ["/", "/user-center/workspace#report-workspace", "/user-center/career-report/polish", "/resume-report", "/test-result", "/test-runner"]

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
    def on_request_failed(request):
        if request.url.startswith("http://127.0.0.1") and request.failure != "net::ERR_ABORTED":
            errors.append(f"requestfailed: {request.url}")

    page.on("requestfailed", on_request_failed)
    return errors


@pytest.mark.parametrize("path", PAGES)
def test_page_loads_without_script_errors(logged_in_page, live_server, path):
    errors = collect_errors(logged_in_page)
    response = logged_in_page.goto(live_server + path, wait_until="load")
    assert response.status == 200
    logged_in_page.wait_for_timeout(1500)
    # 服务端 404/500 的资源请求在控制台里表现为 "Failed to load resource"，一并算作错误。
    assert errors == [], f"{path}:\n" + "\n".join(errors)


def test_fresh_browser_opens_the_local_workspace(browser, live_server):
    page = browser.new_page(viewport={"width": 1440, "height": 900})

    def topbar_signature(navigation):
        page.evaluate("document.fonts.ready")
        return navigation.evaluate("""nav => [
            '.topbar-row', '.nav-tab-strip', '[data-section="dashboard"]', '.topbar-guide-entry',
            '.ca-settings-entry', '#navWorkspaceToggle'
        ].map(selector => {
            const element = nav.querySelector(selector);
            const { x, width, height } = element.getBoundingClientRect();
            return [Math.round(x), Math.round(width), Math.round(height), getComputedStyle(element).textDecorationLine];
        })""")

    try:
        page.add_init_script("localStorage.setItem('tg_done', '1')")
        page.route("**/*", lambda route: route.continue_() if route.request.url.startswith(live_server) else route.abort())
        errors = collect_errors(page)
        page.goto(live_server)
        page.wait_for_url("**/recruitment")
        assert page.get_by_role("heading", name="岗位全链路流水线").is_visible()
        navigation = page.get_by_role("navigation", name="主导航")
        expected_topbar = topbar_signature(navigation)
        avatar_initial = navigation.locator("#currentUserAvatar").inner_text()
        assert [link.strip() for link in navigation.locator(".nav-tab-strip a").all_text_contents()] == [
            "首页", "岗位探索", "测评中心", "规划报告",
        ]
        assert navigation.get_by_role("link", name="岗位探索").get_attribute("aria-current") == "page"
        navigation.get_by_role("button", name="工作区菜单").click()
        assert navigation.get_by_role("menuitem", name="个人中心").is_visible()
        menu_links = navigation.get_by_role("menuitem").all_text_contents()
        navigation.get_by_role("link", name="首页", exact=True).click()
        page.locator("#dashboard").wait_for(state="visible")
        page.wait_for_function("window.getCurrentUser?.()?.username")
        assert page.locator("#startupScreen, #loginForm, #logoutBtn").count() == 0
        page.get_by_role("button", name="关闭引导").click()
        assert topbar_signature(navigation) == expected_topbar
        assert navigation.locator("#currentUserAvatar").inner_text() == avatar_initial
        page.get_by_role("button", name="工作区菜单").click()
        assert page.get_by_role("menuitem", name="个人中心").is_visible()
        assert navigation.get_by_role("menuitem").all_text_contents() == menu_links
        page.keyboard.press("Escape")
        for title in ("测评中心", "规划报告"):
            tab = navigation.get_by_role("button", name=title, exact=True)
            tab.click()
            assert tab.get_attribute("aria-current") == "page"
            assert topbar_signature(navigation) == expected_topbar
        navigation = page.get_by_role("navigation", name="主导航")
        navigation.get_by_role("link", name="岗位探索").click()
        page.wait_for_url("**/recruitment")
        assert page.get_by_role("heading", name="岗位全链路流水线").is_visible()
        assert navigation.get_by_role("link", name="岗位探索").get_attribute("aria-current") == "page"
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth") == 390
        narrow_topbar = topbar_signature(navigation)
        navigation.get_by_role("link", name="测评中心").click()
        page.locator("#profile").wait_for(state="visible")
        assert topbar_signature(navigation) == narrow_topbar
        assert errors == []
    finally:
        page.close()


def test_dashboard_search_uses_the_entered_keyword(logged_in_page, live_server):
    page = logged_in_page
    page.goto(live_server + "/main.html")
    overview = page.get_by_role("region", name="职业工作台")
    tools = page.get_by_role("region", name="求职工具")
    assert overview.is_visible() and tools.is_visible()
    assert page.get_by_text("功能示意", exact=True).count() == 0
    assert overview.get_by_role("button", name="使用引导").count() == 0
    page.wait_for_function("document.querySelector('.dashboard-workspace-panorama').naturalWidth > 0")
    assert page.locator("#dashboard").evaluate("(el) => getComputedStyle(el).backgroundSize").startswith("28px 28px, 28px 28px")
    assert tools.get_by_role("link", name="岗位探索").get_attribute("href") == "/recruitment"
    page.get_by_role("button", name="关闭引导").click()
    overview.get_by_role("button", name="快速开始").click()
    page.get_by_role("dialog", name="新手引导").get_by_role("button", name="查看行业快报 →").click()
    assert page.get_by_role("navigation", name="主导航").get_by_role("link", name="行业资讯", exact=True).count() == 0
    page.wait_for_function("document.getElementById('careerNewsBoard').getBoundingClientRect().top < innerHeight")
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth") == 390
    entry = page.get_by_role("button", name="新手引导")
    entry.click()
    guide = page.get_by_role("dialog", name="新手引导")
    assert guide.get_by_role("listitem").count() == 6
    page.keyboard.press("Escape")
    guide.wait_for(state="hidden")
    search = overview.get_by_role("searchbox", name="搜索岗位")
    search.fill("数据分析")
    search.press("Enter")
    page.wait_for_url("**/recruitment?*")
    assert page.evaluate("new URLSearchParams(location.search).get('q')") == "数据分析"
    assert page.locator('input[aria-label="搜索岗位"], input[aria-label="搜索结果"]').input_value() == "数据分析"
    page.get_by_role("link", name="新手引导").click()
    guide.wait_for()
    with page.expect_request(lambda request: request.url.endswith("/recruitment")):
        guide.get_by_role("link", name="进入岗位探索 →").click()


def test_news_features_real_publisher_icons_and_rotates_the_cover(logged_in_page, live_server, monkeypatch):
    from services import site

    cover = "https://images.example.test/cover.jpg"
    items = [
        {"title": "AI 开发工具进展", "source_name": "InfoQ", "image_url": cover},
        {"title": "招聘观察报告", "source_name": "IT之家"},
        {"title": "科技行业动态与软件开发团队的工作流程更新研究，进一步分析开发效率和岗位变化", "source_name": "Ars Technica"},
        {"title": "如何准备面试", "source_name": "The Verge"},
        {"title": "AI 网络安全动态", "source_name": "IT之家"},
    ]
    for index, item in enumerate(items):
        item.update(url=f"https://example.test/news/{index}", summary="来自原文的摘要",
                    published_at=f"2026-11-{18-index:02d}T12:00:00+08:00", published_label="11-18 12:00")
    monkeypatch.setattr(site, "get_career_news_payload", lambda: {"visible_items": items})
    page = logged_in_page
    image_bytes = BytesIO()
    Image.new("RGB", (32, 12), "#c4d3ed").save(image_bytes, format="PNG")
    page.route(cover, lambda route: route.fulfill(body=image_bytes.getvalue(), content_type="image/png"))
    page.goto(live_server + "/main.html")
    board = page.locator("#careerNewsBoard")
    lead = board.locator(".nd-deck .nd-story--lead")
    assert lead.locator(".nd-source-logo").get_attribute("src").endswith("/infoq.png")
    assert lead.locator(".nd-feature-image").get_attribute("src") == cover
    sides = board.locator(".nd-deck .nd-story--side")
    assert sides.last.bounding_box()["x"] > sides.first.bounding_box()["x"] > lead.bounding_box()["x"]
    assert sides.first.locator(".nd-feature-media").count() == 0
    cards = board.locator(".nd-deck .nd-story")
    assert len({round(card.bounding_box()["height"]) for card in cards.all()}) == 1
    for selector in (".nd-story-title", ".nd-story-summary", ".nd-story-bottom"):
        assert len({round(card.locator(selector).bounding_box()["y"]) for card in cards.all()}) == 1
    pause = board.locator("#careerNewsPauseBtn")
    pause.evaluate("(button) => button.click()")
    lead.locator(".nd-feature-image").dispatch_event("error")
    assert lead.locator(".nd-feature-media").count() == 0
    assert sides.last.bounding_box()["x"] > sides.first.bounding_box()["x"] > lead.bounding_box()["x"]
    assert board.locator("#careerNewsNextBtn").evaluate("""(button) => {
        const previous = document.querySelector('.nd-deck').children[1];
        const start = previous.getBoundingClientRect().left;
        button.click();
        const lead = document.querySelector('.nd-deck .nd-story--lead');
        const animation = lead.getAnimations().find(item =>
            item.effect.getKeyframes().some(frame => frame.transform));
        if (!animation || previous.href !== lead.href) return false;
        animation.currentTime = 0;
        const initial = lead.getBoundingClientRect().left;
        animation.currentTime = 240;
        const midpoint = lead.getBoundingClientRect().left;
        const target = lead.parentElement.getBoundingClientRect().left;
        return Math.abs(initial - start) < 1 && target < midpoint && midpoint < initial;
    }""")
    board.locator(".nd-deck--sliding").wait_for(state="detached")
    assert board.locator(".nd-deck-exit-layer").count() == 0
    lead.get_by_role("heading", name="招聘观察报告").wait_for()
    assert lead.locator(".nd-source-logo").get_attribute("src").endswith("/ithome.png")
    assert lead.locator(".nd-feature-media").count() == 0
    assert sides.last.bounding_box()["x"] > sides.first.bounding_box()["x"] > lead.bounding_box()["x"]
    summary = lead.locator(".nd-story-summary").bounding_box()
    byline = lead.locator(".nd-story-bottom").bounding_box()
    assert byline["y"] - (summary["y"] + summary["height"]) <= 20
    page.emulate_media(reduced_motion="reduce")
    assert board.locator("#careerNewsPrevBtn").evaluate("""(button) => {
        button.click();
        return document.querySelector('.nd-story--lead .nd-story-title').textContent === 'AI 开发工具进展';
    }""")
    board.get_by_role("button", name="职业成长").evaluate("(button) => button.click()")
    assert lead.locator(".nd-tag").inner_text() == "职业成长"
    page.set_viewport_size({"width": 390, "height": 844})
    assert board.evaluate("(board) => board.scrollWidth <= board.clientWidth")


def test_workspace_exposes_the_functions_other_scripts_call(logged_in_page, live_server):
    errors = collect_errors(logged_in_page)
    logged_in_page.goto(live_server + "/main.html", wait_until="load")
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
        page.goto(live_server + "/main.html")
        guide = page.get_by_role("dialog", name="新手引导")
        guide.wait_for(timeout=8000)
        guide.get_by_role("link", name="去系统配置 →").click()
        page.locator("#AI_CHAT_BASE_URL").fill("https://provider.example/v1")
        page.locator("#AI_CHAT_API_KEY").fill("browser-test-key")
        page.locator("#AI_CHAT_MODEL").fill("test-chat")
        save = page.locator("header").get_by_role("button", name="保存配置")
        save.click()
        page.get_by_text("对话模型已配置 3/3").wait_for()
        page.get_by_text("配置已保存。").wait_for()
        assert page.get_by_role("button", name="移除网页值").count() == 0
        assert page.locator("#settingsRequiredCount").inner_text() == "3/3"
        optional_ready, optional_total = map(int, page.locator("#settingsOptionalCount").inner_text().split("/"))
        assert optional_total == 6
        assert page.locator("#settingsCompletionCount").inner_text() == f"{3 + optional_ready}/9 项已配置"
        assert page.locator("#settingsCompletionPercent").inner_text() == f"{round(100 * (3 + optional_ready) / 9)}%"
        assert page.locator("#settingsReadiness").inner_text() == "必填已配齐"
        assert page.locator("#settingsMissing").is_hidden()
        assert page.locator("#settings-chat [data-group-count]").inner_text() == "已配置 3/3"
        assert page.locator("#settings-cleaner summary [data-group-count]").is_visible()
        assert page.locator("#settings-cleaner [data-setting-key]").count() == 3
        assert page.locator("#settings-image, #settings-news, #settings-retrieval").count() == 0
        assert page.locator("#settings-ocr [data-setting-key]").count() == 3
        assert page.locator('[data-setting-key="TESSERACT_CMD"]').count() == 0
        assert page.locator('[data-group-link="chat"]').get_attribute("data-status") == "ready"
        assert page.locator("#AI_CHAT_API_KEY").input_value() == ""
        eye = page.locator('[data-reveal="AI_CHAT_API_KEY"]')
        eye.click()
        page.wait_for_function("document.getElementById('AI_CHAT_API_KEY').type === 'text'")
        assert page.locator("#AI_CHAT_API_KEY").input_value() == "browser-test-key"
        assert page.get_by_role("button", name="保存配置").is_disabled()
        eye.click()
        assert page.locator("#AI_CHAT_API_KEY").input_value() == ""
        assert page.locator("#AI_CHAT_API_KEY").get_attribute("type") == "password"
        probes = iter([(200, {"duration_ms": 12}), (502, {"message": "模型服务暂时不可用。"}), (200, {"duration_ms": 27})])

        def probe(route):
            status, response = next(probes)
            route.fulfill(status=status, json=response)

        page.route("**/api/system-settings/test/chat", probe)
        page.locator("[data-test-group=chat]").click()
        page.get_by_text("已连通 · 12 ms").wait_for()
        page.get_by_role("button", name="重新测试").click()
        page.get_by_text("模型服务暂时不可用。").wait_for()
        assert page.get_by_text("已连通 · 12 ms").count() == 0
        page.get_by_role("button", name="重新测试").click()
        page.get_by_text("已连通 · 27 ms").wait_for()
        page.get_by_role("link", name="PostgreSQL / pgvector").click()
        page.get_by_text("POSTGRES_PASSWORD", exact=True).wait_for()
        assert page.locator('[data-group-link="postgres"]').get_attribute("aria-current") == "location"
        assert page.locator(".sc-group details[open]").count() == 1
        assert page.locator("#settings-chat details[open]").count() == 0
        page.locator("#settings-cleaner summary").click()
        assert page.locator("#settings-cleaner details[open]").count() == 1
        assert page.locator(".sc-group details[open]").count() == 1
        assert page.locator('[data-group-link="cleaner"]').get_attribute("aria-current") == "location"
        assert 0 <= save.bounding_box()["y"] < 88
        page.get_by_role("button", name="›_ 白盒控制台").click()
        page.locator("[data-console-filter]").fill("PATCH")
        page.locator("[data-console-entries] li").filter(has_text="PATCH /api/system-settings/models").wait_for()
        page.get_by_role("button", name="收起控制台").click()
        assert page.locator("#workspaceConsolePanel").is_hidden()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        errors = [error for error in errors if not (error.startswith("console:") and "502" in error
                  and error.endswith("/api/system-settings/test/chat)"))]
        assert errors == [], "\n".join(errors)
    finally:
        context.close()


def test_user_center_exposes_report_generation(logged_in_page, live_server):
    logged_in_page.goto(live_server + "/user-center#report-workspace", wait_until="load")
    logged_in_page.wait_for_url("**/user-center/workspace#report-workspace")
    logged_in_page.wait_for_timeout(1500)
    missing = logged_in_page.evaluate(
        "names => names.filter(name => typeof window[name] !== 'function')",
        ["startCareerReportGeneration", "requestJson", "fetchScopedUserState"])
    assert missing == []


def test_report_reuses_resume_from_personal_center(logged_in_page, live_server):
    page = logged_in_page
    page.add_init_script("localStorage.setItem('tg_done', '1')")
    page.goto(live_server + "/#report", wait_until="load")
    page.get_by_role("button", name="关闭引导").click()
    link = page.get_by_role("link", name="前往我的简历")
    link.wait_for()
    assert page.locator("#reportWorkflowInput").is_hidden()
    assert page.locator("#reportLaunchBtn").is_disabled()
    link.click()
    page.wait_for_url("**/user-center/resumes?from_report=1")
    page.locator("[name=title]").fill("应聘简历")
    page.locator("[data-contact=target]").fill("大模型算法｜Agent 开发实习")
    page.locator(".re-section").first.locator("[data-section-content]").fill("开发招聘系统")
    page.get_by_role("button", name="保存", exact=True).click()
    page.get_by_text("已保存的简历", exact=True).wait_for()
    page.get_by_role("link", name="返回报告生成台").click()
    targets = page.locator("#reportWorkflowTargets")
    targets.wait_for()
    assert targets.input_value() == "大模型算法\nAgent 开发实习"
    targets.fill("Agent 开发工程师")
    page.evaluate("refreshReportResumePanel()")
    assert targets.input_value() == "Agent 开发工程师"
    page.get_by_role("checkbox", name="杭州").check()
    page.get_by_role("checkbox", name="上海").check()
    page.get_by_label("求职类型").select_option("实习")
    page.get_by_label("办公方式").select_option("混合办公")
    page.get_by_label("其他偏好").fill("希望做 AI 产品")
    payload = page.evaluate("buildCareerReportGenerationPayload()")
    assert payload["availability"] is None
    assert payload["workflow"]["targets"] == ["Agent 开发工程师"]
    preferences = "意向城市：杭州、上海\n求职类型：实习\n办公方式：混合办公\n希望做 AI 产品"
    assert payload["workflow"]["preferences"] == preferences
    assert preferences in payload["workflow"]["recruitment"]["request"]
    assert page.locator("#reportResumeNotice").is_hidden()
    assert page.locator("#reportResumeSourceLabel").inner_text() == "应聘简历"
    assert page.locator("#report input[type=file]").count() == 0
    assert page.locator("#reportLaunchBtn").is_hidden()
    assert page.locator("#reportStageStart").is_visible()
    assert page.locator("#reportStageStart").is_enabled()


def test_pipeline_job_card_keeps_materials_beside_metadata_on_desktop(browser, live_server, make_account):
    from test_recruitment_pipeline import JOB_CUSTOM, add_job

    account = make_account("compact-job-card")
    add_job(account, "compact-job", JOB_CUSTOM)
    context = browser.new_context(viewport={"width": 1280, "height": 900}, reduced_motion="reduce")
    try:
        context.add_cookies([{"name": "session", "value": account.client.get_cookie("session").value, "url": live_server}])
        page = context.new_page()
        page.goto(live_server + "/recruitment")
        card = page.locator("#rpJobs .rp-job").filter(has_text=JOB_CUSTOM["title"])
        card.wait_for()
        tags = card.locator(".rp-job-tags").bounding_box()
        status = card.locator(".rp-job-status").bounding_box()
        materials = card.locator(".rp-job-materials").bounding_box()
        customize = card.get_by_role("button", name="定制面板", exact=True)
        assert tags["x"] < status["x"] < materials["x"] < customize.bounding_box()["x"]
        assert abs(tags["y"] + tags["height"] / 2 - materials["y"] - materials["height"] / 2) < 2
        assert card.bounding_box()["height"] <= 106

        page.set_viewport_size({"width": 390, "height": 844})
        assert card.evaluate("(el) => el.scrollWidth <= el.clientWidth + 1")
        assert card.get_by_role("button", name="欢迎语核验").is_visible()
        customize.click()
        page.get_by_role("dialog", name="简历改写 · 定制面板").wait_for()
    finally:
        context.close()


def test_pipeline_start_collection_submits_and_reveals_progress(logged_in_page, live_server, monkeypatch):
    from services import recruitment

    monkeypatch.setattr(recruitment, "use_local_chrome", lambda: True)
    page = logged_in_page
    submitted = []

    def runs(route):
        if route.request.method == "POST":
            submitted.append(route.request.post_data_json)
            route.fulfill(status=202, json={"id": "started-run"})
            return
        route.fulfill(json={"items": [{
            "id": "started-run", "keyword": "Agent实习", "city": "杭州", "status": "running",
            "started_at": 1795000000, "progress": {"zhilian": {"status": "running", "message": "正在读取职位"}},
        }] if submitted else []})

    page.route("**/api/job-market/collection/runs", runs)
    page.goto(live_server + "/recruitment?drawer=scraping")
    form = page.locator(".rp-collect-form")
    form.get_by_label("关键词").fill("Agent实习")
    form.get_by_label("城市").select_option("杭州")
    form.get_by_label("每平台上限").fill("10")
    form.get_by_role("checkbox", name="智联招聘").check()
    assert form.get_by_role("checkbox", name="使用本机 Chrome 登录态（推荐）").is_checked()
    form.get_by_role("button", name="启动采集", exact=True).click()
    form.get_by_text("已启动采集，可在下方查看各平台进度。").wait_for()
    page.locator('.rp-run-history[open] .rp-run[open]').get_by_text("正在读取职位").wait_for()
    assert len(submitted) == 1
    assert submitted[0]["sources"] == ["zhilian"]
    assert submitted[0]["chrome_local"] is True and submitted[0]["boss_local"] is False
    assert submitted[0]["keyword"] == "Agent实习" and submitted[0]["city"] == "杭州" and submitted[0]["limit"] == 10


def test_pipeline_collection_history_is_collapsed_and_keeps_open_records(logged_in_page, live_server):
    page = logged_in_page
    reads = 0

    def history(route):
        nonlocal reads
        reads += 1
        status = "running" if reads == 1 else "complete"
        route.fulfill(json={"items": [
            {"id": "first", "keyword": "后端开发", "city": "杭州", "status": status, "started_at": 1795000000,
             "progress": {"boss": {"status": status, "message": "第一条平台详情" if reads == 1 else "第一条采集完成"}}},
            {"id": "second", "keyword": "数据分析", "city": "上海", "status": "complete", "started_at": 1794990000,
             "progress": {"boss": {"status": "succeeded", "message": "第二条平台详情"}}},
        ]})

    page.route("**/api/job-market/collection/runs", history)
    page.goto(live_server + "/recruitment?drawer=scraping")
    record_history = page.locator(".rp-run-history")
    assert record_history.locator("summary").first.is_visible()
    record_history.get_by_text("2 条", exact=True).wait_for(timeout=5000)
    assert record_history.get_attribute("open") is None
    record_history.get_by_text("采集记录", exact=True).click()
    first = record_history.locator('.rp-run[data-run-id="first"]')
    second = record_history.locator('.rp-run[data-run-id="second"]')
    assert first.get_attribute("open") is None and second.get_attribute("open") is None
    first.locator("summary").click()
    first.get_by_text("第一条平台详情", exact=True).wait_for(timeout=2000)
    first.get_by_text("第一条采集完成", exact=True).wait_for(timeout=8000)
    assert second.locator(".rp-run-source").is_hidden()
    record_history.get_by_text("采集记录", exact=True).click()
    assert first.is_hidden()


def test_pipeline_login_check_shows_authorization_and_official_login(logged_in_page, live_server):
    page = logged_in_page
    statuses = iter([
        {"state": "authorization_required", "label": "等待 Chrome 授权", "message": "已打开 Chrome 授权页"},
        {"state": "not_logged_in", "label": "未登录", "login_url": "https://www.zhipin.com/web/user/"},
        {"state": "ready", "label": "已登录"},
    ])

    def check(route):
        assert route.request.method == "POST"
        route.fulfill(json=next(statuses))

    page.route("**/api/job-market/collection/session/boss", check)
    page.goto(live_server + "/recruitment?drawer=scraping")
    card = page.locator(".rp-session").filter(has_text="BOSS 直聘")
    check_button = card.get_by_role("button", name="检查登录")
    check_button.click()
    card.get_by_text("等待 Chrome 授权", exact=True).wait_for()
    assert card.get_by_role("button", name="复制授权地址").is_hidden()
    check_button.click()
    link = card.get_by_role("link", name="打开平台官网")
    link.wait_for()
    assert link.get_attribute("href") == "https://www.zhipin.com/web/user/"
    check_button.click()
    card.get_by_text("已登录", exact=True).wait_for()
    assert link.is_hidden()


def test_pipeline_internship_salary_uses_daily_fields_and_inline_filters(logged_in_page, live_server):
    page = logged_in_page
    page.goto(live_server + "/recruitment?drawer=cleaning")
    panel = page.get_by_role("dialog", name="规则清洗配置")
    direction = panel.get_by_label("清洗方向")
    direction.select_option("internship")
    minimum = panel.get_by_label("最低日薪（元/天）")
    minimum.fill("150")
    assert panel.get_by_label("最低月薪（K）").is_hidden()
    panel.locator(".rp-pay-estimate").get_by_text("3,300", exact=False).wait_for()
    assert panel.get_by_role("heading", name="薪资与经验").is_visible()
    assert panel.get_by_role("heading", name="城市与学历").is_visible()
    assert panel.get_by_label("岗位标题排除词").is_hidden()
    assert panel.get_by_role("button", name="应用到现有岗位", exact=True).is_hidden()
    assert panel.locator(".rp-drawer-body").evaluate("""body => {
        const footer = body.querySelector('.rp-clean-actions');
        body.scrollTop = 0;
        const before = footer.getBoundingClientRect().bottom;
        body.scrollTop = 180;
        const after = footer.getBoundingClientRect().bottom;
        return body.scrollTop > 0 && Math.abs(before - after) < 2 && Math.abs(after - body.getBoundingClientRect().bottom) < 2;
    }""")
    city = panel.get_by_label("目标城市", exact=True)
    city.fill("杭州")
    city.press("Enter")
    panel.locator(".rp-terms-values").get_by_role("button", name="移除 杭州").wait_for()
    education = panel.get_by_label("最低学历", exact=True)
    assert education.is_hidden()
    education_mode = panel.get_by_label("岗位学历要求", exact=True)
    assert education_mode.locator("option").all_text_contents() == ["不限岗位学历", "按最低学历筛选", "排除指定学历要求"]
    education_mode.select_option("exclude")
    panel.get_by_text("学历要求包含「博士」", exact=False).wait_for()
    panel.get_by_label("要排除的学历", exact=True).wait_for()
    education_mode.select_option("require")
    panel.get_by_text("要求为「大专」的岗位会被淘汰", exact=False).wait_for()
    education.fill("本科")
    assert panel.get_by_label("要排除的学历", exact=True).is_hidden()
    panel.get_by_role("button", name="添加最低学历", exact=True).click()
    panel.locator(".rp-terms-values").get_by_role("button", name="移除 本科").wait_for()
    panel.get_by_role("button", name="预览现有岗位", exact=True).click()
    apply = panel.get_by_role("button", name="应用到现有岗位", exact=True)
    apply.wait_for()
    panel.locator(".rp-clean-exclusions summary").click()
    panel.get_by_label("岗位标题排除词").fill("电话销售")
    assert apply.is_hidden()
    with page.expect_request("**/collection/cleaning/save") as saved:
        panel.get_by_role("button", name="保存规则", exact=True).click()
    rules = saved.value.post_data_json["rules"]
    assert rules["min_daily_salary"] == 150 and rules["min_salary_k"] is None
    assert rules["cities"] == ["杭州"] and rules["require_education"] == ["本科"]
    assert rules["title_exclusions"] == ["电话销售"]
    panel.get_by_text("规则已保存。", exact=True).wait_for()
    direction.select_option("full_time")
    panel.get_by_label("最低月薪（K）").wait_for()
    assert minimum.is_hidden()


def test_pipeline_scout_shows_two_examples_and_keeps_custom_rules(logged_in_page, live_server):
    page = logged_in_page
    page.goto(live_server + "/recruitment?drawer=cleaning")
    samples = page.locator(".rp-scout-example")
    samples.first.wait_for()
    assert samples.count() == 2
    assert samples.locator("summary strong").all_text_contents() == ["单休", "外包"]
    editor = page.locator(".rp-scout-list")
    assert editor.locator(".rp-scout-row").count() == 0
    page.get_by_role("button", name="使用示例", exact=True).click()
    editor.locator(".rp-scout-row[open]").wait_for()
    assert editor.locator(".rp-scout-row").count() == 2
    page.get_by_role("button", name="添加规则", exact=True).click()
    editor.locator(".rp-scout-row").last.get_by_label("规则词").fill("排除纯销售岗位")
    page.get_by_role("button", name="保存规则", exact=True).click()
    page.get_by_text("规则已保存。", exact=True).wait_for()
    page.reload()
    editor.locator("summary").filter(has_text="排除纯销售岗位").wait_for()
    assert editor.locator(".rp-scout-row").count() == 3
    assert editor.locator(".rp-scout-row[open]").count() == 0


def test_pipeline_scout_generation_keeps_draft_separate_from_saved_standard(logged_in_page, live_server):
    page = logged_in_page
    page.goto(live_server + "/recruitment?drawer=cleaning")
    panel = page.get_by_role("dialog", name="规则清洗配置")
    panel.get_by_role("button", name="添加规则", exact=True).click()
    row = panel.locator(".rp-scout-row[open]")
    row.get_by_label("规则词").fill("后端开发")
    condition = row.get_by_label("判定条件")
    condition.select_option("must")
    assert "希望岗位" in row.get_by_label("筛选意图（选填）").get_attribute("placeholder")
    condition.select_option("never")
    intent = row.get_by_label("筛选意图（选填）")
    draft = "不想做后端，和后端团队协作可以"
    intent.fill(draft)
    criterion = row.get_by_label("判定标准")
    criterion.fill("旧的资料整理标准")
    pending = []
    describe_url = "**/collection/cleaning/describe"
    page.route(describe_url, lambda route: pending.append(route))
    generate = row.get_by_role("button", name="AI 生成标准", exact=True)
    with page.expect_request(describe_url) as request:
        generate.click()
    assert request.value.post_data_json == {"keyword": "后端开发", "condition": "never", "intent": draft}
    row.get_by_text("正在生成判定标准…", exact=True).wait_for()
    assert generate.is_disabled()
    intent.fill(draft + "。")
    pending.pop().fulfill(json={"desc": "过时的标准"})
    row.get_by_text("生成期间规则已变更，请重新生成。", exact=True).wait_for()
    assert criterion.input_value() == "旧的资料整理标准"

    standard = "负责服务端接口开发时命中，仅与后端团队协作时不命中。"
    page.unroute(describe_url)
    page.route(describe_url, lambda route: route.fulfill(json={"desc": standard}))
    generate.click()
    row.get_by_text("已生成，可继续编辑。", exact=True).wait_for()
    assert criterion.input_value() == standard
    assert intent.input_value() == draft + "。"
    with page.expect_request("**/collection/cleaning/save") as saved:
        panel.get_by_role("button", name="保存规则", exact=True).click()
    assert saved.value.post_data_json["rules"]["ai_scout_rules"] == [
        {"keyword": "后端开发", "condition": "never", "desc": standard},
    ]
    panel.get_by_text("规则已保存。", exact=True).wait_for()


def test_pipeline_rail_distinguishes_results_waiting_and_execution(logged_in_page, live_server):
    page = logged_in_page
    page.route("**/pipeline/rail", lambda route: route.fulfill(json={
        "warnings": ["rewriting"], "llm_configured": True,
        "steps": [
            {"key": "scraping", "count": 75, "config_state": "configured"},
            {"key": "cleaning", "count": 0, "config_state": "configured"},
            {"key": "evaluating", "count": 0, "config_state": "configured"},
            {"key": "rewriting", "count": 0, "config_state": "required_missing"},
            {"key": "review", "count": 3, "config_state": "auto"},
            {"key": "delivering", "count": 2, "config_state": "configured"},
        ],
    }))
    page.route("**/pipeline/funnel", lambda route: route.fulfill(json={"stages": [
        {"key": "crawled", "count": 75}, {"key": "ready", "count": 2}, {"key": "delivered", "count": 0},
    ]}))
    page.goto(live_server + "/recruitment")
    rail = page.locator("#rpRail")
    for step, state, label in (
        ("scraping", "done", "已采集"), ("cleaning", "next", "下一步"),
        ("evaluating", "idle", "未开始"), ("rewriting", "blocked", "待配置"),
        ("review", "waiting", "待审批"), ("delivering", "waiting", "待投递"),
    ):
        rail.locator(f'[data-step="{step}"][data-state="{state}"]').get_by_text(label, exact=True).wait_for()
    assert rail.locator('[data-step="scraping"]').get_by_text("75 条", exact=True).is_visible()
    assert rail.evaluate("""el => new Set([...el.querySelectorAll('.rp-step')]
        .map(step => getComputedStyle(step).backgroundColor)).size""") == 2
    assert rail.evaluate("""el => new Set([...el.querySelectorAll('.rp-step-chip')]
        .map(badge => getComputedStyle(badge).backgroundColor)).size""") == 5

    pending_requests = []
    page.route("**/pipeline/run", lambda route: pending_requests.append(route))
    with page.expect_request("**/pipeline/run"):
        page.evaluate("void window.RP.runStage('clean')")
    rail.locator('[data-step="cleaning"][data-state="active"]').get_by_text("执行中", exact=True).wait_for()
    assert len(pending_requests) == 1
    pending_requests[0].fulfill(json={"stage": "clean", "processed": 0})
    rail.locator('[data-step="cleaning"][data-state="next"]').wait_for()


def test_pipeline_evaluation_drawer_runs_screen_and_deep_together(browser, live_server, server, make_account):
    from test_recruitment_pipeline import JOB_CUSTOM, add_job, run, setup_account

    account = setup_account(server, make_account, "combined-evaluation-browser")
    add_job(account, "combined-evaluation", JOB_CUSTOM)
    run(account, "clean")
    context = browser.new_context(viewport={"width": 1280, "height": 900}, reduced_motion="reduce")
    try:
        context.add_cookies([{"name": "session", "value": account.client.get_cookie("session").value, "url": live_server}])
        page = context.new_page()
        page.goto(live_server + "/recruitment?drawer=deep_eval")
        rail = page.locator("#rpRail")
        rail.get_by_role("button", name="AI评估", exact=False).wait_for()
        assert rail.get_by_text("深度评估", exact=True).count() == 0
        drawer = page.get_by_role("dialog", name="AI 评估")
        drawer.get_by_text("八维评估权重", exact=True).wait_for()
        assert drawer.get_by_text("分流阈值与投递白名单", exact=True).is_visible()
        with page.expect_response(lambda response: response.url.endswith("/pipeline/run")) as response:
            drawer.get_by_role("button", name="运行 AI 评估", exact=True).click()
        result = response.value.json()
        assert result["stage"] == "evaluate" and result["counts"]["screened"] == result["counts"]["deep"] == 1
        drawer.get_by_role("button", name="查看七键分析", exact=True).wait_for()
    finally:
        context.close()


def test_pipeline_board_saves_and_clears_unsaved_jobs(browser, live_server, make_account):
    from test_recruitment_pipeline import JOB_CUSTOM, add_job

    account = make_account("job-board-saved")
    add_job(account, "saved-example", {**JOB_CUSTOM, "title": "保留样本岗位"})
    add_job(account, "daily-example", {**JOB_CUSTOM, "title": "当日样本岗位"})
    add_job(account, "other-example", {**JOB_CUSTOM, "title": "另一条样本岗位"})
    context = browser.new_context(viewport={"width": 1280, "height": 850})
    try:
        context.add_cookies([{"name": "session", "value": account.client.get_cookie("session").value, "url": live_server}])
        page = context.new_page()
        page.goto(live_server + "/recruitment")
        cards = page.locator("#rpJobs .rp-job")
        kept = cards.filter(has_text="保留样本岗位")
        kept.get_by_role("button", name="保存", exact=True).click()
        kept.wait_for(state="hidden")
        page.get_by_role("button", name="批量删除", exact=True).click()
        page.get_by_role("checkbox", name="全选本页", exact=True).check()
        page.get_by_text("已选 2 条", exact=True).wait_for()
        page.get_by_role("checkbox", name="选择 另一条样本岗位").uncheck()
        page.get_by_role("button", name="删除所选", exact=True).click()
        confirm = page.get_by_role("dialog", name="删除所选岗位？")
        confirm.get_by_role("button", name="确认删除", exact=True).click()
        cards.filter(has_text="当日样本岗位").wait_for(state="hidden")
        cards.filter(has_text="另一条样本岗位").wait_for()
        page.get_by_role("button", name="批量删除", exact=True).click()
        page.get_by_role("button", name="全选全部未保存岗位", exact=True).click()
        page.get_by_role("button", name="删除所选", exact=True).click()
        confirm.get_by_role("button", name="确认删除", exact=True).click()
        page.get_by_text("当日暂无岗位", exact=True).wait_for()
        page.reload()
        page.locator('#rpTabs [data-tab="saved"]').click()
        kept.wait_for()
        assert kept.get_by_text("新线索", exact=True).is_visible()
        assert cards.filter(has_text="当日样本岗位").count() == 0
        page.get_by_role("button", name="获取新岗位", exact=True).click()
        assert page.get_by_role("button", name="启动采集", exact=True).is_visible()
        assert page.get_by_text("手动导入文件", exact=True).is_visible()
        assert page.get_by_role("button", name="导入种子岗位").count() == 0
    finally:
        context.close()


def test_pipeline_poll_keeps_unchanged_job_cards_in_place(browser, live_server, make_account):
    from test_recruitment_pipeline import JOB_CUSTOM, add_job

    account = make_account("job-board-poll")
    add_job(account, "unchanged", {**JOB_CUSTOM, "title": "稳定样本岗位"})
    add_job(account, "updated", {**JOB_CUSTOM, "title": "待更新样本岗位"})
    context = browser.new_context(viewport={"width": 1280, "height": 720})
    try:
        context.add_cookies([{"name": "session", "value": account.client.get_cookie("session").value, "url": live_server}])
        page = context.new_page()
        page.clock.install()
        page.goto(live_server + "/recruitment")
        cards = page.locator("#rpJobs .rp-job")
        unchanged = cards.filter(has_text="稳定样本岗位")
        title = unchanged.get_by_role("button", name="稳定样本岗位")
        title.focus()
        unchanged.evaluate("card => window.checkedJobCard = card")
        y = page.evaluate("window.scrollY")

        def is_board_page(url):
            return "/pipeline/jobs?" in url and "limit=8&" in url

        with page.expect_response(lambda response: is_board_page(response.url)):
            page.clock.fast_forward(12000)
        page.locator("#rpRailRefresh:enabled").wait_for()
        assert unchanged.evaluate("card => card === window.checkedJobCard")
        assert title.evaluate("button => button === document.activeElement")
        assert page.evaluate("window.scrollY") == y

        def update_job(route):
            data = route.fetch().json()
            for job in data["items"]:
                if job["url_key"] == "updated":
                    job["title"] = "已更新样本岗位"
            route.fulfill(json=data)

        page.route(is_board_page, update_job)
        page.clock.fast_forward(12000)
        cards.get_by_role("button", name="已更新样本岗位").wait_for()
        assert unchanged.evaluate("card => card === window.checkedJobCard")
        assert title.evaluate("button => button === document.activeElement")
    finally:
        context.close()


def test_pipeline_platform_filter_combines_with_search_and_pagination(browser, live_server, make_account):
    from test_recruitment_pipeline import JOB_CUSTOM, add_job

    account = make_account("job-board-platform")
    add_job(account, "local-platform", {**JOB_CUSTOM, "title": "城市样本 数据分析"})
    csv = "source,title,url\n" + "\n".join(
        f"boss,{'数据分析' if index == 0 else f'后端开发 {index}'},https://www.zhipin.com/job_detail/platform{index}.html"
        for index in range(9)
    )
    assert account.post("/api/job-market/collection/import", data={
        "file": (BytesIO(csv.encode()), "jobs.csv"),
    }).status_code == 200
    context = browser.new_context(viewport={"width": 390, "height": 844})
    try:
        context.add_cookies([{"name": "session", "value": account.client.get_cookie("session").value, "url": live_server}])
        page = context.new_page()
        page.goto(live_server + "/recruitment")
        pager = page.get_by_role("navigation", name="岗位分页")
        pager.get_by_text("第 1 / 2 页 · 10 条", exact=True).wait_for()
        pager.get_by_role("button", name="下一页").click()
        pager.get_by_text("第 2 / 2 页 · 10 条", exact=True).wait_for()
        platform = page.get_by_role("combobox", name="平台筛选")
        platform.select_option("boss")
        pager.get_by_text("第 1 / 2 页 · 9 条", exact=True).wait_for()
        assert set(page.locator("#rpJobs .rp-source-pill").all_text_contents()) == {"BOSS 直聘"}
        page.get_by_role("searchbox", name="搜索岗位").fill("数据分析")
        page.locator("#rpBoardCount").get_by_text("共 1 条", exact=True).wait_for()
        assert page.locator("#rpJobs .rp-job-title").all_text_contents() == ["数据分析"]
        page.reload()
        page.locator("#rpBoardCount").get_by_text("共 1 条", exact=True).wait_for()
        assert platform.input_value() == "boss"
        platform.select_option("")
        page.locator("#rpBoardCount").get_by_text("共 2 条", exact=True).wait_for()
        assert page.evaluate("document.documentElement.scrollWidth === innerWidth")
    finally:
        context.close()


def test_pipeline_job_board_paginates_beyond_the_local_cache(browser, live_server, make_account):
    from test_recruitment_pipeline import JOB_CUSTOM, add_job

    account = make_account("job-board-pages")
    for index in range(611):
        add_job(account, f"page-{index:03}", {**JOB_CUSTOM, "title": f"分页样本 {index:03}"})

    context = browser.new_context(viewport={"width": 390, "height": 844})
    try:
        context.add_cookies([{"name": "session", "value": account.client.get_cookie("session").value, "url": live_server}])
        page = context.new_page()
        page.goto(live_server + "/recruitment")
        cards = page.locator("#rpJobs .rp-job")
        pager = page.get_by_role("navigation", name="岗位分页")
        pager.get_by_text("第 1 / 77 页 · 611 条", exact=True).wait_for()
        for width in (1440, 390):
            page.set_viewport_size({"width": width, "height": 844})
            assert pager.evaluate("""(nav, wide) => {
                const selectors = wide ? ['#rpJobPrev', '#rpJobNext', '#rpJobPageInput', '#rpJobPageGo']
                                       : ['#rpJobPageInput', '#rpJobPageGo'];
                const centers = selectors.map(selector => {
                    const rect = nav.querySelector(selector).getBoundingClientRect();
                    return rect.top + rect.height / 2;
                });
                return Math.max(...centers) - Math.min(...centers) < 1 && nav.scrollWidth <= nav.clientWidth;
            }""", width == 1440)
        assert cards.count() == 8
        assert pager.get_by_role("button", name="上一页").is_disabled()
        pager.get_by_role("button", name="下一页").click()
        pager.get_by_text("第 2 / 77 页 · 611 条", exact=True).wait_for()
        assert cards.count() == 8

        pager.get_by_role("spinbutton", name="跳转页码").fill("77")
        pager.get_by_role("button", name="跳转", exact=True).click()
        pager.get_by_text("第 77 / 77 页 · 611 条", exact=True).wait_for()
        assert cards.count() == 3
        assert pager.get_by_role("button", name="下一页").is_disabled()
        assert cards.get_by_role("button", name="分页样本 000").is_visible()

        search = page.get_by_role("searchbox", name="搜索岗位")
        search.fill("分页样本 000")
        page.wait_for_function("new URLSearchParams(location.search).get('q') === '分页样本 000'")
        assert cards.count() == 1
        assert pager.is_hidden()
        search.fill("")
        pager.get_by_text("第 1 / 77 页 · 611 条", exact=True).wait_for()
        pager.get_by_role("button", name="下一页").click()
        pager.get_by_text("第 2 / 77 页 · 611 条", exact=True).wait_for()
        page.locator('#rpTabs [data-tab="in_progress"]').click()
        pager.get_by_text("第 1 / 77 页 · 611 条", exact=True).wait_for()
        assert cards.count() == 8
        page.get_by_role("button", name="批量删除", exact=True).click()
        page.get_by_role("checkbox", name="全选本页", exact=True).check()
        page.get_by_text("已选 8 条", exact=True).wait_for()
        pager.get_by_role("button", name="下一页").click()
        pager.get_by_text("第 2 / 77 页 · 611 条", exact=True).wait_for()
        assert not page.get_by_role("checkbox", name="全选本页", exact=True).is_checked()
        page.get_by_role("button", name="全选全部未保存岗位", exact=True).click()
        page.get_by_text("已选 611 条", exact=True).wait_for()
        assert page.get_by_role("checkbox", name="全选本页", exact=True).is_checked()
    finally:
        context.close()


def test_recruitment_page_import_filter_detail_and_export(logged_in_page, live_server):
    page = logged_in_page
    page.goto(live_server + "/recruitment")
    assert page.locator("#recruitmentCollect input[name=source]").count() == 4
    assert page.locator('#recruitmentCollect input[value="liepin"]').count() == 0
    page.get_by_role("button", name="导入网页").click()
    dialog = page.get_by_role("dialog", name="导入已保存的搜索页")
    markup = '''<div class="job-card-wrap">
      <a class="job-name" href="/job_detail/sample.html?tracking=ignored">Agent 开发</a>
      <span class="boss-name">样本公司</span><span class="company-location">杭州</span>
      <script>document.querySelector(".job-name").textContent = "untrusted";</script>
    </div>'''
    dialog.locator("input[type=file]").set_input_files({
        "name": "search.html", "mimeType": "text/html", "buffer": markup.encode()
    })
    dialog.get_by_role("button", name="读取岗位").click()
    page.get_by_text("暂时没有通过清洗的岗位").wait_for()
    assert page.get_by_role("button", name="Agent 开发", exact=True).count() == 0
    page.get_by_role("button", name="查看待清洗岗位").click()
    page.get_by_role("button", name="Agent 开发", exact=True).wait_for()
    page.get_by_role("searchbox", name="搜索结果").fill("样本公司")
    page.get_by_role("button", name="筛选", exact=True).click()
    page.wait_for_function("new URL(document.querySelector('#recruitmentExport').href).searchParams.get('q') === '样本公司'")
    page.get_by_role("button", name="Agent 开发", exact=True).click()
    details = page.get_by_role("dialog", name="Agent 开发")
    assert details.get_by_role("link", name="查看原帖").get_attribute("href") == "https://www.zhipin.com/job_detail/sample.html"
    details.get_by_role("button", name="关闭").click()
    with page.expect_download() as download:
        page.get_by_role("link", name="导出 CSV").click()
    assert download.value.suggested_filename == "recruitment.csv"


def test_recruitment_checks_each_platform_and_keeps_results_separate(logged_in_page, live_server, monkeypatch):
    monkeypatch.setenv("CAREER_RECRUITMENT_USE_LOCAL_CHROME", "1")
    page = logged_in_page
    statuses = {
        "boss": ("BOSS 直聘", "ready", "已登录"),
        "51job": ("前程无忧", "not_logged_in", "未登录"),
        "zhilian": ("智联招聘", "verification_required", "需要安全验证"),
        "xiaohongshu": ("小红书招聘线索", "unavailable", "检查失败"),
    }
    checked = []

    def session(route):
        source = route.request.url.rsplit("/", 1)[-1]
        checked.append(source)
        _, state, label = statuses[source]
        route.fulfill(json={"state": state, "label": label, "message": "Chrome 登录检查结果"})

    page.route("**/api/job-market/collection/session/*", session)
    page.goto(live_server + "/recruitment?drawer=scraping")
    sessions = page.locator(".rp-sessions")
    cards = sessions.locator(".rp-session")
    assert cards.count() == 4
    icons = cards.locator(".rp-platform-mark img")
    assert icons.count() == 4
    assert icons.evaluate_all("(images) => images.every((image) => image.complete && image.naturalWidth > 0)")
    cards.filter(has_text="前程无忧").get_by_role("button", name="检查登录").click()
    sessions.get_by_text("未登录", exact=True).wait_for()
    assert checked == ["51job"]
    assert sessions.get_by_text("未检查", exact=True).count() == 3

    page.get_by_role("button", name="检查全部平台").click()
    for platform, state, label in statuses.values():
        result = cards.filter(has_text=platform).locator(f'[data-state="{state}"]')
        result.get_by_text(label, exact=True).wait_for()
    assert sorted(checked[1:]) == sorted(statuses)
    assert not page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
    page.set_viewport_size({"width": 375, "height": 800})
    assert not page.evaluate("document.documentElement.scrollWidth > window.innerWidth")


def test_recruitment_city_picker_search_group_and_submission(logged_in_page, live_server):
    page = logged_in_page
    requests = []

    def runs(route):
        if route.request.method == "POST":
            requests.append(route.request.post_data_json)
            return route.fulfill(status=202, json={"id": "test"})
        return route.fulfill(json={"items": []})

    page.route("**/api/job-market/collection/runs", runs)
    page.goto(live_server + "/recruitment")
    page.get_by_role("button", name="配置采集").click()
    toggle = page.locator("#recruitmentCityToggle")
    menu = page.locator("#recruitmentCityMenu")
    toggle.click()
    menu.get_by_role("button", name="D", exact=True).click()
    menu.get_by_role("button", name="东莞", exact=True).click()
    assert toggle.inner_text().startswith("东莞")
    assert page.locator("#recruitmentCityCoverage").is_hidden()
    page.set_viewport_size({"width": 375, "height": 800})
    toggle.click()
    bounds = menu.bounding_box()
    assert bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= 375
    search = menu.get_by_role("searchbox", name="搜索城市")
    search.fill("不存在")
    menu.get_by_text("没有匹配的城市。").wait_for()
    search.press("Escape")
    assert menu.is_hidden()
    toggle.click()
    search.fill("泉州市")
    search.press("Enter")
    assert toggle.inner_text().startswith("泉州")
    assert page.locator("#recruitmentCityCoverage").inner_text().startswith("将跳过 BOSS 直聘")
    page.get_by_label("关键词").fill("Agent")
    page.get_by_role("button", name="开始采集").click()
    page.get_by_text("已启动采集。各平台的结果会陆续显示。").wait_for()
    assert page.get_by_role("dialog", name="采集条件").is_hidden()
    assert requests[0]["city"] == "泉州"


def test_recruitment_cleaning_previews_applies_and_releases_job(logged_in_page, live_server):
    page = logged_in_page
    page.goto(live_server + "/recruitment")
    csv = "source,title,url\nboss,电话销售,https://www.zhipin.com/job_detail/cleaning.html\n"
    page.locator("#recruitmentFile").set_input_files({"name": "jobs.csv", "mimeType": "text/csv", "buffer": csv.encode()})
    page.get_by_role("button", name="待清洗", exact=True).click()
    job = page.locator(".recruitment-row").filter(has_text="电话销售")
    job.get_by_text("未清洗", exact=True).wait_for()
    page.get_by_role("button", name="配置与预览").click()
    dialog = page.get_by_role("dialog", name="清洗规则")
    assert dialog.get_by_role("button", name="应用到现有岗位").is_disabled()
    assert dialog.get_by_role("button", name="启用示例").is_visible()
    dialog.get_by_label("目标城市", exact=True).fill("杭州")
    dialog.get_by_label("目标城市", exact=True).press("Enter")
    dialog.get_by_role("button", name="移除 杭州").click()
    dialog.get_by_label("经验上限（年）").fill("5")
    dialog.get_by_role("button", name="启用示例").click()
    scout = dialog.locator(".recruitment-scout-row").first
    scout.get_by_label("判定标准").fill("明确要求每周工作六天时命中")
    dialog.get_by_label("岗位标题排除词").fill("销售")
    dialog.get_by_role("button", name="预览现有岗位").click()
    dialog.get_by_text("淘汰 1 条", exact=True).wait_for()
    assert job.get_by_text("未清洗", exact=True).is_visible()
    dialog.get_by_role("button", name="应用到现有岗位").click()
    dialog.get_by_text("已应用清洗规则。", exact=True).wait_for()
    assert dialog.get_by_label("经验上限（年）").input_value() == "5"
    assert scout.get_by_label("判定标准").input_value() == "明确要求每周工作六天时命中"
    dialog.get_by_role("button", name="关闭").click()
    page.get_by_role("button", name="已淘汰", exact=True).click()
    assert job.get_by_text("标题命中排除词「销售」").count() == 0
    job.get_by_role("button", name="电话销售").click()
    detail = page.get_by_role("dialog", name="电话销售")
    detail.get_by_text("标题命中排除词「销售」").wait_for()
    detail.get_by_role("button", name="关闭").click()
    job.get_by_role("button", name="手动放行").click()
    page.get_by_text("已放行：电话销售").wait_for()
    page.get_by_role("button", name="优先看", exact=True).click()
    job.get_by_text("已放行", exact=True).wait_for()


def test_recruitment_switches_rule_profiles_and_moves_listing(logged_in_page, live_server):
    page = logged_in_page
    page.goto(live_server + "/recruitment")
    page.get_by_role("button", name="配置与预览").click()
    dialog = page.get_by_role("dialog", name="清洗规则")
    profile = dialog.get_by_label("清洗方向")
    profile.select_option("internship")
    dialog.get_by_label("最低日薪（元/天）").fill("200")
    dialog.get_by_role("button", name="保存规则").click()
    dialog.get_by_text("规则已保存。").wait_for()
    dialog.get_by_role("button", name="关闭").click()
    csv = "source,title,url\nboss,示例岗位,https://www.zhipin.com/job_detail/profile.html\n"
    page.locator("#recruitmentFile").set_input_files({"name": "jobs.csv", "mimeType": "text/csv", "buffer": csv.encode()})
    page.get_by_role("button", name="全部岗位", exact=True).click()
    job = page.locator(".recruitment-row").filter(has_text="示例岗位")
    job.get_by_text("实习", exact=True).wait_for()

    page.get_by_role("button", name="配置与预览").click()
    profile.select_option("full_time")
    dialog.get_by_label("最低月薪（K）").fill("15")
    assert dialog.get_by_label("最低日薪（元/天）").is_hidden()
    dialog.get_by_role("button", name="保存规则").click()
    dialog.get_by_text("规则已保存。").wait_for()
    dialog.get_by_role("button", name="关闭").click()
    job.get_by_role("button", name="示例岗位").click()
    detail = page.get_by_role("dialog", name="示例岗位")
    detail.get_by_label("归入求职方向").select_option("full_time")
    detail.get_by_role("button", name="更新方向").click()
    detail.get_by_text("已归入正式工作").wait_for()
    detail.get_by_role("button", name="关闭").click()
    job.get_by_text("正式工作", exact=True).wait_for()


def test_recruitment_ai_drawer_runs_selected_jobs(logged_in_page, live_server):
    page = logged_in_page
    url = "https://www.zhipin.com/job_detail/ai.html"
    requests = []
    page.route("**/collection/ai/settings?*", lambda route: route.fulfill(json={
        "settings": {"resume": "", "preferences": "", "weights": {"role": 5, "skills": 5, "experience": 4}},
        "resume_available": True, "configured": True,
    }))
    page.route("**/collection/ai/candidates/match?*", lambda route: route.fulfill(json={
        "items": [{"source": "boss", "url": url, "title": "待评岗位"}],
    }))

    def run(route):
        requests.append(route.request.post_data_json)
        route.fulfill(json={"result": {"verdict": "scored", "score": 80, "coverage": 3}})

    page.route("**/collection/ai/run/match", run)
    page.goto(live_server + "/recruitment")
    page.get_by_role("button", name="配置与评估").click()
    drawer = page.get_by_role("dialog", name="AI 初评")
    drawer.get_by_role("checkbox", name="待评岗位").check()
    drawer.get_by_role("button", name="评估所选岗位").click()
    drawer.get_by_text("待评岗位 · 80 分 · 3 项有依据").wait_for()
    assert requests == [{"profile": "general", "source": "boss", "url": url}]


def test_recruitment_overview_shows_platform_progress_and_login_action(logged_in_page, live_server):
    page = logged_in_page
    errors = collect_errors(page)
    latest = {
        "id": 1, "keyword": "Agent", "city": "杭州", "started_at": time.time(), "status": "running",
        "progress": {
            "boss": {"status": "succeeded", "count": 15, "search_url": "https://www.zhipin.com/"},
            "zhilian": {"status": "waiting_user", "message": "请在浏览器完成登录",
                        "login_url": "https://passport.zhaopin.com/"},
            "51job": {"status": "empty", "count": 0, "search_url": "https://we.51job.com/"},
        },
    }
    page.route("**/api/job-market/collection/runs", lambda route: route.fulfill(json={"items": [latest]}))
    page.goto(live_server + "/recruitment")
    page.get_by_text("最近一次 · Agent · 杭州 · 采集中", exact=True).wait_for()
    stages = page.locator(".recruitment-stages .recruitment-stage")
    assert stages.count() == 4
    assert len({stage.bounding_box()["y"] for stage in stages.all()}) == 1
    cards = page.locator(".recruitment-platform")
    assert cards.count() == 4
    assert cards.locator("[data-status=succeeded]").inner_text() == "已采集"
    assert cards.filter(has_text="BOSS 直聘").locator(".recruitment-platform-count").inner_text() == "15 条"
    assert cards.filter(has_text="前程无忧").locator(".recruitment-platform-count").inner_text() == "0 条"
    assert cards.filter(has_text="小红书").get_by_text("未参与", exact=True).is_visible()
    login = cards.filter(has_text="智联招聘").get_by_role("link", name="去登录")
    assert login.get_attribute("href") == "https://passport.zhaopin.com/"
    assert login.is_visible()
    start = page.locator("#recruitmentStart")
    platform_choices = page.locator("#recruitmentCollect fieldset")
    drawer = page.locator("#recruitmentCollectDialog")
    assert drawer.is_hidden()
    assert page.locator("#recruitmentCleaningDialog").is_hidden()
    open_button = page.get_by_role("button", name="配置采集")
    open_button.click()
    bounds = drawer.bounding_box()
    assert abs(bounds["x"] + bounds["width"] - page.viewport_size["width"]) <= 1
    assert start.is_disabled()
    assert start.bounding_box()["y"] > platform_choices.bounding_box()["y"]
    page.keyboard.press("Escape")
    assert drawer.is_hidden()
    assert open_button.evaluate("(button) => document.activeElement === button")

    latest["status"] = "interrupted"
    page.get_by_role("button", name="刷新", exact=True).click()
    page.get_by_text("最近一次 · Agent · 杭州 · 已中断", exact=True).wait_for()
    assert login.is_hidden()
    assert start.is_enabled()
    page.get_by_text("采集记录", exact=True).click()
    assert page.locator("#recruitmentRuns").get_by_text("Agent · 杭州", exact=True).is_visible()
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth") == 390
    assert len({stage.bounding_box()["y"] for stage in stages.all()}) == 2
    open_button.click()
    assert drawer.bounding_box()["width"] == 390
    assert start.bounding_box()["y"] > platform_choices.bounding_box()["y"]
    assert errors == []


def test_resume_job_handoff_and_temporary_rewrite(logged_in_page, live_server, monkeypatch, tmp_path):
    from services.resume import rewrite

    skill = tmp_path / "resume_rewrite.md"
    skill.write_text("示例改写规则\n", encoding="utf-8")
    monkeypatch.setenv("RESUME_REWRITE_SKILL_PATH", str(skill))
    monkeypatch.setattr(rewrite.llm_env, "chat_runtime", lambda: ("https://model.invalid", "mock", "mock"))

    def model(*args, **kwargs):
        assert "数据工程师" in args[3][0]["content"]
        return "<FINAL_RESUME>\n## 工作经历\n- 使用 Python 整理订单数据并生成对账记录\n</FINAL_RESUME>"

    monkeypatch.setattr(rewrite, "call_markdown_chat", model)
    page = logged_in_page
    page.goto(live_server + "/user-center/resumes")
    work = page.get_by_role("button", name="工作经历", exact=True)
    work.click()
    original_line = "使用 Python 处理订单数据并编写日常对账记录"
    work_card = page.locator(".re-section").nth(1)
    work_card.locator("textarea:visible").first.fill(original_line)
    page.locator("[name=title]").fill("基础简历")
    page.get_by_role("button", name="保存", exact=True).click()
    page.get_by_text("已保存的简历", exact=True).wait_for()
    page.goto(live_server + "/recruitment")
    csv = "source,title,description,url\nboss,数据工程师,负责编写订单数据管道,https://www.zhipin.com/job_detail/rewrite.html\n"
    page.locator("#recruitmentFile").set_input_files({"name": "jobs.csv", "mimeType": "text/csv", "buffer": csv.encode()})
    page.get_by_role("button", name="全部岗位", exact=True).click()
    page.get_by_role("button", name="数据工程师", exact=True).click()
    page.get_by_role("button", name="按此岗位改写简历").click()
    page.wait_for_url("**/user-center/resumes?rewrite=1")
    drawer = page.get_by_role("dialog", name="简历改写")
    drawer.wait_for()
    assert drawer.get_by_text("改写与版式").count() == 0
    drawer.locator("#resumeRewriteSkill").get_by_role("option", name="简历改写 · 内置规则").wait_for(state="attached")
    bounds = drawer.bounding_box()
    assert abs(bounds["x"] + bounds["width"] - page.viewport_size["width"]) <= 1
    assert drawer.locator("[name=job_title]").input_value() == "数据工程师"
    assert "负责编写订单数据管道" in drawer.locator("[name=job_description]").input_value()
    drawer.get_by_role("button", name="生成改写草稿").click()
    drawer.get_by_text("已生成临时草稿，共 1 处改写。").wait_for()
    drawer.get_by_text("改写：- 使用 Python 整理订单数据并生成对账记录").wait_for()
    drawer.get_by_role("button", name="另存为新版本").click()
    drawer.get_by_text("已另存为新版本，可在「简历版本」中打开编辑。").wait_for()
    drawer.get_by_role("button", name="关闭简历改写").click()
    assert page.locator("[name=title]").input_value() == "基础简历"
    assert work_card.locator("[data-section-content]").input_value().removeprefix("- ") == original_line
    page.locator("#resumeVersions summary").click()
    page.get_by_role("button", name="基础简历 · 数据工程师改写").wait_for()


def test_resume_workshop_import_preview_and_reopen(logged_in_page, live_server):
    page = logged_in_page
    errors = collect_errors(page)
    page.goto(live_server + "/user-center")
    page.wait_for_url("**/user-center/resumes")
    assert page.get_by_role("link", name="我的简历").get_attribute("aria-current") == "page"
    assert page.get_by_role("link", name="职业档案").count() == 0
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
    source = Image.new("RGB", (360, 300), "#d6e4ff")
    ImageDraw.Draw(source).rectangle((140, 30, 200, 260), fill="#365ea8")
    encoded = BytesIO()
    source.save(encoded, format="PNG")
    with page.expect_file_chooser() as chooser:
        page.get_by_role("button", name="上传简历照片").click()
    chooser.value.set_files({"name": "photo.png", "mimeType": "image/png", "buffer": encoded.getvalue()})
    crop = page.get_by_role("dialog", name="裁剪简历照片")
    crop.wait_for()
    canvas = crop.locator("canvas")
    original_crop = canvas.evaluate("(canvas) => canvas.toDataURL()")
    crop.locator("#resumePhotoZoom").press("End")
    assert canvas.evaluate("(canvas) => canvas.toDataURL()") != original_crop
    zoomed_crop = canvas.evaluate("(canvas) => canvas.toDataURL()")
    canvas.press("ArrowRight")
    assert canvas.evaluate("(canvas) => canvas.toDataURL()") != zoomed_crop
    crop.get_by_role("button", name="使用照片").click()
    photo = page.get_by_role("img", name="简历照片")
    assert photo.get_attribute("src").startswith("data:image/jpeg;base64,")
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
    assert photo.is_visible()
    page.locator("[data-contact=name]").fill("林晓更新")
    page.get_by_role("button", name="保存", exact=True).click()
    page.get_by_text("已保存的简历", exact=True).wait_for()
    with page.expect_download() as downloaded:
        page.get_by_role("button", name="导出 PDF").click()
    assert downloaded.value.suggested_filename == "产品开发简历.pdf"
    with pymupdf.open(downloaded.value.path()) as document:
        assert document[0].get_images()[0][2:4] == (144, 187)
    page.get_by_role("link", name="工作区外观").click()
    page.get_by_role("button", name="工作区外观").and_(page.locator("[aria-current=page]")).wait_for()
    page.get_by_role("link", name="返回主工作台").click()
    page.wait_for_url("**/main.html#dashboard")
    page.locator('button[data-section="dashboard"]').wait_for()
    assert errors == [], "\n".join(errors)


def test_resume_form_entries_fill_add_delete_and_reopen(logged_in_page, live_server):
    page = logged_in_page
    errors = collect_errors(page)
    page.goto(live_server + "/user-center/resumes")
    project = page.locator(".re-section").nth(2)
    project.get_by_role("button", name="项目经历", exact=True).click()
    entry = project.locator(".re-entry").first
    entry.locator("[data-entry=name]").fill("校园二手交易平台")
    entry.locator("[data-entry=role]").fill("后端负责人")
    entry.locator("[data-entry=start]").fill("2025.01")
    entry.locator("[data-entry=end]").fill("2025.06")
    entry.locator("[data-entry=content]").fill("负责接口开发\n接口性能提升")
    formatted = "校园二手交易平台 | 后端负责人 | 2025.01–2025.06\n- 负责接口开发\n- 接口性能提升"
    assert project.locator("[data-section-content]").input_value() == formatted
    project.get_by_role("button", name="＋ 添加项目经历").click()
    assert project.locator(".re-entry").count() == 2
    assert project.locator("[data-entry-index]").nth(1).inner_text() == "项目经历 2"
    second = project.locator(".re-entry").nth(1)
    second.locator("[data-entry=name]").fill("推荐系统课程设计")
    second.get_by_role("button", name="删除这段经历").click()
    assert project.locator(".re-entry").count() == 1
    assert project.locator("[data-section-content]").input_value() == formatted
    page.locator("[name=title]").fill("表单简历")
    page.get_by_role("button", name="保存", exact=True).click()
    page.get_by_text("已保存的简历", exact=True).wait_for()
    page.reload()
    page.get_by_text("已保存的简历", exact=True).wait_for()
    reopened = page.locator(".re-section").nth(2)
    assert reopened.locator("[data-entry=name]").first.input_value() == "校园二手交易平台"
    assert reopened.locator("[data-entry=start]").first.input_value() == "2025.01"
    assert reopened.locator("[data-entry=end]").first.input_value() == "2025.06"
    assert reopened.locator("[data-entry=content]").first.input_value() == "- 负责接口开发\n- 接口性能提升"
    assert reopened.locator("[data-section-content]").input_value() == formatted
    assert errors == [], "\n".join(errors)


def test_switching_sections_works(logged_in_page, live_server):
    errors = collect_errors(logged_in_page)
    logged_in_page.goto(live_server + "/main.html#forum", wait_until="load")
    logged_in_page.wait_for_timeout(1200)
    assert logged_in_page.locator("#dashboard").is_visible()
    assert logged_in_page.locator('[data-section="forum"], #forum').count() == 0
    for section in ("profile", "report", "dashboard"):
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


def test_recruitment_header_uses_workspace_grid_and_single_configuration_action(logged_in_page, live_server):
    page = logged_in_page
    page.goto(live_server + "/main.html#report")
    report_grid = page.locator("body").evaluate("el => getComputedStyle(el).backgroundSize")
    assert report_grid.startswith("28px 28px, 28px 28px")

    page.goto(live_server + "/recruitment")
    assert page.locator("body").evaluate("el => getComputedStyle(el).backgroundSize") == report_grid
    header = page.locator(".rp-page-header")
    assert header.get_by_role("heading", name="岗位全链路流水线").is_visible()
    config = header.get_by_role("button", name="待配置", exact=False)
    config.wait_for()
    assert header.get_by_text("待配置", exact=False).count() == 1

    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth") == 390
    config.click()
    page.get_by_role("dialog").wait_for()

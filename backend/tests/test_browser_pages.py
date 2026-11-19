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
        save = page.locator("header").get_by_role("button", name="保存配置")
        save.click()
        page.get_by_text("对话模型已配置 3/3").wait_for()
        page.get_by_text("配置已保存。").wait_for()
        assert page.locator("#settingsRequiredCount").inner_text() == "3/3"
        assert page.locator("#settingsOptionalCount").inner_text().endswith("/3")
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
        "boss": ("ready", "已登录"),
        "51job": ("not_logged_in", "未登录"),
        "zhilian": ("verification_required", "需要安全验证"),
        "xiaohongshu": ("unavailable", "检查失败"),
    }
    checked = []

    def session(route):
        source = route.request.url.rsplit("/", 1)[-1]
        checked.append(source)
        state, label = statuses[source]
        route.fulfill(json={"state": state, "label": label, "message": "Chrome 登录检查结果"})

    page.route("**/api/job-market/collection/session/*", session)
    page.goto(live_server + "/recruitment")
    sessions = page.locator("#recruitmentSessions")
    cards = sessions.locator(".recruitment-session")
    assert cards.count() == 4
    icons = cards.locator("img.recruitment-session-icon")
    assert icons.count() == 4
    assert icons.evaluate_all("(images) => images.every((image) => image.complete && image.naturalWidth > 0)")
    assert cards.get_by_role("link").count() == 4
    sessions.locator('.recruitment-session[data-source="51job"]').get_by_role("button").click()
    sessions.get_by_text("未登录", exact=True).wait_for()
    assert checked == ["51job"]
    assert sessions.get_by_text("未检查", exact=True).count() == 3

    sessions.get_by_role("button", name="检查全部").click()
    for source, (state, label) in statuses.items():
        result = sessions.locator(f'.recruitment-session[data-source="{source}"] [data-state="{state}"]')
        result.get_by_text(label, exact=True).wait_for()
    assert sorted(checked[1:]) == sorted(statuses)
    assert not page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
    page.set_viewport_size({"width": 375, "height": 800})
    assert not page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
    page.get_by_role("checkbox", name="用本机 Chrome 采集").uncheck()
    assert sessions.is_hidden()


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
    assert requests[0]["city"] == "泉州"


def test_recruitment_cleaning_previews_applies_and_releases_job(logged_in_page, live_server):
    page = logged_in_page
    page.goto(live_server + "/recruitment")
    csv = "source,title,url\nboss,电话销售,https://www.zhipin.com/job_detail/cleaning.html\n"
    page.locator("#recruitmentFile").set_input_files({"name": "jobs.csv", "mimeType": "text/csv", "buffer": csv.encode()})
    job = page.locator(".recruitment-row").filter(has_text="电话销售")
    job.get_by_text("未清洗", exact=True).wait_for()
    page.get_by_role("button", name="配置与预览").click()
    dialog = page.get_by_role("dialog", name="清洗规则")
    assert dialog.get_by_role("button", name="应用到现有岗位").is_disabled()
    dialog.get_by_label("岗位标题排除词").fill("销售")
    dialog.get_by_role("button", name="预览现有岗位").click()
    dialog.get_by_text("淘汰 1 条", exact=True).wait_for()
    assert job.get_by_text("未清洗", exact=True).is_visible()
    dialog.get_by_role("button", name="应用到现有岗位").click()
    dialog.get_by_text("已应用清洗规则。", exact=True).wait_for()
    dialog.get_by_role("button", name="关闭").click()
    page.get_by_label("清洗状态").select_option("rejected")
    page.get_by_role("button", name="筛选", exact=True).click()
    job.get_by_text("标题命中排除词「销售」").wait_for()
    job.get_by_role("button", name="手动放行").click()
    page.get_by_text("已放行：电话销售").wait_for()
    page.get_by_label("清洗状态").select_option("passed")
    page.get_by_role("button", name="筛选", exact=True).click()
    job.get_by_text("已放行", exact=True).wait_for()


def test_recruitment_switches_rule_profiles_and_moves_listing(logged_in_page, live_server):
    page = logged_in_page
    page.goto(live_server + "/recruitment")
    profile = page.get_by_label("求职方向", exact=True)
    profile.select_option("internship")
    page.get_by_role("button", name="配置与预览").click()
    dialog = page.get_by_role("dialog", name="清洗规则")
    dialog.get_by_label("最低日薪（元/天）").fill("200")
    dialog.get_by_role("button", name="保存规则").click()
    dialog.get_by_text("规则已保存。").wait_for()
    dialog.get_by_role("button", name="关闭").click()
    csv = "source,title,url\nboss,示例岗位,https://www.zhipin.com/job_detail/profile.html\n"
    page.locator("#recruitmentFile").set_input_files({"name": "jobs.csv", "mimeType": "text/csv", "buffer": csv.encode()})
    job = page.locator(".recruitment-row").filter(has_text="示例岗位")
    job.get_by_text("实习", exact=True).wait_for()

    profile.select_option("full_time")
    page.get_by_role("button", name="配置与预览").click()
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
    assert start.is_disabled()
    assert start.bounding_box()["y"] < platform_choices.bounding_box()["y"]

    latest["status"] = "interrupted"
    page.get_by_role("button", name="刷新", exact=True).click()
    page.get_by_text("最近一次 · Agent · 杭州 · 已中断", exact=True).wait_for()
    assert login.is_hidden()
    assert start.is_enabled()
    page.get_by_text("采集记录", exact=True).click()
    assert page.locator("#recruitmentRuns").get_by_text("Agent · 杭州", exact=True).is_visible()
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth") == 390
    assert start.bounding_box()["y"] > platform_choices.bounding_box()["y"]
    assert errors == []


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
    page.get_by_role("link", name="账户设置").click()
    page.get_by_role("button", name="账户设置").and_(page.locator("[aria-current=page]")).wait_for()
    page.get_by_role("link", name="返回主工作台").click()
    page.wait_for_url("**/main.html#dashboard")
    page.locator('button[data-section="dashboard"]').wait_for()
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

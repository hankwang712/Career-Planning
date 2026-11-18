"""Read the visible results of recruitment searches in an isolated browser."""

import os
from pathlib import Path
from time import monotonic
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit


# Search entry points and listing field names follow Jobhunter AI's five collectors.
# https://github.com/jolie-z/jobhunter-ai/tree/main/backend
SOURCES = {
    "boss": ("BOSS 直聘", "https://www.zhipin.com/web/geek/jobs", "query", "zhipin.com",
             ".job-card-wrap", ".job-name", ".boss-name", ".job-salary", ".company-location", ".job-name, a[href*='/job_detail/']"),
    "51job": ("前程无忧", "https://we.51job.com/pc/search", "keyword", "51job.com",
              ".joblist-item", ".jname, .job-name", ".cname, .company-name", ".sal, .salary", ".area, .job-area", "a[href*='jobs.51job.com'], a[href*='jobdetail'], a[href*='job_detail']"),
    "zhilian": ("智联招聘", "https://www.zhaopin.com/jobs", "kw", "zhaopin.com",
                ".job-card, .joblist-box__iteminfo", ".job-card__title-main, .jobinfo__name", ".job-card__company-name, .companyinfo__name",
                ".job-card__salary, .jobinfo__salary", ".job-card__location, .jobinfo__other-info-item", "a[href*='/jobdetail/'], a[href*='/job/']"),
    "liepin": ("猎聘", "https://www.liepin.com/zhaopin/", "key", "liepin.com",
               ".job-card-pc-container, .job-card-pc, a.job-card", ".job-title .ellipsis, .job-title, .ellipsis-1",
               ".company-name, .job-card-company", ".job-salary, .job-title > :last-child:not(.ellipsis)",
               ".job-dq", "a[href*='/job/'], a[href*='/a/']"),
    "xiaohongshu": ("小红书招聘线索", "https://www.xiaohongshu.com/search_result", "keyword", "xiaohongshu.com",
                    "section.note-item, section:has(a.cover)", "a.title, .title", "", "", "", "a[href*='/explore/'], a[href*='/search_result/']"),
}

# Only city codes supported across all four job boards are offered by the form.
CITIES = {
    "北京": ("101010100", "010000", "530", "010"),
    "上海": ("101020100", "020000", "538", "020"),
    "广州": ("101280100", "030200", "763", "050020"),
    "深圳": ("101280600", "040000", "765", "050090"),
    "杭州": ("101210100", "080200", "653", "070020"),
    "成都": ("101270100", "090200", "801", "280020"),
    "南京": ("101190100", "070200", "635", "060020"),
}
CITY_FIELDS = {"boss": "city", "51job": "jobArea", "zhilian": "jl", "liepin": "dq"}
LIEPIN_PUBLIC_CITIES = {"北京": "bj", "上海": "sh", "广州": "gz", "深圳": "sz", "杭州": "hz", "成都": "cd", "南京": "nj"}
LISTING_PATHS = {
    "boss": ("/job_detail/",), "zhilian": ("/jobdetail/", "/job/"), "liepin": ("/job/", "/a/"),
    "xiaohongshu": ("/explore/", "/search_result/"), "51job": ("/pc/jobdetail", "/pc/job_detail"),
}
STATIC_DOMAINS = {
    "boss": ("zhipin.com", "zhipinstatic.com", "bosszhipin.com"), "51job": ("51job.com", "51jobcdn.com"),
    "zhilian": ("zhaopin.com", "zhaopin.cn", "zstatic.net"), "liepin": ("liepin.com", "lpcdn.com", "lietou-static.com"),
    "xiaohongshu": ("xiaohongshu.com", "xhscdn.com"),
}

READ_CARDS = """({source, card, selectors, limit}) => {
    const text = (node, key) => {
        for (const selector of selectors[key].split(',').filter(Boolean)) {
            const value = node.querySelector(selector)?.innerText.trim();
            if (value) return value;
        }
        return '';
    };
    return Array.from(document.querySelectorAll(card)).slice(0, limit * 3).map(node => {
        const displayedSalary = text(node, 'salary');
        const cardData = source === 'boss'
            ? node.__vue__?.$props?.data ?? node.__vueParentComponent?.props?.data
            : null;
        const salary = typeof cardData?.salaryDesc === 'string' && cardData.salaryDesc.trim()
            ? cardData.salaryDesc.trim() : displayedSalary;
        const description = (node.innerText || '').trim();
        return {
            title: text(node, 'title'), company: text(node, 'company'), salary,
            location: text(node, 'location'),
            description: (displayedSalary ? description.replace(displayedSalary, salary) : description).slice(0, 3000),
            url: (node.matches(selectors.url) ? node : node.querySelector(selectors.url) || node.closest(selectors.url))?.getAttribute('href') || ''
        };
    });
}"""


def search_url(source, keyword, city):
    _, base, field, *_ = SOURCES[source]
    params = {field: f"{keyword} 招聘" if source == "xiaohongshu" else keyword}
    if city and source in CITY_FIELDS:
        params[CITY_FIELDS[source]] = CITIES[city][list(CITY_FIELDS).index(source)]
    if city and source == "xiaohongshu":
        params[field] = f"{city} {params[field]}"
    return f"{base}?{urlencode(params)}"


def platform_url(source, href, base=None):
    try:
        parsed = urlsplit(urljoin(base or SOURCES[source][1], href))
        domain = SOURCES[source][3]
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.port not in (None, 443)
                or not (parsed.hostname == domain or parsed.hostname.endswith("." + domain))):
            return ""
    except ValueError:
        return ""
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


def listing_url(source, href, base=None):
    url = platform_url(source, href, base)
    if not url:
        return ""
    parsed = urlsplit(url)
    if source == "51job" and parsed.hostname == "jobs.51job.com":
        if not parsed.path.lower().endswith(".html"):
            return ""
    elif not parsed.path.lower().startswith(LISTING_PATHS[source]):
        return ""
    query = {}
    if source == "51job":
        query = {key: values[0] for key, values in parse_qs(parsed.query).items()
                 if key.lower() == "jobid" and values[0].isdigit()}
    return urlunsplit(("https", parsed.hostname, parsed.path, urlencode(query), ""))


def allowed_request(source, request):
    if platform_url(source, request.url):
        return True
    parsed = urlsplit(request.url)
    if (source == "51job" and request.method == "GET" and parsed.scheme == "https"
            and parsed.hostname in {"fecdn.51jobcdn.com", "js.51jobcdn.com"}):
        return True
    return (request.resource_type in {"stylesheet", "script", "font", "image"}
            and parsed.scheme == "https" and parsed.hostname
            and any(parsed.hostname == host or parsed.hostname.endswith("." + host) for host in STATIC_DOMAINS[source]))


def cards(page, source, limit):
    _, _, _, _, card, *selectors = SOURCES[source]
    rows = page.evaluate(READ_CARDS, {"source": source, "card": card, "limit": limit,
                                    "selectors": dict(zip(("title", "company", "salary", "location", "url"), selectors))})
    unique = {}
    for row in rows:
        if not row["title"] or not row["url"]:
            continue
        base = page.url if page.url.startswith("https://") else None
        url = listing_url(source, row["url"], base)
        if not url:
            continue
        unique.setdefault(url, {**row, "url": url})
    return list(unique.values())[:limit]


def collect_source(browser, source, keyword, city, limit):
    context = browser.new_context(locale="zh-CN", accept_downloads=False, service_workers="block")
    try:
        context.route("**/*", lambda route: route.continue_() if allowed_request(source, route.request) else route.abort())
        context.route_web_socket("**/*", lambda socket: socket.close())
        page = context.new_page()
        url = search_url(source, keyword, city)
        response = page.goto(url, timeout=12000, wait_until="domcontentloaded")
        if response and response.status in {401, 403, 429}:
            return "blocked", "平台限制了本次访问，请前往原站或导入 CSV。", []
        if not response or response.status >= 400:
            return "unavailable", "平台暂时未提供可读的搜索页。", []
        if page.locator(SOURCES[source][4]).count() == 0:
            from playwright.sync_api import TimeoutError as BrowserTimeout

            try:
                page.locator(SOURCES[source][4]).first.wait_for(state="attached", timeout=5000)
            except BrowserTimeout:
                pass
        rows = cards(page, source, limit)
        if rows:
            return "succeeded", f"读取 {len(rows)} 条结果。", rows
        if any(marker in page.title().lower() for marker in ("security verification", "安全限制", "请稍候", "安全验证", "请登录")) or any(
            part in urlsplit(page.url).path for part in ("/login", "/verify", "/security")
        ):
            return "blocked", "平台要求登录或验证，请在原站查看或导入 CSV。", []
        if source == "liepin" and city:
            rows = collect_liepin_catalog(browser, keyword, city, limit)
            if rows:
                return "succeeded", f"公开城市页匹配到 {len(rows)} 条岗位。", rows
        return "empty", "当前页面未读取到岗位。可以打开原站搜索核对。", []
    finally:
        context.close()


def browser_options(playwright):
    if Path(playwright.chromium.executable_path).is_file():
        return {}
    if os.name == "nt":
        for root in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")):
            if root:
                for relative in ("Google/Chrome/Application/chrome.exe", "Microsoft/Edge/Application/msedge.exe"):
                    path = Path(root) / relative
                    if path.is_file():
                        return {"executable_path": str(path)}
    return {}


def launch_browser(playwright):
    return playwright.chromium.launch(**browser_options(playwright))


def collect_local_boss(playwright, profile_dir, keyword, city, limit, update):
    """Keep the user's login, manual verification and job search in one profile."""
    from playwright.sync_api import Error as BrowserError

    update("opening", "正在打开 BOSS 专用浏览器。")
    options = browser_options(playwright)
    with playwright.chromium.launch_persistent_context(
        profile_dir, headless=False, locale="zh-CN", accept_downloads=False, **options
    ) as context:
        page = context.pages[0] if context.pages else context.new_page()
        page.bring_to_front()
        target = search_url("boss", keyword, city)
        expected_query = parse_qs(urlsplit(target).query)
        deadline = monotonic() + 150
        current_state = "opening"
        retried_search = False

        def go_to_search():
            try:
                page.goto(target, timeout=12000, wait_until="commit")
            except BrowserError:
                if page.is_closed():
                    raise

        go_to_search()
        while monotonic() < deadline and not page.is_closed():
            if not platform_url("boss", page.url):
                state = "waiting_user"
            else:
                address = urlsplit(page.url)
                title = page.title()
                gated = (any(word in title for word in ("安全验证", "安全限制", "请稍候", "请登录"))
                         or address.hostname == "passport.zhipin.com"
                         or any(part in address.path for part in ("/login", "/verify", "/security"))
                         or page.locator("#nc_1_n1z").first.is_visible())
                if gated:
                    state = "waiting_user"
                elif address.path.rstrip("/") == "/web/geek/jobs" and all(
                    parse_qs(address.query).get(key) == value for key, value in expected_query.items()
                ):
                    rows = cards(page, "boss", limit)
                    if rows:
                        return "succeeded", f"从 BOSS 登录窗口读取 {len(rows)} 条岗位。", rows
                    if page.get_by_text("暂无相关职位", exact=False).first.is_visible():
                        return "empty", "BOSS 暂无匹配职位，请调整关键词。", []
                    state = "waiting_user"
                else:
                    state = "waiting_user"
                    if current_state == "waiting_user" and not retried_search and page.locator(".user-nav").first.is_visible():
                        retried_search = True
                        go_to_search()
            if state != current_state:
                update(state, "请在 BOSS 窗口登录或完成安全验证。搜索结果出现后会自动读取。")
                current_state = state
            page.wait_for_timeout(1000)
        return "blocked", "BOSS 窗口已关闭，或等待登录、验证超时。可以重新开始。", []


def parse_page(browser, source, document, limit):
    from lxml import html

    parsed = html.document_fromstring(document)
    for element in parsed.xpath("//script | //iframe | //object | //embed | //meta | //link | //base"):
        element.drop_tree()
    markup = html.tostring(parsed, encoding="unicode")
    context = browser.new_context(java_script_enabled=False, offline=True, accept_downloads=False, service_workers="block")
    try:
        context.route("**/*", lambda route: route.abort())
        context.route_web_socket("**/*", lambda socket: socket.close())
        page = context.new_page()
        # Any links in the saved document are treated as data, never visited.
        page.set_content(markup, timeout=5000, wait_until="domcontentloaded")
        return cards(page, source, limit)
    finally:
        context.close()


def read_saved_page(source, document, limit=150):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright, launch_browser(playwright) as browser:
        return parse_page(browser, source, document, limit)


def collect_liepin_catalog(browser, keyword, city, limit):
    import httpx
    from lxml.etree import ParserError

    url = f"https://m.liepin.com/city-{LIEPIN_PUBLIC_CITIES[city]}/"
    try:
        with httpx.stream("GET", url, timeout=8, follow_redirects=False) as response:
            if response.status_code != 200 or "text/html" not in response.headers.get("content-type", ""):
                return []
            document = bytearray()
            for chunk in response.iter_bytes():
                document.extend(chunk)
                if len(document) > 2_000_000:
                    return []
        rows = parse_page(browser, "liepin", document.decode("utf-8", errors="replace"), 100)
    except (httpx.HTTPError, ParserError):
        return []
    wanted = keyword.casefold().split()
    return [{**row, "location": row["location"] or city} for row in rows
            if all(word in row["title"].casefold() for word in wanted)][:limit]

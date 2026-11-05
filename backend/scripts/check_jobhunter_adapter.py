"""Checks for upstream adapter fixes using fixtures, without browser/network access."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

VENDOR = Path(__file__).resolve().parents[1] / "integrations/jobhunter/vendor"
sys.path.insert(0, str(VENDOR))
os.environ.setdefault("JOBHUNTER_LOG_DIR", str(Path(tempfile.gettempdir()) / "career-jobhunter-check"))
from crawler.api_crawler import ApiCrawler
from crawler.ncss_crawler import NCSSCrawler
from crawler.website_crawler import WebsiteCrawler


class AdapterChecks(unittest.TestCase):
    @staticmethod
    def page(text, url='https://example.com/jobs', passwords=0):
        return SimpleNamespace(url=url, locator=lambda selector: SimpleNamespace(
            inner_text=lambda **kwargs: text, count=lambda: passwords))

    def test_login_navigation_does_not_block_public_jobs(self):
        page = self.page('校园招聘 登录 AI应用工程师 上海 查看详情')
        self.assertFalse(WebsiteCrawler().check_captcha_or_login(page))

    def test_visible_verification_wall_is_still_respected(self):
        page = self.page('请完成安全验证，拖动滑块完成验证后继续')
        self.assertTrue(WebsiteCrawler().check_captcha_or_login(page))

    def test_actual_login_route_and_password_form_are_detected(self):
        crawler = WebsiteCrawler()
        self.assertTrue(crawler.check_captcha_or_login(self.page('账号 密码 登录', url='https://example.com/login')))
        self.assertTrue(crawler.check_captcha_or_login(self.page('账号 密码 登录', passwords=1)))

    def crawl(self, payload):
        crawler = ApiCrawler()
        definition = deepcopy(crawler.API_CONFIGS["腾讯"])
        definition["payload"] = payload
        definition["headers"]["portal-channel"] = "campus"
        crawler.API_CONFIGS = {"fixture": definition}
        crawler.max_pages = 2
        calls = []
        def evaluate(script, args):
            calls.append(args)
            return json.dumps({"data": {"positionList": [{"id": index, "positionTitle": "Fixture role", "workCities": "上海", "postId": str(index)} for index in range(2)]}})
        page = SimpleNamespace(evaluate=evaluate, close=lambda: None)
        crawler.create_page = lambda: page
        crawler.safe_goto = lambda *args: True
        crawler.random_delay = lambda *args: None
        with patch("crawler.api_crawler.time.sleep"):
            rows = crawler._crawl_by_api("fixture")
        return rows, calls

    def test_maximum_page_limit_stops_repeating_api_results(self):
        rows, calls = self.crawl({"pageIndex": 1, "pageSize": 2})
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(rows), 4)

    def test_offset_pagination_starts_at_zero_and_advances_by_page_size(self):
        _, calls = self.crawl({"offset": 0, "limit": 2})
        self.assertEqual([args[1]["offset"] for args in calls], [0, 2])

    def test_nested_pagination_keeps_page_object(self):
        _, calls = self.crawl({"page": {"pageNo": 1, "pageSize": 2}})
        self.assertEqual([args[1]["page"] for args in calls], [{"pageNo": 1, "pageSize": 2}, {"pageNo": 2, "pageSize": 2}])

    def test_source_specific_request_headers_are_forwarded(self):
        _, calls = self.crawl({"pageIndex": 1, "pageSize": 2})
        self.assertEqual(calls[0][3]["portal-channel"], "campus")

    def test_tencent_list_label_is_not_mistaken_for_job_description(self):
        crawler = ApiCrawler()
        raw = {"id": 22444, "postId": "1282707398326592512", "positionTitle": "AI全栈工程师", "workCities": "上海", "recruitLabelName": "应届毕业生"}
        row = crawler._parse_api_item(raw, "腾讯", crawler.API_CONFIGS["腾讯"])
        self.assertEqual(row["job_desc"], "")
        self.assertEqual(row["job_url"], "https://join.qq.com/post_detail.html?postid=1282707398326592512")

    def test_ncss_decimal_salary_and_conservative_type(self):
        crawler = NCSSCrawler()
        row = crawler._normalize_job({"jobId": "42", "jobName": "开发工程师", "lowMonthPay": 1.5, "highMonthPay": 2.5})
        self.assertEqual(row["salary"], "1.5K-2.5K")
        self.assertEqual(row["job_type"], "unknown")


if __name__ == "__main__":
    unittest.main()

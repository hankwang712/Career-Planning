import unittest

from career_news import _score_relevance, _split_visible_items


class CareerNewsRelevanceTest(unittest.TestCase):
    def setUp(self):
        self.search_source = {"kind": "search", "topic": "程序员就业"}
        self.direct_source = {"kind": "direct", "topic": "全球科技"}

    def test_accepts_programmer_employment_news(self):
        result = _score_relevance(
            self.search_source,
            "AI动画师、AI算法研究员、App独立开发者 青年就业迎来新蓝海",
            "聚焦程序员、开发者和 AI 岗位的就业变化。",
        )
        self.assertTrue(result["accepted"])
        self.assertIn("career", result["labels"])
        self.assertIn("tech", result["labels"])

    def test_rejects_sports_career_story(self):
        result = _score_relevance(
            self.search_source,
            "拒绝退役，陈梦发声宣布未来心声，职业规划首次揭秘",
            "运动员的个人生涯安排引发热议。",
        )
        self.assertFalse(result["accepted"])

    def test_rejects_training_advertorial(self):
        result = _score_relevance(
            self.search_source,
            "2026年口碑好的AI大模型开发培训机构汇总，如何选择？",
            "培训课程、学费和哪家好对比。",
        )
        self.assertFalse(result["accepted"])

    def test_direct_feed_requires_career_and_tech(self):
        result = _score_relevance(
            self.direct_source,
            "OpenAI expands hiring for AI safety engineers",
            "The company is hiring software engineers and AI researchers across teams.",
        )
        self.assertTrue(result["accepted"])

    def test_direct_feed_rejects_plain_tech_story(self):
        result = _score_relevance(
            self.direct_source,
            "OpenAI adds open source tools to help developers build for teen safety",
            "A new release for developers focused on product safety and tooling only.",
        )
        self.assertFalse(result["accepted"])

    def test_visible_items_are_topic_balanced(self):
        items = []
        for index in range(5):
            items.append({"topic": "AI 与计算机岗位", "title": f"ai-{index}"})
        for index in range(4):
            items.append({"topic": "求职就业", "title": f"job-{index}"})
        for index in range(3):
            items.append({"topic": "职业规划", "title": f"plan-{index}"})
        for index in range(3):
            items.append({"topic": "科技行业变化", "title": f"trend-{index}"})

        visible, hidden = _split_visible_items(items, 10)

        self.assertEqual(len(visible), 10)
        self.assertEqual(sum(1 for item in visible if item["topic"] == "AI 与计算机岗位"), 3)
        self.assertEqual(len(hidden), 5)


if __name__ == "__main__":
    unittest.main()

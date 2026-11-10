import unittest

from backend.advisor.utils.resume_grounding import rewrite_errors, verify_resume_grounding


class ResumeGroundingTests(unittest.TestCase):
    def test_unverified_experiment_count_and_past_future_date_are_not_suggestions(self):
        data = {"recommendations": ["若无法确认，注明单次实验。", "注明预计2026年6月毕业。"]}
        errors = verify_resume_grounding(data, {"raw_resume": "教育经历", "analysis_date": "2026-11-10"})
        self.assertTrue(any("实验次数未知" in error for error in errors))
        self.assertTrue(any("过去月份" in error for error in errors))

    def test_math_superscript_and_latex_match_without_losing_exponent(self):
        from backend.advisor.utils.resume_grounding import normalized
        self.assertEqual(normalized('R²提升2.4%'), normalized(r'\(\mathrm{R}^2\)提升\(2.4\%\)'))
        self.assertNotEqual(normalized('R²'), normalized('R2'))

    def test_original_check_is_not_an_assertion_of_a_typo(self):
        self.assertEqual(verify_resume_grounding({'recommendations': ['核对原稿：检查“结化提取”等表述是否为笔误，确保语言准确。']}, {'raw_resume': '结化提取'}), [])

    def test_profile_cannot_attach_conference_claim_to_journal_quote(self):
        data = {"career_profile": [{"field": "strengths", "value": "期刊录用及会议接收", "quote": "论文已录用", "source": "raw_resume"}]}
        self.assertTrue(verify_resume_grounding(data, {"raw_resume": "论文已录用"}))

    def test_rejects_fabricated_allocation_and_placeholder(self):
        materials = {"raw_resume": "负责人，参与设计预测模型。"}
        evidence = [{"source": "raw_resume", "status": "weak", "quote": materials["raw_resume"]}]
        self.assertTrue(rewrite_errors("负责人（团队X人）：独立完成训练；合作者负责融合模块。", evidence, materials))
        self.assertTrue(rewrite_errors("独立完成训练。", evidence, materials))

    def test_extractive_reordering_is_useful_and_allowed(self):
        text = "本人贡献：数据预处理，参与模型训练。负责生产环境部署发布和维护。"
        evidence = [{"source": "raw_resume", "status": "clear", "quote": text}]
        self.assertEqual(rewrite_errors("负责生产环境部署发布和维护；本人贡献：数据预处理，参与模型训练。", evidence, {"raw_resume": text}), [])
        self.assertEqual(rewrite_errors(None, [], {}), [])

    def test_rewrite_cannot_turn_range_into_decimal(self):
        text = "F1提升6~9%。"
        rows = [{"source": "raw_resume", "status": "clear", "quote": text}]
        self.assertTrue(rewrite_errors("F1提升6.9%。", rows, {"raw_resume": text}))
        self.assertEqual(rewrite_errors(text, rows, {"raw_resume": text}), [])

    def test_validates_all_evidence_and_missing_status(self):
        data = {"issues": [{"problem": "结果未说明", "evidence": [{"source": "raw_resume", "status": "missing", "quote": "虚构"}]}]}
        self.assertTrue(verify_resume_grounding(data, {"raw_resume": "原始材料"}))
        data["issues"][0]["evidence"][0]["quote"] = "原始材料"
        self.assertEqual(verify_resume_grounding(data, {"raw_resume": "原始材料"}), [])

    def test_award_only_is_not_an_independent_experience(self):
        text = "## 竞赛情况\n1. 数学建模比赛一等奖\n2. 设计竞赛三等奖\n## 实习\n负责开发接口。"
        experience = {"name": "数学建模比赛", "source_quote": "数学建模比赛一等奖"}
        self.assertTrue(verify_resume_grounding({"experiences": [experience]}, {"raw_resume": text}))
        text = "## 竞赛经历\n数学建模比赛一等奖，负责数据清洗与建模验证。"
        self.assertEqual(verify_resume_grounding({"experiences": [experience]}, {"raw_resume": text}), [])

    def test_unknown_degree_cannot_be_filled_from_school(self):
        data = {"career_profile": [{"field": "education", "value": "某大学本科"}]}
        self.assertTrue(verify_resume_grounding(data, {"raw_resume": "某大学 某专业 2022.09-2026.06"}))
        self.assertEqual(verify_resume_grounding(data, {"raw_resume": "某大学 本科 2022.09-2026.06"}), [])

    def test_ocr_layout_requires_tentative_language(self):
        self.assertTrue(verify_resume_grounding({"issues": [{"problem": "编号错乱，影响观感"}]}, {}))
        self.assertEqual(verify_resume_grounding({"issues": [{"problem": "OCR编号顺序可能受双栏影响，需核对原稿"}]}, {}), [])
        self.assertTrue(verify_resume_grounding({"issues": [{"problem": "结化提取是错字"}]}, {}))

    def test_repeated_supplied_city_question_is_rejected(self):
        data = {"missing_information": ["期望城市是否确为甲市或乙市（简历未写）"]}
        self.assertTrue(verify_resume_grounding(data, {"preferences": "优先甲市或乙市，两个城市按或处理"}))

    def test_qualitative_delivery_is_not_erased_by_missing_metrics(self):
        prepared = {"raw_resume": "## 实习经历\n实现查询接口，负责上线部署。"}
        self.assertTrue(verify_resume_grounding({"summary": "实习没有任何产出描述。"}, prepared))
        self.assertEqual(verify_resume_grounding({"summary": "实习已有功能交付，缺少效果评测记录。"}, prepared), [])

    def test_past_date_does_not_establish_graduation(self):
        prepared = {"raw_resume": "某大学 2022.09-2026.06"}
        self.assertTrue(verify_resume_grounding({"summary": "按简历时间已毕业，建议投递。"}, prepared))
        self.assertEqual(verify_resume_grounding({"summary": "学段时间已过去，是否已毕业待确认。"}, prepared), [])

    def test_cannot_transfer_evidence_between_experiences(self):
        text = "## 项目甲\n2024负责模型训练。\n## 项目乙\n2025负责部署。"
        data = {"experiences": [{"name": "项目甲", "source_quote": "2024负责模型训练", "issues": [
            {"problem": "部署描述不足", "evidence": [{"source": "raw_resume", "status": "clear", "quote": "2025负责部署"}]}]}]}
        self.assertTrue(verify_resume_grounding(data, {"raw_resume": text}))

    def test_ocr_math_cosmetics_do_not_invalidate_true_quote(self):
        data = {"dimensions": [{"evidence": [{"source": "raw_resume", "status": "clear", "quote": "R^2超过2.4%，F1提升6~9%"}]}]}
        text = r"\(\mathrm{R}^2\) 超过 \(2.4\%\)，F1提升\(6\sim9\%\)"
        self.assertEqual(verify_resume_grounding(data, {"raw_resume": text}), [])

    def test_tentative_examples_are_not_graduation_assertions(self):
        data = {"issues": [{"suggestion": "补充当前身份（如“已毕业，获学士学位”），这些需本人确认后填写。"}]}
        self.assertEqual(verify_resume_grounding(data, {"raw_resume": "某大学2022.09-2026.06"}), [])

    def test_missing_fields_are_questions_not_assertions(self):
        data = {"issues": [{"problem": "当前身份未说明", "missing_evidence": ["当前身份（本科已毕业/在读研究生/推免待入学）"]}]}
        self.assertEqual(verify_resume_grounding(data, {"raw_resume": "某大学2022.09-2026.06"}), [])
        data = {"issues": [{"suggestion": "若只有一个模型名称是笔误，核对原稿后再统一。"}]}
        self.assertEqual(verify_resume_grounding(data, {}), [])

    def test_ambiguous_ocr_sections_do_not_reassign_evidence(self):
        text = "## 项目甲\n核心成员\n训练模型。\n## 项目乙\n核心成员\n部署模型。"
        data = {"experiences": [{"name": "未稳定识别名称", "source_quote": "核心成员", "issues": [
            {"problem": "部署细节未说明", "evidence": [{"source": "raw_resume", "status": "weak", "quote": "部署模型"}]}]}]}
        self.assertEqual(verify_resume_grounding(data, {"raw_resume": text}), [])

    def test_full_schema_points_to_fabricated_interest_source(self):
        from pydantic import ValidationError
        from backend.advisor.agents.resume import ResumeAnalysisAgent
        agent = ResumeAnalysisAgent(None)
        prepared = agent.prepare({"raw_resume": "某大学，设计专业", "target_role": "产品设计", "additional_evidence": ""})
        data = {"summary": "需要核实职业兴趣", "dimensions": [], "experiences": [], "issues": [], "recommendations": [],
                "missing_information": [], "career_profile": [{"field": "interests", "value": "产品设计", "quote": "产品设计", "source": "additional_evidence"}]}
        with self.assertRaises(ValidationError) as caught:
            agent.get_output_schema(prepared).model_validate(data)
        self.assertIn("interests", str(caught.exception))
        self.assertIn("additional_evidence", str(caught.exception))
        self.assertIn("为空", str(caught.exception))

    def test_profile_quote_must_support_its_technical_claims(self):
        text = "课程Python。实习开发RAG与OCR。"
        data = {"career_profile": [{"field": "skills", "value": "Python、RAG、OCR", "quote": "课程Python。"}]}
        self.assertTrue(verify_resume_grounding(data, {"raw_resume": text}))
        data["career_profile"] = [{"field": "skills", "value": "RAG、OCR", "quote": "实习开发RAG与OCR。"}]
        self.assertEqual(verify_resume_grounding(data, {"raw_resume": text}), [])

    def test_qualitative_internship_results_are_not_absent(self):
        text = "## 实习经历\n某公司，负责生产部署发布和维护。"
        data = {"experiences": [{"name": "某公司", "experience_type": "internship", "source_quote": "某公司", "issues": [{"problem": "实习缺少结果和验证。"}]}]}
        self.assertTrue(verify_resume_grounding(data, {"raw_resume": text}))
        data["experiences"][0]["issues"][0]["problem"] = "部署已有定性交付，但缺少可核查的评测记录。"
        self.assertEqual(verify_resume_grounding(data, {"raw_resume": text}), [])


if __name__ == "__main__":
    unittest.main()

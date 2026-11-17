"""Grounded skill extraction before taxonomy retrieval and candidate adjudication."""
import json
import re


def negated(text, phrase):
    """Conservative guard for explicit negation/unknown claims; never infer proficiency."""
    for match in re.finditer(re.escape(phrase), text, re.I):
        prefix = re.split(r"[。；;，,\n]", text[:match.start()])[-1][-18:]
        suffix = text[match.end():match.end() + 10]
        if re.search(r"不会|不懂|不熟悉|不具备|没有.{0,8}|未掌握|未学过|未使用过|不要求|无需|不需要|尚未|计划.{0,8}学|打算.{0,8}学|准备.{0,8}学", prefix):
            return True
        if re.match(r"(?:能力)?(?:尚不清楚|待确认|待核实|未知)", suffix):
            return True
    return False


class SkillExtractor:
    SYSTEM = (
        '从两份原文提取明确出现的技能短语，分别返回 resume 和 job 数组。'
        '每项为 {"phrase":"原文技能短语","quote":"包含该短语的连续原文"}。'
        '只抽取原文明确表达的技能，不猜测、不改写技能名称。'
        '简历中否认、尚未掌握、待验证、未来计划学习的技能不计入；岗位中无需、不要求的技能不计入。'
        '不要提取岗位名称、公司、地点、学历、福利和纯业务行业词。最多每边40项。只输出JSON。'
    )

    def __init__(self, runtime, call=None):
        from ..llm_calls import call_structured_chat
        self.runtime, self.call = runtime, call or call_structured_chat

    def extract(self, resume, job):
        inputs = {"resume": resume, "job": job}
        payload = self.call(*self.runtime,
            [{"role": "user", "content": json.dumps(inputs, ensure_ascii=False)}],
            system_prompt=self.SYSTEM, max_tokens=3500)
        if not isinstance(payload, dict):
            raise ValueError("Invalid skill extraction")
        result = {}
        for side, source in inputs.items():
            rows = payload.get(side)
            if not isinstance(rows, list):
                raise ValueError("Missing skill extraction side")
            accepted = []
            for row in rows[:40]:
                if not isinstance(row, dict):
                    continue
                phrase, quote = row.get("phrase"), row.get("quote")
                if (not isinstance(phrase, str) or not isinstance(quote, str)
                        or not 1 < len(phrase) <= 50 or phrase not in quote or quote not in source
                        or negated(quote, phrase)):
                    continue
                if not any(item["phrase"] == phrase for item in accepted):
                    accepted.append({"phrase": phrase, "quote": quote})
            result[side] = accepted
        return result

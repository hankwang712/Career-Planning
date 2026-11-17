import re

from pydantic import Field, model_validator

from .base import BaseAgent
from ..schemas.job_filters import JobFilters


class JobConstraintsAgent(BaseAgent):
    name = "job_constraints"
    system_prompt = """从本次用户求职偏好提取岗位筛选条件，只返回JSON。
只读取preferences，不猜测用户未表达的条件。cities是接受的工作城市，多个城市为或；
排除城市、过往经历城市、公司所在地不能当作接受城市。全国/城市不限时cities为空。
candidate_education只在用户明确说明本人学历时填写，不能把希望岗位的学历或未来计划当作本人学历。
薪资只转换明确的人民币税前月薪，单位元；日薪、年薪、税后、总包和面议均不换算。
本科、硕士等优先条件不应变成用户学历。include_unknown固定true，未说明的数值为null。
evidence逐项复制支撑每一个非空条件的用户连续原文，不能引用提示词或编造。
"""

    def prepare(self, payload):
        return {"preferences": payload["preferences"]}

    def get_output_schema(self, prepared):
        preferences = prepared["preferences"]

        class Extraction(JobFilters):
            evidence: dict[str, str] = Field(default_factory=dict)

            @model_validator(mode="after")
            def grounded(self):
                for key in ("cities", "candidate_education", "min_monthly_salary", "max_monthly_salary"):
                    if getattr(self, key):
                        quote = self.evidence.get(key, "")
                        if not quote or quote not in preferences:
                            raise ValueError(f"{key}需要本次偏好的原文依据")
                        if key == "cities" and any(city not in quote for city in self.cities):
                            raise ValueError("城市必须出现在对应引文中")
                        if key == "candidate_education" and self.candidate_education not in quote:
                            raise ValueError("本人学历必须出现在对应引文中")
                        if key in {"min_monthly_salary", "max_monthly_salary"}:
                            amounts = [int(float(number) * {"k": 1000, "千": 1000, "万": 10000, "": 1}[unit.lower()])
                                       for number, unit in re.findall(r"(\d+(?:\.\d+)?)\s*([kK千万]?)", quote)]
                            if "月" not in quote or re.search(r"日薪|年薪|税后|美元|美金", quote) or getattr(self, key) not in amounts:
                                raise ValueError("薪资数值必须有明确税前人民币月薪原文依据")
                if not self.include_unknown:
                    raise ValueError("自动提取必须保留条件未知的岗位")
                return self

        return Extraction

    async def _arun_prepared(self, prepared, config=None):
        return await self._arun_validated_json(prepared, config)

"""Unified Recruitment Radar agent used by the lab and multi-agent report workflow."""
from datetime import datetime
from zoneinfo import ZoneInfo
from langchain_core.runnables import RunnableConfig
from ..prompt.recruitment_search import RECRUITMENT_SEARCH_PROMPT
from ..schemas.recruitment_search import RecruitmentSearchInput, RecruitmentSearchResult
from ..tools.radar import search_recruitment_radar, verify_recruitment_radar_candidates
from .base import BaseAgent


class RecruitmentSearchAgent(BaseAgent):
    name = "recruitment_search"
    system_prompt = RECRUITMENT_SEARCH_PROMPT

    def __init__(self, model, *, use_tools=True, max_model_calls=5, max_tool_calls=8, max_search_calls=3):
        super().__init__(model, use_tools=use_tools, max_model_calls=max_model_calls)
        if not 1 <= max_tool_calls <= 20 or not 1 <= max_search_calls <= 5:
            raise ValueError("工具或检索预算超出范围")
        self.max_tool_calls = max_tool_calls
        self.max_search_calls = max_search_calls

    def prepare(self, payload):
        return {"request": RecruitmentSearchInput.model_validate(payload).model_dump(),
            "analysis_date": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
            "_sources": {}, "_tool_runs": [], "_search_calls": 0, "_discarded_sources": [], "_search_audits": []}

    def get_tools(self, prepared):
        return [search_recruitment_radar, verify_recruitment_radar_candidates]

    def get_output_schema(self, prepared):
        return RecruitmentSearchResult

    async def arun(self, payload, config: RunnableConfig | None = None):
        prepared = self.prepare(payload)
        if not self.use_tools:
            return {"agent": self.name, "status": "retrieval_error", "data": {}, "error": "已禁用工具，无法核实招聘信息"}
        from .radar_pipeline import run_radar_pipeline
        result = await run_radar_pipeline(self, prepared, config=config)
        result.update(channel="radar", sources=list(prepared["_sources"].values()), tool_runs=prepared["_tool_runs"],
                      discarded_sources=prepared["_discarded_sources"])
        return result

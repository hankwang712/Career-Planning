"""Publish current Agent work without exposing prompts or model reasoning."""
from langchain_core.callbacks import AsyncCallbackHandler


class AgentActivity(AsyncCallbackHandler):
    def __init__(self, publish):
        self.publish = publish

    async def on_tool_start(self, serialized, input_str, **kwargs):
        name = (serialized or {}).get("name", "")
        messages = {
            "read_document": "正在读取简历文档，提取经历与技能",
            "search_recruitment_radar": "正在从招聘汇总表筛选匹配岗位",
            "verify_recruitment_radar_candidates": "正在读取招聘原文，核对岗位与投递条件",
        }
        self.publish(messages.get(name, "正在查询岗位资料，核对来源证据"))

    async def on_tool_end(self, output, **kwargs):
        self.publish("资料查询已返回，正在核对证据并整理分析")

    async def on_custom_event(self, name, data, **kwargs):
        if name == "recruitment_progress" and isinstance(data, dict):
            if data.get("phase") == "validation":
                self.publish("正在修正招聘筛选结果并重新核对")
            elif data.get("reason"):
                self.publish(str(data["reason"])[:180])

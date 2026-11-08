from time import perf_counter

from langchain_core.callbacks import AsyncCallbackHandler


class AgentMetrics(AsyncCallbackHandler):
    def __init__(self):
        self.started = perf_counter()
        self.calls = set()
        self.failed = set()
        self.reported = set()
        self.tokens = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        self.tool_calls = 0

    async def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        self.calls.add(run_id)

    async def on_llm_start(self, serialized, prompts, *, run_id, **kwargs):
        self.calls.add(run_id)

    async def on_llm_error(self, error, *, run_id, **kwargs):
        self.calls.add(run_id)
        self.failed.add(run_id)

    async def on_llm_end(self, response, *, run_id, **kwargs):
        self.calls.add(run_id)
        if run_id in self.reported:
            return
        # 一次模型响应只记一份 usage；多个候选 generation 常共享同一份账单。
        usage = None
        for group in response.generations:
            for generation in group:
                message = getattr(generation, "message", None)
                usage = getattr(message, "usage_metadata", None)
                if not usage and message is not None:
                    usage = (message.response_metadata or {}).get("token_usage")
                if usage:
                    break
            if usage:
                break
        if not usage:
            usage = (response.llm_output or {}).get("token_usage")
        if not isinstance(usage, dict) or not usage:
            return
        if not any(isinstance(usage.get(key), (int, float)) and not isinstance(usage.get(key), bool)
                   and usage[key] >= 0 for key in
                   ("input_tokens", "prompt_tokens", "output_tokens", "completion_tokens", "total_tokens")):
            return

        def count(*keys):
            for key in keys:
                value = usage.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
                    return int(value)
            return 0

        incoming = count("input_tokens", "prompt_tokens")
        outgoing = count("output_tokens", "completion_tokens")
        self.tokens["input_tokens"] += incoming
        self.tokens["output_tokens"] += outgoing
        self.tokens["total_tokens"] += count("total_tokens") or incoming + outgoing
        self.reported.add(run_id)

    async def on_tool_start(self, serialized, input_str, **kwargs):
        self.tool_calls += 1

    def summary(self):
        calls, reported = len(self.calls), len(self.reported)
        status = "not_run" if not calls else "unavailable" if not reported else "reported" if reported == calls else "partial"
        return {
            "elapsed_seconds": round(perf_counter() - self.started, 3),
            "model_calls": calls, "failed_model_calls": len(self.failed),
            "tool_calls": self.tool_calls, "usage_reported_calls": reported,
            "usage_status": status,
            # 缺少用量时明确为未知，不能被误读为免费调用。
            **{key: value if reported else None for key, value in self.tokens.items()},
        }


def summarize_executions(results):
    """汇总最终保留的节点结果；重试和复核前已被替换的调用不计入此口径。"""
    stages = []
    for name, result in results.items():
        if name == "job_analysis":
            for target in result.get("data", {}).get("targets", []):
                stages.append({"stage": name, "target_id": target["target_id"],
                               "status": target["job_analysis"].get("status"),
                               **target["job_analysis"].get("execution", {})})
        else:
            stages.append({"stage": name, "status": result.get("status"), **result.get("execution", {})})
    measured = [item for item in stages if item.get("usage_reported_calls", 0)]
    return {
        "scope": "retained_results", "stages": stages,
        "model_calls": sum(item.get("model_calls", 0) for item in stages),
        "usage_reported_calls": sum(item.get("usage_reported_calls", 0) for item in stages),
        "usage_complete": bool(measured) and all(
            item.get("usage_status") in {"reported", "not_run"}
            for item in stages if item.get("status") != "skipped"
        ),
        **{key: sum(item.get(key) or 0 for item in measured) if measured else None
           for key in ("input_tokens", "output_tokens", "total_tokens")},
    }

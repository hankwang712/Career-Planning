import asyncio
from copy import deepcopy
from datetime import datetime
from time import perf_counter
from typing import Annotated, Literal, TypedDict
from zoneinfo import ZoneInfo

from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import merge_configs
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .agents import ActionPlanningAgent, CareerDecisionAgent, RecruitmentSearchAgent, ResumeAnalysisAgent
from .agents.job import JobAnalysisAgent
from .report_collaboration import MAX_EVIDENCE_ROUNDS, merge_job_evidence, pending_evidence_requests
from .schemas.action_planning import PlanningConstraints
from .schemas.followup import Clarification
from .schemas.recruitment_search import RecruitmentSearchInput
from .activity import AgentActivity


class AgentExecutionError(RuntimeError):
    def __init__(self, result: dict):
        self.result = result
        message = f"{result['agent']}: {result['status']}"
        if result.get("error"):
            message += f"；{result['error']}"
        super().__init__(message)


def followup_questions(result: dict) -> list[str]:
    data = result.get("data", {})
    questions = list(data.get("followup_questions", []))
    if result.get("agent") == "resume_analysis":
        questions.extend(data.get("missing_information", []))
        questions.extend(question for item in data.get("experiences", []) for question in item.get("followup_questions", []))
    return list(dict.fromkeys(question for question in questions if question.strip()))


class ReportInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    raw_resume: Annotated[str, Field(min_length=1, max_length=100000)]
    targets: list[Annotated[str, Field(min_length=1, max_length=300)]] = Field(min_length=1, max_length=5)
    preferences: str = Field(default="", max_length=5000)
    additional_evidence: str = Field(default="", max_length=20000)
    recruitment: RecruitmentSearchInput | None = None

    @model_validator(mode="after")
    def unique_targets(self):
        if len(set(self.targets)) != len(self.targets):
            raise ValueError("目标方向不能重复")
        return self


class ReportReview(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    target_id: str = Field(min_length=1)
    constraints: PlanningConstraints
    answers: dict[Literal["resume_analysis", "career_decision", "recruitment_search"], list[Clarification]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_period(self):
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        start = self.constraints.start_date or today
        if start < today or self.constraints.deadline < start:
            raise ValueError("开始日期不得早于今天，截止日期不得早于开始日期")
        if (self.constraints.deadline - start).days >= 366:
            raise ValueError("本阶段规划最多覆盖 366 天")
        self.constraints.start_date = start
        return self


def merge_results(current: dict, updates: dict) -> dict:
    """Each parallel branch owns its result key; later revisions replace that key."""
    return {**current, **updates}


class JobTask(TypedDict):
    target_id: str
    title: str


class ReportState(TypedDict, total=False):
    input: dict
    results: Annotated[dict, merge_results]
    job_targets: Annotated[dict, merge_results]
    decision_input: dict
    review: dict
    profile_snapshot: dict
    provenance: dict
    evidence_rounds: int
    evidence_attempts: list[dict]


def review_request(state: ReportState) -> dict:
    results = state.get("results", {})
    return {
        "kind": "report_review",
        "targets": [{"target_id": f"T{i}", "title": title} for i, title in enumerate(state["input"]["targets"], 1)],
        "questions": {name: questions for name, result in results.items()
                      if (questions := followup_questions(result))},
        "summary": results.get("career_decision", {}).get("data", {}).get("summary", ""),
        "assessments": results.get("career_decision", {}).get("data", {}).get("assessments", []),
    }


def validate_review(payload: dict, pending: dict) -> dict:
    review = ReportReview.model_validate(payload)
    if review.target_id not in {target["target_id"] for target in pending["targets"]}:
        raise ValueError("请选择本次已分析的目标")
    for agent, answers in review.answers.items():
        allowed = set(pending["questions"].get(agent, []))
        questions = [answer.question for answer in answers]
        if len(set(questions)) != len(questions) or any(question not in allowed for question in questions):
            raise ValueError("只能回答本次 Agent 实际提出的问题，每个问题回答一次")
    return review.model_dump(mode="json")


async def gather_results(*operations):
    # Drain siblings before returning an error, so they cannot outlive the node or its HTTP clients.
    results = await asyncio.gather(*operations, return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException):
            raise result
    return results


def build_report_graph(model_provider, *, checkpointer, stage_callback=None, agent_factory=None, agent_status_callback=None,
                       max_parallel_agents=3):
    if not 1 <= max_parallel_agents <= 10:
        raise ValueError("并发 Agent 数量必须在 1~10 之间")
    slots = asyncio.Semaphore(max_parallel_agents)
    activities = {}
    activity_failures = {}
    classes = {"resume_analysis": ResumeAnalysisAgent, "job_analysis": JobAnalysisAgent,
               "recruitment_search": RecruitmentSearchAgent, "career_decision": CareerDecisionAgent,
               "action_planning": ActionPlanningAgent}
    labels = {"resume_analysis": "简历分析", "job_analysis": "岗位分析", "recruitment_search": "招聘雷达",
              "career_decision": "职业决策", "review": "补充与确认", "action_planning": "行动规划",
              "parallel_analysis": "并行分析"}

    def notify(name, detail):
        if stage_callback:
            stage_callback(name, labels[name], detail)

    def activity(name, token, status, detail):
        tasks = activities.setdefault(name, {})
        if status in {"active", "pending"}:
            tasks[token] = (status, detail)
        else:
            tasks.pop(token, None)
        if status == "failed":
            activity_failures[name] = detail
        running = [value for value in tasks.values() if value[0] == "active"]
        if running:
            status, detail = running[-1]
            if len(running) > 1:
                detail += f"（共 {len(running)} 项并行任务）"
        elif tasks and status != "failed":
            status, detail = "pending", "等待执行其余目标岗位分析"
        if name in activity_failures:
            status, detail = "failed", activity_failures[name]
        if agent_status_callback:
            agent_status_callback(name, status, detail)

    async def run(name, payload, config, *, detail=None, parallel=False):
        token = object()
        activity(name, token, "pending", "等待空闲执行位置")
        try:
            async with slots:
                message = detail or {"resume_analysis": "正在梳理简历中的经历、技能与项目证据",
                    "career_decision": "正在汇总各方分析，对照经历与岗位要求比较方向",
                    "action_planning": "正在根据目标与可投入时间安排行动计划",
                    "recruitment_search": "正在理解岗位需求，准备筛选招聘机会"}.get(name, f"正在执行{labels[name]}")
                notify("parallel_analysis" if parallel else name, message)
                activity(name, token, "active", message)
                started = perf_counter()
                agent = agent_factory(name) if agent_factory else classes[name](model_provider())
                monitor = AgentActivity(lambda text: activity(name, token, "active", text))
                result = await agent.arun(deepcopy(payload), config=merge_configs(config, {"callbacks": [monitor]}))
                result.setdefault("execution", {})["stage_elapsed_seconds"] = round(perf_counter() - started, 3)
                allowed = {"ok", "insufficient_evidence"} if name == "recruitment_search" else {"ok"}
                if result["status"] not in allowed:
                    raise AgentExecutionError(result)
                activity(name, token, "done", "分析已完成，结果已交给后续步骤")
                return result
        except asyncio.CancelledError:
            activity(name, token, "canceled", "本次任务已停止")
            raise
        except Exception:
            activity(name, token, "failed", "本次分析未完成，可从已保存的步骤重试")
            raise

    async def resume(state, config: RunnableConfig, *, parallel=False):
        inputs = ReportInput.model_validate(state["input"])
        result = await run("resume_analysis", {
            "raw_resume": inputs.raw_resume, "additional_evidence": inputs.additional_evidence,
            "target_role": "、".join(inputs.targets),
        }, config, parallel=parallel)
        return {"results": {"resume_analysis": result}}

    def dispatch_jobs(state):
        return [Send("analyze_target", {"target_id": f"T{index}", "title": title})
                for index, title in enumerate(ReportInput.model_validate(state["input"]).targets, 1)]

    def dispatch_analyses(state):
        targets = dispatch_jobs(state)
        # Queue these branches first so multiple targets cannot occupy every slot ahead of them.
        return [Send("parallel_resume", {"input": state["input"]}),
                Send("parallel_recruitment", {"input": state["input"]}), *targets]

    async def analyze_target(state: JobTask, config: RunnableConfig):
        result = await run("job_analysis", {"target_role": state["title"]}, config, parallel=True,
                           detail=f"正在分析目标岗位：{state['title']}")
        return {"job_targets": {state["target_id"]: result}}

    def collect_jobs(state):
        targets = [{"target_id": f"T{index}", "title": title,
                    "job_analysis": state["job_targets"][f"T{index}"]}
                   for index, title in enumerate(state["input"]["targets"], 1)]
        return {"results": {"job_analysis": {"agent": "job_analysis", "status": "ok", "data": {"targets": targets}}}}

    async def legacy_jobs(state, config: RunnableConfig):
        # Older serial checkpoints can still have this batch node pending.
        targets = dispatch_jobs(state)
        updates = await gather_results(*(analyze_target(target.arg, config) for target in targets))
        combined = {key: result for update in updates for key, result in update["job_targets"].items()}
        return collect_jobs({**state, "job_targets": combined})

    async def recruitment(state, config: RunnableConfig, *, parallel=False):
        payload = state["input"].get("recruitment")
        if not payload:
            notify("parallel_analysis" if parallel else "recruitment_search", "未请求招聘搜索，跳过此步骤")
            result = {"agent": "recruitment_search", "status": "skipped", "data": {}}
            activity("recruitment_search", None, "skipped", "本次未启用招聘雷达")
        else:
            result = await search_with_fallback(payload, config, parallel=parallel)
        return {"results": {"recruitment_search": result}}

    async def search_with_fallback(payload, config, *, parallel=False):
        # Resume old checkpoints through the same replacement channel as new requests.
        payload = RecruitmentSearchInput.model_validate(payload).model_dump(mode="json")
        try:
            return await run("recruitment_search", payload, config, parallel=parallel)
        except AgentExecutionError as error:
            notify("parallel_analysis" if parallel else "recruitment_search", "招聘搜索暂不可用，将保留限制说明并继续已有材料分析")
            return {**error.result, "error": "招聘搜索暂不可用，请稍后重试。", "sources": [], "data": {
                "outcome": "unavailable", "summary": "本次招聘搜索暂不可用，继续依据简历与岗位知识库分析。",
                "findings": [], "followup_questions": [],
                "limitations": ["未获取可核实的招聘线索，不代表没有招聘机会，招聘状态需另行核实。"],
            }}

    async def evaluate(payload, state, config, *, detail=None):
        payload = deepcopy(payload)
        payload["evidence_rounds_remaining"] = MAX_EVIDENCE_ROUNDS - state.get("evidence_rounds", 0)
        payload["evidence_feedback"] = [
            {"target_id": item["request"]["target_id"], "question": item["request"]["question"], "outcome": item["outcome"]}
            for item in state.get("evidence_attempts", [])
        ]
        result = await run("career_decision", payload, config, detail=detail)
        # 即使模型仍然请求补查，也由编排器强制停止重复查询或超额循环。
        updated = {**state, "results": {**state["results"], "career_decision": result}}
        if result.get("data", {}).get("evidence_requests") and not pending_evidence_requests(updated):
            limitations = result["data"].setdefault("limitations", [])
            limitations.append("岗位证据补查已达轮次上限或问题已查过，尚未核实的条件继续保留为未知。")
        return {"decision_input": payload, "results": {**state["results"], "career_decision": result}}

    async def decision(state, config: RunnableConfig):
        inputs = state["input"]
        payload = {"raw_resume": inputs["raw_resume"], "additional_evidence": inputs.get("additional_evidence", ""),
                   "preferences": inputs.get("preferences", ""), "resume_analysis": state["results"]["resume_analysis"],
                   "recruitment_search": state["results"].get("recruitment_search", {}),
                   "targets": state["results"]["job_analysis"]["data"]["targets"]}
        return await evaluate(payload, state, config)

    async def supplement_evidence(state, config: RunnableConfig):
        results = deepcopy(state["results"])
        targets = {target["target_id"]: target for target in results["job_analysis"]["data"]["targets"]}
        attempts = deepcopy(state.get("evidence_attempts", []))
        round_number = state.get("evidence_rounds", 0) + 1
        requests = pending_evidence_requests(state)

        async def lookup(request):
            target = targets[request["target_id"]]
            try:
                return await run("job_analysis", {"target_role": target["title"], "question": request["question"]}, config,
                    detail=f"正在为{target['title']}补查影响决策的岗位要求（第 {round_number}/{MAX_EVIDENCE_ROUNDS} 轮）")
            except AgentExecutionError as error:
                return error.result

        supplements = await gather_results(*(lookup(request) for request in requests))
        # Merge in request order, even when several concurrent queries concern the same target.
        for request, result in zip(requests, supplements):
            target = targets[request["target_id"]]
            target["job_analysis"], outcome = merge_job_evidence(target["job_analysis"], result)
            attempts.append({"round": round_number, "request": request, "outcome": outcome,
                             "execution": result.get("execution", {})})
            if outcome != "added":
                notify("job_analysis", "本次补查未取得可合并的新证据，保留已有材料和未知条件")
        return {"results": results, "evidence_rounds": round_number, "evidence_attempts": attempts}

    async def reconsider(state, config: RunnableConfig):
        payload = deepcopy(state["decision_input"])
        payload["targets"] = state["results"]["job_analysis"]["data"]["targets"]
        return await evaluate(payload, state, config, detail="正在结合岗位补查结果重新核对职业建议")

    def route_after_decision(state):
        if pending_evidence_requests(state):
            return "supplement_evidence"
        return "action_planning" if state.get("review") else "review"

    def review(state):
        notify("review", "请补充信息、选择目标并确认可投入时间")
        pending = review_request(state)
        response = interrupt(pending)
        return {"review": validate_review(response, pending)}

    async def revise(state, config: RunnableConfig):
        results = dict(state["results"])
        payload = deepcopy(state["decision_input"])
        answers = state["review"].get("answers", {})
        operations, names = [], []
        if answers.get("resume_analysis"):
            names.append("resume_analysis")
            operations.append(run("resume_analysis", {
                "raw_resume": payload["raw_resume"], "additional_evidence": payload["additional_evidence"],
                "target_role": "、".join(state["input"]["targets"]), "clarifications": answers["resume_analysis"],
            }, config))
        if answers.get("recruitment_search"):
            search = deepcopy(state["input"]["recruitment"])
            search.setdefault("clarifications", []).extend(answers["recruitment_search"])
            names.append("recruitment_search")
            operations.append(search_with_fallback(search, config))
        for name, result in zip(names, await gather_results(*operations)):
            results[name] = result
            payload[name] = result
        # 简历追问的回答也属于候选人事实；问题文本不会作为事实证据。
        payload["clarifications"] = answers.get("resume_analysis", []) + answers.get("career_decision", [])
        if payload["clarifications"] or answers.get("recruitment_search"):
            return await evaluate(payload, {**state, "results": results}, config)
        return {"results": results, "decision_input": payload}

    async def planning(state, config: RunnableConfig):
        payload = {"decision_input": state["decision_input"], "decision_result": state["results"]["career_decision"],
                   "target_id": state["review"]["target_id"], "constraints": state["review"]["constraints"]}
        result = await run("action_planning", payload, config)
        review = deepcopy(state["review"])
        if result.get("constraints"):
            # A resumed plan may reduce its remaining window after crossing midnight.
            review["constraints"] = result["constraints"]
        return {"results": {**state["results"], "action_planning": result}, "review": review}

    async def parallel_resume(state, config: RunnableConfig):
        return await resume(state, config, parallel=True)

    async def parallel_recruitment(state, config: RunnableConfig):
        return await recruitment(state, config, parallel=True)

    graph = StateGraph(ReportState)
    graph.add_node("parallel_resume", parallel_resume)
    graph.add_node("parallel_recruitment", parallel_recruitment)
    graph.add_node("analyze_target", analyze_target)
    graph.add_node("collect_jobs", collect_jobs)
    graph.add_conditional_edges(START, dispatch_analyses,
                                ["parallel_resume", "parallel_recruitment", "analyze_target"])
    graph.add_edge("analyze_target", "collect_jobs")
    for name, node in [("resume_analysis", resume), ("job_analysis", legacy_jobs), ("recruitment_search", recruitment),
                       ("career_decision", decision), ("review", review), ("revise", revise), ("action_planning", planning),
                       ("supplement_evidence", supplement_evidence), ("reconsider", reconsider)]:
        graph.add_node(name, node)
    # This barrier spans steps: decisions wait for all branches, including the job aggregation.
    graph.add_edge(["parallel_resume", "parallel_recruitment", "collect_jobs"], "career_decision")
    # Retain the old entry nodes and edges so pre-parallel checkpoints can still resume in place.
    sequence = ["resume_analysis", "job_analysis", "recruitment_search", "career_decision"]
    for before, after in zip(sequence, sequence[1:]):
        graph.add_edge(before, after)
    for name in ("career_decision", "reconsider", "revise"):
        graph.add_conditional_edges(name, route_after_decision,
            ["supplement_evidence", "review", "action_planning"])
    graph.add_edge("supplement_evidence", "reconsider")
    graph.add_edge("review", "revise")
    graph.add_edge("action_planning", END)
    return graph.compile(checkpointer=checkpointer, name="career_report")

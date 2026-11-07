from copy import deepcopy
from datetime import datetime
from time import perf_counter
from typing import Annotated, Literal, TypedDict
from zoneinfo import ZoneInfo

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .agents import ActionPlanningAgent, CareerDecisionAgent, RecruitmentSearchAgent, ResumeAnalysisAgent
from .agents.job import JobAnalysisAgent
from .graph import AgentExecutionError, followup_questions
from .report_collaboration import MAX_EVIDENCE_ROUNDS, merge_job_evidence, pending_evidence_requests
from .schemas.action_planning import PlanningConstraints
from .schemas.followup import Clarification
from .schemas.recruitment_search import RecruitmentSearchInput


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


class ReportState(TypedDict, total=False):
    input: dict
    results: dict
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


def build_report_graph(model_provider, *, checkpointer, stage_callback=None, agent_factory=None):
    classes = {"resume_analysis": ResumeAnalysisAgent, "job_analysis": JobAnalysisAgent,
               "recruitment_search": RecruitmentSearchAgent, "career_decision": CareerDecisionAgent,
               "action_planning": ActionPlanningAgent}
    labels = {"resume_analysis": "简历分析", "job_analysis": "岗位分析", "recruitment_search": "招聘搜索",
              "career_decision": "职业决策", "review": "补充与确认", "action_planning": "行动规划"}

    def notify(name, detail):
        if stage_callback:
            stage_callback(name, labels[name], detail)

    async def run(name, payload, config, *, detail=None):
        notify(name, detail or f"正在执行{labels[name]}")
        started = perf_counter()
        agent = agent_factory(name) if agent_factory else classes[name](model_provider())
        result = await agent.arun(deepcopy(payload), config=config)
        result.setdefault("execution", {})["stage_elapsed_seconds"] = round(perf_counter() - started, 3)
        allowed = {"ok", "insufficient_evidence"} if name == "recruitment_search" else {"ok"}
        if result["status"] not in allowed:
            raise AgentExecutionError(result)
        return result

    async def resume(state, config: RunnableConfig):
        inputs = ReportInput.model_validate(state["input"])
        result = await run("resume_analysis", {
            "raw_resume": inputs.raw_resume, "additional_evidence": inputs.additional_evidence,
            "target_role": "、".join(inputs.targets),
        }, config)
        return {"results": {"resume_analysis": result}}

    async def jobs(state, config: RunnableConfig):
        results = dict(state["results"])
        targets = []
        for index, title in enumerate(state["input"]["targets"], 1):
            result = await run("job_analysis", {"target_role": title}, config)
            targets.append({"target_id": f"T{index}", "title": title, "job_analysis": result})
        results["job_analysis"] = {"agent": "job_analysis", "status": "ok", "data": {"targets": targets}}
        return {"results": results}

    async def recruitment(state, config: RunnableConfig):
        payload = state["input"].get("recruitment")
        if not payload:
            notify("recruitment_search", "未请求招聘搜索，跳过此步骤")
            result = {"agent": "recruitment_search", "status": "skipped", "data": {}}
        else:
            result = await search_with_fallback(payload, config)
        return {"results": {**state["results"], "recruitment_search": result}}

    async def search_with_fallback(payload, config):
        try:
            return await run("recruitment_search", payload, config)
        except AgentExecutionError as error:
            notify("recruitment_search", "招聘搜索暂不可用，将保留限制说明并继续已有材料分析")
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
        for request in pending_evidence_requests(state):
            target = targets[request["target_id"]]
            try:
                result = await run("job_analysis", {"target_role": target["title"], "question": request["question"]}, config,
                    detail=f"正在为{target['title']}补查影响决策的岗位要求（第 {round_number}/{MAX_EVIDENCE_ROUNDS} 轮）")
            except AgentExecutionError as error:
                result = error.result
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
        if answers.get("resume_analysis"):
            result = await run("resume_analysis", {
                "raw_resume": payload["raw_resume"], "additional_evidence": payload["additional_evidence"],
                "target_role": "、".join(state["input"]["targets"]), "clarifications": answers["resume_analysis"],
            }, config)
            results["resume_analysis"] = result
            payload["resume_analysis"] = result
        if answers.get("recruitment_search"):
            search = deepcopy(state["input"]["recruitment"])
            search.setdefault("clarifications", []).extend(answers["recruitment_search"])
            results["recruitment_search"] = await search_with_fallback(search, config)
            payload["recruitment_search"] = results["recruitment_search"]
        # 简历追问的回答也属于候选人事实；问题文本不会作为事实证据。
        payload["clarifications"] = answers.get("resume_analysis", []) + answers.get("career_decision", [])
        if payload["clarifications"] or answers.get("recruitment_search"):
            return await evaluate(payload, {**state, "results": results}, config)
        return {"results": results, "decision_input": payload}

    async def planning(state, config: RunnableConfig):
        payload = {"decision_input": state["decision_input"], "decision_result": state["results"]["career_decision"],
                   "target_id": state["review"]["target_id"], "constraints": state["review"]["constraints"]}
        result = await run("action_planning", payload, config)
        return {"results": {**state["results"], "action_planning": result}}

    graph = StateGraph(ReportState)
    for name, node in [("resume_analysis", resume), ("job_analysis", jobs), ("recruitment_search", recruitment),
                       ("career_decision", decision), ("review", review), ("revise", revise), ("action_planning", planning),
                       ("supplement_evidence", supplement_evidence), ("reconsider", reconsider)]:
        graph.add_node(name, node)
    sequence = [START, "resume_analysis", "job_analysis", "recruitment_search", "career_decision"]
    for before, after in zip(sequence, sequence[1:]):
        graph.add_edge(before, after)
    for name in ("career_decision", "reconsider", "revise"):
        graph.add_conditional_edges(name, route_after_decision,
            ["supplement_evidence", "review", "action_planning"])
    graph.add_edge("supplement_evidence", "reconsider")
    graph.add_edge("review", "revise")
    graph.add_edge("action_planning", END)
    return graph.compile(checkpointer=checkpointer, name="career_report")

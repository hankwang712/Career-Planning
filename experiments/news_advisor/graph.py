"""用 LangGraph State 和 Checkpointer 保存各 Agent 的输入、结果与补充回答。"""

from copy import deepcopy
import json

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, MessagesState, StateGraph

from .agents import ActionPlanningAgent, CareerDecisionAgent, RecruitmentSearchAgent, ResumeAnalysisAgent
from .schemas.action_planning import ActionPlanningInput
from .schemas.career_decision import CareerDecisionInput
from .schemas.followup import Clarification
from .schemas.recruitment_search import RecruitmentSearchInput
from .schemas.resume import ResumeInput
from .schemas.workflow import AgentRequest


AGENTS = {
    "resume_analysis": (ResumeInput, ResumeAnalysisAgent),
    "recruitment_search": (RecruitmentSearchInput, RecruitmentSearchAgent),
    "career_decision": (CareerDecisionInput, CareerDecisionAgent),
    "action_planning": (ActionPlanningInput, ActionPlanningAgent),
}


class AdvisorState(MessagesState, total=False):
    request: dict
    candidate: dict
    inputs: dict[str, dict]
    results: dict[str, dict]


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


def build_advisor_graph(model_provider, *, checkpointer: BaseCheckpointSaver):
    async def prepare(state: AdvisorState):
        request = AgentRequest.model_validate(state["request"])
        name = request.agent
        inputs, results = deepcopy(state.get("inputs", {})), deepcopy(state.get("results", {}))
        payload = inputs.get(name, {}).copy()
        payload.update(request.input)
        candidate = deepcopy(state.get("candidate", {}))
        if request.answers:
            questions = set(followup_questions(results.get(name, {})))
            if any(item.question not in questions for item in request.answers):
                raise ValueError("请回答当前线程中该 Agent 实际提出的问题")
        if name in {"resume_analysis", "career_decision"}:
            for key in ("raw_resume", "additional_evidence", "clarifications"):
                if key in request.input:
                    value = request.input[key]
                    if key == "additional_evidence" and candidate.get(key):
                        if not isinstance(value, str):
                            raise ValueError("additional_evidence 必须为文本")
                        value = candidate[key] + "\n" + value
                    if key == "clarifications":
                        if not isinstance(value, list):
                            raise ValueError("clarifications 必须为列表")
                        value = [Clarification.model_validate(item).model_dump() for item in value]
                    candidate[key] = value
            if "raw_resume" in request.input:
                candidate["document"] = {}
            if request.answers:
                candidate.setdefault("clarifications", []).extend(item.model_dump() for item in request.answers)
        elif request.answers:
            payload.setdefault("clarifications", []).extend(item.model_dump() for item in request.answers)

        if name == "resume_analysis":
            if request.input.get("file_path"):
                from .tools.document import read_document

                if request.input.get("raw_resume"):
                    raise ValueError("file_path 和 raw_resume 只需提供一个")
                document = await read_document.ainvoke({
                    "file_path": request.input["file_path"], "max_pages": payload.get("max_pages", 20),
                })
                if document.get("status") not in {"ok", "partial"} or not document.get("markdown", "").strip():
                    raise ValueError("简历读取失败，请确认文件内容和 OCR 服务")
                payload.update(file_path="", raw_resume=document["markdown"], document={
                    key: document[key] for key in ("file_path", "status", "warnings", "processed_pages", "total_pages")
                    if key in document
                })
                candidate.update(raw_resume=payload["raw_resume"], document=payload["document"])
            elif "raw_resume" in request.input:
                payload.update(file_path="", document={})
                candidate["document"] = {}
            elif "document" in request.input:
                candidate["document"] = request.input["document"]

        if candidate != state.get("candidate", {}):
            for key in ("resume_analysis", "career_decision", "action_planning"):
                results.pop(key, None)

        if name in {"resume_analysis", "career_decision"}:
            payload.update({key: value for key, value in candidate.items()
                            if key != "document" or name == "resume_analysis"})

        if name == "career_decision":
            if "resume_analysis" not in request.input:
                payload["resume_analysis"] = results.get("resume_analysis", {
                    "status": "not_run", "document": candidate.get("document", {}),
                })

        if name == "action_planning" and not {"decision_input", "decision_result"} <= request.input.keys():
            decision = results.get("career_decision", {})
            if decision.get("status") != "ok":
                raise ValueError("请先在本线程完成或更新职业决策，再生成行动计划")
            payload.update(decision_input=inputs["career_decision"], decision_result=decision)

        schema = AGENTS[name][0]
        payload = schema.model_validate(payload).model_dump(mode="json")
        # 条件更新后不继续展示依赖旧材料的决策与计划。
        invalidated = {name}
        if name == "resume_analysis":
            invalidated.update(("career_decision", "action_planning"))
        elif name == "career_decision":
            invalidated.add("action_planning")
        for key in invalidated:
            results.pop(key, None)
        inputs[name] = payload
        return {"candidate": candidate, "inputs": inputs, "results": results, "messages": [HumanMessage(
            content=json.dumps(request.model_dump(exclude={"checkpoint_id"}), ensure_ascii=False),
        )]}

    def execution_node(name):
        async def execute(state: AdvisorState, config: RunnableConfig):
            agent = AGENTS[name][1](model_provider())
            result = await agent.arun(deepcopy(state["inputs"][name]), config=config)
            if result["status"] not in {"ok", "insufficient_evidence"}:
                # 保留原生失败检查点；ainvoke(None, config) 可从该节点重试。
                raise AgentExecutionError(result)
            summary = result.get("data", {}).get("summary") or result["status"]
            # 当前状态仅保留最近 20 条消息；历史检查点仍由 checkpointer 管理。
            messages = [RemoveMessage(id=message.id) for message in state.get("messages", [])[:-19] if message.id]
            return {"results": {**state.get("results", {}), name: result},
                    "messages": messages + [AIMessage(content=summary)]}

        return execute

    graph = StateGraph(AdvisorState)
    graph.add_node("prepare", prepare)
    graph.add_edge(START, "prepare")
    for name in AGENTS:
        graph.add_node(name, execution_node(name))
        graph.add_edge(name, END)
    graph.add_conditional_edges("prepare", lambda state: state["request"]["agent"], {name: name for name in AGENTS})
    return graph.compile(checkpointer=checkpointer, name="career_advisor")

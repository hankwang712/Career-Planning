"""在项目根目录运行：uvicorn experiments.main:app --port 8001 --reload。"""

import argparse
import asyncio
import json
from functools import lru_cache
from typing import TypedDict

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from .news_advisor.agents.base import BaseAgent
from .news_advisor.config import get_ai_config


@lru_cache(maxsize=1)
def get_model() -> ChatOpenAI:
    try:
        settings = get_ai_config("chat")
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    return ChatOpenAI(
        api_key=settings.api_key,
        base_url=settings.base_url,
        model=settings.model,
        # 此演示使用工具提交结构化结果，关闭 DeepSeek 思考模式以兼容 tool_choice。
        extra_body={"thinking": {"type": "disabled"}},
        timeout=60,
        max_retries=0,
    )


app = FastAPI(title="FastAPI + LangGraph 最小测试")


@app.get("/", include_in_schema=False)
async def index():
    return RedirectResponse("/docs")


@app.get("/health")
async def health():
    """只检查 HTTP 服务，不调用模型。"""
    return {"status": "ok"}


# 以下为多智能体演示：商品和价格均为本地模拟数据。
CATALOG = {
    "基础笔记本": {"kind": "notebook", "price": 8},
    "加厚笔记本": {"kind": "notebook", "price": 12},
    "普通中性笔": {"kind": "pen", "price": 2},
    "舒适中性笔": {"kind": "pen", "price": 3},
}


@tool
def lookup_products() -> dict:
    """查询演示商品目录，返回商品名称、种类及人民币单价。"""
    print("[工具 lookup_products] " + json.dumps(CATALOG, ensure_ascii=False), flush=True)
    return CATALOG


@tool
def check_budget(notebook_name: str, pen_name: str, people: int, budget: int) -> dict:
    """按目录价格计算每人一本笔记本、两支笔的总价和预算余额。"""
    notebook = CATALOG.get(notebook_name)
    pen = CATALOG.get(pen_name)
    if not notebook or notebook["kind"] != "notebook" or not pen or pen["kind"] != "pen":
        result = {"error": "商品不存在或种类错误，请使用目录中的完整商品名。"}
    elif people < 1 or budget < 1:
        result = {"error": "人数和预算必须为正整数。"}
    else:
        total = people * (notebook["price"] + 2 * pen["price"])
        result = {"total": total, "remaining": budget - total, "within_budget": total <= budget}
    print(
        f"[工具 check_budget] {notebook_name}, {pen_name}, 人数={people}, 预算={budget} -> "
        + json.dumps(result, ensure_ascii=False),
        flush=True,
    )
    return result


class TeamRequest(BaseModel):
    budget: int = Field(default=100, ge=1, le=100000, strict=True)
    people: int = Field(default=6, ge=1, le=1000, strict=True)


class PurchasePlan(BaseModel):
    notebook_name: str
    pen_name: str
    reason: str


class BudgetReview(BaseModel):
    within_budget: bool
    total: int
    remaining: int
    conclusion: str


class PurchaseAgent(BaseAgent):
    name = "purchase"
    system_prompt = (
        "你是采购 Agent。任务：按输入人数，为每人买一本笔记本和两支笔，尽量节省预算。"
        "必须先调用 lookup_products 查询真实可选商品，再选最便宜的笔记本和笔。"
        "完整商品名必须来自工具。即使预算不足也提交最便宜组合，并在 reason 说明。用中文回答。"
    )

    def prepare(self, payload: dict) -> dict:
        return payload

    def get_tools(self, prepared: dict) -> list:
        return [lookup_products]

    def get_output_schema(self, prepared: dict) -> type[BaseModel]:
        return PurchasePlan


class ReviewAgent(PurchaseAgent):
    name = "review"
    system_prompt = (
        "你是独立的预算核算 Agent。根据上一个采购 Agent 的方案，必须调用 check_budget，"
        "传入采购方案的完整商品名以及原始请求的 people、budget。"
        "只按工具计算结果填写 total、remaining、within_budget，不要自行猜测。"
        "工具报错时明确说明失败，不得编造金额。conclusion 用中文说明方案是否可行。"
    )

    def get_tools(self, prepared: dict) -> list:
        return [check_budget]

    def get_output_schema(self, prepared: dict) -> type[BaseModel]:
        return BudgetReview


class TeamState(TypedDict, total=False):
    request: dict
    purchase: dict
    review: dict


def build_team(model):
    purchase = PurchaseAgent(model, max_model_calls=5)
    reviewer = ReviewAgent(model, max_model_calls=5)

    async def purchase_node(state: TeamState) -> dict:
        print("\n[Agent 1：采购] 查询商品并制定方案…", flush=True)
        result = await purchase.arun(state["request"])
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return {"purchase": result}

    async def review_node(state: TeamState) -> dict:
        print("\n[Agent 2：核算] 接收采购方案并调用预算工具…", flush=True)
        result = await reviewer.arun({
            **state["request"], "plan": state["purchase"]["data"],
        })
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return {"review": result}

    graph = StateGraph(TeamState)
    graph.add_node("purchase", purchase_node)
    graph.add_node("review", review_node)
    graph.add_edge(START, "purchase")
    graph.add_conditional_edges(
        "purchase",
        lambda state: "review" if state["purchase"]["status"] == "ok" else END,
        {"review": "review", END: END},
    )
    graph.add_edge("review", END)
    return graph.compile()


async def run_team(request: TeamRequest) -> dict:
    print(f"\n任务：预算 {request.budget} 元，为 {request.people} 人每人买一本笔记本和两支笔。", flush=True)
    graph = build_team(get_model())
    state = await graph.ainvoke({"request": request.model_dump()})
    return {name: state[name] for name in ("purchase", "review") if name in state}


@app.post("/api/demo/team", tags=["多智能体测试"])
async def team(request: TeamRequest):
    results = await run_team(request)
    for result in results.values():
        if result["status"] != "ok":
            code = 503 if result["status"] == "execution_limit" else 502
            raise HTTPException(status_code=code, detail=result)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="两个带工具的 Agent 协作采购并核算预算")
    parser.add_argument("--budget", type=int, default=100, help="预算，默认 100 元")
    parser.add_argument("--people", type=int, default=6, help="人数，默认 6 人")
    args = parser.parse_args()
    try:
        outcome = asyncio.run(run_team(TeamRequest(budget=args.budget, people=args.people)))
        if any(result["status"] != "ok" for result in outcome.values()):
            raise SystemExit(1)
        print("\n[完成] 两个 Agent 已依次完成执行。", flush=True)
    except HTTPException as exc:
        parser.exit(1, f"配置错误：{exc.detail}\n")

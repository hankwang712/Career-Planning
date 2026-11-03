import argparse
import asyncio
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def run(args) -> dict:
    from langchain_openai import ChatOpenAI
    from experiments.news_advisor.agents import RecruitmentSearchAgent
    from experiments.news_advisor.config import get_ai_config

    settings = get_ai_config("chat")
    model = ChatOpenAI(
        api_key=settings.api_key, base_url=settings.base_url, model=settings.model,
        temperature=0, timeout=args.timeout, max_retries=0,
        extra_body={"thinking": {"type": "disabled"}, "max_tokens": 8192},
    )
    return await RecruitmentSearchAgent(model, max_model_calls=args.max_model_calls,
                                      max_tool_calls=args.max_tool_calls).arun({
        "request": args.request, "channel": args.channel, "days": args.days, "limit": args.limit,
    })


def main() -> int:
    parser = argparse.ArgumentParser(description="根据自然语言需求搜索校招、实习、社招及相关招聘信息")
    parser.add_argument("request", help="例如：找近7天上海杭州的算法实习公众号推文，保留发布日期和原文")
    parser.add_argument("--channel", choices=["wechat", "web", "all"], default="wechat")
    parser.add_argument("--days", type=int, help="可选，显式指定时间窗口；默认从自然语言需求理解")
    parser.add_argument("--limit", type=int, choices=range(1, 11), default=5, metavar="1..10")
    parser.add_argument("--max-model-calls", type=int, choices=range(1, 11), default=5, metavar="1..10")
    parser.add_argument("--max-tool-calls", type=int, choices=range(1, 21), default=8, metavar="1..20")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--output", type=Path, help="可选 JSON 结果文件，包含真实来源与调用记录")
    args = parser.parse_args()
    if args.days is not None and not 1 <= args.days <= 365:
        parser.error("days 必须为 1—365")
    if not args.request.strip() or len(args.request) > 3000 or args.timeout <= 0:
        parser.error("request 必须非空且不超过3000字，timeout 必须大于0")
    try:
        result = asyncio.run(run(args))
    except ImportError as error:
        parser.exit(2, f"依赖缺失或不兼容：{error.name}；请在当前 Python 环境安装 experiments/requirements-resume.txt\n")
    except Exception as error:
        parser.exit(1, f"运行失败：{type(error).__name__}，请检查模型配置与浏览器服务\n")
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
        print(f"状态：{result['status']}；已保存：{args.output.resolve()}")
    else:
        print(text)
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())

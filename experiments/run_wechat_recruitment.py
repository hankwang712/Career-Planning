"""运行微信公众号招聘文章搜索或读取工具，不调用 LLM。"""

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="发现近期微信招聘文章，或读取指定微信文章",
        epilog="需已启动浏览器 HTTP 会话服务；WECHAT_BROWSER_PROXY_URL 默认 http://localhost:3456。",
    )
    parser.add_argument("query", nargs="?", help="搜索词，例如人工智能、联想或互联网")
    parser.add_argument("--read-url", help="读取搜索返回的完整微信文章链接")
    parser.add_argument("--company", default="", help="可选企业词")
    parser.add_argument("--recruitment-type", choices=["不限", "社招", "春招", "秋招", "实习", "校招"], default="不限")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--output", type=Path, help="可选 JSON 结果文件")
    args = parser.parse_args()
    if bool(args.query) == bool(args.read_url):
        parser.error("提供搜索词或 --read-url，二者择一")
    from experiments.news_advisor.tools import read_wechat_article, search_wechat_recruitment

    if args.read_url:
        result = read_wechat_article.invoke({"url": args.read_url})
    else:
        if not 1 <= args.days <= 365 or not 1 <= args.limit <= 10:
            parser.error("days 需为 1—365，limit 需为 1—10")
        result = search_wechat_recruitment.invoke({"query": args.query, "company": args.company,
            "recruitment_type": args.recruitment_type, "days": args.days, "limit": args.limit})
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
        print(f"状态：{result['status']}；已保存：{args.output.resolve()}")
    else:
        print(text)
    return 0 if result["status"] in {"ok", "partial", "image_only"} else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())

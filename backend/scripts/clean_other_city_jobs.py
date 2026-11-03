#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
from typing import Any


def extract_city_from_address(address: str) -> str:
    raw = str(address or "").strip()
    if not raw:
        return ""
    if "_" in raw:
        return raw.split("_", 1)[0].strip().strip("-").strip()
    if "-" in raw:
        return raw.split("-", 1)[0].strip()
    return raw


def first_industry_segment(industry: str) -> str:
    parts = [p.strip() for p in re.split(r"[,，、/|]+", str(industry or "")) if p.strip()]
    return parts[0] if parts else ""


def normalize_salary_range(raw: str) -> str:
    """
    将 other_city 常见薪资文案统一转为「K/月」月薪形式，便于前端 parseSalary 与各图表统计。
    处理范围：
      - 万/月      -> K/月（例：1-1.2万·13薪 -> 10-12K·13薪）
      - 元/月      -> K/月（例：8000-12000元/月 -> 8-12K）
      - 元（无后缀）-> 视为月薪，转 K/月（例：3000-4000元 -> 3-4K）
      - 元/天      -> 按 22 天/月折算为月薪 K/月（例：100-150元/天 -> 2.2-3.3K）
      - 面议       -> 原样返回
    """
    s = str(raw or "").strip().replace(" ", "")
    if not s or s == "面议":
        return str(raw or "").strip()

    pay_suffix = ""
    m_pay = re.search(r"(·\d+薪)$", s, flags=re.I)
    if m_pay:
        pay_suffix = m_pay.group(1)
        s_body = s[: m_pay.start()]
    else:
        s_body = s

    def fmt_k(x: float) -> str:
        if abs(x - round(x)) < 1e-6:
            return str(int(round(x)))
        t = f"{x:.2f}".rstrip("0").rstrip(".")
        return t

    # 1) 万/月 或 万
    wan_r = re.match(r"^(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)万(?:/月)?$", s_body, flags=re.I)
    if wan_r:
        lo = float(wan_r.group(1)) * 10
        hi = float(wan_r.group(2)) * 10
        return f"{fmt_k(lo)}-{fmt_k(hi)}K{pay_suffix}"
    wan_one = re.match(r"^(\d+(?:\.\d+)?)万(?:/月)?$", s_body, flags=re.I)
    if wan_one:
        v = float(wan_one.group(1)) * 10
        return f"{fmt_k(v)}K{pay_suffix}"

    # 2) 元/月
    ym_r = re.match(r"^(\d+)\s*-\s*(\d+)元/月$", s_body, flags=re.I)
    if ym_r:
        lo = int(ym_r.group(1)) / 1000
        hi = int(ym_r.group(2)) / 1000
        return f"{fmt_k(lo)}-{fmt_k(hi)}K{pay_suffix}"
    ym_one = re.match(r"^(\d+)元/月$", s_body, flags=re.I)
    if ym_one:
        v = int(ym_one.group(1)) / 1000
        return f"{fmt_k(v)}K{pay_suffix}"

    # 3) 元/天 -> 按 22 天/月折算为月薪
    DAILY_TO_MONTHLY_DAYS = 22
    daily_r = re.match(r"^(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)元/天$", s_body, flags=re.I)
    if daily_r:
        lo = float(daily_r.group(1)) * DAILY_TO_MONTHLY_DAYS / 1000
        hi = float(daily_r.group(2)) * DAILY_TO_MONTHLY_DAYS / 1000
        return f"{fmt_k(lo)}-{fmt_k(hi)}K{pay_suffix}"
    daily_one = re.match(r"^(\d+(?:\.\d+)?)元/天$", s_body, flags=re.I)
    if daily_one:
        v = float(daily_one.group(1)) * DAILY_TO_MONTHLY_DAYS / 1000
        return f"{fmt_k(v)}K{pay_suffix}"

    # 4) 纯 元（无 /月、/天 后缀）-> 视为月薪处理
    yuan_r = re.match(r"^(\d+)\s*-\s*(\d+)元$", s_body, flags=re.I)
    if yuan_r:
        lo = int(yuan_r.group(1)) / 1000
        hi = int(yuan_r.group(2)) / 1000
        return f"{fmt_k(lo)}-{fmt_k(hi)}K{pay_suffix}"
    yuan_one = re.match(r"^(\d+)元$", s_body, flags=re.I)
    if yuan_one:
        v = int(yuan_one.group(1)) / 1000
        return f"{fmt_k(v)}K{pay_suffix}"
    yuan_below = re.match(r"^(\d+)元以下$", s_body, flags=re.I)
    if yuan_below:
        v = int(yuan_below.group(1)) / 1000
        return f"{fmt_k(v)}K{pay_suffix}"

    # 5) 已经含 K/k/元/天/万/元/月 但未能被上面规则捕获的，原样保留
    if re.search(r"K|k|元/天|万|元/月", s_body):
        return str(raw or "").strip()
    return str(raw or "").strip()


def trim_text(value: Any, max_len: int) -> str:
    s = str(value or "").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def normalize_record(raw: dict[str, Any], seq: int) -> dict[str, Any] | None:
    title = str(raw.get("岗位名称") or "").strip()
    company = str(raw.get("公司名称") or "").strip()
    if not title or not company:
        return None

    addr = str(raw.get("地址") or "").strip()
    city = extract_city_from_address(addr)
    industry = first_industry_segment(str(raw.get("所属行业") or ""))

    return {
        "采集序号": seq,
        "采集城市": city or addr or "",
        "公司名称": company,
        "岗位名称": title,
        "职位类别": industry or "",
        "城市": city or addr or "",
        "经验要求": "",
        "学历要求": "",
        "薪资": normalize_salary_range(str(raw.get("薪资范围") or "")),
        "岗位描述": trim_text(raw.get("岗位详情"), 12000),
        "工作地址": addr,
        "技能要求": "",
        "融资阶段": str(raw.get("公司类型") or "").strip(),
        "公司规模": str(raw.get("公司规模") or "").strip(),
        "公司行业": str(raw.get("所属行业") or "").strip(),
        "公司简介": trim_text(raw.get("公司详情"), 12000),
        "公司福利": "",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default=str(Path(__file__).resolve().parents[2] / "data" / "raw" / "other_city.json"),
        help="原始 other_city.json 路径",
    )
    parser.add_argument(
        "--output",
        default=str(Path(__file__).resolve().parents[2] / "data" / "cleaned" / "other_city_boss_format.json"),
        help="清洗后输出路径",
    )
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as fp:
        data = json.load(fp)
    if not isinstance(data, list):
        raise SystemExit("输入 JSON 应为数组")

    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    seq = 1
    for item in data:
        if not isinstance(item, dict):
            continue
        rec = normalize_record(item, seq)
        if not rec:
            continue
        key = (rec["公司名称"], rec["岗位名称"], rec["工作地址"])
        if key in seen:
            continue
        seen.add(key)
        out.append(rec)
        seq += 1

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False, indent=2)

    print(f"读取: {args.input}")
    print(f"写出: {args.output}")
    print(f"条数: {len(out)}（已去重、已过滤空岗位/公司）")


if __name__ == "__main__":
    main()

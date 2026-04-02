from __future__ import annotations

from html import escape
from typing import Any


def _join_tags(tags: list[str]) -> str:
    return " · ".join([escape(str(item)) for item in tags if str(item).strip()])


def render_report_markdown(report: dict[str, Any]) -> str:
    meta = report.get("meta") if isinstance(report.get("meta"), dict) else {}
    doc = report.get("report_document") if isinstance(report.get("report_document"), dict) else {}
    lines = [
        f"# {doc.get('title') or meta.get('title') or '职业规划报告'}",
        "",
        f"> 生成时间：{meta.get('generated_at') or '--'}",
        f"> 报告版本：{meta.get('version') or '--'}",
        f"> 生成模式：{meta.get('generation_mode') or '--'}",
        "",
        "## 执行摘要",
        str(doc.get("executive_summary") or meta.get("summary") or "系统已根据当前画像生成职业规划报告。"),
        "",
    ]
    for section in doc.get("sections") or []:
        if not isinstance(section, dict):
            continue
        lines.append(f"## {section.get('title') or '章节'}")
        lines.append(str(section.get("summary") or ""))
        lines.append("")
        for card in section.get("cards") or []:
            if not isinstance(card, dict):
                continue
            lines.append(f"### {card.get('title') or '要点'}")
            lines.append(str(card.get("body") or ""))
            evidence = [str(item) for item in card.get("evidence_sources") or [] if str(item).strip()]
            tags = [str(item) for item in card.get("tags") or [] if str(item).strip()]
            if evidence:
                lines.append(f"- 来源：{'、'.join(evidence)}")
            lines.append(f"- 置信度：{card.get('confidence') or '中'}")
            if tags:
                lines.append(f"- 标签：{'、'.join(tags)}")
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def _render_visualization_html(visualization: dict[str, Any] | None) -> str:
    if not isinstance(visualization, dict):
        return ""
    viz_type = str(visualization.get("type") or "").strip()
    items = visualization.get("items") if isinstance(visualization.get("items"), list) else []
    if viz_type == "score-bars":
        bars = []
        for item in items:
            value = max(0, min(100, int(item.get("value") or 0)))
            bars.append(
                f"""
                <div class="viz-row">
                  <div class="viz-row-meta">
                    <strong>{escape(str(item.get('label') or '方向'))}</strong>
                    <span>{escape(str(item.get('hint') or ''))}</span>
                  </div>
                  <div class="viz-track"><div class="viz-fill" style="width:{value}%"></div></div>
                  <em>{value}%</em>
                </div>
                """
            )
        return f'<div class="viz-box">{"".join(bars)}</div>'
    if viz_type == "gap-matrix":
        cells = []
        for item in items:
            current = "--" if item.get("current") is None else f"{int(item.get('current') or 0)}"
            required = "--" if item.get("required") is None else f"{int(item.get('required') or 0)}"
            cells.append(
                f"""
                <article class="matrix-card">
                  <span>{escape(str(item.get('label') or '能力项'))}</span>
                  <strong>{current} / {required}</strong>
                  <em>{escape(str(item.get('status') or '待补证'))}</em>
                </article>
                """
            )
        return f'<div class="viz-grid">{"".join(cells)}</div>'
    if viz_type == "timeline":
        points = []
        for item in items:
            points.append(
                f"""
                <article class="timeline-item">
                  <span class="timeline-label">{escape(str(item.get('label') or '阶段'))}</span>
                  <strong>{escape(str(item.get('title') or '成长节点'))}</strong>
                  <p>{escape(str(item.get('summary') or ''))}</p>
                </article>
                """
            )
        return f'<div class="timeline-box">{"".join(points)}</div>'
    if viz_type == "signal-cards":
        signals = []
        for item in items:
            signals.append(
                f"""
                <article class="signal-card">
                  <span>{escape(str(item.get('impact') or '趋势信号'))}</span>
                  <strong>{escape(str(item.get('title') or '趋势摘要'))}</strong>
                  <p>{escape(str(item.get('summary') or ''))}</p>
                </article>
                """
            )
        return f'<div class="signal-grid">{"".join(signals)}</div>'
    return ""


def render_report_html(report: dict[str, Any]) -> str:
    meta = report.get("meta") if isinstance(report.get("meta"), dict) else {}
    doc = report.get("report_document") if isinstance(report.get("report_document"), dict) else {}
    sections_html = []
    for section in doc.get("sections") or []:
        if not isinstance(section, dict):
            continue
        cards_html = []
        for card in section.get("cards") or []:
            if not isinstance(card, dict):
                continue
            cards_html.append(
                f"""
                <article class="card tone-{escape(str(card.get('tone') or 'indigo'))}">
                  <div class="card-top">
                    <h4>{escape(str(card.get('title') or '要点'))}</h4>
                    <span>{escape(str(card.get('confidence') or '中'))}置信</span>
                  </div>
                  <p>{escape(str(card.get('body') or ''))}</p>
                  <div class="card-meta">
                    <small>来源：{_join_tags(card.get('evidence_sources') or []) or '报告系统'}</small>
                    <small>{_join_tags(card.get('tags') or [])}</small>
                  </div>
                </article>
                """
            )
        sections_html.append(
            f"""
            <section id="{escape(str(section.get('id') or 'section'))}" class="section">
              <div class="section-head">
                <span class="kicker">{escape(str(section.get('kicker') or 'Career Report'))}</span>
                <h2>{escape(str(section.get('title') or '章节'))}</h2>
                <p>{escape(str(section.get('summary') or ''))}</p>
              </div>
              {_render_visualization_html(section.get('visualization'))}
              <div class="card-grid">
                {''.join(cards_html)}
              </div>
            </section>
            """
        )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(str(doc.get('title') or meta.get('title') or '职业规划报告'))}</title>
  <style>
    :root {{
      --bg:#f7f9fc;
      --panel:#ffffff;
      --text:#111827;
      --muted:#667085;
      --line:#d8e1f0;
      --brand:#4f46e5;
      --brand-2:#2563eb;
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:"Microsoft YaHei","PingFang SC",sans-serif; background:var(--bg); color:var(--text); }}
    .page {{ max-width:1200px; margin:0 auto; padding:32px 24px 56px; }}
    .hero {{ background:linear-gradient(135deg,#1e3a8a,#4f46e5 60%,#7c3aed); color:#fff; border-radius:28px; padding:28px 32px; box-shadow:0 24px 60px rgba(79,70,229,.18); }}
    .hero small {{ display:block; opacity:.82; letter-spacing:.12em; text-transform:uppercase; }}
    .hero h1 {{ margin:10px 0 12px; font-size:34px; }}
    .hero p {{ margin:0; line-height:1.8; max-width:820px; }}
    .hero-meta {{ display:flex; gap:18px; flex-wrap:wrap; margin-top:18px; font-size:13px; opacity:.92; }}
    .section {{ background:var(--panel); border:1px solid var(--line); border-radius:24px; padding:24px; margin-top:20px; box-shadow:0 14px 36px rgba(15,23,42,.06); }}
    .section-head h2 {{ margin:8px 0 10px; font-size:24px; }}
    .section-head p {{ margin:0; color:var(--muted); line-height:1.8; }}
    .kicker {{ font-size:12px; letter-spacing:.18em; text-transform:uppercase; color:#7c8baa; }}
    .card-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:16px; margin-top:18px; }}
    .card {{ border:1px solid var(--line); border-radius:20px; padding:18px; background:#fbfcff; }}
    .card-top {{ display:flex; justify-content:space-between; gap:12px; align-items:flex-start; }}
    .card h4 {{ margin:0; font-size:16px; }}
    .card p {{ margin:12px 0 0; color:var(--muted); line-height:1.75; }}
    .card-meta {{ display:flex; flex-direction:column; gap:6px; margin-top:14px; color:#8a94a8; }}
    .viz-box,.viz-grid,.signal-grid,.timeline-box {{ margin-top:18px; }}
    .viz-row {{ display:grid; grid-template-columns:minmax(140px,220px) 1fr auto; gap:12px; align-items:center; margin-top:10px; }}
    .viz-row-meta {{ display:flex; flex-direction:column; gap:4px; }}
    .viz-row-meta span {{ color:var(--muted); font-size:13px; }}
    .viz-track {{ height:10px; border-radius:999px; background:#e9eef8; overflow:hidden; }}
    .viz-fill {{ height:100%; border-radius:999px; background:linear-gradient(90deg,var(--brand),#60a5fa); }}
    .viz-grid,.signal-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:14px; }}
    .matrix-card,.signal-card,.timeline-item {{ border:1px solid var(--line); border-radius:18px; background:#fff; padding:16px; }}
    .matrix-card span,.signal-card span,.timeline-label {{ color:var(--muted); font-size:12px; display:block; margin-bottom:8px; }}
    .matrix-card strong,.signal-card strong,.timeline-item strong {{ font-size:15px; }}
    .matrix-card em {{ display:block; margin-top:8px; color:#4f46e5; font-style:normal; }}
    .timeline-box {{ display:grid; gap:12px; }}
    @media (max-width: 900px) {{
      .page {{ padding:20px 14px 40px; }}
      .hero {{ padding:22px 18px; border-radius:22px; }}
      .hero h1 {{ font-size:28px; }}
      .section {{ padding:18px; border-radius:20px; }}
      .viz-row {{ grid-template-columns:1fr; }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <small>Career Planning Report</small>
      <h1>{escape(str(doc.get('title') or meta.get('title') or '职业规划报告'))}</h1>
      <p>{escape(str(doc.get('executive_summary') or meta.get('summary') or '系统已根据当前画像生成职业规划报告。'))}</p>
      <div class="hero-meta">
        <span>生成时间：{escape(str(meta.get('generated_at') or '--'))}</span>
        <span>置信度：{escape(str(doc.get('confidence') or meta.get('confidence') or '--'))}</span>
        <span>版本：{escape(str(meta.get('version') or '--'))}</span>
        <span>模式：{escape(str(meta.get('generation_mode') or '--'))}</span>
      </div>
    </section>
    {''.join(sections_html)}
  </main>
</body>
</html>
"""

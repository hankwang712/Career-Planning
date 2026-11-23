"""Resume Workshop AI Insights: Multi-turn Interviewer Grill-Me & Multi-Job JD Skill Heatmap."""
from collections import Counter
import json
import re

from openai import OpenAI

from services import llm_audit, llm_env, privacy_shield
from services.llm_calls import normalize_sdk_base_url, parse_structured_json, safe_create_chat_completion


def _call_json(runtime, system, payload, feature, max_tokens=2048):
    base, key, model = runtime
    with llm_audit.track_feature(feature):
        with OpenAI(base_url=normalize_sdk_base_url(base), api_key=key, timeout=60, max_retries=0) as client:
            resp = safe_create_chat_completion(
                client, model,
                [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                temperature=0.3, max_tokens=max_tokens, force_json=True, max_retries=1,
            )
    raw = (resp.choices[0].message.content or "").strip()
    return parse_structured_json(raw)


def grill_entry(section, name, role, content, history=(), *, synthesize=False):
    """Multi-turn strict technical interviewer grilling a resume project/experience entry."""
    clean_content = str(content or "").strip()
    if not clean_content:
        raise ValueError("请先填写该段经历的内容后再进行考官拷打。")
    safe_history = [
        {"q": str(turn.get("q") or "")[:400], "a": str(turn.get("a") or "")[:1000]}
        for turn in (history or []) if isinstance(turn, dict) and (turn.get("q") or turn.get("a"))
    ][:6]

    runtime = llm_env.chat_runtime()
    masked_content, pii_map = privacy_shield.mask_pii(clean_content[:4000])

    if synthesize:
        if not safe_history:
            raise ValueError("请先回答至少一轮拷打问题，再提炼回写。")
        if all(runtime):
            system = (
                "你是资深简历教练。根据候选人原始经历和他在多轮技术追问中的真实回答，把回答里补充的具体技术细节、权衡思路与量化结果，"
                "自然融入原始经历的 Markdown 要点中。\n"
                "硬性规则：1) 严禁编造原始经历和回答中都没出现过的数字或技术名词；2) 保持精炼单页风格（不超过原字数的 125%）；"
                "3) 只输出严格 JSON 对象，含键 improved_content(字符串，Markdown `- **模块：**...` 列表) 与 highlights(字符串数组，2-3 条提炼亮点)。"
            )
            payload = {
                "section": section, "name": name, "role": role,
                "original_content": masked_content, "qa_history": safe_history,
            }
            try:
                parsed = _call_json(runtime, system, payload, "resume_grill_synth", max_tokens=2048)
                improved = privacy_shield.unmask_pii(str(parsed.get("improved_content") or "").strip(), pii_map)
                if improved:
                    return {
                        "mode": "llm",
                        "improved_content": improved,
                        "highlights": [str(h) for h in (parsed.get("highlights") or [])[:4]],
                    }
            except Exception:
                pass
        # Deterministic fallback synthesis
        extra = "；".join(t["a"].strip()[:90] for t in safe_history if t.get("a"))
        improved = clean_content + (f"\n- **关键补充与验证：**{extra}" if extra else "")
        return {"mode": "heuristic", "improved_content": improved, "highlights": ["已将你的真实回答要点整理追加至经历末尾"]}

    round_num = len(safe_history) + 1
    if all(runtime):
        system = (
            "你是大厂资深技术面试官兼「证据边界审计官（Evidence Guard）」，正在对候选人简历中的某一段经历做深度技术拷打（Grill-me）。\n"
            "请围绕以下维度循序渐进发问：第 1 轮挖架构取舍与真实边界（是否存在无证据夸大），第 2 轮挖指标口径/实验对照组/评测方法，第 3 轮挖异常边界/并发或失败恢复。\n"
            "不要重复已经问过的问题；针对候选人上一轮回答中模糊的地方精准追问。\n"
            "只输出严格 JSON 对象，包含 6 个键：\n"
            "- verdict: 字符串，必须是以下四档之一：「可以写」「谨慎写」「补证据后写」「不能写」\n"
            "- question: 字符串（一句锋利具体的面试官追问）\n"
            "- weakness: 字符串（指出原文或上轮回答中最容易被质疑穿帮的 1 个薄弱点/夸大风险）\n"
            "- danger_answer: 字符串（35–60 字，最容易在面试现场翻车的虚夸/空泛「危险回答」反例）\n"
            "- strong_answer: 字符串（45–90 字，基于现有真实证据、诚实界定边界且扛得住追问的「强回答」示范）\n"
            "- tip: 字符串（给候选人的简短补证据或答题提示，35 字以内）"
        )
        payload = {
            "round": round_num, "section": section, "name": name, "role": role,
            "content": masked_content, "qa_history": safe_history,
        }
        try:
            parsed = _call_json(runtime, system, payload, "resume_grill", max_tokens=1800)
            if parsed.get("question"):
                verdict = str(parsed.get("verdict") or "谨慎写").strip()
                if verdict not in {"可以写", "谨慎写", "补证据后写", "不能写"}:
                    verdict = "谨慎写"
                return {
                    "mode": "llm",
                    "round": round_num,
                    "verdict": verdict,
                    "question": str(parsed["question"]).strip(),
                    "weakness": str(parsed.get("weakness") or "").strip(),
                    "danger_answer": str(parsed.get("danger_answer") or "").strip(),
                    "strong_answer": str(parsed.get("strong_answer") or "").strip(),
                    "tip": str(parsed.get("tip") or "").strip(),
                }
        except Exception:
            pass

    has_fluff = any(w in clean_content for w in ("企业级", "显著提升", "行业领先", "大幅提升", "优化效果"))
    fallback_qs = [
        (
            "补证据后写" if has_fluff else "谨慎写",
            f"在「{name or section}」中，你选择当前技术方案而非更简单的替代方案，核心瓶颈和取舍依据是什么？",
            "原文存在泛化表述或偏重罗列组件，缺少方案对比与真实工程边界。" if has_fluff else "原文偏重罗列使用了哪些组件，缺少方案对比与决策依据。",
            "只说“这个框架业内最流行、效果最好”，说不出具体替换成本和失败样例。",
            "先明确项目规模与真实边界（如 Demo/实验环境），再对比 2 种方案在延迟、召回或显存上的实测差异。",
            "从性能、成本、可维护性三方面各说 1 个可验证对比点。",
        ),
        (
            "补证据后写",
            "你提到的效果提升或核心指标，评测集是怎么构造的？Baseline 是什么，有没有做过消融实验？",
            "量化结果若缺少 Baseline 与样本规模，面试容易被质疑说服力。",
            "答“人工感觉准了很多”或现场临时编造一个没有日志支撑的百分比。",
            "坦诚说明评测集条数、构造方式（如 bad case 抽样）以及引入该模块前后的对照组差异。",
            "补充测试集规模、对照组以及单模块贡献。",
        ),
        (
            "可以写",
            "如果线上出现模型超时、检索召回为空或外部接口抖动，你这套链路里最脆弱的一环怎么兜底？",
            "工程稳定性与异常恢复细节往往决定实习/校招定级。",
            "答“本地跑的时候没遇到过异常，所以没做处理”。",
            "讲清实际落地的重试退避、超时降级策略，以及尚未覆盖但已识别的改进边界。",
            "讲清楚重试退避、降级策略和状态恢复点。",
        ),
    ]
    verdict, q, w, danger, strong, tip = fallback_qs[(round_num - 1) % len(fallback_qs)]
    return {
        "mode": "heuristic",
        "round": round_num,
        "verdict": verdict,
        "question": q,
        "weakness": w,
        "danger_answer": danger,
        "strong_answer": strong,
        "tip": tip,
    }


def jd_heatmap_report(conn, owner, resume_text):
    """Aggregate JD hard skills across the user's pipeline jobs and compare against current resume."""
    from services import recruitment_pipeline as rp

    rows = conn.execute(
        """
        SELECT j.title, j.company, j.source, COALESCE(d.description, j.description) AS description,
               p.grade, p.score, p.saved, p.deep_payload
        FROM recruitment_pipeline p
        JOIN recruitment_listings j USING(owner, source, url_key)
        LEFT JOIN recruitment_job_details d USING(owner, source, url_key)
        WHERE p.owner=? AND p.stage <> 'rejected'
        ORDER BY p.saved DESC, (p.score IS NULL) ASC, p.score DESC, p.updated_at DESC
        LIMIT 30
        """,
        (owner,),
    ).fetchall()

    total_jobs = len(rows)
    if total_jobs == 0:
        return {
            "total_jobs": 0,
            "skills": [],
            "gaps": [],
            "covered_count": 0,
            "summary": "岗位库暂无有效岗位，请先在「岗位全链路流水线」采集或导入目标岗位。",
            "recommendations": [],
        }

    counter = Counter()
    for row in rows:
        deep = rp._load(row["deep_payload"]) if row["deep_payload"] else {}
        extracted = deep.get("extracted_skills") or rp.extract_skills(dict(row), {})
        seen_in_job = set()
        for raw_skill in extracted:
            sk = str(raw_skill or "").strip()
            if not sk or len(sk) > 30:
                continue
            norm = sk.lower()
            if norm not in seen_in_job:
                seen_in_job.add(norm)
                counter[sk] += 1

    # Merge case variants (e.g. Python vs python)
    merged = {}
    for sk, cnt in counter.items():
        key = sk.lower()
        if key not in merged:
            merged[key] = [sk, cnt]
        else:
            merged[key][1] += cnt
            if sk[0].isupper() and not merged[key][0][0].isupper():
                merged[key][0] = sk

    ranked = sorted(merged.values(), key=lambda x: (-x[1], x[0]))[:18]
    resume_body = str(resume_text or "")
    skills = []
    gaps = []
    for name, count in ranked:
        pct = min(100, int(round((count / total_jobs) * 100)))
        covered = rp._term_in(resume_body, name)
        entry = {"skill": name, "count": count, "percent": pct, "covered": covered}
        skills.append(entry)
        if not covered:
            gaps.append(entry)

    covered_count = sum(1 for s in skills if s["covered"])
    coverage_rate = int(round((covered_count / len(skills)) * 100)) if skills else 0

    # Project Scout: concrete minimum-verifiable evidence plans for missing skills (no fabrication!)
    scout_catalog = [
        (("rag", "检索", "向量", "milvus", "pgvector", "lightrag"), "补 50 条 query-answer-evidence 评测集与 bad case 分类表（召回漏检 / 引用错位 / 幻觉），沉淀可复现评测脚本"),
        (("agent", "langgraph", "mcp", "function", "工具调用"), "围绕单任务搭建带失败重试、超时降级与工具调用 trace 日志的最小 Agent 闭环，记录成功率与耗时"),
        (("lora", "微调", "sft", "dpo", "rlhf", "post-training", "训练"), "复现小参数模型（如 Qwen/MiniMind）微调流程，保存数据清洗脚本、loss 曲线与微调前后对比样例"),
        (("vllm", "sglang", "推理", "部署", "量化", "tensorrt"), "本机/单卡跑通 vLLM 或 llama.cpp 压测脚本，记录不同 batch/量化精度下的 TTFT 与吞吐量对比"),
        (("docker", "k8s", "linux", "ci", "部署"), "为现有项目补全 Dockerfile + 健康检查 + 启动脚本，验证一键拉起与日志排查流程"),
        (("多模态", "vlm", "ocr", "cv", "语音"), "选取 20–30 份真实图文/表格样例跑通 VLM 解析对比实验，沉淀错误模式分析笔记"),
        (("fastapi", "redis", "mysql", "postgresql", "高并发", "异步"), "为现有接口补充异步并发压测（Locust/wrk）与缓存命中率监控记录，形成可验证性能数据"),
    ]
    evidence_plans = []
    used_plans = set()
    for g in gaps[:6]:
        sk_low = g["skill"].lower()
        matched_action = None
        for keys, action in scout_catalog:
            if any(k in sk_low for k in keys):
                matched_action = action
                break
        if not matched_action:
            matched_action = f"围绕「{g['skill']}」做一个 1 周可交付的最小复现 Demo，保留代码仓库、运行日志与 1 组前后对比样例"
        if matched_action not in used_plans:
            used_plans.add(matched_action)
            evidence_plans.append({"skill": g["skill"], "percent": g["percent"], "action": matched_action})

    recs = []
    if gaps:
        top_gaps = "、".join(g["skill"] for g in gaps[:4])
        recs.append(f"高频未覆盖词：{top_gaps}。遵循「证据护卫」原则，切勿直接硬写进简历，建议按下方补证据方案沉淀真实代码/评测后再补充。")
    if covered_count:
        top_hits = "、".join(s["skill"] for s in skills if s["covered"])[:40]
        recs.append(f"你的核心强项已命中多数目标岗位（{top_hits}…），建议放在每个项目第 1 条要点显眼位置。")
    recs.append(f"当前基准简历对这 {total_jobs} 个目标岗位的高频技能覆盖率为 {coverage_rate}%。")

    return {
        "total_jobs": total_jobs,
        "coverage_rate": coverage_rate,
        "covered_count": covered_count,
        "skills": skills,
        "gaps": gaps[:8],
        "evidence_plans": evidence_plans[:5],
        "summary": f"已聚合分析你岗位库中最相关的 {total_jobs} 个目标 JD，识别出 {len(skills)} 项核心技能需求。",
        "recommendations": recs,
    }

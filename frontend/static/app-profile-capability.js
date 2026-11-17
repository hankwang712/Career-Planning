// 画像：能力推导、关联图与画像工作台
// 由原来的 app.js 拆出，仍是普通脚本、共享全局作用域；加载顺序见 templates/partials/app_scripts.html。

function getAssessmentHubSnapshotSafe() {
  try {
    const snapshot = typeof window.getAssessmentHubSnapshot === "function" ? window.getAssessmentHubSnapshot() : null;
    return snapshot?.owner === (getCurrentUser()?.username || "guest") ? snapshot : null;
  } catch (error) {
    console.error("read assessment snapshot failed", error);
    return null;
  }
}

function buildAssessmentContextPayload() {
  const assessment = getAssessmentHubSnapshotSafe() || {};
  return {
    mbti: assessment.mbti || {},
    holland: assessment.holland || {},
    basics: getEffectiveProfileBasics()
  };
}

function addCapabilitySignal(bag, key, value, source) {
  if (!Object.prototype.hasOwnProperty.call(bag, key)) return;
  const score = clampPercent(value, NaN);
  if (!Number.isFinite(score)) return;
  bag[key].push({ score, source });
}

function deriveCapabilityScores(assessment, interviewProfile, basics, resumeProfile = null) {
  const bag = {
    professional: [],
    learning: [],
    communication: [],
    innovation: [],
    stress_tolerance: [],
    internship: [],
    execution: []
  };

  const mbtiType = assessment?.mbti?.completed
    ? String(assessment.mbti.final_type || assessment.mbti.raw_type || "")
    : "";
  if (mbtiType.length === 4) {
    const [ei, sn, tf, jp] = mbtiType.split("");
    if (ei === "E") {
      addCapabilitySignal(bag, "communication", 82, "MBTI");
      addCapabilitySignal(bag, "internship", 72, "MBTI");
    } else {
      addCapabilitySignal(bag, "learning", 80, "MBTI");
      addCapabilitySignal(bag, "professional", 72, "MBTI");
    }
    if (sn === "N") {
      addCapabilitySignal(bag, "innovation", 88, "MBTI");
      addCapabilitySignal(bag, "learning", 84, "MBTI");
    } else {
      addCapabilitySignal(bag, "execution", 78, "MBTI");
      addCapabilitySignal(bag, "internship", 76, "MBTI");
    }
    if (tf === "T") {
      addCapabilitySignal(bag, "professional", 78, "MBTI");
      addCapabilitySignal(bag, "stress_tolerance", 74, "MBTI");
    } else {
      addCapabilitySignal(bag, "communication", 80, "MBTI");
      addCapabilitySignal(bag, "innovation", 72, "MBTI");
    }
    if (jp === "J") {
      addCapabilitySignal(bag, "execution", 86, "MBTI");
      addCapabilitySignal(bag, "stress_tolerance", 78, "MBTI");
    } else {
      addCapabilitySignal(bag, "innovation", 84, "MBTI");
      addCapabilitySignal(bag, "execution", 58, "MBTI");
    }
  }

  const hollandCodes = Array.isArray(assessment?.holland?.top_codes) ? assessment.holland.top_codes : [];
  hollandCodes.forEach((code) => {
    if (code === "R") {
      addCapabilitySignal(bag, "internship", 82, "Holland");
      addCapabilitySignal(bag, "execution", 76, "Holland");
    }
    if (code === "I") {
      addCapabilitySignal(bag, "learning", 88, "Holland");
      addCapabilitySignal(bag, "professional", 82, "Holland");
    }
    if (code === "A") {
      addCapabilitySignal(bag, "innovation", 92, "Holland");
    }
    if (code === "S") {
      addCapabilitySignal(bag, "communication", 88, "Holland");
      addCapabilitySignal(bag, "internship", 72, "Holland");
    }
    if (code === "E") {
      addCapabilitySignal(bag, "communication", 90, "Holland");
      addCapabilitySignal(bag, "execution", 78, "Holland");
      addCapabilitySignal(bag, "stress_tolerance", 80, "Holland");
    }
    if (code === "C") {
      addCapabilitySignal(bag, "execution", 86, "Holland");
      addCapabilitySignal(bag, "professional", 78, "Holland");
    }
  });

  if (basics.major) {
    addCapabilitySignal(bag, "professional", 68, "基础信息");
  }
  if (basics.grade) {
    const gradeText = basics.grade;
    if (/博士|phd/i.test(gradeText)) {
      addCapabilitySignal(bag, "internship", 82, "基础信息");
      addCapabilitySignal(bag, "execution", 78, "基础信息");
    } else if (/硕士|研究生|master/i.test(gradeText)) {
      addCapabilitySignal(bag, "internship", 76, "基础信息");
      addCapabilitySignal(bag, "execution", 72, "基础信息");
    } else if (/本科|学士|bachelor/i.test(gradeText)) {
      addCapabilitySignal(bag, "internship", 62, "基础信息");
      addCapabilitySignal(bag, "execution", 66, "基础信息");
    } else {
      if (/大一|一年级/.test(gradeText)) addCapabilitySignal(bag, "internship", 45, "基础信息");
      else if (/大二|二年级/.test(gradeText)) addCapabilitySignal(bag, "internship", 55, "基础信息");
      else if (/大三|三年级/.test(gradeText)) addCapabilitySignal(bag, "internship", 68, "基础信息");
      else if (/大四|四年级|研/.test(gradeText)) addCapabilitySignal(bag, "internship", 78, "基础信息");
      addCapabilitySignal(bag, "execution", /大三|大四|研/.test(gradeText) ? 72 : 60, "基础信息");
    }
  }

  if (interviewProfile) {
    const dimensions = Array.isArray(interviewProfile.dimensions) ? interviewProfile.dimensions : [];
    const dimMap = {};
    dimensions.forEach((item) => {
      const name = String(item.name || "").trim();
      if (name) dimMap[name] = clampPercent(item.score, 0);
    });
    if (dimMap["学习方式"] !== undefined) addCapabilitySignal(bag, "learning", dimMap["学习方式"], "访谈");
    if (dimMap["沟通风格"] !== undefined) addCapabilitySignal(bag, "communication", dimMap["沟通风格"], "访谈");
    if (dimMap["行动证据"] !== undefined) {
      addCapabilitySignal(bag, "internship", dimMap["行动证据"], "访谈");
      addCapabilitySignal(bag, "execution", dimMap["行动证据"], "访谈");
    }
    if (dimMap["职业成熟度"] !== undefined) {
      addCapabilitySignal(bag, "stress_tolerance", dimMap["职业成熟度"], "访谈");
      addCapabilitySignal(bag, "execution", dimMap["职业成熟度"], "访谈");
    }
    if (dimMap["职业兴趣"] !== undefined) addCapabilitySignal(bag, "innovation", dimMap["职业兴趣"], "访谈");
    if (dimMap["工作价值观"] !== undefined) addCapabilitySignal(bag, "communication", dimMap["工作价值观"], "访谈");

    const riasec = interviewProfile.riasec || {};
    addCapabilitySignal(bag, "innovation", Math.max(Number(riasec.artistic || 0), Number(riasec.investigative || 0)), "访谈");
    addCapabilitySignal(bag, "communication", Math.max(Number(riasec.social || 0), Number(riasec.enterprising || 0)), "访谈");
  }

  if (resumeProfile) {
    const cap = resumeProfile.capability_scores || {};
    addCapabilitySignal(bag, "communication", Number(cap.communication || 0), "简历");
    addCapabilitySignal(bag, "execution", Number(cap.execution || 0), "简历");
    addCapabilitySignal(bag, "stress_tolerance", Number(cap.stress_resilience || 0), "简历");
    addCapabilitySignal(bag, "innovation", Number(cap.innovation || 0), "简历");
    addCapabilitySignal(bag, "professional", Number(cap.collaboration || 0), "简历");
    addCapabilitySignal(bag, "internship", Number(cap.leadership || 0), "简历");
  }

  const capabilities = Object.fromEntries(Object.entries(bag).map(([key, items]) => {
    const score = averageValues(items.map((item) => item.score));
    return [key, {
      score,
      sources: uniqueValues(items.map((item) => item.source), 4),
      inferred: Boolean(score !== null && !items.some((item) => item.source === "访谈" || item.source === "基础信息"))
    }];
  }));

  const availableCount = Object.values(capabilities).filter((item) => item.score !== null).length;
  return {
    capabilities,
    coverage: Math.round(availableCount / Object.keys(capabilities).length * 100)
  };
}

function normalizeTextForMatch(value) {
  return String(value || "").toLowerCase().replace(/\s+/g, "");
}

function roleMatchesText(role, text) {
  const target = normalizeTextForMatch(text);
  if (!target) return false;
  return [role.name, role.category, ...(role.requiredSkills || []), ...(role.workValues || [])]
    .some((item) => {
      const normalized = normalizeTextForMatch(item);
      return normalized && (target.includes(normalized) || normalized.includes(target));
    });
}

function deriveUnifiedProfile() {
  const assessment = getAssessmentHubSnapshotSafe() || { mbti: { completed: false }, holland: { completed: false } };
  const interviewProfile = careerInterviewState.result?.profile || null;
  const resumeState = userWorkspaceState.scopedData.resume_profile || null;
  const resumeProfile = resumeState?.profile || null;
  /** 与人岗匹配 API 对齐：后端从 resume.profile 读取 matcher / structured_resume，需从 workspace 根合并进来 */
  const resumeProfileForApis =
    resumeProfile && typeof resumeProfile === "object"
      ? {
          ...resumeProfile,
          matcher: resumeState?.matcher || resumeProfile.matcher,
          structured_resume: resumeState?.structured_resume || resumeProfile.structured_resume
        }
      : resumeProfile;
  const basics = mergeProfileBasicsWithResume(careerInterviewState.profileBasics, resumeProfile);
  const capabilityModel = deriveCapabilityScores(assessment, interviewProfile, basics, resumeProfile);
  const missingItems = [];
  if (!assessment?.mbti?.completed) missingItems.push("MBTI 测评待完成");
  if (!assessment?.holland?.completed) missingItems.push("霍兰德测评待完成");
  PROFILE_BASIC_FIELDS.forEach((key) => {
    if (!basics[key]) missingItems.push(`${PROFILE_BASIC_LABELS[key]}待补充`);
  });
  if (!interviewProfile) missingItems.push("职业访谈待完成");
  if (!resumeState?.file_name) missingItems.push("简历待上传");
  else if (resumeState?.status !== "analyzed") missingItems.push("简历待解析");

  const summaryParts = [];
  if (assessment?.mbti?.completed) summaryParts.push(`MBTI ${assessment.mbti.display_type || assessment.mbti.final_type}`);
  if (assessment?.holland?.completed) summaryParts.push(`霍兰德 ${assessment.holland.code}`);
  if (basics.major) summaryParts.push(`专业 ${basics.major}`);
  if (basics.grade) summaryParts.push(`学历 ${basics.grade}`);
  if (basics.target_direction) summaryParts.push(`目标方向 ${basics.target_direction}`);
  if (resumeProfile?.candidate_summary && resumeProfile?.candidate_summary !== "unknown") summaryParts.push(`简历画像 ${resumeProfile.candidate_summary}`);
  const fallbackSummary = summaryParts.length
    ? `${summaryParts.join("，")}。当前画像已可用于岗位初筛，缺失项会在匹配和报告中显式标记。`
    : "画像基础信息仍较少，建议先完成双测评并补充基础信息。";

  return {
    assessment,
    basics,
    interview: {
      started: careerInterviewState.started,
      isComplete: careerInterviewState.isComplete,
      completionScore: clampPercent(careerInterviewState.completionScore),
      profile: interviewProfile
    },
    resume: {
      status: resumeState?.status || "empty",
      uploadedAt: resumeState?.uploaded_at || null,
      analyzedAt: resumeState?.analyzed_at || null,
      profile: resumeProfileForApis
    },
    summary: interviewProfile?.summary || fallbackSummary,
    workValues: uniqueValues(
      [...(interviewProfile?.work_values || []), ...(resumeProfile?.leadership_signals || []).map((item) => item.signal || "")],
      4
    ),
    recommendedRoles: uniqueValues([...(interviewProfile?.recommended_roles || []), ...(resumeProfile?.roles_detected || []).map((item) => item.role || "")], 6),
    nextSteps: uniqueValues(interviewProfile?.next_steps || [], 6),
    capabilities: capabilityModel.capabilities,
    capabilityCoverage: capabilityModel.coverage,
    missingItems
  };
}

function computeRoleMatches(profile) {
  void profile;
  const saved = userWorkspaceState?.scopedData?.career_matching?.role_rankings;
  return (Array.isArray(saved) ? saved : []).filter((role) => role && role.matchSource !== "career_graph");
}

function buildAgentModuleStates(profile, roles) {
  const basicsReady = PROFILE_BASIC_FIELDS.every((key) => Boolean(profile.basics[key]));
  const staticMemoryReady = Boolean(profile.assessment?.mbti?.completed || profile.assessment?.holland?.completed || basicsReady);
  const dynamicMemoryReady = Boolean(profile.interview.profile);
  const planningReady = Boolean(roles[0]);
  return [
    {
      title: "静态记忆",
      status: staticMemoryReady ? "available" : "pending",
      reason: staticMemoryReady ? "测评结果与基础信息已保存。" : "等待 MBTI / 霍兰德结果与基础信息补齐。",
      action_label: staticMemoryReady ? "已同步" : "补充基础信息"
    },
    {
      title: "动态记忆",
      status: dynamicMemoryReady ? "available" : "pending",
      reason: dynamicMemoryReady ? "访谈结果已保存。" : "等待完成职业访谈。",
      action_label: dynamicMemoryReady ? "继续访谈" : "开始访谈"
    },
    {
      title: "规划模块",
      status: planningReady ? "available" : "pending",
      reason: planningReady ? "已根据统一画像生成阶段性岗位方向与行动建议。" : "等待画像基础形成后生成阶段计划。",
      action_label: planningReady ? "查看报告" : "先完成测评"
    },
    {
      title: "工具模块",
      status: "placeholder",
      reason: "",
      action_label: "待接入"
    },
    {
      title: "反思模块",
      status: "placeholder",
      reason: "",
      action_label: "即将上线"
    }
  ];
}

function renderCapabilityList(profile) {
  const labels = {
    professional: "专业技能",
    learning: "学习能力",
    communication: "沟通能力",
    innovation: "创新能力",
    stress_tolerance: "抗压能力",
    internship: "实践/实习能力",
    execution: "执行能力"
  };
  return Object.entries(labels).map(([key, label]) => {
    const item = profile.capabilities[key];
    const score = item?.score;
    const text = score === null ? "待补充" : `${score}%`;
    const hint = score === null
      ? "当前主要依赖测评与基础信息，后续用访谈/经历补强。"
      : `${(item.sources || []).join(" / ")}${item.inferred ? " · 推断值" : " · 有实证输入"}`;
    return `
      <div class="rounded-xl border border-slate-200 bg-slate-50 p-4">
        <div class="flex items-center justify-between gap-3 mb-2">
          <span class="text-sm font-medium text-slate-700">${escHtml(label)}</span>
          <span class="text-sm font-semibold ${score === null ? "text-slate-400" : "text-sky-700"}">${escHtml(text)}</span>
        </div>
        <div class="h-2 rounded-full bg-white overflow-hidden">
          <div class="h-full rounded-full ${score === null ? "bg-slate-200" : "bg-gradient-to-r from-sky-500 to-cyan-400"}" style="width:${score === null ? 18 : score}%"></div>
        </div>
        <p class="mt-2 text-xs text-slate-500 leading-5">${escHtml(hint)}</p>
      </div>
    `;
  }).join("");
}

function renderCapabilityCorrelation(profile, roles) {
  const keyToLabel = {
    professional: "专业技能",
    learning: "学习能力",
    communication: "沟通能力",
    innovation: "创新能力",
    stress_tolerance: "抗压能力",
    internship: "实践/实习能力",
    execution: "执行能力"
  };
  const labelToKey = Object.fromEntries(Object.entries(keyToLabel).map(([k, v]) => [v, k]));
  const scoreOf = (key) => profile.capabilities?.[key]?.score;
  const topRole = roles?.[0] || null;
  const relationItems = [];

  const rules = [
    {
      primary: "professional",
      secondary: "communication",
      minPrimary: 72,
      maxSecondary: 64,
      risk: "技术能力已具备，但沟通偏弱会影响需求澄清与跨团队协作。",
      action: "补齐表达与协作证据：需求复盘、方案评审纪要、跨团队协作案例。"
    },
    {
      primary: "innovation",
      secondary: "execution",
      minPrimary: 72,
      maxSecondary: 64,
      risk: "创意和想法较强，但执行与落地不足会导致成果转化率低。",
      action: "强化落地闭环：设置里程碑、输出可验证成果（Demo/上线记录/指标）。"
    },
    {
      primary: "execution",
      secondary: "stress_tolerance",
      minPrimary: 70,
      maxSecondary: 62,
      risk: "执行意愿较好，但高压情境下稳定性不足，容易在关键节点失速。",
      action: "通过高压场景练习与节奏管理补齐：周计划、复盘和风险预案。"
    },
    {
      primary: "learning",
      secondary: "internship",
      minPrimary: 74,
      maxSecondary: 60,
      risk: "学习吸收快，但实践转化不足，面试时难以证明业务产出。",
      action: "把学习成果转成项目证据：实习经历、竞赛记录、可量化结果。"
    }
  ];

  rules.forEach((rule) => {
    const p = scoreOf(rule.primary);
    const s = scoreOf(rule.secondary);
    if (p === null || p === undefined || s === null || s === undefined) return;
    if (p >= rule.minPrimary && s <= rule.maxSecondary) {
      relationItems.push({
        type: "risk",
        title: `${keyToLabel[rule.primary]}（${p}%）→ ${keyToLabel[rule.secondary]}（${s}%）`,
        risk: rule.risk,
        action: rule.action
      });
    }
  });

  const synergyPairs = [
    ["professional", "learning"],
    ["communication", "execution"],
    ["innovation", "learning"]
  ];
  synergyPairs.forEach(([a, b]) => {
    const sa = scoreOf(a);
    const sb = scoreOf(b);
    if (sa === null || sa === undefined || sb === null || sb === undefined) return;
    if (sa >= 75 && sb >= 72) {
      relationItems.push({
        type: "advantage",
        title: `${keyToLabel[a]}（${sa}%）+ ${keyToLabel[b]}（${sb}%）`,
        risk: "这组能力具备协同优势，可直接作为岗位竞争亮点。",
        action: "在简历与面试中用“场景-动作-结果”呈现这组能力的联合作用。"
      });
    }
  });

  if (topRole?.ability?.gaps?.length) {
    const complementMap = {
      "专业技能": ["学习能力", "沟通能力"],
      "学习能力": ["执行能力", "实践/实习能力"],
      "沟通能力": ["执行能力", "抗压能力"],
      "创新能力": ["执行能力", "专业技能"],
      "执行能力": ["抗压能力", "沟通能力"],
      "实践/实习能力": ["执行能力", "专业技能"],
      "抗压能力": ["执行能力", "沟通能力"]
    };
    topRole.ability.gaps.slice(0, 2).forEach((gapText) => {
      const label = String(gapText || "").split(" ")[0].trim();
      const linked = complementMap[label] || [];
      const linkedState = linked.map((name) => {
        const key = labelToKey[name];
        const score = key ? scoreOf(key) : null;
        return `${name}${score === null || score === undefined ? "" : ` ${score}%`}`;
      });
      relationItems.push({
        type: "focus",
        title: `岗位「${topRole.name}」关键缺口：${label}`,
        risk: linked.length ? `该缺口通常受 ${linked.join("、")} 联动影响。` : "该缺口需要结合上下游能力一起补齐。",
        action: linkedState.length ? `建议并行提升：${linkedState.join("、")}。` : "建议结合目标岗位要求补充一项可量化成果。"
      });
    });
  }

  if (!relationItems.length) {
    return `
      <div class="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-4 text-sm text-slate-500">
        暂未识别到明显的“强项-短板”联动关系。继续补充简历、访谈与测评后，这里会显示更明确的能力耦合分析。
      </div>
    `;
  }

  return relationItems.slice(0, 6).map((item) => {
    const cls = item.type === "risk"
      ? "border-amber-200 bg-amber-50"
      : item.type === "advantage"
        ? "border-emerald-200 bg-emerald-50"
        : "border-sky-200 bg-sky-50";
    return `
      <div class="rounded-xl border ${cls} p-4">
        <p class="text-sm font-semibold text-slate-800">${escHtml(item.title)}</p>
        <p class="mt-2 text-xs text-slate-600 leading-6">${escHtml(item.risk)}</p>
        <p class="mt-2 text-xs font-medium text-slate-700">建议：${escHtml(item.action)}</p>
      </div>
    `;
  }).join("");
}

function renderProfileWorkspace() {
  window.AssessmentCenter?.refresh();
}

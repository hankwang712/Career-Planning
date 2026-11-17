// 画像：基础信息、综合画像与画像海报
// 由原来的 app.js 拆出，仍是普通脚本、共享全局作用域；加载顺序见 templates/partials/app_scripts.html。

function normalizeProfileBasics(raw) {
  const source = raw && typeof raw === "object" ? raw : {};
  return {
    gender: String(source.gender || "").trim(),
    major: String(source.major || "").trim(),
    grade: String(source.grade || source.education_level || source.educationLevel || "").trim(),
    target_city: String(source.target_city || source.targetCity || "").trim(),
    target_direction: String(source.target_direction || source.targetDirection || "").trim()
  };
}

function normalizeResumeBasicValue(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  const normalized = text.toLowerCase();
  if (["unknown", "n/a", "na", "暂无", "未知", "未提供", "无"].includes(normalized)) return "";
  return text;
}

function extractProfileBasicsFromResume(resumeProfile) {
  const basics = resumeProfile?.basics && typeof resumeProfile.basics === "object" ? resumeProfile.basics : {};
  return normalizeProfileBasics({
    gender: normalizeResumeBasicValue(basics.gender),
    major: normalizeResumeBasicValue(basics.major),
    grade: normalizeResumeBasicValue(basics.education_level || basics.grade),
    target_city: normalizeResumeBasicValue(basics.target_city || basics.targetCity),
    target_direction: normalizeResumeBasicValue(basics.target_direction || basics.targetDirection)
  });
}

function mergeProfileBasicsWithResume(profileBasics, resumeProfile) {
  const manual = normalizeProfileBasics(profileBasics);
  const fromResume = extractProfileBasicsFromResume(resumeProfile);
  const manualLooksLikeYear = /大一|大二|大三|大四|一年级|二年级|三年级|四年级|研一|研二|研三/i.test(manual.grade || "");
  const gradeValue = fromResume.grade && (!manual.grade || manualLooksLikeYear)
    ? fromResume.grade
    : (manual.grade || fromResume.grade);
  return normalizeProfileBasics({
    gender: manual.gender || fromResume.gender,
    major: manual.major || fromResume.major,
    grade: gradeValue,
    target_city: manual.target_city || fromResume.target_city,
    target_direction: manual.target_direction || fromResume.target_direction
  });
}

function getEffectiveProfileBasics(resumeState = userWorkspaceState.scopedData.resume_profile || null) {
  return mergeProfileBasicsWithResume(careerInterviewState.profileBasics, resumeState?.profile || null);
}

function syncProfileBasicsForm() {
  const manualBasics = normalizeProfileBasics(careerInterviewState.profileBasics);
  const resumeBasics = extractProfileBasicsFromResume(userWorkspaceState.scopedData.resume_profile?.profile || null);
  const basics = getEffectiveProfileBasics();
  const fieldMap = {
    profileGenderInput: basics.gender,
    profileMajorInput: basics.major,
    profileGradeInput: basics.grade,
    profileTargetCityInput: basics.target_city,
    profileTargetDirectionInput: basics.target_direction
  };
  Object.entries(fieldMap).forEach(([id, value]) => {
    const el = document.getElementById(id);
    if (el) el.value = value;
  });
  const missing = PROFILE_BASIC_FIELDS.filter((key) => !basics[key]);
  const autoFilledKeys = PROFILE_BASIC_FIELDS.filter((key) => !manualBasics[key] && resumeBasics[key] && basics[key]);
  const statusEl = document.getElementById("profileBasicsStatus");
  if (statusEl) {
    if (missing.length) {
      if (autoFilledKeys.length) {
        statusEl.textContent = `已从简历回填：${autoFilledKeys.map((key) => PROFILE_BASIC_LABELS[key]).join("、")}；待补充：${missing.map((key) => PROFILE_BASIC_LABELS[key]).join("、")}`;
      } else {
        statusEl.textContent = `待补充：${missing.map((key) => PROFILE_BASIC_LABELS[key]).join("、")}`;
      }
    } else if (autoFilledKeys.length) {
      statusEl.textContent = `基础信息已从简历自动回填，可手动修改后保存。`;
    } else {
      statusEl.textContent = "基础信息已同步到画像、匹配与报告。";
    }
  }
}

function collectProfileBasicsFromForm() {
  return normalizeProfileBasics({
    gender: document.getElementById("profileGenderInput")?.value || "",
    major: document.getElementById("profileMajorInput")?.value || "",
    grade: document.getElementById("profileGradeInput")?.value || "",
    target_city: document.getElementById("profileTargetCityInput")?.value || "",
    target_direction: document.getElementById("profileTargetDirectionInput")?.value || ""
  });
}

function saveProfileBasics() {
  careerInterviewState.profileBasics = collectProfileBasicsFromForm();
  persistCareerInterviewSnapshot();
  syncProfileBasicsForm();
  refreshUnifiedExperience();
  showToast("基础信息已保存", "后续匹配与报告会直接引用这些字段。", "success", 1800);
}

function formatPortraitProjectHighlight(item) {
  const source = item && typeof item === "object" ? item : {};
  const project = String(source.project || source.projectName || source.title || "").trim();
  const role = String(source.role || source.jobTitle || "").trim();
  const impact = String(source.impact || "").trim();
  const evidence = String(source.evidence || source.description || "").trim();
  const head = project ? `${project}${role ? `（${role}）` : ""}` : role;
  const parts = [head, impact, evidence].map((part) => String(part || "").trim()).filter(Boolean);
  return parts.join("：");
}

function formatPortraitExperience(item) {
  const source = item && typeof item === "object" ? item : {};
  const title = String(source.jobTitle || source.role || source.title || "").trim();
  const company = String(source.company || source.organization || "").trim();
  const description = Array.isArray(source.description)
    ? source.description.map((part) => String(part || "").trim()).filter(Boolean).join("；")
    : String(source.description || source.evidence || "").trim();
  const head = title ? `${title}${company ? ` @ ${company}` : ""}` : company;
  const parts = [head, description].map((part) => String(part || "").trim()).filter(Boolean);
  return parts.join("：");
}

function buildResumePortraitTraits(resumeState) {
  const profile = resumeState?.profile && typeof resumeState.profile === "object" ? resumeState.profile : null;
  const structuredResume = resumeState?.structured_resume && typeof resumeState.structured_resume === "object"
    ? resumeState.structured_resume
    : null;
  const roles = uniqueValues((Array.isArray(profile?.roles_detected) ? profile.roles_detected : [])
    .map((item) => {
      if (typeof item === "string") return item;
      return item?.role || item?.name || "";
    }), 5);
  const signals = uniqueValues((Array.isArray(profile?.leadership_signals) ? profile.leadership_signals : [])
    .map((item) => {
      if (typeof item === "string") return item;
      return item?.signal || item?.title || "";
    }), 5);
  const competitions = uniqueValues((Array.isArray(profile?.competition_records) ? profile.competition_records : [])
    .map((item) => {
      if (typeof item === "string") return item;
      return item?.competition || item?.award || item?.name || item?.title || "";
    }), 3);
  const highlightProjects = uniqueValues((Array.isArray(profile?.project_highlights) ? profile.project_highlights : [])
    .map((item) => formatPortraitProjectHighlight(item)), 4);
  const structuredProjects = uniqueValues((Array.isArray(structuredResume?.Projects) ? structuredResume.Projects : [])
    .map((item) => formatPortraitProjectHighlight(item)), 3);
  const experiences = uniqueValues((Array.isArray(structuredResume?.Experiences) ? structuredResume.Experiences : [])
    .map((item) => formatPortraitExperience(item)), 3);
  const rawProfileSkills = (Array.isArray(profile?.skills) ? profile.skills : []).map((item) => {
    if (typeof item === "string") return item;
    return item?.skillName || item?.skill || item?.name || item?.category || "";
  });
  const rawStructuredSkills = (Array.isArray(structuredResume?.Skills) ? structuredResume.Skills : []).map((item) => {
    if (typeof item === "string") return item;
    return item?.skillName || item?.name || item?.category || "";
  });
  const skills = uniqueValues([...rawProfileSkills, ...rawStructuredSkills], 8);

  return {
    summary: profile?.candidate_summary || "",
    roles,
    signals,
    competitions,
    projects: uniqueValues([...highlightProjects, ...structuredProjects], 4),
    experiences,
    skills
  };
}

function unifiedAverageDefined(values) {
  const nums = values.map((item) => Number(item)).filter((item) => Number.isFinite(item));
  if (!nums.length) return null;
  return Math.round(nums.reduce((sum, item) => sum + item, 0) / nums.length);
}

function getUnifiedCapabilityScore(profile, key) {
  const raw = Number(profile?.capabilities?.[key]?.score);
  return Number.isFinite(raw) ? raw : null;
}

function getUnifiedEvidenceScore(profile, keys, source) {
  const values = keys
    .map((key) => profile?.capabilities?.[key])
    .filter((item) => item && Array.isArray(item.sources) && item.sources.includes(source) && Number.isFinite(Number(item.score)))
    .map((item) => Number(item.score));
  return unifiedAverageDefined(values);
}

function getUnifiedEvidenceTone(score) {
  if (!Number.isFinite(Number(score))) return "empty";
  if (Number(score) >= 80) return "hot";
  if (Number(score) >= 64) return "warm";
  if (Number(score) >= 48) return "soft";
  return "empty";
}

function buildUnifiedArchetype(signals) {
  const collaboration = Number(signals.collaboration || 0);
  const structure = Number(signals.structure || 0);
  const exploration = Number(signals.exploration || 0);
  const drive = Number(signals.drive || 0);
  const domain = Number(signals.domain || 0);

  if (collaboration >= 68 && structure >= 70) {
    return {
      name: "结构型协调者",
      short: "协调",
      thesis: "更擅长在明确目标下整合信息、推动协作，并把事务拆成可执行步骤。",
      tone: "blue",
      palette: ["#2563eb", "#7c3aed"],
      scene: "协同推进 / 中后台支持 / 结构化执行"
    };
  }
  if (exploration >= 72 && collaboration >= 60) {
    return {
      name: "探索型连接者",
      short: "探索",
      thesis: "更容易在变化中寻找机会，通过连接信息、人和场景形成新方向。",
      tone: "violet",
      palette: ["#7c3aed", "#ec4899"],
      scene: "增长探索 / 内容策划 / 新方向试验"
    };
  }
  if (domain >= 72 && structure >= 66) {
    return {
      name: "分析型构建者",
      short: "分析",
      thesis: "更适合在信息密度高的场景里建立方法、形成判断并持续优化结果。",
      tone: "cyan",
      palette: ["#0891b2", "#2563eb"],
      scene: "分析判断 / 结构搭建 / 系统优化"
    };
  }
  if (drive >= 66 && structure >= 62) {
    return {
      name: "稳态执行者",
      short: "执行",
      thesis: "更偏向在稳定环境中持续交付，擅长把明确目标转成持续输出。",
      tone: "teal",
      palette: ["#0f766e", "#2563eb"],
      scene: "执行落地 / 节奏管理 / 事务闭环"
    };
  }
  return {
    name: "综合支持者",
    short: "支持",
    thesis: "当前画像更像一个多面支持型角色，具备一定适配性，但主导特征仍需更多证据来拉开。",
    tone: "slate",
    palette: ["#475569", "#2563eb"],
    scene: "综合支持 / 适应过渡 / 方向待收敛"
  };
}

function buildUnifiedProfileConstellationSvg(synthesis) {
  const [startColor, endColor] = synthesis.archetype.palette;
  const axes = synthesis.axes || [];
  const angleMap = {
    collaboration: 0,
    structure: -90,
    exploration: 90,
    drive: 180
  };
  const nodes = axes.map((item) => {
    const angle = (angleMap[item.key] ?? 0) * Math.PI / 180;
    const radius = 54 + (Number(item.value || 0) * 0.28);
    const x = 160 + Math.cos(angle) * radius;
    const y = 120 + Math.sin(angle) * radius;
    return { x, y };
  });
  const polygon = nodes.map((node) => `${node.x},${node.y}`).join(" ");
  return `
    <svg viewBox="0 0 320 240" class="unified-profile-svg" aria-hidden="true">
      <defs>
        <linearGradient id="unifiedProfileGradient" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="${startColor}" />
          <stop offset="100%" stop-color="${endColor}" />
        </linearGradient>
        <radialGradient id="unifiedProfileGlow" cx="50%" cy="50%" r="60%">
          <stop offset="0%" stop-color="rgba(255,255,255,0.9)" />
          <stop offset="100%" stop-color="rgba(255,255,255,0)" />
        </radialGradient>
      </defs>
      <rect x="12" y="12" width="296" height="216" rx="32" fill="url(#unifiedProfileGlow)" opacity="0.85" />
      <circle cx="160" cy="120" r="76" fill="none" stroke="rgba(255,255,255,0.5)" stroke-width="1.2" />
      <circle cx="160" cy="120" r="56" fill="none" stroke="rgba(255,255,255,0.36)" stroke-width="1.2" />
      ${nodes.map((node) => `<line x1="160" y1="120" x2="${node.x}" y2="${node.y}" stroke="rgba(255,255,255,0.42)" stroke-width="1.2" />`).join("")}
      ${polygon ? `<polygon points="${polygon}" fill="url(#unifiedProfileGradient)" opacity="0.24" stroke="url(#unifiedProfileGradient)" stroke-width="2.4" />` : ""}
      ${nodes.map((node) => `<circle cx="${node.x}" cy="${node.y}" r="7" fill="#ffffff" stroke="url(#unifiedProfileGradient)" stroke-width="3" />`).join("")}
      <circle cx="160" cy="120" r="36" fill="url(#unifiedProfileGradient)" />
      <text x="160" y="128" text-anchor="middle" font-size="18" font-weight="700" fill="#ffffff">${escHtml(synthesis.archetype.short)}</text>
    </svg>
  `;
}

function buildUnifiedProfileSynthesis(profile, roles) {
  const communication = getUnifiedCapabilityScore(profile, "communication");
  const execution = getUnifiedCapabilityScore(profile, "execution");
  const stress = getUnifiedCapabilityScore(profile, "stress_tolerance");
  const innovation = getUnifiedCapabilityScore(profile, "innovation");
  const learning = getUnifiedCapabilityScore(profile, "learning");
  const professional = getUnifiedCapabilityScore(profile, "professional");
  const internship = getUnifiedCapabilityScore(profile, "internship");

  const signals = {
    collaboration: unifiedAverageDefined([communication, internship, roles[0]?.willingness?.score]),
    structure: unifiedAverageDefined([execution, stress, professional]),
    exploration: unifiedAverageDefined([innovation, learning]),
    drive: unifiedAverageDefined([execution, communication, innovation]),
    domain: unifiedAverageDefined([professional, internship, execution])
  };
  const archetype = buildUnifiedArchetype(signals);
  const roleCluster = uniqueValues([
    ...(profile.recommendedRoles || []),
    ...(roles || []).slice(0, 2).map((item) => item.name || ""),
    profile.basics.target_direction || ""
  ], 4);
  const workValues = uniqueValues(profile.workValues || [], 4);
  const coreFocus = roleCluster[0] || archetype.scene;
  const thesis = `${archetype.thesis} 当前最像的职业场景是 ${coreFocus}。`;

  const axes = [
    {
      key: "collaboration",
      label: "协作倾向",
      left: "独立深挖",
      right: "协同推进",
      value: Number(signals.collaboration || 50),
      focus: Number(signals.collaboration || 50) >= 55 ? "更偏协同" : "更偏独立",
      note: Number(signals.collaboration || 50) >= 55 ? "更容易在对齐人与信息后推进结果。" : "更适合先独立梳理，再输出结论。"
    },
    {
      key: "structure",
      label: "秩序偏好",
      left: "灵活变化",
      right: "秩序稳定",
      value: Number(signals.structure || 50),
      focus: Number(signals.structure || 50) >= 55 ? "偏结构化" : "偏弹性化",
      note: Number(signals.structure || 50) >= 55 ? "更适合边界清晰、节奏稳定的工作环境。" : "在更弹性的场景里能保留一定适应空间。"
    },
    {
      key: "exploration",
      label: "探索倾向",
      left: "务实收敛",
      right: "探索拓展",
      value: Number(signals.exploration || 50),
      focus: Number(signals.exploration || 50) >= 55 ? "偏探索" : "偏务实",
      note: Number(signals.exploration || 50) >= 55 ? "会被新问题和新方向激活。" : "更看重可执行性和现实落点。"
    },
    {
      key: "drive",
      label: "推进方式",
      left: "支持执行",
      right: "主动牵引",
      value: Number(signals.drive || 50),
      focus: Number(signals.drive || 50) >= 55 ? "偏主动" : "偏支持",
      note: Number(signals.drive || 50) >= 55 ? "有一定主导意识，愿意带动事情往前走。" : "更适合在清晰目标下稳定支撑与落地。"
    }
  ];

  const workstyleCards = [
    {
      title: "决策方式",
      accent: "blue",
      value: Number(signals.structure || 0) >= 68
        ? "先建结构，再做判断"
        : Number(signals.exploration || 0) >= 68
          ? "先看机会，再逐步收敛"
          : "会在稳定与试探之间找平衡",
      copy: Number(signals.structure || 0) >= 68
        ? "更自然的方式是先厘清边界、步骤和优先级，再推进结果。"
        : Number(signals.exploration || 0) >= 68
          ? "面对新方向时更愿意先试，再根据反馈形成方法。"
          : "既会考虑现实落点，也会保留一定探索空间。"
    },
    {
      title: "沟通风格",
      accent: "violet",
      value: Number(signals.collaboration || 0) >= 68
        ? "对齐共识后推进"
        : Number(signals.collaboration || 0) >= 54
          ? "先梳理，再协同"
          : "更偏独立整理后输出",
      copy: Number(signals.collaboration || 0) >= 68
        ? "更适合在多方之间整合信息、统一节奏并推动下一步。"
        : Number(signals.collaboration || 0) >= 54
          ? "沟通时会先形成自己的框架，再和他人对齐。"
          : "更需要先形成内部判断，再对外表达。"
    },
    {
      title: "适配环境",
      accent: "teal",
      value: Number(signals.structure || 0) >= 65
        ? "目标明确、分工清晰"
        : Number(signals.exploration || 0) >= 65
          ? "允许试错、节奏灵活"
          : "中等变化、边界可协商",
      copy: Number(signals.structure || 0) >= 65
        ? "在流程明确、节奏清楚的团队里更容易稳定发挥。"
        : Number(signals.exploration || 0) >= 65
          ? "面对更开放的任务时，更容易被激活并找到新解法。"
          : "更适合既有方向又保留一定自主空间的团队。"
    },
    {
      title: "发力位置",
      accent: "amber",
      value: archetype.scene,
      copy: roleCluster.length
        ? `当前职业画像最容易落在 ${roleCluster.slice(0, 2).join(" / ")} 这类角色附近。`
        : "当前最强特征更接近支撑协作、执行推进或结构化判断这类位置。"
    }
  ];

  const evidenceRows = [
    {
      title: "结构秩序",
      desc: "是否更擅长在清晰目标下保持节奏、稳定输出。",
      assessment: getUnifiedEvidenceScore(profile, ["execution", "stress_tolerance"], "MBTI") ?? getUnifiedEvidenceScore(profile, ["execution"], "Holland"),
      resume: getUnifiedEvidenceScore(profile, ["execution", "professional"], "简历"),
      interview: getUnifiedEvidenceScore(profile, ["execution", "stress_tolerance"], "访谈")
    },
    {
      title: "协作推进",
      desc: "是否更像协调信息、连接角色并推动结果的人。",
      assessment: getUnifiedEvidenceScore(profile, ["communication"], "MBTI") ?? getUnifiedEvidenceScore(profile, ["communication"], "Holland"),
      resume: getUnifiedEvidenceScore(profile, ["communication", "internship"], "简历"),
      interview: getUnifiedEvidenceScore(profile, ["communication", "internship"], "访谈")
    },
    {
      title: "探索成长",
      desc: "是否会被新问题、新方向或快速学习场景激活。",
      assessment: getUnifiedEvidenceScore(profile, ["innovation", "learning"], "MBTI") ?? getUnifiedEvidenceScore(profile, ["innovation", "learning"], "Holland"),
      resume: getUnifiedEvidenceScore(profile, ["innovation", "learning"], "简历"),
      interview: getUnifiedEvidenceScore(profile, ["innovation", "learning"], "访谈")
    },
    {
      title: "业务实践",
      desc: "是否已经有足够的经历证据把画像落到真实角色上。",
      assessment: getUnifiedEvidenceScore(profile, ["professional", "internship"], "基础信息"),
      resume: getUnifiedEvidenceScore(profile, ["professional", "internship", "execution"], "简历"),
      interview: getUnifiedEvidenceScore(profile, ["internship", "execution"], "访谈")
    }
  ];

  const uncertainty = [];
  if (profile.missingItems?.length) {
    uncertainty.push(...profile.missingItems.slice(0, 2));
  }
  const topRole = roles?.[0] || null;
  if (profile.basics.target_direction && topRole && !roleMatchesText(topRole, profile.basics.target_direction)) {
    uncertainty.push("当前填写的目标方向，与画像最强证据并不完全一致。");
  }
  if (Math.abs(Number(signals.exploration || 0) - Number(signals.structure || 0)) <= 8) {
    uncertainty.push("探索倾向与秩序偏好接近，说明你的工作风格仍有双重性。");
  }
  if (!uncertainty.length) {
    uncertainty.push("当前各项信息较为一致。");
  }

  return {
    archetype,
    thesis,
    axes,
    workstyleCards,
    evidenceRows,
    roleCluster,
    workValues,
    uncertainty: uniqueValues(uncertainty, 3)
  };
}

function renderUnifiedFeatureAxes(axes) {
  return (axes || []).map((item) => `
    <article class="unified-axis-item">
      <div class="unified-axis-head">
        <p class="unified-axis-title">${escHtml(item.label)}</p>
        <span class="unified-axis-focus">${escHtml(item.focus)}</span>
      </div>
      <div class="unified-axis-meta">
        <span>${escHtml(item.left)}</span>
        <span>${escHtml(item.right)}</span>
      </div>
      <div class="unified-axis-track">
        <div class="unified-axis-track-fill"></div>
        <span class="unified-axis-marker" style="left:${Math.max(6, Math.min(94, Number(item.value || 50)))}%"></span>
      </div>
      <p class="unified-axis-note">${escHtml(item.note)}</p>
    </article>
  `).join("");
}

function renderUnifiedWorkstyleCards(items) {
  return (items || []).map((item) => `
    <article class="unified-style-card ${escHtml(item.accent || "blue")}">
      <p class="unified-style-label">${escHtml(item.title)}</p>
      <p class="unified-style-value">${escHtml(item.value)}</p>
      <p class="unified-style-copy">${escHtml(item.copy)}</p>
    </article>
  `).join("");
}

function renderUnifiedEvidenceMatrix(rows) {
  return (rows || []).map((item) => `
    <article class="unified-evidence-card">
      <div class="unified-evidence-head">
        <p class="unified-evidence-title">${escHtml(item.title)}</p>
        <p class="unified-evidence-copy">${escHtml(item.desc)}</p>
      </div>
      <div class="unified-evidence-source-grid">
        ${[
          ["测评", item.assessment],
          ["简历", item.resume],
          ["访谈", item.interview]
        ].map(([label, value]) => `
          <div class="unified-evidence-source ${getUnifiedEvidenceTone(value)}">
            <span>${escHtml(label)}</span>
            <strong>${Number.isFinite(Number(value)) ? `${Math.round(Number(value))}` : "--"}</strong>
          </div>
        `).join("")}
      </div>
    </article>
  `).join("");
}

function renderUnifiedUncertaintyList(items) {
  return (items || []).length
    ? (items || []).map((item) => `<div class="unified-uncertainty-item">${escHtml(item)}</div>`).join("")
    : `<div class="career-list-empty">当前没有明显待验证项</div>`;
}

function getProfilePortraitState() {
  const state = userWorkspaceState.scopedData.profile_portrait;
  return state && typeof state === "object" ? state : null;
}

function buildProfileAssessmentModuleOutput(profile) {
  const mbti = profile?.assessment?.mbti?.display_type || profile?.assessment?.mbti?.final_type || "";
  const holland = profile?.assessment?.holland?.code || "";
  const prose = collectPortraitAssessmentProse();
  const careers = profile?.assessment?.mbti?.careers && Array.isArray(profile.assessment.mbti.careers)
    ? profile.assessment.mbti.careers.slice(0, 4).filter(Boolean)
    : [];
  const chips = uniqueValues([
    mbti ? `MBTI ${mbti}` : "",
    holland ? `霍兰德 ${holland}` : "",
    ...(Array.isArray(profile?.assessment?.holland?.top_codes) ? profile.assessment.holland.top_codes.map((item) => `兴趣 ${item}`) : []),
    ...careers.map((c) => `职业线索 ${c}`)
  ], 8);
  const status = mbti && holland ? "complete" : (mbti || holland ? "partial" : "missing");
  const detailProse = prose.trim()
    || [portraitMbtiFallbackNarrative(mbti), portraitHollandCodeNarrative(holland)].filter(Boolean).join("\n");
  const headline = mbti && holland
    ? `测评已给出 ${mbti} 与 ${holland} 的人格—兴趣组合锚点；下方为系统抽取的测评正文与类型补述，将一并送入画像与绘图提示词。`
    : mbti || holland
      ? `测评只完成了一部分，仍会把已有结果与类型补述写进链路；建议补全另一项测评以稳定画像。`
      : "测评阶段尚未形成稳定输出，人物画像会更多依赖简历和访谈信号。";
  const summary = detailProse ? `${headline}\n\n${detailProse.slice(0, 520)}${detailProse.length > 520 ? "…" : ""}` : headline;
  const note = mbti && holland
    ? "这一层回答“你大致是什么样的人、会被什么工作场景激活”。长文来自主测摘要、四维侧写与类型气质补述，不是简单标签。"
    : "测评没有补齐时，人物画像仍可生成，但人格与兴趣的稳定度会下降。";
  return {
    stepLabel: "01",
    title: "测评输出",
    status,
    summary,
    chips,
    note,
    detail: detailProse,
    raw: {
      status,
      summary: headline,
      chips,
      note,
      mbti,
      holland,
      detail_prose: detailProse
    }
  };
}

function buildProfileResumeModuleOutput(profile, resumeTraits = null) {
  const traits = resumeTraits || buildResumePortraitTraits(userWorkspaceState.scopedData.resume_profile || null);
  const resumeStatus = String(profile?.resume?.status || "");
  const chips = uniqueValues([
    ...(traits.roles || []),
    ...(traits.skills || []).slice(0, 3),
    ...(traits.projects || []).slice(0, 2)
  ], 6);
  const status = resumeStatus === "analyzed" ? "complete" : (resumeStatus === "uploaded" ? "partial" : "missing");
  const summary = traits.summary
    || (resumeStatus === "uploaded"
      ? "简历已经上传，但还没有解析完成，当前无法稳定提取经历证据。"
      : "简历阶段尚未形成角色线索、项目证据和技能关键词。");
  const note = status === "complete"
    ? "这一层主要负责告诉系统“你做过什么、拿什么证明自己像这个岗位”。"
    : "没有简历证据时，人物画像可以做首版，但岗位证明材料会更弱。";
  return {
    stepLabel: "02",
    title: "简历输出",
    status,
    summary,
    chips,
    note,
    raw: {
      status,
      summary,
      chips,
      note,
      roles: traits.roles || [],
      projects: traits.projects || [],
      experiences: traits.experiences || [],
      skills: traits.skills || []
    }
  };
}

function buildPortraitInterviewSupplement(profile, synthesis) {
  const parts = [];
  const thesis = synthesis?.thesis ? String(synthesis.thesis).trim() : "";
  if (thesis) parts.push(`【补述·主画像收敛】${thesis}`);
  const ps = profile?.summary ? String(profile.summary).trim() : "";
  if (ps && ps !== thesis) parts.push(`【全景摘要】${ps.slice(0, 360)}${ps.length > 360 ? "…" : ""}`);
  const roles = uniqueValues(profile?.recommendedRoles || [], 4);
  if (roles.length) parts.push(`【岗位线索】${roles.join("、")}`);
  const wv = uniqueValues(profile?.workValues || [], 5);
  if (wv.length) parts.push(`【价值观线索】${wv.join("、")}`);
  const mbti = profile?.assessment?.mbti?.display_type || profile?.assessment?.mbti?.final_type || "";
  const hol = profile?.assessment?.holland?.code || "";
  if (mbti || hol) {
    parts.push(`【与测评交叉】MBTI ${mbti || "—"}；霍兰德 ${hol || "—"}。访谈若提前结束或仅弱信号，系统仍强制把上述线索并入访谈层，避免本卡片空白。`);
  }
  return parts.filter(Boolean).join("\n");
}

function buildProfileInterviewModuleOutput(profile, synthesis) {
  const interviewProfile = profile?.interview?.profile || null;
  const completionScore = Math.max(0, Math.min(100, Number(profile?.interview?.completionScore || 0)));
  const isComplete = Boolean(profile?.interview?.isComplete);
  const usableForPortrait = Boolean(
    interviewProfile?.portrait_ready
    || interviewProfile?.output_scope === "full"
    || interviewProfile?.output_scope === "usable"
    || interviewProfile?.summary
  );
  const status = !interviewProfile
    ? "missing"
    : isComplete
      ? "complete"
      : (usableForPortrait ? "partial" : "missing");
  let chips = uniqueValues([
    ...(interviewProfile?.work_values || []),
    ...(interviewProfile?.recommended_roles || []),
    interviewProfile?.leadership_style || "",
    interviewProfile?.role_model || ""
  ], 8);
  if (!chips.length) {
    chips = uniqueValues([
      ...(synthesis?.roleCluster || []).slice(0, 2),
      ...(profile?.recommendedRoles || []).slice(0, 3),
      completionScore > 0 ? `访谈进度 ${completionScore}%` : "",
      "补述：主画像与测评交叉"
    ].filter(Boolean), 8);
  }
  const supplement = buildPortraitInterviewSupplement(profile, synthesis);
  const baseSummary = interviewProfile?.summary
    || (completionScore
      ? `访谈已形成 ${completionScore}% 进度，但尚未沉淀出稳定访谈摘要。`
      : "访谈阶段尚未形成独立摘要。");
  const weakInterview = !interviewProfile?.summary
    || String(interviewProfile.summary).trim().length < 24
    || (interviewProfile?.coverage_note && String(interviewProfile.coverage_note).includes("弱信号"));
  let summary = baseSummary;
  if (weakInterview && supplement) {
    summary = `${baseSummary}\n\n${supplement}`.trim();
  }
  const detail = [
    interviewProfile?.key_experience ? `关键经历：${String(interviewProfile.key_experience).trim()}` : "",
    interviewProfile?.growth_mindset ? `成长观：${String(interviewProfile.growth_mindset).trim()}` : "",
    Array.isArray(interviewProfile?.evidence_highlights) && interviewProfile.evidence_highlights.length
      ? `证据亮点：${interviewProfile.evidence_highlights.slice(0, 4).filter(Boolean).join("；")}`
      : "",
    weakInterview && supplement ? `系统补述：\n${supplement}` : ""
  ].filter(Boolean).join("\n\n");
  const note = !interviewProfile
    ? "这一层负责补足价值观、关键经历、协作风格和行动证据。"
    : (interviewProfile?.coverage_note
      ? `${interviewProfile.coverage_note} 下方「补述」为系统根据主画像与测评强制写入，用于绘图与 brief，不等同于真实访谈逐字稿。`
      : (isComplete
        ? "访谈已经形成完整输出，可直接进入人物明信片。"
        : "即使提前结束，也会用主画像与测评做补述，保证链路可渲染。"));
  const missingFollowups = uniqueValues(interviewProfile?.missing_followups || [], 4);
  return {
    stepLabel: "03",
    title: "访谈输出",
    status,
    summary,
    chips,
    note,
    detail,
    raw: {
      status,
      summary,
      chips,
      note,
      completion_score: completionScore,
      usable_for_portrait: usableForPortrait || Boolean(supplement),
      missing_followups: missingFollowups,
      forced_supplement: supplement,
      work_values: interviewProfile?.work_values || [],
      recommended_roles: interviewProfile?.recommended_roles || [],
      role_model: interviewProfile?.role_model || "",
      leadership_style: interviewProfile?.leadership_style || "",
      key_experience: interviewProfile?.key_experience || "",
      growth_mindset: interviewProfile?.growth_mindset || "",
      evidence_highlights: interviewProfile?.evidence_highlights || [],
      recommended_exploration: interviewProfile?.recommended_exploration || [],
    }
  };
}

function buildProfilePromptOutput(profile, roles, synthesis, portraitState) {
  const brief = getResolvedProfilePortraitBrief(profile, roles, synthesis, portraitState);
  const promptWriterMode = String(portraitState?.prompt_writer_mode || "").trim();
  const promptModeLabel = promptWriterMode === "llm"
    ? `AI 重写${portraitState?.prompt_writer_model ? ` · ${portraitState.prompt_writer_model}` : ""}`
    : (portraitState?.brief ? "规则兜底" : "待生成");
  const status = portraitState?.brief ? "complete" : "partial";
  const chips = uniqueValues([
    brief?.title || "",
    brief?.primary_role || "",
    ...(brief?.evidence_tags || []).slice(0, 3),
    ...(brief?.value_tags || []).slice(0, 2),
    portraitState?.prompt_writer_mode === "llm" ? "叙事级 render_prompt" : ""
  ].filter(Boolean), 8);
  const promptText = String(portraitState?.prompt_text || "").trim();
  const ps = String(portraitState?.prompt_summary || "").trim();
  const lead = ps || brief?.subtitle || synthesis?.thesis
    || "系统会把前 3 步的输出压缩成标题、定位句、主角色、任务句和视觉设定。";
  const summary = promptText
    ? `${lead}\n\n—— 图像渲染提示词节选 ——\n${promptText.slice(0, 480)}${promptText.length > 480 ? "…" : ""}`
    : lead;
  const detail = promptText || "";
  const note = portraitState?.brief
    ? `以下为送入图像模型的完整中文渲染提示词（含叙事依据与视觉硬约束）。当前模式：${promptModeLabel}。未生成前仅显示规则草稿。`
    : "点击「生成任务海报」后，系统会合并测评/简历/访谈与补述，输出完整叙事级提示词。";
  return {
    stepLabel: "AI",
    title: "提示词重写",
    status,
    summary,
    chips,
    note,
    detail,
    meta: promptModeLabel
  };
}

function buildProfilePortraitOutputCards(profile, roles, synthesis, portraitState, resumeTraits = null) {
  return [
    buildProfileAssessmentModuleOutput(profile),
    buildProfileResumeModuleOutput(profile, resumeTraits),
    buildProfileInterviewModuleOutput(profile, synthesis),
    buildProfilePromptOutput(profile, roles, synthesis, portraitState)
  ];
}

function renderProfilePortraitOutputBoard(boardEl, cards) {
  if (!boardEl) return;
  const items = Array.isArray(cards) ? cards : [];
  boardEl.innerHTML = items.map((item) => {
    const chips = Array.isArray(item.chips) && item.chips.length
      ? item.chips.map((chip) => `<span class="profile-portrait-output-chip">${escHtml(chip)}</span>`).join("")
      : `<span class="profile-portrait-output-chip is-muted">当前还没有稳定信号</span>`;
    const metaHtml = item.meta ? `<span class="profile-portrait-output-meta">${escHtml(item.meta)}</span>` : "";
    const detailRaw = item.detail != null ? String(item.detail).trim() : "";
    const detailHtml = detailRaw
      ? `
        <div class="profile-portrait-output-detail-wrap">
          <p class="profile-portrait-output-detail-h">链路完整正文（送入模型 / 提示词管线）</p>
          <pre class="profile-portrait-output-detail" spellcheck="false">${escHtml(detailRaw)}</pre>
        </div>`
      : "";
    return `
      <article class="profile-portrait-output-card is-${escHtml(item.status || "missing")}${detailHtml ? " has-detail" : ""}">
        <div class="profile-portrait-output-head">
          <div class="profile-portrait-output-headline">
            <span class="profile-portrait-output-step">${escHtml(item.stepLabel || "--")}</span>
            <div>
              <h4 class="profile-portrait-output-title">${escHtml(item.title || "模块输出")}</h4>
              <p class="profile-portrait-output-summary">${escHtml(item.summary || "当前还没有稳定输出。")}</p>
            </div>
          </div>
          ${metaHtml}
        </div>
        <div class="profile-portrait-output-chiprow">${chips}</div>
        ${detailHtml}
        <p class="profile-portrait-output-note">${escHtml(item.note || "")}</p>
      </article>
    `;
  }).join("");
}

// ─── 数据来源状态条 ───────────────────────────────────────────────────────────
function renderProfileSourcePills(el, profile) {
  if (!el) return;
  const mbtiDone = Boolean(profile?.assessment?.mbti?.completed);
  const hollandDone = Boolean(profile?.assessment?.holland?.completed);
  const assessStatus = mbtiDone && hollandDone ? "complete" : (mbtiDone || hollandDone ? "partial" : "missing");

  const resumeStatus = String(profile?.resume?.status || "");
  const resumeDone = resumeStatus === "analyzed";
  const resumePartial = resumeStatus === "uploaded";

  const completionScore = Math.max(0, Math.min(100, Number(profile?.interview?.completionScore || 0)));
  const interviewProfile = profile?.interview?.profile || null;
  const interviewDone = Boolean(profile?.interview?.isComplete);
  const interviewUsable = Boolean(interviewProfile?.summary || interviewProfile?.portrait_ready);

  const pills = [
    {
      label: "测评",
      detail: assessStatus === "complete" ? `MBTI · Holland` : assessStatus === "partial" ? "部分完成" : "未完成",
      status: assessStatus
    },
    {
      label: "简历",
      detail: resumeDone ? "已解析" : resumePartial ? "待解析" : "未上传",
      status: resumeDone ? "complete" : resumePartial ? "partial" : "missing"
    },
    {
      label: "访谈",
      detail: interviewDone ? "已完成" : completionScore > 0 ? `${completionScore}%` : "未开始",
      status: interviewDone ? "complete" : interviewUsable ? "partial" : "missing"
    }
  ];

  const colorMap = {
    complete: { pill: "bg-emerald-50 border-emerald-200", dot: "bg-emerald-400", label: "text-emerald-700", detail: "text-emerald-600" },
    partial:  { pill: "bg-amber-50 border-amber-200",   dot: "bg-amber-400",   label: "text-amber-700",   detail: "text-amber-600"  },
    missing:  { pill: "bg-slate-50 border-slate-200",   dot: "bg-slate-300",   label: "text-slate-500",   detail: "text-slate-400"  }
  };

  el.innerHTML = `
    <div class="flex flex-wrap items-center gap-2 py-3">
      <span class="text-xs text-slate-400 font-medium mr-1">画像来源</span>
      ${pills.map((p) => {
        const c = colorMap[p.status];
        return `
          <span class="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs ${c.pill}">
            <span class="w-1.5 h-1.5 rounded-full flex-shrink-0 ${c.dot}"></span>
            <span class="font-semibold ${c.label}">${escHtml(p.label)}</span>
            <span class="${c.detail}">${escHtml(p.detail)}</span>
          </span>
        `;
      }).join("")}
    </div>
  `;
}

// ─── 六维能力速览 ─────────────────────────────────────────────────────────────
function renderProfileCapabilityStrip(el, profile, portraitLoading = false) {
  if (!el) return;
  const dims = [
    { key: "professional",     label: "专业技能", icon: "⚙️" },
    { key: "learning",         label: "学习能力", icon: "📖" },
    { key: "communication",    label: "沟通能力", icon: "💬" },
    { key: "innovation",       label: "创新能力", icon: "💡" },
    { key: "stress_tolerance", label: "抗压能力", icon: "🧱" },
    { key: "execution",        label: "执行力",   icon: "🎯" }
  ];

  if (portraitLoading) {
    el.innerHTML = dims.map((d) => `
      <div class="profile-capability-skeleton-card" aria-hidden="true">
        <div class="profile-cap-skel-row">
          <div class="profile-cap-skel-title">
            <span class="profile-cap-skel-ico">${d.icon}</span>
            <span class="profile-cap-skel-bar profile-cap-skel-bar--label"></span>
          </div>
          <span class="profile-cap-skel-bar profile-cap-skel-bar--pct"></span>
        </div>
        <div class="profile-cap-skel-track">
          <span class="profile-cap-skel-fill"></span>
        </div>
        <span class="profile-cap-skel-bar profile-cap-skel-bar--src"></span>
      </div>
    `).join("") + `
      <p class="profile-cap-skel-hint col-span-full">
        <span class="profile-cap-skel-pill">
          <span class="profile-cap-strip-spinner" aria-hidden="true"></span>
          任务海报生成中，六维推断结果将在完成后呈现（分数随测评与经历变化，非写死）
        </span>
      </p>
    `;
    return;
  }

  const hasAnyCap = dims.some((d) => profile?.capabilities?.[d.key]?.score != null);

  if (!hasAnyCap) {
    el.innerHTML = `
      <div class="col-span-full flex items-center gap-3 rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-5 py-4 text-sm text-slate-400">
        <span class="text-lg">📊</span>
        <span>完成测评与访谈后，六维能力评分会自动出现在这里。</span>
      </div>
    `;
    return;
  }

  el.innerHTML = dims.map((d) => {
    const cap = profile?.capabilities?.[d.key];
    const score = cap?.score ?? null;
    const inferred = cap?.inferred ?? true;
    const sources = Array.isArray(cap?.sources) && cap.sources.length ? cap.sources.join(" · ") : "";
    const pct = score === null ? 0 : score;
    const barColor = score === null
      ? "bg-slate-200"
      : score >= 75 ? "bg-gradient-to-r from-emerald-400 to-teal-400"
      : score >= 55 ? "bg-gradient-to-r from-sky-400 to-cyan-400"
      : "bg-gradient-to-r from-amber-400 to-yellow-400";
    const scoreText = score === null ? "待补充" : `${score}%`;
    const scoreColor = score === null ? "text-slate-400" : score >= 75 ? "text-emerald-600" : score >= 55 ? "text-sky-600" : "text-amber-600";
    const tagHtml = score !== null && !inferred
      ? `<span class="ml-1 rounded-full bg-emerald-50 border border-emerald-200 px-1.5 py-0.5 text-[10px] text-emerald-600">有实证</span>`
      : score !== null
        ? `<span class="ml-1 rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-400">推断</span>`
        : "";

    return `
      <div class="rounded-2xl border border-slate-100 bg-white p-4 shadow-sm hover:border-slate-200 transition">
        <div class="flex items-center justify-between gap-2 mb-2">
          <div class="flex items-center gap-1.5">
            <span class="text-base leading-none">${d.icon}</span>
            <span class="text-sm font-semibold text-slate-700">${escHtml(d.label)}</span>
            ${tagHtml}
          </div>
          <span class="text-sm font-bold ${scoreColor}">${escHtml(scoreText)}</span>
        </div>
        <div class="h-1.5 rounded-full bg-slate-100 overflow-hidden mb-2">
          <div class="h-full rounded-full ${barColor} transition-all duration-500" style="width:${pct}%"></div>
        </div>
        ${sources ? `<p class="text-[11px] text-slate-400 leading-4 truncate">来源：${escHtml(sources)}</p>` : ""}
      </div>
    `;
  }).join("");
}

// ─── 关键证据 & 信息缺口 ──────────────────────────────────────────────────────
function renderProfileEvidenceGaps(el, profile, portraitLoading = false) {
  if (!el) return;
  if (portraitLoading) {
    el.innerHTML = `
      <div class="profile-evidence-gaps-loading">
        <span class="profile-cap-strip-spinner" aria-hidden="true"></span>
        <div class="profile-evidence-gaps-loading-text">
          <p class="profile-evidence-gaps-loading-title">正在生成任务海报</p>
          <p class="profile-evidence-gaps-loading-desc">关键证据与信息缺口将在生成完成后展示；内容与当前访谈、简历和测评状态联动，并非固定文案。</p>
        </div>
      </div>`;
    return;
  }
  const interviewProfile = profile?.interview?.profile || null;
  const evidenceHighlights = Array.isArray(interviewProfile?.evidence_highlights)
    ? interviewProfile.evidence_highlights.filter(Boolean).slice(0, 4)
    : [];
  const missingFollowups = Array.isArray(interviewProfile?.missing_followups)
    ? interviewProfile.missing_followups.filter(Boolean).slice(0, 4)
    : [];
  const missingItems = Array.isArray(profile?.missingItems)
    ? profile.missingItems.filter(Boolean).slice(0, 3)
    : [];
  const allGaps = [...missingFollowups, ...missingItems].slice(0, 4);

  const hasEvidence = evidenceHighlights.length > 0;
  const hasGaps = allGaps.length > 0;

  if (!hasEvidence && !hasGaps) return (el.innerHTML = "");

  const evidenceHtml = hasEvidence ? `
    <div class="rounded-2xl border border-slate-100 bg-white p-5 shadow-sm">
      <div class="flex items-center gap-2 mb-3">
        <span class="text-base">🔍</span>
        <p class="text-xs font-semibold tracking-[0.15em] text-slate-400 uppercase">关键证据</p>
      </div>
      <ul class="space-y-2">
        ${evidenceHighlights.map((item) => `
          <li class="flex items-start gap-2 text-sm text-slate-600 leading-5">
            <span class="mt-0.5 w-4 h-4 flex-shrink-0 rounded-full bg-emerald-100 flex items-center justify-center">
              <svg width="8" height="8" viewBox="0 0 8 8" fill="none"><path d="M1.5 4l2 2 3-3" stroke="#059669" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </span>
            ${escHtml(item)}
          </li>
        `).join("")}
      </ul>
    </div>
  ` : "";

  const gapsHtml = hasGaps ? `
    <div class="rounded-2xl border border-amber-100 bg-amber-50 p-5 shadow-sm">
      <div class="flex items-center gap-2 mb-3">
        <span class="text-base">📋</span>
        <p class="text-xs font-semibold tracking-[0.15em] text-amber-600 uppercase">信息缺口</p>
      </div>
      <ul class="space-y-2">
        ${allGaps.map((item) => `
          <li class="flex items-start gap-2 text-sm text-amber-800 leading-5">
            <span class="mt-0.5 w-4 h-4 flex-shrink-0 rounded-full bg-amber-200 flex items-center justify-center text-[10px] text-amber-700 font-bold">?</span>
            ${escHtml(item)}
          </li>
        `).join("")}
      </ul>
      <p class="mt-3 text-[11px] text-amber-600 border-t border-amber-200 pt-2">继续访谈可补齐以上缺口，提升画像置信度。</p>
    </div>
  ` : "";

  el.innerHTML = `<div class="grid gap-4 md:grid-cols-2">${evidenceHtml}${gapsHtml}</div>`;
}

function portraitHollandCodeNarrative(code) {
  const c = String(code || "").trim().toUpperCase();
  if (!c) return "";
  const parts = [];
  for (let i = 0; i < c.length; i += 1) {
    const letter = c[i];
    if (PORTRAIT_HOLLAND_LETTER_BLURB[letter]) parts.push(PORTRAIT_HOLLAND_LETTER_BLURB[letter]);
  }
  return parts.join(" ");
}

function portraitMbtiFallbackNarrative(code) {
  const key = String(code || "").trim().toUpperCase();
  return PORTRAIT_MBTI_TYPE_NARRATIVE[key] || "";
}

function collectPortraitIdentityNarrative(profile, synthesis) {
  const parts = [];
  const thesis = synthesis?.thesis ? String(synthesis.thesis).trim() : "";
  if (thesis) parts.push(`收敛结论：${thesis}`);
  const ip = profile?.interview?.profile;
  if (ip?.summary) parts.push(`访谈摘要：${String(ip.summary).trim()}`);
  if (ip?.key_experience) parts.push(`关键经历：${String(ip.key_experience).trim()}`);
  if (ip?.leadership_style) parts.push(`协作与领导风格：${String(ip.leadership_style).trim()}`);
  if (ip?.growth_mindset) parts.push(`成长观：${String(ip.growth_mindset).trim()}`);
  if (ip?.role_model) parts.push(`认同榜样：${String(ip.role_model).trim()}`);
  const dims = Array.isArray(ip?.dimensions) ? ip.dimensions : [];
  dims.forEach((d) => {
    const ev = d?.evidence && String(d.evidence).trim();
    if (ev) parts.push(`${d.name || "维度"}：${ev}`);
  });
  return parts.join("\n").slice(0, 3500);
}

function collectPortraitAssessmentProse() {
  try {
    const snap = getAssessmentHubSnapshotSafe();
    if (!snap) return "";
    const chunks = [];
    if (snap.mbti?.completed) {
      const code = snap.mbti.display_type || snap.mbti.final_type || "";
      const sum = snap.mbti.summary ? String(snap.mbti.summary).trim() : "";
      if (sum) chunks.push(`MBTI（${code}）测评文字：${sum}`);
      else if (code) chunks.push(`MBTI 已完成，类型 ${code}（请结合四维与主测摘要理解气质，而非仅四字标签）。`);
      const d = snap.mbti.detail && typeof snap.mbti.detail === "object" ? snap.mbti.detail : null;
      if (d) {
        if (d.nickname) chunks.push(`MBTI 角色标签：${String(d.nickname).trim()}`);
        if (Array.isArray(d.strengths) && d.strengths.length) chunks.push(`典型优势：${d.strengths.slice(0, 6).filter(Boolean).join("；")}`);
        if (Array.isArray(d.risks) && d.risks.length) chunks.push(`需注意：${d.risks.slice(0, 4).filter(Boolean).join("；")}`);
        if (Array.isArray(d.work_style) && d.work_style.length) chunks.push(`工作风格线索：${d.work_style.slice(0, 5).filter(Boolean).join("；")}`);
        if (Array.isArray(d.career_advice) && d.career_advice.length) chunks.push(`发展建议摘录：${d.career_advice.slice(0, 4).filter(Boolean).join("；")}`);
        if (d.summary && String(d.summary).trim() && String(d.summary).trim() !== sum) {
          chunks.push(`MBTI 详细侧写：${String(d.summary).trim()}`);
        }
      }
      const fb = portraitMbtiFallbackNarrative(code);
      if (fb) chunks.push(`类型气质参考（补述）：${fb}`);
    }
    if (snap.holland?.completed) {
      const h = snap.holland;
      const sum = h.summary ? String(h.summary).trim() : "";
      if (sum) chunks.push(`霍兰德（${h.code || ""}）测评文字：${sum}`);
      else if (h.code) chunks.push(`霍兰德兴趣代码 ${h.code}。`);
      if (h.primary && (h.primary.name || h.primary.code)) {
        chunks.push(`霍兰德主导类型：${h.primary.name || h.primary.code}${h.primary.score != null ? `（强度约 ${h.primary.score}）` : ""}`);
      }
      const hd = h.detail && typeof h.detail === "object" ? h.detail : null;
      if (hd?.summary) chunks.push(`霍兰德主导兴趣详解：${String(hd.summary).trim()}`);
      const holNarr = portraitHollandCodeNarrative(h.code);
      if (holNarr) chunks.push(`兴趣代码展开（补述）：${holNarr}`);
    }
    if (snap.combined_summary) chunks.push(`测评综合：${String(snap.combined_summary).trim()}`);
    return chunks.filter(Boolean).join("\n").slice(0, 3800);
  } catch (_) {
    return "";
  }
}

function collectPortraitExtendedTestsProse() {
  try {
    const core = window.__DeepTestHubCore__;
    if (!core || typeof core.getStoredResultByType !== "function") return "";
    const chunks = [];
    const nameMap = typeof core.getMbtiNameMap === "function" ? core.getMbtiNameMap() : {};
    const deep = core.getStoredResultByType("deep");
    if (deep?.result?.type) {
      const t = deep.result.type;
      const cn = nameMap[t] || "";
      const p = deep.result.pct && typeof deep.result.pct === "object" ? deep.result.pct : null;
      const pctHint = p
        ? `四维倾向强度（约）：内向-外向 ${p.IE ?? 0}% 、感觉-直觉 ${p.SN ?? 0}% 、思考-情感 ${p.TF ?? 0}% 、判断-感知 ${p.JP ?? 0}% 。`
        : "";
      let line = `深层 MBTI（52 题）：${t}${cn ? `（${cn}）` : ""}${pctHint ? ` ${pctHint}` : ""}`;
      if (deep.aiText) line += ` 扩展解读摘录：${String(deep.aiText).trim().slice(0, 420)}`;
      chunks.push(line.trim());
    }
    const fr = core.getStoredResultByType("friends");
    if (fr?.winner) {
      const syn = fr.detail?.synopsis ? String(fr.detail.synopsis).trim() : "";
      const traits = Array.isArray(fr.detail?.traits) ? fr.detail.traits.slice(0, 5).filter(Boolean).join("、") : "";
      chunks.push(
        `老友记角色测评：最像 ${fr.winner}${syn ? `；角色叙事：${syn}` : ""}${traits ? `；相关特质：${traits}` : ""}`.trim()
      );
    }
    const io = core.getStoredResultByType("insideout");
    if (io?.winner) {
      const syn = io.detail?.synopsis ? String(io.detail.synopsis).trim() : "";
      chunks.push(`头脑特工队情绪主导：${io.winner}${syn ? `；气质描述：${syn}` : ""}`.trim());
    }
    const sb = core.getStoredResultByType("sbti");
    if (sb?.code) {
      chunks.push(
        `SBTI 人格扩展：${String(sb.title || sb.code).trim()}（匹配度 ${sb.match != null ? sb.match : "--"}%）。${String(sb.summary || "").trim()}`.trim()
      );
    }
    return chunks.filter(Boolean).join("\n").slice(0, 2800);
  } catch (_) {
    return "";
  }
}

function buildProfilePortraitContext(profile, roles, synthesis) {
  const resumeState = userWorkspaceState.scopedData.resume_profile || null;
  const resumeTraits = buildResumePortraitTraits(resumeState);
  const interviewProfile = profile?.interview?.profile || null;
  const assessmentOutput = buildProfileAssessmentModuleOutput(profile);
  const resumeOutput = buildProfileResumeModuleOutput(profile, resumeTraits);
  const interviewOutput = buildProfileInterviewModuleOutput(profile, synthesis);
  const nextSteps = uniqueValues([
    ...(Array.isArray(profile?.nextSteps) ? profile.nextSteps : []),
    ...(((roles || [])[0]?.nextActions) || [])
  ], 4);
  return {
    gender: profile?.basics?.gender || "",
    archetype_name: synthesis?.archetype?.name || "",
    archetype_scene: synthesis?.archetype?.scene || "",
    summary: synthesis?.thesis || profile?.summary || "",
    mbti: profile?.assessment?.mbti?.display_type || profile?.assessment?.mbti?.final_type || "",
    holland: profile?.assessment?.holland?.code || "",
    holland_top_codes: Array.isArray(profile?.assessment?.holland?.top_codes) ? profile.assessment.holland.top_codes : [],
    major: profile?.basics?.major || "",
    grade: profile?.basics?.grade || "",
    target_city: profile?.basics?.target_city || "",
    target_direction: profile?.basics?.target_direction || "",
    role_cluster: synthesis?.roleCluster || [],
    top_roles: (roles || []).slice(0, 3).map((item) => item?.name || "").filter(Boolean),
    work_values: synthesis?.workValues || [],
    axis_traits: (synthesis?.axes || []).map((item) => `${item.label}：${item.focus}`).filter(Boolean),
    workstyle_traits: (synthesis?.workstyleCards || []).map((item) => `${item.title}：${item.value}`).filter(Boolean),
    interview_summary: interviewProfile?.summary || "",
    interview_roles: uniqueValues(interviewProfile?.recommended_roles || [], 4),
    interview_values: uniqueValues(interviewProfile?.work_values || [], 5),
    interview_evidence: uniqueValues(interviewProfile?.evidence_highlights || [], 4),
    resume_summary: resumeTraits.summary,
    resume_roles: resumeTraits.roles,
    resume_signals: resumeTraits.signals,
    resume_projects: resumeTraits.projects,
    resume_experiences: resumeTraits.experiences,
    resume_skills: resumeTraits.skills,
    resume_competitions: resumeTraits.competitions,
    next_steps: nextSteps,
    missing_items: uniqueValues(profile?.missingItems || [], 4),
    uncertainty: uniqueValues(synthesis?.uncertainty || [], 4),
    identity_narrative: collectPortraitIdentityNarrative(profile, synthesis),
    assessment_prose: collectPortraitAssessmentProse(),
    extended_tests_prose: collectPortraitExtendedTestsProse(),
    module_outputs: {
      assessment: assessmentOutput.raw,
      resume: resumeOutput.raw,
      interview: interviewOutput.raw
    },
    prompt_request: {
      card_style: "人物明信片",
      card_goal: "美观清晰，一眼看懂这个人最像什么岗位、能做什么任务、下一步该补什么。",
      visual_direction: "半写实出版物/编辑插图质感，自然窗光或柔光，浅景深，低饱和配色；避免廉价滤镜与 Q 版卡通。",
      required_fields: ["标题", "定位句", "主角色", "任务句", "证据标签", "下一步"]
    }
  };
}

function getProfilePortraitActivityLine() {
  const maxStage = PROFILE_PORTRAIT_STAGE_ACTIVITY.length - 1;
  const si = Math.min(Math.max(profilePortraitTaskState.stageIndex, 0), maxStage);
  const lines = PROFILE_PORTRAIT_STAGE_ACTIVITY[si] || PROFILE_PORTRAIT_STAGE_ACTIVITY[0];
  const idx = lines.length ? profilePortraitTaskState.pulseIndex % lines.length : 0;
  return lines[idx] || "处理中…";
}

function getProfilePortraitElapsedLabel() {
  if (!profilePortraitTaskState.loading || !profilePortraitTaskState.startedAt) return "";
  const sec = Math.floor((Date.now() - profilePortraitTaskState.startedAt) / 1000);
  return sec > 0 ? `已进行约 ${sec} 秒` : "";
}

function startProfilePortraitLoading(mode = "render") {
  if (profilePortraitTaskState.stageTimer) clearInterval(profilePortraitTaskState.stageTimer);
  if (profilePortraitTaskState.pulseTimer) clearInterval(profilePortraitTaskState.pulseTimer);
  profilePortraitTaskState.loading = true;
  profilePortraitTaskState.mode = mode;
  profilePortraitTaskState.stageIndex = 0;
  profilePortraitTaskState.pulseIndex = 0;
  profilePortraitTaskState.startedAt = Date.now();
  profilePortraitTaskState.stageTimer = setInterval(() => {
    profilePortraitTaskState.stageIndex = Math.min(PROFILE_PORTRAIT_LOADING_STAGES.length - 1, profilePortraitTaskState.stageIndex + 1);
    const profile = appState.derivedProfile || deriveUnifiedProfile();
    const roles = Array.isArray(appState.matchingRoles) && appState.matchingRoles.length
      ? appState.matchingRoles
      : computeRoleMatches(profile);
    renderProfileWorkspace(profile, roles);
  }, 850);
  profilePortraitTaskState.pulseTimer = setInterval(() => {
    profilePortraitTaskState.pulseIndex += 1;
    const profile = appState.derivedProfile || deriveUnifiedProfile();
    const roles = Array.isArray(appState.matchingRoles) && appState.matchingRoles.length
      ? appState.matchingRoles
      : computeRoleMatches(profile);
    renderProfileWorkspace(profile, roles);
  }, 1500);
}

function stopProfilePortraitLoading() {
  if (profilePortraitTaskState.stageTimer) clearInterval(profilePortraitTaskState.stageTimer);
  if (profilePortraitTaskState.pulseTimer) clearInterval(profilePortraitTaskState.pulseTimer);
  profilePortraitTaskState.stageTimer = null;
  profilePortraitTaskState.pulseTimer = null;
  profilePortraitTaskState.loading = false;
  profilePortraitTaskState.stageIndex = 0;
  profilePortraitTaskState.pulseIndex = 0;
  profilePortraitTaskState.startedAt = 0;
}

function buildFallbackProfilePortraitBrief(profile, roles, synthesis, portraitState) {
  const primaryRole = (roles || [])[0]?.name || synthesis?.roleCluster?.[0] || profile?.basics?.target_direction || "职业探索中";
  const supportRoles = uniqueValues([
    ...(synthesis?.roleCluster || []).slice(1),
    ...(Array.isArray(profile?.recommendedRoles) ? profile.recommendedRoles : [])
  ], 3).filter((item) => item !== primaryRole).slice(0, 2);
  const nextAction = uniqueValues([
    ...(Array.isArray(profile?.nextSteps) ? profile.nextSteps : []),
    ...((((roles || [])[0]?.nextActions) || []))
  ], 3)[0] || `围绕 ${primaryRole} 补一条更可量化的项目成果。`;
  return {
    title: synthesis?.archetype?.name || portraitState?.archetype_name || "职业探索型支持者",
    subtitle: String(portraitState?.prompt_summary || synthesis?.thesis || "当前画像会先收敛成一张可对外展示的职业任务名片。").slice(0, 88),
    positioning: synthesis?.thesis || "当前画像会优先总结你的职业定位，再生成海报。",
    primary_role: primaryRole,
    support_roles: supportRoles,
    mission_line: `最适合在 ${primaryRole} 相关场景中承担支持执行、信息组织与任务推进类工作。`,
    evidence_tags: uniqueValues([
      profile?.assessment?.mbti?.display_type ? `MBTI：${profile.assessment.mbti.display_type}` : "",
      profile?.assessment?.holland?.code ? `霍兰德：${profile.assessment.holland.code}` : "",
      primaryRole ? `岗位线索：${primaryRole}` : ""
    ], 3),
    value_tags: uniqueValues(profile?.workValues || synthesis?.workValues || [], 3),
    risk_note: (Array.isArray(synthesis?.uncertainty) && synthesis.uncertainty[0]) || "当前主导特征仍建议继续用新经历补强。",
    next_action: nextAction,
    confidence_band: portraitState?.brief?.confidence_band || ((roles || [])[0]?.confidence || "待验证")
  };
}

function getResolvedProfilePortraitBrief(profile, roles, synthesis, portraitState) {
  const brief = portraitState?.brief && typeof portraitState.brief === "object" ? portraitState.brief : null;
  if (brief) return brief;
  return buildFallbackProfilePortraitBrief(profile, roles, synthesis, portraitState);
}

function buildProfilePortraitCopyText(brief) {
  const safeBrief = brief && typeof brief === "object" ? brief : {};
  const roles = [safeBrief.primary_role, ...(Array.isArray(safeBrief.support_roles) ? safeBrief.support_roles : [])].filter(Boolean).join(" / ");
  return [
    safeBrief.title || "职业任务名片",
    safeBrief.subtitle || "",
    roles ? `最像岗位：${roles}` : "",
    safeBrief.mission_line ? `适合任务：${safeBrief.mission_line}` : "",
    safeBrief.next_action ? `下一步：${safeBrief.next_action}` : ""
  ].filter(Boolean).join("\n");
}

function renderProfilePortraitVisual(archetypeVisualEl, portraitState, synthesis, brief) {
  if (!archetypeVisualEl) return;
  const safeBrief = brief && typeof brief === "object" ? brief : {};
  if (profilePortraitTaskState.loading) {
    const activityLine = escHtml(getProfilePortraitActivityLine());
    const elapsedRaw = getProfilePortraitElapsedLabel();
    const elapsedHtml = elapsedRaw ? `<p class="profile-portrait-activity-elapsed">${escHtml(elapsedRaw)}</p>` : "";
    const items = PROFILE_PORTRAIT_LOADING_STAGES.map((item, index) => {
      const stateClass = index < profilePortraitTaskState.stageIndex
        ? "done"
        : index === profilePortraitTaskState.stageIndex
          ? "active"
          : "";
      return `
        <div class="profile-portrait-loading-item ${stateClass}">
          <span class="profile-portrait-loading-dot">${index + 1}</span>
          <div class="profile-portrait-loading-copy">
            <strong>${escHtml(item.title)}</strong>
            <span>${escHtml(item.copy)}</span>
          </div>
        </div>
      `;
    }).join("");
    archetypeVisualEl.innerHTML = `
      <div class="profile-portrait-poster-empty">
        <div class="profile-portrait-poster-copy-block">
          <span class="profile-portrait-poster-status is-live">生成中</span>
          <div>
            <h4 class="profile-portrait-poster-title">任务海报正在生成</h4>
          </div>
          <div class="profile-portrait-activity-block" aria-live="polite">
            <div class="profile-portrait-activity-track" role="progressbar" aria-busy="true" aria-valuetext="处理中">
              <span class="profile-portrait-activity-indeterminate"></span>
            </div>
            <p class="profile-portrait-activity-line">${activityLine}</p>
            ${elapsedHtml}
          </div>
        </div>
        <div class="profile-portrait-loading-list">${items}</div>
      </div>
    `;
    return;
  }

  const hasPortrait = Boolean(portraitState?.image_url);
  if (hasPortrait) {
    const safeUrl = escHtml(String(portraitState.image_url || ""));
    const safeTitle = escHtml(safeBrief.title || portraitState?.archetype_name || synthesis?.archetype?.name || "职业画像");
    const safeSubtitle = escHtml(String(safeBrief.subtitle || portraitState?.prompt_summary || synthesis?.thesis || "").slice(0, 80));
    archetypeVisualEl.innerHTML = `
      <div class="profile-portrait-poster-shell has-image">
        <img src="${safeUrl}" alt="${safeTitle}" class="profile-portrait-poster-image">
        <div class="profile-portrait-poster-badge">AI Portrait</div>
        <div class="profile-portrait-poster-overlay">
          <strong>${safeTitle}</strong>
          <p>${safeSubtitle}</p>
        </div>
      </div>
    `;
    return;
  }

  const statusLabel = portraitState?.status === "brief_ready" ? "待重试海报" : "待生成";
  const posterTitle = safeBrief.title || synthesis?.archetype?.name || "任务海报";
  const posterCopy = portraitState?.status === "brief_ready"
    ? "职业定位已完成，海报生成失败，请重试。"
    : "这里会显示 3:4 半写实人物海报。完成输入后，系统会先收敛职业定位，再生成可对外展示的任务名片。";
  archetypeVisualEl.innerHTML = `
    <div class="profile-portrait-poster-empty">
      <div class="profile-portrait-poster-copy-block">
        <span class="profile-portrait-poster-status">${escHtml(statusLabel)}</span>
        <div>
          <h4 class="profile-portrait-poster-title">${escHtml(posterTitle)}</h4>
          <p class="profile-portrait-poster-copy">${escHtml(posterCopy)}</p>
        </div>
      </div>
      <div class="profile-portrait-poster-mini-card">
        <span class="profile-portrait-poster-mini-label">当前主角色</span>
        <strong class="profile-portrait-poster-mini-value">${escHtml(safeBrief.primary_role || "职业探索中")}</strong>
      </div>
    </div>
  `;
}

function renderProfilePortraitBriefCard(briefCardEl, portraitState, brief) {
  if (!briefCardEl) return;
  const safeBrief = brief && typeof brief === "object" ? brief : {};
  const hasGeneratedBrief = Boolean(portraitState?.brief && typeof portraitState.brief === "object");
  if (profilePortraitTaskState.loading) {
    const activityLine = escHtml(getProfilePortraitActivityLine());
    const elapsedRaw = getProfilePortraitElapsedLabel();
    const elapsedHtml = elapsedRaw ? `<p class="profile-portrait-activity-elapsed">${escHtml(elapsedRaw)}</p>` : "";
    const items = PROFILE_PORTRAIT_LOADING_STAGES.map((item, index) => {
      const stateClass = index < profilePortraitTaskState.stageIndex
        ? "done"
        : index === profilePortraitTaskState.stageIndex
          ? "active"
          : "";
      return `
        <div class="profile-portrait-loading-item ${stateClass}">
          <span class="profile-portrait-loading-dot">${index + 1}</span>
          <div class="profile-portrait-loading-copy">
            <strong>${escHtml(item.title)}</strong>
            <span>${escHtml(item.copy)}</span>
          </div>
        </div>
      `;
    }).join("");
    briefCardEl.innerHTML = `
      <div class="profile-portrait-brief-surface">
        <div class="profile-portrait-brief-head">
          <div>
            <p class="profile-portrait-kicker is-live">任务名片生成中</p>
            <h4 class="profile-portrait-brief-title">正在压缩关键信息</h4>
            <div class="profile-portrait-activity-block" aria-live="polite">
              <div class="profile-portrait-activity-track" role="progressbar" aria-busy="true" aria-valuetext="处理中">
                <span class="profile-portrait-activity-indeterminate"></span>
              </div>
              <p class="profile-portrait-activity-line">${activityLine}</p>
              ${elapsedHtml}
            </div>
          </div>
        </div>
        <div class="profile-portrait-loading-list">${items}</div>
      </div>
    `;
    return;
  }

  if (!hasGeneratedBrief && !portraitState?.image_url) {
    briefCardEl.innerHTML = `
      <div class="profile-portrait-brief-surface">
        <div class="profile-portrait-brief-head">
          <div>
            <p class="profile-portrait-kicker">待生成</p>
            <h4 class="profile-portrait-brief-title">任务名片尚未生成</h4>
          </div>
        </div>
        <div class="profile-portrait-brief-grid">
          <section class="profile-portrait-brief-section label-strong">
            <p class="profile-portrait-brief-label">你是谁</p>
            <p class="profile-portrait-brief-body muted">点击“生成任务海报”开始。</p>
          </section>
          <section class="profile-portrait-brief-section">
            <p class="profile-portrait-brief-label">最像岗位</p>
            <div class="profile-portrait-chip-row"><span class="profile-portrait-chip soft">等待生成后展示</span></div>
          </section>
          <section class="profile-portrait-brief-section">
            <p class="profile-portrait-brief-label">你能承担什么任务</p>
            <p class="profile-portrait-brief-body muted">待生成</p>
          </section>
        </div>
      </div>
    `;
    return;
  }

  const roleChips = [safeBrief.primary_role, ...(Array.isArray(safeBrief.support_roles) ? safeBrief.support_roles : [])]
    .filter(Boolean)
    .map((item, index) => `<span class="profile-portrait-chip ${index === 0 ? "" : "soft"}">${escHtml(item)}</span>`)
    .join("");
  const evidenceChips = (Array.isArray(safeBrief.evidence_tags) ? safeBrief.evidence_tags : [])
    .filter(Boolean)
    .slice(0, 3)
    .map((item) => `<span class="profile-portrait-chip soft">${escHtml(item)}</span>`)
    .join("");
  const confidence = escHtml(safeBrief.confidence_band || (portraitState?.status === "brief_ready" ? "待验证" : "中"));
  const riskHtml = safeBrief.risk_note
    ? `<div class="profile-portrait-risk">${escHtml(safeBrief.risk_note)}</div>`
    : "";
  briefCardEl.innerHTML = `
    <div class="profile-portrait-brief-surface">
      <div class="profile-portrait-brief-head">
        <div>
          <p class="profile-portrait-kicker">任务名片</p>
          <h4 class="profile-portrait-brief-title">${escHtml(safeBrief.title || "职业探索型支持者")}</h4>
          <p class="profile-portrait-brief-subtitle">${escHtml(safeBrief.subtitle || "当前画像会先收敛职业定位，再生成任务海报。")}</p>
        </div>
        <span class="profile-portrait-confidence">置信度 ${confidence}</span>
      </div>

      <div class="profile-portrait-brief-grid">
        <section class="profile-portrait-brief-section label-strong">
          <p class="profile-portrait-brief-label">你是谁</p>
          <p class="profile-portrait-brief-body">${escHtml(safeBrief.positioning || safeBrief.subtitle || "当前画像会优先总结你的职业定位。")}</p>
        </section>

        <section class="profile-portrait-brief-section">
          <p class="profile-portrait-brief-label">最像岗位</p>
          <div class="profile-portrait-chip-row">${roleChips || `<span class="profile-portrait-chip soft">职业探索中</span>`}</div>
        </section>

        <section class="profile-portrait-brief-section">
          <p class="profile-portrait-brief-label">你能承担什么任务</p>
          <p class="profile-portrait-brief-body muted">${escHtml(safeBrief.mission_line || "待生成")}</p>
        </section>

        <section class="profile-portrait-brief-section">
          <p class="profile-portrait-brief-label">为什么这么判断</p>
          <div class="profile-portrait-chip-row">${evidenceChips || `<span class="profile-portrait-chip soft">等待更多输入证据</span>`}</div>
        </section>

        <section class="profile-portrait-brief-section">
          <p class="profile-portrait-brief-label">下一步最该做什么</p>
          <p class="profile-portrait-brief-body muted">${escHtml(safeBrief.next_action || "先完成测评、简历或访谈中的任一输入。")}</p>
        </section>
      </div>

      ${riskHtml}
    </div>
  `;
}

function updateProfilePortraitControls(profile, roles, synthesis) {
  const portraitState = getProfilePortraitState();
  const brief = getResolvedProfilePortraitBrief(profile, roles, synthesis, portraitState);
  const hasGeneratedBrief = Boolean(portraitState?.brief && typeof portraitState.brief === "object");
  const renderBtn = document.getElementById("profilePortraitGenerateBtn");
  const refineBtn = document.getElementById("profilePortraitRefineBtn");
  const copyBtn = document.getElementById("profilePortraitCopyBtn");
  const backBtn = document.getElementById("profilePortraitBackBtn");
  const statusLead = document.getElementById("profilePortraitStatusLead");
  const hint = document.getElementById("profilePortraitHint");
  if (renderBtn) {
    renderBtn.disabled = profilePortraitTaskState.loading;
    renderBtn.textContent = profilePortraitTaskState.loading
      ? "生成中..."
      : portraitState?.image_url
        ? "重新生成海报"
        : portraitState?.status === "brief_ready"
          ? "重试海报"
        : "生成任务海报";
  }
  if (refineBtn) refineBtn.disabled = profilePortraitTaskState.loading || !hasGeneratedBrief;
  if (copyBtn) copyBtn.disabled = profilePortraitTaskState.loading || !hasGeneratedBrief;
  if (backBtn) backBtn.disabled = profilePortraitTaskState.loading;

  if (statusLead) {
    if (profilePortraitTaskState.loading) {
      statusLead.textContent = "正在生成任务名片与海报…";
    } else if (portraitState?.status === "brief_ready") {
      statusLead.textContent = "任务名片已生成，海报生成失败，请重试。";
    } else if (portraitState?.image_url) {
      statusLead.textContent = "";
    } else if (!hasGeneratedBrief) {
      statusLead.textContent = "";
    } else {
      statusLead.textContent = "";
    }
  }

  if (hint) {
    if (profilePortraitTaskState.loading) {
      hint.textContent = "正在融合测评、简历、访谈与目标方向，收敛职业定位并生成任务海报。";
    } else if (portraitState?.status === "brief_ready") {
      hint.textContent = portraitState?.image_error || "职业定位已生成，可直接重试海报。";
    } else if (portraitState?.image_url) {
      hint.textContent = `当前任务名片已聚焦到 ${brief?.primary_role || synthesis?.archetype?.name || "职业画像"}，可随时重绘海报或重新收敛定位。`;
    } else {
      hint.textContent = "";
    }
  }
}

async function generateProfilePortrait(options = {}) {
  if (profilePortraitTaskState.loading) return;
  if (!isAuthenticatedUser()) {
    showToast("请先登录", "登录后才能生成个人画像。", "warning", 1800);
    return;
  }
  const profile = appState.derivedProfile || deriveUnifiedProfile();
  const roles = Array.isArray(appState.matchingRoles) && appState.matchingRoles.length
    ? appState.matchingRoles
    : computeRoleMatches(profile);
  const synthesis = buildUnifiedProfileSynthesis(profile, roles);
  const context = buildProfilePortraitContext(profile, roles, synthesis);
  const hasPortraitSignals = Boolean(
    context.summary
    || context.archetype_name
    || context.target_direction
    || context.interview_summary
    || context.resume_summary
    || (context.resume_projects || []).length
    || (context.resume_roles || []).length
    || (context.identity_narrative && String(context.identity_narrative).trim())
    || (context.assessment_prose && String(context.assessment_prose).trim())
    || (context.extended_tests_prose && String(context.extended_tests_prose).trim())
  );
  if (!hasPortraitSignals) {
    showToast("画像信息不足", "先完成测评、简历或目标方向补充后再生成。", "warning", 2000);
    return;
  }

  startProfilePortraitLoading(options?.reuseBrief ? "rerender" : "rebuild");
  renderProfileWorkspace(profile, roles);
  try {
    const payload = await requestJson("/api/profile-portrait/generate", {
      method: "POST",
      body: {
        context,
        reuse_brief: Boolean(options?.reuseBrief)
      }
    });
    userWorkspaceState.scopedData.profile_portrait = payload?.data || null;
    userWorkspaceState.scopedDataLoaded.profile_portrait = true;
    const imageError = payload?.data?.image_error;
    if (imageError) {
      showToast("名片已更新", payload?.message || "职业定位已生成，但海报渲染失败。", "warning", 2600);
    } else {
      showToast("用户画像已生成", payload?.message || "任务名片与海报已经更新。", "success", 1800);
    }
  } catch (error) {
    showToast("生成失败", error.message || "用户画像生成失败。", "error", 2600);
  } finally {
    stopProfilePortraitLoading();
    renderProfileWorkspace(profile, roles);
  }
}

function rerenderProfilePortrait() {
  return generateProfilePortrait({ reuseBrief: true });
}

function regenerateProfilePortraitBrief() {
  return generateProfilePortrait({ reuseBrief: false });
}

function copyProfilePortraitSummary() {
  const portraitState = getProfilePortraitState();
  if (!(portraitState?.brief && typeof portraitState.brief === "object")) {
    showToast("没有可复制内容", "先生成任务名片后再复制。", "warning", 1800);
    return;
  }
  const profile = appState.derivedProfile || deriveUnifiedProfile();
  const roles = Array.isArray(appState.matchingRoles) && appState.matchingRoles.length
    ? appState.matchingRoles
    : computeRoleMatches(profile);
  const synthesis = buildUnifiedProfileSynthesis(profile, roles);
  const brief = getResolvedProfilePortraitBrief(profile, roles, synthesis, portraitState);
  return copyPlainText(buildProfilePortraitCopyText(brief), "定位文案已复制", "任务名片文案已经复制到剪贴板。");
}

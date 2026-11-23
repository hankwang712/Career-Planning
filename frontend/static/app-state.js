// 全局状态与常量（只含加载时不会调用函数的声明）
// 由原来的 app.js 拆出，仍是普通脚本、共享全局作用域；加载顺序见 templates/partials/app_scripts.html。

const appState = {
  currentSection: "dashboard",
  selectedJobs: [],
  profileComplete: false,
  reportGenerated: false,
  careerReport: null,
  careerReportState: null,
  careerReportTracker: null,
  careerReportVersions: [],
  careerReportCanonicalId: "",
  careerReportViewingHistorical: false,
  baseExploredJobs: 0,
  score: 0,
  profileCompletion: 0,
  timersStarted: false,
  lastGreetingKey: "",
  dashboardRadarChart: null,
  profileRadarChart: null,
  derivedProfile: null,
  matchingRoles: [],
  focusedRoleId: ""
};

const userWorkspaceState = {
  currentUser: null,
  authReadyPromise: null,
  llmConfigs: {
    career_interview: null,
    assessment_hub: null
  },
  scopedData: {
    career_interview: null,
    assessment_hub: null,
    resume_profile: null,
    career_report: null,
    profile_portrait: null,
    account_avatar: null,
    profile_snapshot: null,
    career_matching: null,
    news_context: null
  },
  scopedDataLoaded: {
    career_interview: false,
    assessment_hub: false,
    resume_profile: false,
    career_report: false,
    profile_portrait: false,
    account_avatar: false,
    profile_snapshot: false,
    career_matching: false,
    news_context: false
  }
};

let accountRequestEpoch = 0;

const inFlightGetRequests = new Map();

const jobNameMap = { ml: "Machine Learning Engineer", da: "Data Analyst", pm: "AI Product Manager", fe: "Frontend Engineer" };

const jobRateMap = { ml: 94, da: 91, pm: 87, fe: 86 };

const liveActivityTemplates = [
  "Model service latency dropped by 4%",
  "New job samples synced to recommendation engine",
  "Profile dimensions auto-calibrated",
  "Matching strategy generated fresh candidates",
  "Report module completed incremental update",
  "System detected new job trend changes"
];

const CAREER_INTERVIEW_DIMENSIONS = ["职业兴趣", "工作价值观", "学习方式", "沟通风格", "行动证据", "职业成熟度"];

const CAREER_INTERVIEW_RIASEC_LABELS = [
  { key: "realistic", label: "现实型" },
  { key: "investigative", label: "研究型" },
  { key: "artistic", label: "艺术型" },
  { key: "social", label: "社会型" },
  { key: "enterprising", label: "企业型" },
  { key: "conventional", label: "常规型" }
];

const CAREER_INTERVIEW_DIMENSION_PLAN = [
  {
    name: "职业兴趣",
    target: 2,
    prompts: [
      "如果不考虑专业限制，你最想长期投入哪类工作或行业？为什么？",
      "最近一次让你很投入、甚至停不下来的任务是什么？你最享受哪一部分？"
    ]
  },
  {
    name: "工作价值观",
    target: 2,
    prompts: [
      "你在选职业时最看重哪三件事？比如成长、收入、稳定、影响力或自由度。",
      "如果两份工作内容差不多，你通常会用什么标准做决定？"
    ]
  },
  {
    name: "学习方式",
    target: 2,
    prompts: [
      "遇到一个完全陌生的新方向时，你通常怎么学得最快？",
      "你更适合边做边学、先搭框架，还是先把资料研究透再动手？"
    ]
  },
  {
    name: "沟通风格",
    target: 2,
    prompts: [
      "团队协作时，你通常更像推动者、协调者，还是深度执行者？",
      "当你和别人意见不一致时，你一般会怎么表达并推动事情继续？"
    ]
  },
  {
    name: "行动证据",
    target: 2,
    prompts: [
      "讲一个你主动推进并真正做成的项目、活动或作品，最后结果怎么样？",
      "有没有一段经历能证明你对某个方向不是嘴上感兴趣，而是真的投入过？"
    ]
  },
  {
    name: "职业成熟度",
    target: 2,
    prompts: [
      "你对下一步是升学、求职还是转方向，现在的判断有多明确？",
      "如果今天就要开始准备下一阶段，你最先会行动的三件事是什么？"
    ]
  }
];

const CAREER_INTERVIEW_GUIDE_LIBRARY = {
  "职业兴趣": {
    headline: "先从真正吸引你的工作画面切入",
    body: "不要急着给自己贴职业标签。先选一个你愿意长期投入的场景，再补一句为什么。",
    guide: "比如：我会被 AI 产品这类工作吸引，因为它既需要理解用户，也能把想法真正落地。",
    scenes: [
      { title: "AI 产品", caption: "理解用户，再把想法落成真实功能", draft: "如果不考虑专业限制，我会先被 AI 产品这类工作吸引，因为它既需要理解用户，也能把想法真正落地。" },
      { title: "技术研发", caption: "搭系统、解问题、长期深挖", draft: "我会被技术研发这类工作吸引，因为我更享受搭结构、解决复杂问题，并愿意长期深挖一个方向。" },
      { title: "内容表达", caption: "写作、策划、传播与表达", draft: "我会被内容表达这类工作吸引，因为我喜欢把复杂信息整理清楚，再用更有感染力的方式传达出去。" },
      { title: "商业分析", caption: "用信息和数据支持判断", draft: "我会被商业分析这类工作吸引，因为我享受从信息和数据里找规律，并据此支持决策。" }
    ],
    chips: [
      { label: "互联网行业", draft: "我对互联网行业会更有兴趣，因为" },
      { label: "体制内", draft: "如果长期选择方向，我会认真考虑体制内，因为" },
      { label: "自由职业", draft: "自由职业会吸引我，因为我在意" },
      { label: "创业", draft: "创业这条路对我有吸引力，因为" },
      { label: "教育方向", draft: "教育相关方向吸引我，因为" },
      { label: "AI 应用", draft: "我会被 AI 应用相关方向吸引，因为" }
    ]
  },
  "工作价值观": {
    headline: "先说你真正看重什么，再谈职业选择",
    body: "很多人不是不知道能做什么，而是不清楚自己为什么想选。先把判断标准说清楚。",
    guide: "先选一个价值关键词，再补一句它为什么会影响你的职业选择。",
    scenes: [
      { title: "成长速度", caption: "更在意学习曲线和成长密度", draft: "选职业时，我会优先看成长速度，因为我希望在短时间内获得明显的学习和能力提升。" },
      { title: "稳定保障", caption: "更在意确定性与长期安全感", draft: "选职业时，我会优先看稳定保障，因为我希望未来的生活节奏和风险都更可控。" },
      { title: "收入回报", caption: "希望投入和回报更匹配", draft: "选职业时，收入回报会是很重要的标准，因为我希望自己的投入能得到明确反馈。" },
      { title: "影响力", caption: "希望工作本身能产生真实影响", draft: "我比较看重工作的影响力，因为我希望做的事情不仅完成任务，还能对别人产生价值。" }
    ],
    chips: [
      { label: "团队氛围", draft: "如果两份工作内容差不多，我会看团队氛围，因为" },
      { label: "自主空间", draft: "我会重视自主空间，因为" },
      { label: "发展平台", draft: "平台和发展空间对我重要，因为" },
      { label: "成就感", draft: "我会看这份工作是否有成就感，因为" },
      { label: "生活平衡", draft: "工作和生活平衡会影响我的选择，因为" },
      { label: "社会价值", draft: "我会在意工作的社会价值，因为" }
    ]
  },
  "学习方式": {
    headline: "用你最真实的学习路径来回答",
    body: "系统更想知道你怎么学得快、学得稳，而不是听一个标准答案。",
    guide: "先选一个你最常用的学习方式，再补一句这套方法为什么对你有效。",
    scenes: [
      { title: "边做边学", caption: "先上手实践，再边做边补", draft: "遇到陌生方向时，我通常更适合边做边学，因为先动手会让我更快理解关键问题。" },
      { title: "先搭框架", caption: "先建立结构，再逐步填细节", draft: "面对新方向时，我会先搭一个整体框架，因为这样我更容易判断该先学什么。" },
      { title: "找案例模仿", caption: "先看成熟案例，再拆方法", draft: "我经常通过看案例、模仿成熟做法来学，因为这样能更快建立正确的判断标准。" },
      { title: "找人请教", caption: "向有经验的人快速取经", draft: "遇到陌生问题时，我会优先找有经验的人请教，因为这样能少走很多弯路。" }
    ],
    chips: [
      { label: "自己查资料", draft: "我经常自己查资料推进学习，因为" },
      { label: "反复练习", draft: "我更依赖反复练习来掌握新内容，因为" },
      { label: "先理解原理", draft: "我会先弄懂原理再动手，因为" },
      { label: "快速复盘", draft: "我会通过快速复盘来加深学习，因为" },
      { label: "和别人讨论", draft: "我通过和别人讨论学得更快，因为" },
      { label: "项目驱动", draft: "如果有项目牵引，我会学得更快，因为" }
    ]
  },
  "沟通风格": {
    headline: "先把你在团队里更自然的角色说出来",
    body: "不用追求最强势或最标准的表达，只要说清你平时更像哪种人。",
    guide: "先选一个最像你的协作角色，再补一句在冲突或推进里你通常怎么做。",
    scenes: [
      { title: "推动事情前进", caption: "更像推进者，喜欢把事情往前拽", draft: "在团队里，我更像推动事情前进的人，因为我不太喜欢任务长期悬着，会主动把节奏往前带。" },
      { title: "协调多方资源", caption: "更像协调者，擅长对齐信息", draft: "我比较像协调者，因为我擅长在不同人的想法之间找平衡，并把信息对齐。" },
      { title: "深度执行交付", caption: "更像执行者，把结果做扎实", draft: "在协作里我更像深度执行者，因为我习惯把自己的部分做扎实，再推动整体结果稳定落地。" },
      { title: "用事实说服", caption: "更依赖逻辑、证据和结构", draft: "遇到分歧时，我更倾向用事实和逻辑说服别人，因为这样能让讨论更聚焦问题本身。" }
    ],
    chips: [
      { label: "先听再说", draft: "我通常会先听清楚再表达，因为" },
      { label: "喜欢当面沟通", draft: "我更喜欢当面沟通，因为" },
      { label: "写下来更清楚", draft: "很多时候我会先写下来再沟通，因为" },
      { label: "不怕冲突", draft: "遇到意见不一致时，我并不太怕冲突，因为" },
      { label: "重视边界", draft: "我在沟通里会比较重视边界，因为" },
      { label: "愿意补位", draft: "如果团队需要，我通常愿意补位，因为" }
    ]
  },
  "行动证据": {
    headline: "用一段做过的事情证明你的偏好",
    body: "比起“我想做什么”，更有价值的是“我曾经为这个方向真的投入过什么”。",
    guide: "先选一类最有代表性的经历，再补结果、任务和你承担的角色。",
    scenes: [
      { title: "课程项目", caption: "课堂内做过的完整任务", draft: "如果要举一个行动证据，我会先讲课程项目，因为那段经历最能体现我在真实任务里的投入方式。" },
      { title: "社团活动", caption: "组织、策划或协调过事情", draft: "我有一段比较能说明问题的社团活动经历，因为它能体现我在组织和推进上的真实状态。" },
      { title: "实习经历", caption: "在真实工作环境里承担过职责", draft: "我最能拿得出手的行动证据可能是实习经历，因为它直接体现了我在真实工作环境中的表现。" },
      { title: "个人作品", caption: "自己主动做出来的东西", draft: "如果要证明我不是停留在兴趣层面，我会讲一个个人作品，因为那是我主动投入并真的做出来的成果。" }
    ],
    chips: [
      { label: "比赛作品", draft: "我有一段比赛作品经历能说明这个方向，因为" },
      { label: "兼职副业", draft: "我做过一段兼职或副业，这能说明我的投入，因为" },
      { label: "主动发起", draft: "我主动发起过一件事，这能说明我的行动力，因为" },
      { label: "长期投入", draft: "我曾经持续投入过一段时间，这能说明我的稳定性，因为" },
      { label: "自己补技能", draft: "我曾经主动补过相关技能，因为" },
      { label: "拿到结果", draft: "那段经历最后拿到了明确结果，这说明" }
    ]
  },
  "职业成熟度": {
    headline: "把下一步怎么走说得更具体一点",
    body: "不用现在就完全确定，但最好能说清楚你最近会先做什么。",
    guide: "先选一件你最可能先行动的事，再补一句为什么它是优先级最高的。",
    scenes: [
      { title: "先找实习", caption: "用真实岗位快速验证方向", draft: "如果今天就开始准备下一阶段，我会先去找实习，因为我想先用真实岗位反馈来验证方向。" },
      { title: "先补作品", caption: "先把可展示成果做出来", draft: "我会先补作品或项目成果，因为如果没有能展示的内容，后面的投递和沟通都会比较弱。" },
      { title: "先定城市", caption: "先把地域和生活节奏想清楚", draft: "我会先把目标城市和生活方式想清楚，因为这会直接影响我后面的选择范围。" },
      { title: "先定方向", caption: "先收窄赛道，再集中准备", draft: "我会先收窄职业方向，因为方向不清楚的话，后面准备会很容易发散。" }
    ],
    chips: [
      { label: "考证准备", draft: "如果要马上行动，我可能会先做考证准备，因为" },
      { label: "信息访谈", draft: "我会先去做信息访谈，因为" },
      { label: "补简历", draft: "我会先把简历和经历整理清楚，因为" },
      { label: "投递尝试", draft: "我会先做一轮投递尝试，因为" },
      { label: "继续深造", draft: "继续深造也会进入我的考虑，因为" },
      { label: "转方向验证", draft: "如果转方向，我会先做小范围验证，因为" }
    ]
  }
};

const PROFILE_BASIC_FIELDS = ["major", "grade", "target_city", "target_direction"];

const PROFILE_BASIC_LABELS = {
  major: "专业",
  grade: "学历",
  target_city: "目标城市",
  target_direction: "目标方向"
};

const careerInterviewVoiceState = {
  recognition: null,
  listening: false,
  supported: null
};

/** 职业访谈输入框自动增高时的最大高度（与 CSS max-height: 14rem 对齐） */
const CAREER_INTERVIEW_INPUT_MAX_HEIGHT_PX = 224;

const CAREER_VOICE_MIC_SVG = `<svg class="career-voice-icon-svg" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>`;

const CAREER_VOICE_STOP_SVG = `<svg class="career-voice-icon-svg" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>`;

const resumeTaskState = {
  uploadInFlight: false,
  analyzeInFlight: false,
  analyzeTimer: null,
  analyzeFrameIndex: 0,
  analyzeStartedAt: 0,
  lastLoadingStageIndex: -1,
  forceInputView: false,
  jobInputExpanded: false,
  deckIndices: {},
  reportObserver: null
};

const reportResumeUiState = { pending: false, loaded: false, source: null, options: [], selectedId: "", error: "" };

let reportGenerationStarting = false;

let reportGenerationError = "";

const profilePortraitTaskState = {
  loading: false,
  stageIndex: 0,
  stageTimer: null,
  pulseTimer: null,
  pulseIndex: 0,
  startedAt: 0,
  mode: "render"
};

let careerInterviewGuideUserCountSeen = 0;

let careerInterviewGuideAutoCollapsedThisSession = false;

const careerNewsState = {
  initialized: false,
  displayLimit: 10,
  visibleCount: 10,
  pageSize: 10,
  /** 在当前已加载列表中的焦点下标（三卡轮排中心） */
  spotlightIndex: 0,
  items: [],
  autoPlayTimer: null,
  progressRaf: null,
  /** 10s 进度条起点（ms） */
  progressEpoch: 0
};

/** 当测评快照缺少长文时，用类型代码补一段「可读的」人格与兴趣侧写，避免折叠区只剩标签 */
const PORTRAIT_MBTI_TYPE_NARRATIVE = {
  INTJ: "建筑师型：内向直觉思维判断，偏好独立推演与长期架构；对低效与模糊容忍度低，习惯用模型与标准把复杂问题收口。",
  INTP: "思想家型：内向直觉思维感知，热衷概念拆解与可能性探索；更在意逻辑自洽，节奏上可能显得审慎或反复求证。",
  ENTJ: "指挥官型：外向直觉思维判断，擅长定目标、配资源、推团队执行；高压下仍保持决断，偏好清晰结构与可量化结果。",
  ENTP: "辩论家型：外向直觉思维感知，擅长联想、挑战假设与快速试错；适合需要创意碰撞与方案迭代的场景。",
  INFJ: "提倡者型：内向直觉情感判断，关注意义与人本价值；善于洞察他人动机，表达克制但立场坚定。",
  INFP: "调停者型：内向直觉情感感知，价值驱动、共情强；在冲突中倾向寻找共识，创作与叙事表达有优势。",
  ENFJ: "主人公型：外向直觉情感判断，善于激励与协调群体；在团队里常承担桥梁角色，关注氛围与共同目标。",
  ENFP: "竞选者型：外向直觉情感感知，热情、发散、善于连接人与想法；需要结构伙伴帮助落地与收尾。",
  ISTJ: "物流师型：内向感觉思维判断，可靠、重流程与责任边界；擅长把规则执行到位并持续优化细节。",
  ISFJ: "守卫者型：内向感觉情感判断，细致、体贴、稳定交付；在支持型岗位中表现突出。",
  ISTP: "鉴赏家型：内向感觉思维感知，动手与问题解决导向；偏好现场判断而非长篇讨论。",
  ISFP: "探险家型：内向感觉情感感知，审美与体验敏感；表达温和，重视真实感受与当下体验。",
  ESTJ: "总经理型：外向感觉思维判断，强执行与组织推进；擅长制度、排期与结果复盘。",
  ESFJ: "执政官型：外向感觉情感判断，关注协作与关系维护；适合需要客户/团队润滑的角色。",
  ESTP: "企业家型：外向感觉思维感知，行动快、应变强；适合高压现场与谈判推进。",
  ESFP: "表演者型：外向感觉情感感知，外向热情、感染力强；适合需要表达与现场互动的场景。"
};

const PORTRAIT_HOLLAND_LETTER_BLURB = {
  R: "实用型(R)：偏好工具、操作与具体产出，强调动手能力与现场感。",
  I: "研究型(I)：偏好分析、实验与理论推演，强调证据与模型。",
  A: "艺术型(A)：偏好创造、审美与表达，强调原创与风格。",
  S: "社会型(S)：偏好助人、教育与协作，强调沟通与影响力。",
  E: "企业型(E)：偏好说服、领导与资源整合，强调目标与推进。",
  C: "常规型(C)：偏好流程、数据与规范，强调稳定与可控。"
};

const PROFILE_PORTRAIT_LOADING_STAGES = [
  { title: "收敛定位", copy: "从测评、简历与访谈里收敛主角色和职业定位。" },
  { title: "生成名片", copy: "把定位压缩成可对外展示的任务名片结构。" },
  { title: "生成海报", copy: "生成人物海报。" }
];

/** 各阶段轮换的细粒度状态，让用户感知后台仍在工作 */
const PROFILE_PORTRAIT_STAGE_ACTIVITY = [
  ["正在读取测评、简历与访谈信号…", "合并目标方向与岗位线索…", "整理叙事与证据标签…", "计算主角色与置信度…"],
  ["生成任务名片 brief 结构…", "压缩「你是谁」与下一步建议…", "预组装图像提示词约束…", "校验白底页面展示字段…"],
  ["请求图像模型…", "应用 3:4 构图与半写实风格…", "优化光影与职业场景…", "写入海报资源…"]
];

/** 与「多智能体图片」PNG 对应（报告合成等无图则回退 SVG） */
const REPORT_AGENT_IMAGE_URL = {
  resume_analysis: "/static/img/multi-agent/resume-analyst.png",
  job_analysis: "/static/img/multi-agent/role-match.png",
  recruitment_search: "/static/img/multi-agent/industry-analyst.png",
  career_decision: "/static/img/multi-agent/career-advisor.png",
  action_planning: "/static/img/multi-agent/path-planner.png",
  report_writer: "/static/img/multi-agent/report-writer.png"
};

const REPORT_AGENT_FLOW = [
  { key: "resume_analysis", title: "简历分析", role: "ResumeAnalysisAgent", detail: "诊断简历证据与待补充事实", icon: "file", x: 20, y: 56 },
  { key: "job_analysis", title: "岗位分析", role: "JobAnalysisAgent", detail: "并行分析各目标岗位，核对原文引证", icon: "match", x: 20, y: 326 },
  { key: "recruitment_search", title: "招聘雷达", role: "RecruitmentSearchAgent", detail: "检索招聘汇总与企业官网，优先核验相关岗位", icon: "trend", x: 20, y: 596 },
  { key: "career_decision", title: "职业决策", role: "CareerDecisionAgent", detail: "汇总分析结果，对照岗位与候选人事实", icon: "target", x: 350, y: 326 },
  { key: "review", title: "补充与确认", role: "用户确认", detail: "回答追问，选择目标和时间安排", icon: "verify", x: 670, y: 326 },
  { key: "action_planning", title: "行动规划", role: "ActionPlanningAgent", detail: "安排依赖、工时、交付物与验收标准", icon: "route", x: 990, y: 326 },
  { key: "report_writer", title: "报告合成", role: "结果整理", detail: "整理已校验结果供阅读与导出", icon: "report", x: 1310, y: 326 }
];

const reportWizardUiState = { stage: 2, runtimeKey: "", started: false, manual: false };

const reportAgentConsoleState = { selected: "", collapsed: false, tab: "overview", nodes: [], scope: "", snapshot: null, loading: false, loadedVersion: "", error: "", retrying: false };

const REPORT_AGENT_INPUTS = {
  resume_analysis: ["上传的简历与补充事实", []],
  job_analysis: ["目标岗位与岗位描述", []],
  recruitment_search: ["目标方向与招聘检索条件", []],
  career_decision: ["简历证据、岗位要求与招聘结果", ["resume_analysis", "job_analysis", "recruitment_search"]],
  review: ["职业决策与待确认问题", ["career_decision"]],
  action_planning: ["职业决策与已确认的目标、时间条件", ["career_decision"]],
  report_writer: ["已校验的分析结果与行动计划", ["career_decision", "action_planning"]]
};

const reportAgentCamera = { scope: "", initialized: false, autoFit: true, scale: 1, x: 0, y: 0, width: 0, height: 0, drag: null, suppressClickUntil: 0 };

let reportAgentMapResizeObserver;

const CAREER_REPORT_POLL_MS = 4000;

let careerReportPollTimer = null;

let careerReportPollJobId = "";

let reportWorkflowSnapshot = null;

let reportWorkflowLoading = "";

let unifiedRefreshScheduled = false;

let unifiedRefreshRunning = false;

let unifiedRefreshPending = false;

// --------------------------------------------------
//  弹窗：打开 / 关闭
// --------------------------------------------------
// 福利关键词 → emoji 映射
const welfareIcons = {
  "年终奖": "★",
  "五险一金": "保",
  "弹性工作": "时",
  "远程办公": "远",
  "股票期权": "股",
  "带薪年假": "假",
  "团队旅游": "游",
  "员工旅游": "游",
  "餐补": "餐",
  "包吃": "食",
  "零食下午茶": "茶",
  "定期体检": "检",
  "补充医疗保险": "医",
  "节日福利": "礼",
  "通讯补贴": "讯",
  "交通补贴": "交",
  "包住": "住",
  "提供住宿": "住",
  "绩效奖金": "奖",
  "周末双休": "休",
  "大小周": "周"
};

// 在 dashboard 显示时初始化动画

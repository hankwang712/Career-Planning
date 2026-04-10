const appState = {
  currentSection: "dashboard",
  selectedJobs: [],
  profileComplete: false,
  matchingComplete: false,
  reportGenerated: false,
  careerReport: null,
  careerReportState: null,
  careerReportTracker: null,
  careerReportVersions: [],
  careerReportCanonicalId: "",
  careerReportViewingHistorical: false,
  notifications: 3,
  baseExploredJobs: 0,
  score: 0,
  profileCompletion: 0,
  timersStarted: false,
  lastGreetingKey: "",
  lastJobFilterKey: "",
  dashboardRadarChart: null,
  profileRadarChart: null,
  derivedProfile: null,
  matchingRoles: [],
  focusedRoleId: "",
  weights: { "特质匹配": 30, "能力匹配": 40, "专业匹配": 15, "意愿匹配": 15 }
};

const DASHBOARD_PORTRAIT_ASSETS = {
  male: "/app_data/man.png",
  female: "/app_data/woman.png"
};

// 岗位数据（从 /api/jobs 加载）
let allJobsData = [];
let filteredJobsData = [];
let jobCurrentPage = 1;
const JOB_PAGE_SIZE  = 12;
let fuseIndex = null;

let jobsGeoAssetsPromise = null;
let careerGraphAssetsPromise = null;
const JOBS_CACHE_TTL_MS = 15 * 60 * 1000;
const JOBS_CACHE_VERSION = "v4";
const JOBS_CITIES_CACHE_KEY = `ms_jobs_cities_${JOBS_CACHE_VERSION}`;
const JOBS_LIST_CACHE_PREFIX = `ms_jobs_list_${JOBS_CACHE_VERSION}_`;
const JOBS_DETAIL_CACHE_PREFIX = `ms_jobs_detail_${JOBS_CACHE_VERSION}_`;

const authConfig = {
  allowSelfRegister: false,
  superUser: {
    username: "system",
    password: "123456",
    role: "super_admin",
    displayName: "System Admin"
  }
};

function getApiBase() {
  const raw = String(window.__API_BASE__ || "").trim();
  return raw.replace(/\/+$/, "");
}

function resolveApiUrl(path) {
  const target = String(path || "").trim();
  if (!target) return target;
  if (/^https?:\/\//i.test(target)) return target;
  const base = getApiBase();
  if (!base) return target;
  if (target.startsWith("/")) return `${base}${target}`;
  return `${base}/${target}`;
}

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
    profile_portrait: null
  },
  scopedDataLoaded: {
    career_interview: false,
    assessment_hub: false,
    resume_profile: false,
    career_report: false,
    profile_portrait: false
  }
};
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

const COMMUNITY_FORUM_BOARD_META = {
  all: { label: "全部", icon: "全", chip: "bg-slate-100 text-slate-700 border-slate-200", soft: "bg-slate-50 text-slate-600" },
  "面经互助": { label: "面经互助", icon: "面", chip: "bg-rose-100 text-rose-700 border-rose-200", soft: "bg-rose-50 text-rose-700" },
  "简历门诊": { label: "简历门诊", icon: "简", chip: "bg-sky-100 text-sky-700 border-sky-200", soft: "bg-sky-50 text-sky-700" },
  "实习内推": { label: "实习内推", icon: "推", chip: "bg-amber-100 text-amber-700 border-amber-200", soft: "bg-amber-50 text-amber-700" },
  "选岗热议": { label: "选岗热议", icon: "岗", chip: "bg-emerald-100 text-emerald-700 border-emerald-200", soft: "bg-emerald-50 text-emerald-700" },
  "职场日常": { label: "职场日常", icon: "聊", chip: "bg-violet-100 text-violet-700 border-violet-200", soft: "bg-violet-50 text-violet-700" }
};

const communityForumState = {
  loading: false,
  loaded: false,
  posts: [],
  boards: [],
  hotTags: [],
  stats: {
    threads: 0,
    today_posts: 0,
    active_users: 0,
    unanswered: 0
  },
  board: "all",
  sort: "hot",
  query: "",
  selectedPostId: "",
  viewedIds: {},
  view: "list"
};

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
const PROFILE_FLOW_STEPS = [1, 2, 3, 4];
const profileFlowState = {
  currentStep: 1,
  skippedSteps: [],
  completedSteps: [],
  touched: false
};
const ROLE_LIBRARY = [
  {
    id: "java_backend",
    name: "Java 后端开发",
    category: "互联网/科技",
    majors: ["计算机", "软件", "信息", "网络", "智能"],
    requiredSkills: ["编程", "数据库", "Spring"],
    certificates: ["软考"],
    requirements: { professional: 85, innovation: 60, learning: 90, stress_tolerance: 80, communication: 50, internship: 80, execution: 85 },
    recommendedHolland: ["I", "R", "C"],
    recommendedMbti: ["ISTJ", "INTJ"],
    workValues: ["稳定成长", "技术深耕"],
    path: "后端开发 → 高级开发 → 架构师"
  },
  {
    id: "product_manager",
    name: "产品经理",
    category: "互联网/科技",
    majors: ["不限", "计算机", "智能", "管理"],
    requiredSkills: ["需求分析", "原型设计", "数据分析"],
    certificates: ["NPDP", "PMP"],
    requirements: { professional: 75, innovation: 90, learning: 80, stress_tolerance: 90, communication: 90, internship: 85, execution: 80 },
    recommendedHolland: ["E", "I", "S"],
    recommendedMbti: ["ENTJ", "ENFP", "INTJ"],
    workValues: ["成长空间", "影响力", "协作成就"],
    path: "产品助理 → 产品经理 → 高级产品经理"
  },
  {
    id: "data_analyst",
    name: "数据分析师",
    category: "数据与商业分析",
    majors: ["统计", "计算机", "经管", "数学", "智能"],
    requiredSkills: ["SQL", "Python", "BI"],
    certificates: ["CDA"],
    requirements: { professional: 80, innovation: 70, learning: 90, stress_tolerance: 70, communication: 60, internship: 65, execution: 75 },
    recommendedHolland: ["I", "C", "S"],
    recommendedMbti: ["INTJ", "ISTJ"],
    workValues: ["问题解决", "稳定成长", "数据驱动"],
    path: "数据分析师 → 高级分析师 → 数据策略"
  },
  {
    id: "new_media_ops",
    name: "新媒体运营",
    category: "内容与增长",
    majors: ["不限", "新闻", "传播", "中文", "设计"],
    requiredSkills: ["内容策划", "剪辑", "运营分析"],
    certificates: ["营销师"],
    requirements: { professional: 65, innovation: 80, learning: 70, stress_tolerance: 60, communication: 80, internship: 60, execution: 70 },
    recommendedHolland: ["A", "E", "S"],
    recommendedMbti: ["ENFP", "ESFP"],
    workValues: ["创造表达", "传播影响", "节奏灵活"],
    path: "运营专员 → 内容负责人 → 增长运营"
  },
  {
    id: "hr_specialist",
    name: "人力资源专员",
    category: "组织与服务",
    majors: ["管理", "心理", "不限"],
    requiredSkills: ["招聘", "沟通", "劳动法规"],
    certificates: ["人力资源管理师"],
    requirements: { professional: 65, innovation: 50, learning: 60, stress_tolerance: 70, communication: 95, internship: 65, execution: 72 },
    recommendedHolland: ["S", "C", "E"],
    recommendedMbti: ["ESFJ", "ENFJ"],
    workValues: ["助人成长", "组织支持", "关系协作"],
    path: "HR 助理 → HRBP/招聘专员 → 人力负责人"
  },
  {
    id: "sales_trainee",
    name: "销售管培生",
    category: "商业拓展",
    majors: ["不限"],
    requiredSkills: ["谈判", "客户管理", "目标推进"],
    certificates: [],
    requirements: { professional: 55, innovation: 60, learning: 80, stress_tolerance: 95, communication: 95, internship: 80, execution: 82 },
    recommendedHolland: ["E", "S", "A"],
    recommendedMbti: ["ESTJ", "ENTJ"],
    workValues: ["回报激励", "竞争成就", "成长速度"],
    path: "管培生 → 销售经理 → 区域负责人"
  },
  {
    id: "uiux_designer",
    name: "UI/UX 设计师",
    category: "设计与体验",
    majors: ["设计", "计算机", "数字媒体", "不限"],
    requiredSkills: ["界面设计", "交互设计", "用户研究"],
    certificates: ["Adobe"],
    requirements: { professional: 72, innovation: 95, learning: 80, stress_tolerance: 70, communication: 70, internship: 75, execution: 68 },
    recommendedHolland: ["A", "I", "R"],
    recommendedMbti: ["INFP", "ENFP"],
    workValues: ["审美表达", "用户体验", "作品成就"],
    path: "设计师 → 高级设计师 → 体验负责人"
  },
  {
    id: "finance_audit",
    name: "财务/审计助理",
    category: "财务与风控",
    majors: ["会计", "财务", "审计", "经济"],
    requiredSkills: ["会计准则", "税务", "报表"],
    certificates: ["初级会计", "CPA"],
    requirements: { professional: 80, innovation: 40, learning: 70, stress_tolerance: 80, communication: 50, internship: 80, execution: 90 },
    recommendedHolland: ["C", "I", "E"],
    recommendedMbti: ["ISTJ", "ISFJ"],
    workValues: ["稳定性", "规范流程", "准确性"],
    path: "财务助理 → 审计/财务专员 → 财务经理"
  },
  {
    id: "project_assistant",
    name: "项目管理助理",
    category: "组织与项目",
    majors: ["不限", "管理", "工程", "计算机"],
    requiredSkills: ["进度管理", "风险跟踪", "协调沟通"],
    certificates: ["PMP"],
    requirements: { professional: 68, innovation: 50, learning: 70, stress_tolerance: 80, communication: 90, internship: 65, execution: 88 },
    recommendedHolland: ["E", "S", "C"],
    recommendedMbti: ["ENTJ", "ESTJ"],
    workValues: ["组织推进", "交付成果", "节奏掌控"],
    path: "项目助理 → 项目经理 → PMO"
  },
  {
    id: "content_editor",
    name: "内容创作/编辑",
    category: "内容与表达",
    majors: ["文史", "新闻", "中文", "传播", "不限"],
    requiredSkills: ["写作", "策划", "选题"],
    certificates: ["出版资格"],
    requirements: { professional: 68, innovation: 90, learning: 60, stress_tolerance: 60, communication: 60, internship: 60, execution: 70 },
    recommendedHolland: ["A", "S", "I"],
    recommendedMbti: ["INFP", "INFJ"],
    workValues: ["表达自由", "内容影响", "持续创作"],
    path: "编辑 → 内容策划 → 内容负责人"
  }
];

function getDefaultProfileBasics() {
  return {
    gender: "",
    major: "",
    grade: "",
    target_city: "",
    target_direction: ""
  };
}

const careerInterviewState = {
  started: false,
  loading: false,
  isComplete: false,
  messages: [],
  result: null,
  completionScore: 0,
  focusDimension: "职业兴趣",
  profileBasics: getDefaultProfileBasics(),
  helperAnchor: ""
};

const careerInterviewVoiceState = {
  recognition: null,
  listening: false,
  supported: null
};

careerInterviewState.dimensionProgress = [];

function formatDateCN(date, withTime = false) {
  const y = date.getFullYear();
  const m = date.getMonth() + 1;
  const d = date.getDate();
  if (!withTime) return `${y} 年${m} 月${d} 日`;
  const hh = String(date.getHours()).padStart(2, "0");
  const mm = String(date.getMinutes()).padStart(2, "0");
  return `${y} 年${m} 月${d} 日 ${hh}:${mm}`;
}

function formatClock(date) {
  const hh = String(date.getHours()).padStart(2, "0");
  const mm = String(date.getMinutes()).padStart(2, "0");
  const ss = String(date.getSeconds()).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}

function formatRelativeTimeCN(value) {
  const ts = Number(value || 0);
  if (!ts) return "刚刚";
  const diff = Math.max(0, Math.floor(Date.now() / 1000) - ts);
  if (diff < 60) return "刚刚";
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} 天前`;
  try {
    return new Date(ts * 1000).toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
  } catch (_) {
    return "较早";
  }
}

function addMonths(date, count) {
  const d = new Date(date.getTime());
  d.setMonth(d.getMonth() + count);
  return d;
}

function showAuthMessage(message, type = "info") {
  const el = document.getElementById("authMessage");
  if (!el) return;
  el.textContent = message;
  el.className = "auth-message";
  if (type === "success" || type === "error" || type === "warning") el.classList.add(type);
}

function showToast(title, text = "", type = "info", duration = 2200) {
  const container = document.getElementById("toastContainer");
  if (!container) return;
  const toast = document.createElement("div");
  toast.className = `toast-item ${type}`;
  toast.innerHTML = `<p class="toast-title">${title}</p>${text ? `<p class="toast-text">${text}</p>` : ""}`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.classList.add("removing");
    setTimeout(() => toast.remove(), 220);
  }, duration);
}

function loadScriptOnce(src, key) {
  return new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[data-script-key="${key}"]`);
    if (existing) {
      if (existing.dataset.loaded === "true") {
        resolve();
        return;
      }
      existing.addEventListener("load", () => resolve(), { once: true });
      existing.addEventListener("error", () => reject(new Error(`Failed to load ${key}`)), { once: true });
      return;
    }

    const script = document.createElement("script");
    script.src = src;
    script.async = false;
    script.dataset.scriptKey = key;
    script.addEventListener("load", () => {
      script.dataset.loaded = "true";
      resolve();
    }, { once: true });
    script.addEventListener("error", () => reject(new Error(`Failed to load ${key}`)), { once: true });
    document.body.appendChild(script);
  });
}

async function ensureJobsGeoAssets() {
  if (window.echarts && typeof window.initializeJobGeoInsights === "function") return;
  if (!jobsGeoAssetsPromise) {
    jobsGeoAssetsPromise = (async () => {
      await loadScriptOnce("/static/vendor/echarts.min.js?v=20260319-lazy-geo", "echarts");
      await loadScriptOnce("/static/vendor/china.js?v=20260318-geo", "china-map");
      await loadScriptOnce("/static/jobs-geo.js?v=20260408-geo-salary-ui-v1", "jobs-geo");
    })().catch((error) => {
      jobsGeoAssetsPromise = null;
      throw error;
    });
  }
  return jobsGeoAssetsPromise;
}

function getCareerGraphMatchingApi() {
  return window.__careerGraphMatchingApi || null;
}

async function ensureCareerGraphMatchingAssets() {
  if (getCareerGraphMatchingApi()) return getCareerGraphMatchingApi();
  if (!careerGraphAssetsPromise) {
    careerGraphAssetsPromise = (async () => {
      if (!window.d3) {
        await loadScriptOnce("/static/vendor/d3.v7.min.js?v=20260404-kb-v1", "d3");
      }
      await loadScriptOnce("/static/career-graph-matching.js?v=20260408-kb-pathdeck-v1", "career-graph-matching");
      const api = getCareerGraphMatchingApi();
      if (!api) {
        throw new Error("职业图谱模块已加载，但没有成功完成初始化");
      }
      return api;
    })().catch((error) => {
      careerGraphAssetsPromise = null;
      throw error;
    });
  }
  return careerGraphAssetsPromise;
}

window.startCareerGraphMatching = function startCareerGraphMatching(force = false) {
  return ensureCareerGraphMatchingAssets()
    .then((api) => api?.startMatch?.({ force }))
    .catch((error) => {
      showToast("职业匹配加载失败", error.message, "error", 2200);
    });
};

window.focusCareerGraphNodeById = function focusCareerGraphNodeById(nodeId) {
  return ensureCareerGraphMatchingAssets()
    .then((api) => api?.focusNode?.(nodeId))
    .catch((error) => {
      showToast("图谱加载失败", error.message, "warning", 2200);
    });
};

window.resetCareerGraphLayout = function resetCareerGraphLayout() {
  return ensureCareerGraphMatchingAssets()
    .then((api) => api?.resetLayout?.())
    .catch((error) => {
      showToast("图谱布局重置失败", error.message, "warning", 2200);
    });
};

function getDefaultCareerInterviewConfig() {
  return {
    base_url: "",
    api_key: "",
    model: "gpt-4o-mini"
  };
}

function safeJsonParse(raw, fallback) {
  try {
    return JSON.parse(raw);
  } catch (_) {
    return fallback;
  }
}

function getCurrentUser() {
  return userWorkspaceState.currentUser;
}

function isAuthenticatedUser() {
  return Boolean(userWorkspaceState.currentUser);
}

function isSuperAdminUser() {
  return userWorkspaceState.currentUser?.role === "super_admin";
}

function emitAuthStateChange() {
  window.dispatchEvent(new CustomEvent("app:auth-changed", {
    detail: {
      user: userWorkspaceState.currentUser
    }
  }));
}

async function requestJson(url, options = {}) {
  const method = String(options.method || "GET").toUpperCase();
  const headers = { ...(options.headers || {}) };
  let body = options.body;
  if (body && typeof body !== "string") {
    headers["Content-Type"] = headers["Content-Type"] || "application/json";
    body = JSON.stringify(body);
  }
  const isGetWithoutBody = method === "GET" && !body;
  const dedupeKey = isGetWithoutBody ? `${method}::${url}::${JSON.stringify(headers)}` : "";
  if (isGetWithoutBody && inFlightGetRequests.has(dedupeKey)) {
    return inFlightGetRequests.get(dedupeKey);
  }

  const runner = (async () => {
    const response = await fetch(resolveApiUrl(url), {
      ...options,
      method,
      headers,
      body,
      credentials: options.credentials || "include"
    });

    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (response.status === 401) {
        userWorkspaceState.currentUser = null;
        userWorkspaceState.scopedData.career_interview = null;
        userWorkspaceState.scopedData.assessment_hub = null;
        userWorkspaceState.scopedData.resume_profile = null;
        userWorkspaceState.scopedData.career_report = null;
        userWorkspaceState.scopedData.profile_portrait = null;
        userWorkspaceState.scopedDataLoaded.career_interview = false;
        userWorkspaceState.scopedDataLoaded.assessment_hub = false;
        userWorkspaceState.scopedDataLoaded.resume_profile = false;
        userWorkspaceState.scopedDataLoaded.career_report = false;
        userWorkspaceState.scopedDataLoaded.profile_portrait = false;
        if (typeof lockApp === "function") lockApp();
        emitAuthStateChange();
      }
      const error = new Error(payload.message || `请求失败：${response.status}`);
      error.status = response.status;
      throw error;
    }
    return payload;
  })();

  if (isGetWithoutBody) {
    inFlightGetRequests.set(dedupeKey, runner);
    runner.finally(() => {
      inFlightGetRequests.delete(dedupeKey);
    });
  }
  return runner;
}

function getDefaultScopedData(scope) {
  return scope === "career_interview" ? null : null;
}

async function fetchScopedUserState(scope, force = false) {
  if (!force && userWorkspaceState.scopedDataLoaded?.[scope]) {
    return userWorkspaceState.scopedData[scope];
  }
  if (!isAuthenticatedUser()) return getDefaultScopedData(scope);
  const payload = await requestJson(`/api/user-state/${scope}`);
  userWorkspaceState.scopedData[scope] = payload.data ?? null;
  if (userWorkspaceState.scopedDataLoaded && Object.prototype.hasOwnProperty.call(userWorkspaceState.scopedDataLoaded, scope)) {
    userWorkspaceState.scopedDataLoaded[scope] = true;
  }
  return userWorkspaceState.scopedData[scope];
}

async function loadProfilePortraitState(force = false) {
  if (!isAuthenticatedUser()) return null;
  const data = await fetchScopedUserState("profile_portrait", force);
  userWorkspaceState.scopedData.profile_portrait = data ?? null;
  userWorkspaceState.scopedDataLoaded.profile_portrait = true;
  return userWorkspaceState.scopedData.profile_portrait;
}

async function saveScopedUserState(scope, data) {
  if (!isAuthenticatedUser()) return null;
  await requestJson(`/api/user-state/${scope}`, {
    method: "PUT",
    body: { data }
  });
  userWorkspaceState.scopedData[scope] = data ?? null;
  if (userWorkspaceState.scopedDataLoaded && Object.prototype.hasOwnProperty.call(userWorkspaceState.scopedDataLoaded, scope)) {
    userWorkspaceState.scopedDataLoaded[scope] = true;
  }
  return userWorkspaceState.scopedData[scope];
}

async function requestFormData(url, formData, options = {}) {
  const response = await fetch(resolveApiUrl(url), {
    method: options.method || "POST",
    body: formData,
    credentials: options.credentials || "include"
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(payload.message || `请求失败：${response.status}`);
    error.status = response.status;
    throw error;
  }
  return payload;
}

function formatUnixTime(ts) {
  if (!ts) return "--";
  try {
    return new Date(Number(ts) * 1000).toLocaleString("zh-CN", { hour12: false });
  } catch (_) {
    return "--";
  }
}

function emptyResumeProfile() {
  return {
    status: "empty",
    profile: null,
    file_name: "",
    file_size: 0,
    file_type: "",
    uploaded_at: null,
    analyzed_at: null,
    analysis_meta: {},
    analysis_result: "",
    analysis_html: "",
    job_description: "",
    matcher: {},
    structured_resume: null,
    structured_job: null,
    error_message: ""
  };
}

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

const profilePortraitTaskState = {
  loading: false,
  stageIndex: 0,
  stageTimer: null,
  mode: "render"
};

function setResumeProgress(kind, percent, label = "", active = false) {
  const wrap = document.getElementById(kind === "upload" ? "resumeUploadProgressWrap" : "resumeAnalyzeProgressWrap");
  const bar = document.getElementById(kind === "upload" ? "resumeUploadProgressBar" : "resumeAnalyzeProgressBar");
  const text = document.getElementById(kind === "upload" ? "resumeUploadProgressText" : "resumeAnalyzeProgressText");
  if (!wrap || !bar || !text) return;
  const safePercent = Math.max(0, Math.min(100, Number(percent || 0)));
  wrap.classList.remove("hidden");
  bar.style.width = `${safePercent}%`;
  text.textContent = label || `${Math.round(safePercent)}%`;
  if (active) {
    bar.classList.add("animate-pulse");
  } else {
    bar.classList.remove("animate-pulse");
  }
}

function setResumeLoadingText(text) {
  const el = document.getElementById("resumeJudgeLoadingText");
  if (!el) return;
  el.textContent = String(text || "系统正在提取简历文本并组织诊断结构，请稍候。");
}

function hideResumeProgress(kind) {
  const wrap = document.getElementById(kind === "upload" ? "resumeUploadProgressWrap" : "resumeAnalyzeProgressWrap");
  if (wrap) wrap.classList.add("hidden");
}

function setResumeLoadingStage(stage) {
  const stageMap = {
    queued: 0,
    extract_resume: 0,
    structured_resume: 1,
    job_context: 2,
    resume_review: 3,
    hr_judge: 3,
    done: 3,
    failed: 3
  };
  const parsedIndex = typeof stage === "number" ? stage : (stageMap[String(stage || "").trim()] ?? 0);
  const safeIndex = Math.max(0, Math.min(3, Number(parsedIndex || 0)));
  const activeIndex = Math.max(resumeTaskState.lastLoadingStageIndex, safeIndex);
  resumeTaskState.lastLoadingStageIndex = activeIndex;
  document.querySelectorAll(".resume-judge-loading-step").forEach((node) => {
    const index = Number(node.dataset.stepIndex || 0);
    node.classList.toggle("active", index === activeIndex);
    node.classList.toggle("done", index < activeIndex);
  });
}

function syncResumeJudgeFlow(state) {
  const inputSection = document.getElementById("resumeJudgeInputSection");
  const loadingSection = document.getElementById("resumeJudgeLoadingSection");
  const reportSection = document.getElementById("resumeJudgeReportSection");
  if (!inputSection || !loadingSection || !reportSection) return;
  const status = String(state?.status || "").trim();
  const hasReport = status === "analyzed" && (String(state?.analysis_result || "").trim() || String(state?.analysis_html || "").trim());
  const showLoading = resumeTaskState.analyzeInFlight || status === "analyzing";
  const showReport = !showLoading && hasReport && !resumeTaskState.forceInputView;
  const showInput = !showLoading && !showReport;
  inputSection.classList.toggle("hidden", !showInput);
  loadingSection.classList.toggle("hidden", !showLoading);
  reportSection.classList.toggle("hidden", !showReport);
}

function showResumeJudgeInputView() {
  resumeTaskState.forceInputView = true;
  syncResumeJudgeFlow(getResumeProfileFromCache());
}

function updateResumeActionButtons() {
  const uploadBtn = document.getElementById("resumeUploadBtn");
  const analyzeBtn = document.getElementById("resumeAnalyzeBtn");
  const deleteBtn = document.getElementById("resumeDeleteBtn");
  const busy = resumeTaskState.uploadInFlight || resumeTaskState.analyzeInFlight;
  if (uploadBtn) uploadBtn.disabled = busy;
  if (analyzeBtn) analyzeBtn.disabled = busy;
  if (deleteBtn) deleteBtn.disabled = busy;
}

function syncResumeJobInputFrame() {
  const input = document.getElementById("resumeJobDescriptionInput");
  const button = document.getElementById("resumeJobInputToggleBtn");
  const expanded = Boolean(resumeTaskState.jobInputExpanded);
  if (input) {
    input.rows = expanded ? 12 : 7;
    input.classList.toggle("expanded", expanded);
  }
  if (button) {
    button.textContent = expanded ? "收起输入区" : "展开输入区";
  }
}

function toggleResumeJobInput(forceExpanded = null) {
  if (typeof forceExpanded === "boolean") {
    resumeTaskState.jobInputExpanded = forceExpanded;
  } else {
    resumeTaskState.jobInputExpanded = !resumeTaskState.jobInputExpanded;
  }
  syncResumeJobInputFrame();
}

function startAnalyzeProgressTicker() {
  stopAnalyzeProgressTicker();
  resumeTaskState.analyzeStartedAt = Date.now();
  resumeTaskState.analyzeFrameIndex = 0;
  resumeTaskState.lastLoadingStageIndex = -1;
  setResumeProgress("analyze", 100, "正在启动简历分析 · 0s", true);
  setResumeLoadingText("系统正在提取简历文本并组织诊断结构，请稍候。");
  setResumeLoadingStage("queued");
  resumeTaskState.analyzeTimer = setInterval(() => {
    if (!resumeTaskState.analyzeInFlight) return;
    const elapsedSec = Math.max(0, Math.floor((Date.now() - resumeTaskState.analyzeStartedAt) / 1000));
    const stageLabels = ["提取简历文本", "结构化简历", "理解岗位文本", "生成分析结论"];
    const stage = stageLabels[Math.max(0, resumeTaskState.lastLoadingStageIndex)];
    setResumeProgress("analyze", 100, `${stage} · ${elapsedSec}s`, true);
    setResumeLoadingText(`${stage} · 已运行 ${elapsedSec}s`);
  }, 900);
}

function stopAnalyzeProgressTicker() {
  if (resumeTaskState.analyzeTimer) {
    clearInterval(resumeTaskState.analyzeTimer);
    resumeTaskState.analyzeTimer = null;
  }
}

function sleepMs(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function applyResumeAnalyzeRuntimeStatus(job, elapsedSec) {
  const analyzeStatus = document.getElementById("resumeAnalyzeStatus");
  const analyzeMeta = document.getElementById("resumeAnalyzeMeta");
  const stage = String(job?.stage || "").trim();
  const detail = String(job?.stage_detail || "").trim();
  const stageLabelMap = {
    queued: "任务排队中",
    extract_resume: "提取简历文本",
    structured_resume: "结构化简历",
    job_context: "理解岗位文本",
    resume_review: "生成简历诊断",
    hr_judge: "生成分析结论",
    done: "分析完成",
    failed: "分析失败"
  };
  const stageLabel = detail || stageLabelMap[stage] || "分析中";
  if (analyzeStatus) analyzeStatus.textContent = stage === "queued" ? "排队中" : "分析中";
  if (analyzeMeta) analyzeMeta.textContent = `${stageLabel} · 已运行 ${elapsedSec}s`;
  setResumeProgress("analyze", 100, `${stageLabel} · ${elapsedSec}s`, true);
  setResumeLoadingText(`${stageLabel} · 已运行 ${elapsedSec}s`);
  setResumeLoadingStage(stage);
}

function getResumeProfileFromCache() {
  return userWorkspaceState.scopedData.resume_profile || emptyResumeProfile();
}

async function loadResumeProfile(force = false) {
  if (!isAuthenticatedUser()) return emptyResumeProfile();
  if (!force && userWorkspaceState.scopedDataLoaded.resume_profile) {
    return userWorkspaceState.scopedData.resume_profile || emptyResumeProfile();
  }
  const payload = await requestJson("/api/resume/profile");
  const data = payload.data || emptyResumeProfile();
  userWorkspaceState.scopedData.resume_profile = data;
  userWorkspaceState.scopedDataLoaded.resume_profile = true;
  return data;
}

function setResumeJobDescription(value) {
  const input = document.getElementById("resumeJobDescriptionInput");
  if (!input) return;
  if (document.activeElement === input) return;
  input.value = String(value || "");
}

function getResumeJobDescription() {
  return String(document.getElementById("resumeJobDescriptionInput")?.value || "").trim();
}

function fillResumeJobSuggestion(text) {
  const input = document.getElementById("resumeJobDescriptionInput");
  if (!input) return;
  input.value = String(text || "").trim();
  resumeTaskState.jobInputExpanded = true;
  syncResumeJobInputFrame();
  input.focus();
}

function resumeInlineMarkupHtml(value) {
  const escaped = escHtml(String(value || "").trim());
  if (!escaped) return "";
  return escaped
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/__(.+?)__/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}

function decodeHtmlEntities(raw) {
  if (typeof document === "undefined") return String(raw || "");
  const textarea = document.createElement("textarea");
  textarea.innerHTML = String(raw || "");
  return textarea.value;
}

function resumeAnalysisHtmlToText(raw) {
  const html = String(raw || "").trim();
  if (!html) return "";
  const normalized = html
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/(p|div|section|article|h1|h2|h3|h4|h5|h6)>/gi, "\n")
    .replace(/<li[^>]*>/gi, "- ")
    .replace(/<\/(li|ul|ol)>/gi, "\n")
    .replace(/<pre[^>]*><code[^>]*>/gi, "")
    .replace(/<\/code><\/pre>/gi, "");
  return decodeHtmlEntities(normalized.replace(/<[^>]+>/g, ""))
    .replace(/\u00a0/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function resumeReportBlocksPartition(blocks) {
  const leadBlocks = [];
  const groups = [];
  let currentGroup = null;
  blocks.forEach((block) => {
    if (block.type === "heading") {
      currentGroup = {
        title: block.html,
        blocks: []
      };
      groups.push(currentGroup);
      return;
    }
    if (currentGroup) {
      currentGroup.blocks.push(block);
      return;
    }
    leadBlocks.push(block);
  });
  return { leadBlocks, groups };
}

function resumeReportListHtml(block) {
  const ordered = block.listType === "ol";
  return `
    <div class="resume-report-list-grid ${ordered ? "ordered" : "unordered"}">
      ${block.items.map((item, index) => `
        <article class="resume-report-list-card">
          <span class="resume-report-list-badge">${ordered ? String(index + 1).padStart(2, "0") : "•"}</span>
          <p class="resume-report-list-copy">${item}</p>
        </article>
      `).join("")}
    </div>
  `;
}

function resumeReportBlocksHtml(blocks) {
  return blocks.map((block) => {
    if (block.type === "paragraph") {
      return `<p class="resume-report-paragraph">${block.html}</p>`;
    }
    if (block.type === "divider") {
      return `<div class="resume-report-divider"></div>`;
    }
    if (block.type === "list") {
      return resumeReportListHtml(block);
    }
    if (block.type === "codeblock") {
      const id = `rcb-${Math.random().toString(36).slice(2, 9)}`;
      return `
        <div class="resume-report-code-block">
          <div class="resume-report-code-toolbar">
            <span class="resume-report-code-label">📄 修改后简历范本</span>
            <button class="resume-report-code-copy" onclick="copyResumeCodeBlock('${id}')">复制全文</button>
          </div>
          <pre id="${id}" class="resume-report-code-pre"><code>${escHtml(block.code)}</code></pre>
        </div>
      `;
    }
    return "";
  }).join("");
}

function copyResumeCodeBlock(id) {
  const el = document.getElementById(id);
  if (!el) return;
  const text = el.innerText || el.textContent || "";
  navigator.clipboard.writeText(text).then(() => {
    const btn = el.closest(".resume-report-code-block")?.querySelector(".resume-report-code-copy");
    if (btn) {
      const prev = btn.textContent;
      btn.textContent = "已复制 ✓";
      setTimeout(() => { btn.textContent = prev; }, 2000);
    }
  }).catch(() => {});
}

function copyPlainText(text, successTitle = "已复制", successMessage = "内容已复制到剪贴板。") {
  const raw = String(text || "").trim();
  if (!raw) {
    showToast("没有可复制内容", "先生成任务名片后再复制。", "warning", 1800);
    return Promise.resolve(false);
  }
  return navigator.clipboard.writeText(raw).then(() => {
    showToast(successTitle, successMessage, "success", 1600);
    return true;
  }).catch(() => {
    showToast("复制失败", "当前环境不允许直接写入剪贴板。", "error", 1800);
    return false;
  });
}

function resumeMarkdownBlocksHtml(raw) {
  const lines = String(raw || "").replace(/\r\n/g, "\n").split("\n");
  const blocks = [];
  let paragraphLines = [];
  let listItems = [];
  let listType = "";
  let inCodeBlock = false;
  let codeBlockLines = [];

  function flushParagraph() {
    if (!paragraphLines.length) return;
    blocks.push({
      type: "paragraph",
      html: resumeInlineMarkupHtml(paragraphLines.join(" "))
    });
    paragraphLines = [];
  }

  function flushList() {
    if (!listItems.length) return;
    blocks.push({
      type: "list",
      listType,
      items: [...listItems]
    });
    listItems = [];
    listType = "";
  }

  lines.forEach((rawLine) => {
    const line = String(rawLine || "").trim();

    // Inside a fenced code block — collect lines until closing fence
    if (inCodeBlock) {
      if (/^```/.test(line)) {
        inCodeBlock = false;
        blocks.push({ type: "codeblock", code: codeBlockLines.join("\n") });
        codeBlockLines = [];
      } else {
        codeBlockLines.push(rawLine);
      }
      return;
    }

    if (!line) {
      flushParagraph();
      flushList();
      return;
    }
    if (/^```/.test(line)) {
      flushParagraph();
      flushList();
      inCodeBlock = true;
      codeBlockLines = [];
      return;
    }
    if (/^-{3,}$/.test(line)) {
      flushParagraph();
      flushList();
      blocks.push({ type: "divider" });
      return;
    }
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      flushList();
      blocks.push({
        type: "heading",
        level: heading[1].length,
        html: resumeInlineMarkupHtml(heading[2])
      });
      return;
    }
    const ordered = line.match(/^\d+\.\s+(.+)$/);
    if (ordered) {
      flushParagraph();
      if (listType && listType !== "ol") flushList();
      listType = "ol";
      listItems.push(resumeInlineMarkupHtml(ordered[1]));
      return;
    }
    // Checklist items: - [ ] or - [x]
    const checklist = line.match(/^[-*]\s+\[( |x)\]\s+(.+)$/i);
    if (checklist) {
      flushParagraph();
      if (listType && listType !== "ul") flushList();
      listType = "ul";
      const checked = checklist[1].toLowerCase() === "x";
      listItems.push(`<span class="resume-checklist-icon">${checked ? "✅" : "⬜"}</span> ${resumeInlineMarkupHtml(checklist[2])}`);
      return;
    }
    const unordered = line.match(/^[-*]\s+(.+)$/);
    if (unordered) {
      flushParagraph();
      if (listType && listType !== "ul") flushList();
      listType = "ul";
      listItems.push(resumeInlineMarkupHtml(unordered[1]));
      return;
    }
    flushList();
    paragraphLines.push(line);
  });
  // flush any open code block
  if (inCodeBlock && codeBlockLines.length) {
    blocks.push({ type: "codeblock", code: codeBlockLines.join("\n") });
  }

  flushParagraph();
  flushList();

  const sectionParts = [];
  let currentSection = null;
  function pushCurrentSection() {
    if (!currentSection) return;
    if (!currentSection.intro && !currentSection.content.length) return;
    sectionParts.push(currentSection);
  }
  blocks.forEach((block) => {
    if (block.type === "heading" && block.level <= 2) {
      pushCurrentSection();
      currentSection = {
        title: block.html,
        intro: "",
        content: []
      };
      return;
    }
    if (!currentSection) {
      currentSection = {
        title: "分析内容",
        intro: "",
        content: []
      };
    }
    if (block.type === "paragraph" && !currentSection.intro) {
      currentSection.intro = block.html;
      return;
    }
    currentSection.content.push(block);
  });
  pushCurrentSection();

  if (!sectionParts.length && currentSection) {
    sectionParts.push(currentSection);
  }

  return `
    <div class="resume-report-doc">
      ${sectionParts.map((section, index) => {
        const { leadBlocks, groups } = resumeReportBlocksPartition(section.content);
        return `
        <section id="resume-report-section-${index + 1}" class="resume-report-section ${index === 0 ? "primary" : ""}">
          <div class="resume-report-head">
            <div class="resume-report-head-main">
              <span class="resume-report-step">${String(index + 1).padStart(2, "0")}</span>
              <div>
                <p class="resume-report-title">${section.title}</p>
                ${section.intro ? `<p class="resume-report-intro">${section.intro}</p>` : ""}
              </div>
            </div>
          </div>
          <div class="resume-report-body">
            ${leadBlocks.length ? `<div class="resume-report-lead">${resumeReportBlocksHtml(leadBlocks)}</div>` : ""}
            ${groups.length ? `
              <div class="resume-report-subgrid">
                ${groups.map((group) => `
                  <article class="resume-report-subcard">
                    <p class="resume-report-subtitle">${group.title}</p>
                    <div class="resume-report-subcontent">
                      ${resumeReportBlocksHtml(group.blocks)}
                    </div>
                  </article>
                `).join("")}
              </div>
            ` : ""}
          </div>
        </section>
      `;
      }).join("")}
    </div>
  `;
}

function resumeDetailedReportHtml(state) {
  const markdown = String(state.analysis_result || "").trim();
  if (markdown) {
    return resumeMarkdownBlocksHtml(markdown);
  }
  const htmlText = resumeAnalysisHtmlToText(state.analysis_html);
  if (htmlText) return resumeMarkdownBlocksHtml(htmlText);
  if (state.analysis_html) return `<div class="resume-report-doc html"><article class="resume-report-html-fallback">${state.analysis_html}</article></div>`;
  return `<div class="career-list-empty">等待生成简历分析结果</div>`;
}

function extractResumeReportTitles(reportHtml) {
  return Array.from(String(reportHtml || "").matchAll(/<p class="resume-report-title">([\s\S]*?)<\/p>/g))
    .map((match) => decodeHtmlEntities(String(match[1] || "").replace(/<[^>]+>/g, "")).trim())
    .filter(Boolean);
}

function buildResumeReportPreviewItems(titles) {
  return titles.slice(0, 4);
}

function clearResumeReportObserver() {
  if (resumeTaskState.reportObserver) {
    resumeTaskState.reportObserver.disconnect();
    resumeTaskState.reportObserver = null;
  }
}

function setActiveResumeReportOutline(index) {
  document.querySelectorAll(".resume-report-outline-btn").forEach((button) => {
    button.classList.toggle("active", Number(button.dataset.sectionIndex || 0) === Number(index || 0));
  });
}

function bindResumeReportOutlineTracking() {
  clearResumeReportObserver();
  const root = document.getElementById("resumeReportModalContent");
  if (!root || typeof IntersectionObserver === "undefined") return;
  const sections = Array.from(root.querySelectorAll(".resume-report-section[id]"));
  if (!sections.length) return;
  resumeTaskState.reportObserver = new IntersectionObserver((entries) => {
    const visible = entries
      .filter((entry) => entry.isIntersecting)
      .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
    if (!visible) return;
    const matched = String(visible.target.id || "").match(/(\d+)$/);
    if (!matched) return;
    setActiveResumeReportOutline(Number(matched[1]));
  }, {
    root,
    threshold: [0.2, 0.35, 0.55, 0.75]
  });
  sections.forEach((section) => resumeTaskState.reportObserver.observe(section));
  setActiveResumeReportOutline(1);
}

function resumeReportLauncherHtml(state, profile, matcher, analysisMode, recommendedDirections) {
  const hasReport = state?.status === "analyzed" && (String(state?.analysis_result || "").trim() || String(state?.analysis_html || "").trim());
  const reportHtml = hasReport ? resumeDetailedReportHtml(state) : "";
  const titles = hasReport ? extractResumeReportTitles(reportHtml) : [];
  const previewItems = buildResumeReportPreviewItems(titles);
  const matchedCount = Array.isArray(matcher?.matched_keywords) ? matcher.matched_keywords.length : 0;
  const jobCount = Array.isArray(matcher?.job_keywords) ? matcher.job_keywords.length : 0;
  const summaryText = profile?.candidate_summary || (
    String(state?.status || "").trim() === "failed"
      ? (humanizeResumeErrorMessage(state?.error_message || state?.analysis_meta?.stage_detail || "") || "这份简历暂时没有生成可阅读的完整报告。")
      : (analysisMode === "resume_review"
        ? "完整报告会收纳方向建议、优势短板、风险边界和下一步修改建议。"
        : "完整报告会收纳匹配结论、命中缺口、风险边界和可执行修改建议。")
  );
  return `
    <section class="resume-bento-card resume-bento-span-12 resume-details-card resume-report-entry ${hasReport ? "" : "is-placeholder"}">
      <div class="resume-bento-head">
        <div>
          <p class="resume-bento-kicker">Full Report</p>
          <p class="resume-bento-title">${analysisMode === "resume_review" ? "完整诊断报告" : "完整匹配报告"}</p>
        </div>
        <button type="button" class="resume-report-open-btn" onclick="openResumeReportPage()" ${hasReport ? "" : "disabled"}>${hasReport ? "跳转详细报告" : (String(state?.status || "").trim() === "failed" ? "分析失败，暂无报告" : "等待分析完成")}</button>
      </div>
      <div class="resume-report-entry-grid">
        <div class="resume-report-entry-summary">
          <p class="resume-report-entry-copy">${escHtml(shortenResumeText(summaryText, 168))}</p>
          <div class="resume-report-entry-metrics">
            <article class="resume-report-entry-metric">
              <span>综合判断</span>
              <strong>${profile ? `${Math.round(Number(profile.confidence || 0) * 100)}%` : "--"}</strong>
            </article>
            <article class="resume-report-entry-metric">
              <span>阅读模式</span>
              <strong>${analysisMode === "resume_review" ? "简历诊断" : "岗位匹配"}</strong>
            </article>
            <article class="resume-report-entry-metric">
              <span>章节数</span>
              <strong>${hasReport ? titles.length || 1 : "--"}</strong>
            </article>
            <article class="resume-report-entry-metric">
              <span>${analysisMode === "resume_review" ? "建议方向" : "命中情况"}</span>
              <strong>${analysisMode === "resume_review" ? `${recommendedDirections.length || 0} 个` : `${matchedCount}/${jobCount || 0}`}</strong>
            </article>
          </div>
        </div>
        <div class="resume-report-entry-outline">
          <p class="resume-report-entry-label">报告包含</p>
          <div class="resume-report-entry-tags">
            ${previewItems.length ? previewItems.map((title, index) => `
              <span class="resume-report-entry-tag"><b>${String(index + 1).padStart(2, "0")}</b>${escHtml(title)}</span>
            `).join("") : `<span class="resume-radar-pill">分析完成后可查看完整报告</span>`}
          </div>
        </div>
      </div>
    </section>
  `;
}

function resolveResumeCapabilityScore(profile, key) {
  const scores = profile?.capability_scores && typeof profile.capability_scores === "object"
    ? profile.capability_scores
    : {};
  const raw = scores[key];
  const num = Number(raw);
  return Number.isFinite(num) ? normalizeResumeScore(num) : 0;
}

function resumeJudgeStoryScore(profile, matcher) {
  const overview = matcher?.resume_overview && typeof matcher.resume_overview === "object" ? matcher.resume_overview : {};
  const experienceCount = Number(overview.experience_count || 0);
  const projectCount = Number(overview.project_count || 0);
  const evidenceCount = Array.isArray(profile?.evidence_spans) ? profile.evidence_spans.length : 0;
  const summaryBonus = profile?.candidate_summary ? 10 : 0;
  return normalizeResumeScore(42 + experienceCount * 14 + projectCount * 9 + evidenceCount * 4 + summaryBonus);
}

function resumeJudgeTechScore(profile) {
  const professional = resolveResumeCapabilityScore(profile, "professional");
  const learning = resolveResumeCapabilityScore(profile, "learning");
  const execution = resolveResumeCapabilityScore(profile, "execution");
  return averageResumeScores([professional, learning, execution]);
}

function resumeJudgeFormatScore(profile, matcher) {
  const basics = profile?.basics && typeof profile.basics === "object" ? profile.basics : {};
  const overview = matcher?.resume_overview && typeof matcher.resume_overview === "object" ? matcher.resume_overview : {};
  const baseScore = 44
    + (basics.major ? 10 : 0)
    + (basics.grade ? 10 : 0)
    + (profile?.candidate_summary ? 10 : 0)
    + Math.min(Number(overview.skill_count || 0) * 3, 16)
    + Math.min(Number(overview.project_count || 0) * 3, 10);
  return normalizeResumeScore(baseScore);
}

function resumeJudgeMatchScore(profile, matcher, analysisMode, recommendedDirections) {
  const matchedCount = Array.isArray(matcher?.matched_keywords) ? matcher.matched_keywords.length : 0;
  const jobCount = Array.isArray(matcher?.job_keywords) ? matcher.job_keywords.length : 0;
  if (analysisMode === "resume_review") {
    const matching = resolveResumeCapabilityScore(profile, "matching");
    return matching || normalizeResumeScore((recommendedDirections.length ? 72 : 58) + Math.min(recommendedDirections.length * 6, 18));
  }
  if (jobCount > 0) {
    return normalizeResumeScore((matchedCount / jobCount) * 100);
  }
  return resolveResumeCapabilityScore(profile, "matching") || normalizeResumeScore(Number(profile?.confidence || 0) * 100);
}

function resumeJudgeOverallScore(profile, matcher, analysisMode, recommendedDirections) {
  return averageResumeScores([
    normalizeResumeScore(Number(profile?.confidence || 0) * 100),
    resumeJudgeMatchScore(profile, matcher, analysisMode, recommendedDirections),
    resumeJudgeStoryScore(profile, matcher),
    resumeJudgeTechScore(profile),
    resumeJudgeFormatScore(profile, matcher)
  ]);
}

function switchResumeJudgeTab(index) {
  const shell = document.getElementById("resumeJudgeShell");
  if (!shell) return;
  const safeIndex = Number(index || 1);
  shell.querySelectorAll(".resume-judge-tab-btn, .resume-hj-tab-btn").forEach((button) => {
    button.classList.toggle("active", Number(button.dataset.sectionIndex || 0) === safeIndex);
  });
  shell.querySelectorAll(".resume-judge-tab-panel, .resume-hj-panel").forEach((panel) => {
    panel.classList.toggle("active", Number(panel.dataset.sectionIndex || 0) === safeIndex);
  });
}

function switchResumeJudgeEvidenceView(view) {
  const structured = document.getElementById("resumeJudgeStructuredResumeView");
  const raw = document.getElementById("resumeJudgeRawResumeView");
  const tabStructured = document.getElementById("resumeJudgeEvidenceTabStructured");
  const tabRaw = document.getElementById("resumeJudgeEvidenceTabRaw");
  if (!structured || !raw || !tabStructured || !tabRaw) return;
  const isRaw = String(view || "") === "raw";
  structured.classList.toggle("hidden", isRaw);
  raw.classList.toggle("hidden", !isRaw);
  tabStructured.classList.toggle("active", !isRaw);
  tabRaw.classList.toggle("active", isRaw);
}

function openResumeReportPage() {
  const state = userWorkspaceState.scopedData.resume_profile || emptyResumeProfile();
  const hasReport = state?.status === "analyzed" && (String(state?.analysis_result || "").trim() || String(state?.analysis_html || "").trim());
  if (!hasReport) {
    showToast("完整报告未生成", "请先完成简历分析。", "warning", 1800);
    return;
  }
  window.location.href = "/resume-report.html";
}

function renderResumeReportModal(state, profile, matcher, analysisMode, recommendedDirections) {
  const eyebrow = document.getElementById("resumeReportModalEyebrow");
  const title = document.getElementById("resumeReportModalTitle");
  const subtitle = document.getElementById("resumeReportModalSubtitle");
  const aside = document.getElementById("resumeReportModalAside");
  const content = document.getElementById("resumeReportModalContent");
  if (!eyebrow || !title || !subtitle || !aside || !content) return;
  clearResumeReportObserver();

  const hasReport = state?.status === "analyzed" && (String(state?.analysis_result || "").trim() || String(state?.analysis_html || "").trim());
  const reportHtml = hasReport ? resumeDetailedReportHtml(state) : "";
  const titles = hasReport ? extractResumeReportTitles(reportHtml) : [];
  const score = profile ? `${Math.round(Number(profile.confidence || 0) * 100)}%` : "--";
  const modeLabel = analysisMode === "resume_review" ? "Resume Review" : "Role Matching";
  const docTitle = analysisMode === "resume_review" ? "完整诊断报告" : "完整匹配报告";
  const jobOverview = matcher?.job_overview && typeof matcher.job_overview === "object" ? matcher.job_overview : {};
  const roles = previewTagValues((profile?.roles_detected || []).map((item) => item.role), 4);
  const focusTags = analysisMode === "resume_review"
    ? previewTagValues(recommendedDirections, 4)
    : previewTagValues(matcher?.matched_keywords || [], 4);
  const matchedCount = Array.isArray(matcher?.matched_keywords) ? matcher.matched_keywords.length : 0;
  const jobCount = Array.isArray(matcher?.job_keywords) ? matcher.job_keywords.length : 0;

  eyebrow.textContent = modeLabel;
  title.textContent = docTitle;
  subtitle.textContent = hasReport
    ? `${formatUnixTime(state.analyzed_at)} · 点击左侧目录可跳转章节`
    : "分析完成后，这里会以阅读模式展示完整报告。";

  if (!hasReport) {
    aside.innerHTML = `
      <div class="resume-report-side-card muted">
        <p class="resume-report-side-kicker">准备中</p>
        <p class="resume-report-side-title">完整报告尚未生成</p>
        <p class="resume-report-side-copy">上传简历并完成分析后，这里会显示报告摘要、章节目录和阅读导航。</p>
      </div>
    `;
    content.innerHTML = `<div class="resume-report-modal-empty">完整报告会在分析完成后出现在这里。</div>`;
    return;
  }

  aside.innerHTML = `
    <div class="resume-report-side-card primary">
      <p class="resume-report-side-kicker">诊断概览</p>
      <p class="resume-report-side-title">${escHtml(profile?.candidate_summary || "系统已生成完整阅读报告")}</p>
      <div class="resume-report-side-metrics">
        <article><span>综合判断</span><strong>${escHtml(score)}</strong></article>
        <article><span>阅读模式</span><strong>${analysisMode === "resume_review" ? "简历诊断" : "岗位匹配"}</strong></article>
        <article><span>${analysisMode === "resume_review" ? "建议方向" : "匹配结果"}</span><strong>${analysisMode === "resume_review" ? `${recommendedDirections.length || 0} 个` : `${matchedCount}/${jobCount || 0}`}</strong></article>
        <article><span>岗位焦点</span><strong>${escHtml(analysisMode === "resume_review" ? (recommendedDirections[0] || "待探索") : (jobOverview.job_title || "未识别"))}</strong></article>
      </div>
    </div>
    <div class="resume-report-side-card">
      <p class="resume-report-side-kicker">目录</p>
      <div class="resume-report-outline">
        ${titles.length ? titles.map((item, index) => `
          <button type="button" class="resume-report-outline-btn" data-section-index="${index + 1}" onclick="jumpResumeReportSection(${index + 1})">
            <span>${String(index + 1).padStart(2, "0")}</span>
            <strong>${escHtml(item)}</strong>
          </button>
        `).join("") : `<div class="career-list-empty">暂无章节目录</div>`}
      </div>
    </div>
    <div class="resume-report-side-card">
      <p class="resume-report-side-kicker">阅读提示</p>
      <div class="resume-report-side-tags">
        ${roles.length ? roles.map((item) => `<span class="resume-report-side-tag">${escHtml(item)}</span>`).join("") : ""}
        ${focusTags.length ? focusTags.map((item) => `<span class="resume-report-side-tag accent">${escHtml(item)}</span>`).join("") : ""}
      </div>
      <p class="resume-report-side-copy">先看 30 秒结论，再按目录跳到你最关心的章节。每一章都已经拆成摘要卡和内容卡，不需要从头顺着读。</p>
    </div>
  `;

  content.innerHTML = `
    <div class="resume-report-reading-canvas">
      <div class="resume-report-modal-hero">
        <div>
          <p class="resume-report-modal-hero-kicker">${analysisMode === "resume_review" ? "Career Diagnosis" : "Job Match Diagnosis"}</p>
          <h4 class="resume-report-modal-hero-title">${escHtml(docTitle)}</h4>
          <p class="resume-report-modal-hero-copy">${escHtml(profile?.candidate_summary || "系统已根据简历与岗位文本生成完整报告。")}</p>
        </div>
        <div class="resume-report-modal-hero-tags">
          ${focusTags.length ? focusTags.map((item) => `<span class="resume-report-side-tag accent">${escHtml(item)}</span>`).join("") : `<span class="resume-report-side-tag">完整章节阅读模式</span>`}
        </div>
      </div>
      <div class="resume-report-modal-reader">
        ${reportHtml}
      </div>
    </div>
  `;
  bindResumeReportOutlineTracking();
}

function openResumeReportModal() {
  const state = userWorkspaceState.scopedData.resume_profile || emptyResumeProfile();
  const profile = state.profile || null;
  const matcher = state.matcher && typeof state.matcher === "object" ? state.matcher : {};
  const analysisMode = String(matcher.analysis_mode || state.analysis_meta?.analysis_mode || "").trim();
  const recommendedDirections = Array.isArray(matcher.recommended_directions) ? matcher.recommended_directions : [];
  const hasReport = state?.status === "analyzed" && (String(state?.analysis_result || "").trim() || String(state?.analysis_html || "").trim());
  if (!hasReport) {
    showToast("完整报告未生成", "请先完成简历分析。", "warning", 1800);
    return;
  }
  renderResumeReportModal(state, profile, matcher, analysisMode, recommendedDirections);
  const modal = document.getElementById("resumeReportModal");
  if (!modal) return;
  modal.classList.remove("hidden");
  document.body.style.overflow = "hidden";
}

function closeResumeReportModal() {
  clearResumeReportObserver();
  const modal = document.getElementById("resumeReportModal");
  if (modal) modal.classList.add("hidden");
  document.body.style.overflow = "";
}

function handleResumeReportOverlayClick(event) {
  if (event.target?.id === "resumeReportModal") {
    closeResumeReportModal();
  }
}

function jumpResumeReportSection(index) {
  setActiveResumeReportOutline(index);
  const target = document.getElementById(`resume-report-section-${Number(index || 0)}`);
  if (target) {
    target.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function resumeJobAssistHtml(jobDescription, analysisMode, recommendedDirections) {
  const text = String(jobDescription || "").trim();
  if (!text) {
    const suggestions = [
      {
        label: "留空直接诊断",
        title: "还没想清岗位也可以直接分析",
        copy: "系统会先基于简历本身判断优势、短板、风险点和更适合的职业方向。",
        action: ""
      },
      {
        label: "写一句方向",
        title: "只写模糊方向也能匹配",
        copy: "例如：我想尝试产品运营、项目助理、HR 或数据分析相关岗位。",
        action: "我想先看看自己更适合产品运营、项目助理、HR 还是数据分析方向。"
      },
      {
        label: "粘贴完整 JD",
        title: "有明确岗位时再贴完整要求",
        copy: "系统会提炼岗位重点，并用简历证据去判断匹配程度和待补强项。",
        action: "工作地点：上海\n岗位职责：\n1. 负责用户运营和数据复盘。\n2. 协调跨团队推进活动落地。\n任职要求：\n1. 具备数据分析和内容运营能力。\n2. 有项目推进或活动执行经历。"
      }
    ];
    return `
      <div class="resume-job-assist-panel empty">
        <div class="resume-job-assist-head">
          <div>
            <p class="resume-job-assist-kicker">Explore Mode</p>
            <p class="resume-job-assist-title">未指定岗位时，默认进入简历诊断模式</p>
          </div>
          <span class="resume-score-chip muted">无 JD 也可分析</span>
        </div>
        <div class="resume-job-assist-grid">
          ${suggestions.map((item) => {
            const encodedAction = encodeURIComponent(item.action || "");
            return `
            <article class="resume-job-assist-card">
              <span class="resume-job-assist-tag">${escHtml(item.label)}</span>
              <p class="resume-job-assist-card-title">${escHtml(item.title)}</p>
              <p class="resume-job-assist-copy">${escHtml(item.copy)}</p>
              ${item.action ? `<button type="button" class="resume-job-assist-action" onclick="fillResumeJobSuggestion(decodeURIComponent('${encodedAction}'))">填入示例</button>` : `<span class="resume-job-assist-hint">保持留空即可</span>`}
            </article>
          `;
          }).join("")}
        </div>
      </div>
    `;
  }

  const focusTags = analysisMode === "resume_review"
    ? previewTagValues(recommendedDirections, 4)
    : previewTagValues(text.split(/[，。；;、\n]/).map((item) => item.trim()).filter(Boolean), 4);
  return `
    <div class="resume-job-assist-panel filled">
      <div class="resume-job-assist-head">
        <div>
          <p class="resume-job-assist-kicker">Input Preview</p>
          <p class="resume-job-assist-title">系统会直接理解这段文本，不要求固定 JD 格式</p>
        </div>
        <span class="resume-score-chip brand">${analysisMode === "resume_review" ? "方向描述" : "岗位文本"}</span>
      </div>
      <div class="resume-analysis-tag-row">
        ${focusTags.length ? focusTags.map((item) => `<span class="resume-analysis-tag">${escHtml(shortenResumeText(item, 24))}</span>`).join("") : `<span class="resume-radar-pill">已输入 ${text.length} 字</span>`}
      </div>
    </div>
  `;
}

function previewTagValues(items, limit = 8) {
  const values = [...new Set((Array.isArray(items) ? items : []).map((item) => String(item || "").trim()).filter(Boolean))];
  if (values.length <= limit) return values;
  return [...values.slice(0, limit), `+${values.length - limit}`];
}

function resumeModeMeta(analysisMode) {
  if (analysisMode === "resume_review") {
    return {
      badge: "简历诊断模式",
      title: "先看方向，再看优势和短板",
      description: "没有填写 JD 时，系统会优先给出通用竞争力判断和建议职业方向。"
    };
  }
  return {
    badge: "岗位匹配模式",
    title: "先看匹配度，再看风险和改法",
    description: "系统会先理解岗位文本，再把简历证据、缺口和建议整理成可操作结论。"
  };
}

function normalizeResumeScore(value) {
  return Math.max(0, Math.min(100, Math.round(Number(value || 0))));
}

function shortenResumeText(value, max = 92) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (!text) return "";
  if (text.length <= max) return text;
  return `${text.slice(0, max)}...`;
}

function humanizeResumeErrorMessage(raw) {
  const text = String(raw || "").trim();
  if (!text) return "";
  if (text.includes("未能从简历中提取到有效文本")) {
    return "这份简历更像扫描版图片，系统暂时没有拿到可分析文本。建议优先上传文字版 PDF 或 DOCX；如果继续使用扫描版 PDF，识别结果可能会有偏差。";
  }
  return text;
}

function resumeProfileSummaryText(state, profile) {
  if (profile?.candidate_summary) return profile.candidate_summary;
  const status = String(state?.status || "").trim();
  const hasFile = Boolean(state?.file_name);
  const errorText = humanizeResumeErrorMessage(state?.error_message || state?.analysis_meta?.stage_detail || "");
  if (status === "failed" && hasFile) {
    return errorText || "简历已上传，但本次分析失败。请检查文件内容后重新开始匹配。";
  }
  if (hasFile) {
    return "简历已上传，当前还没有生成分析结果。点击“开始匹配”后即可查看摘要和详细报告。";
  }
  return "上传简历后会在这里显示摘要，开始匹配后可查看完整结果。";
}

function resumeQuickBoardHtml(profile, matcher, analysisMode, recommendedDirections) {
  const basics = profile?.basics && typeof profile.basics === "object" ? profile.basics : {};
  const resumeOverview = matcher?.resume_overview && typeof matcher.resume_overview === "object" ? matcher.resume_overview : {};
  const jobOverview = matcher?.job_overview && typeof matcher.job_overview === "object" ? matcher.job_overview : {};
  const focusValue = analysisMode === "resume_review"
    ? (recommendedDirections[0] || normalizeResumeBasicValue(basics.target_direction) || "待探索")
    : (jobOverview.job_title || normalizeResumeBasicValue(basics.target_direction) || "待识别");
  const cards = [
    {
      label: "分析模式",
      value: analysisMode === "resume_review" ? "简历诊断" : "岗位匹配",
      note: analysisMode === "resume_review" ? "未绑定单一 JD" : "基于岗位文本判断"
    },
    {
      label: analysisMode === "resume_review" ? "建议方向" : "目标焦点",
      value: focusValue,
      note: analysisMode === "resume_review" ? "可后续再补充 JD" : (jobOverview.company_name || "直接提炼自输入文本")
    },
    {
      label: "地点信息",
      value: normalizeResumeBasicValue(basics.target_city) || jobOverview.location || "未明确",
      note: normalizeResumeBasicValue(jobOverview.employment_type) || "当前简历未给出稳定偏好"
    },
    {
      label: "经历体量",
      value: `${Number(resumeOverview.experience_count || 0)} 段经历`,
      note: `${Number(resumeOverview.project_count || 0)} 个项目 · ${Number(resumeOverview.skill_count || 0)} 项技能`
    }
  ];

  return cards
    .map((item) => `
      <article class="resume-quick-card">
        <p class="resume-quick-label">${escHtml(item.label)}</p>
        <p class="resume-quick-value">${escHtml(item.value)}</p>
        <p class="resume-quick-note">${escHtml(item.note)}</p>
      </article>
    `)
    .join("");
}

function resumeOverviewCardsHtml(profile, matcher, analysisMode, recommendedDirections) {
  const basics = profile?.basics && typeof profile.basics === "object" ? profile.basics : {};
  const resumeOverview = matcher?.resume_overview && typeof matcher.resume_overview === "object" ? matcher.resume_overview : {};
  const jobOverview = matcher?.job_overview && typeof matcher.job_overview === "object" ? matcher.job_overview : {};
  const cards = [
    {
      label: "候选人",
      value: resumeOverview.candidate_name || normalizeResumeBasicValue(basics.name) || "未识别",
      note: resumeOverview.headline || "等待识别当前角色"
    },
    {
      label: "教育背景",
      value: normalizeResumeBasicValue(basics.grade) || "待补充",
      note: normalizeResumeBasicValue(basics.major) || "未识别专业"
    },
    {
      label: analysisMode === "resume_review" ? "建议方向" : "目标岗位",
      value: analysisMode === "resume_review"
        ? (recommendedDirections[0] || normalizeResumeBasicValue(basics.target_direction) || "待探索")
        : (jobOverview.job_title || normalizeResumeBasicValue(basics.target_direction) || "待识别"),
      note: analysisMode === "resume_review"
        ? (recommendedDirections.slice(1, 3).join(" / ") || "后续可补充明确 JD")
        : (jobOverview.company_name || "直接提炼自岗位文本")
    },
    {
      label: "地点",
      value: normalizeResumeBasicValue(basics.target_city) || jobOverview.location || "未明确",
      note: normalizeResumeBasicValue(jobOverview.employment_type) || "未识别用工方式"
    },
    {
      label: "项目数量",
      value: `${Number(resumeOverview.project_count || 0)} 个`,
      note: `${Number(resumeOverview.skill_count || 0)} 项技能被识别`
    },
    {
      label: "经历数量",
      value: `${Number(resumeOverview.experience_count || 0)} 段`,
      note: analysisMode === "resume_review" ? "用于判断方向适配" : "用于判断岗位匹配"
    }
  ];

  return `<div class="resume-overview-grid">${cards.map((item) => `
    <article class="resume-meta-card">
      <p class="resume-meta-label">${escHtml(item.label)}</p>
      <p class="resume-meta-value">${escHtml(item.value)}</p>
      <p class="resume-meta-note">${escHtml(item.note)}</p>
    </article>
  `).join("")}</div>`;
}

function resumeEvidenceCardsHtml(profile) {
  const groups = [
    {
      label: "来自简历",
      tone: "neutral",
      items: (Array.isArray(profile?.evidence_spans) ? profile.evidence_spans : []).slice(0, 4).map((item) => ({
        title: shortenResumeText(item.quote || "", 68) || "待补充证据",
        copy: "直接来自简历原文的关键片段。"
      }))
    },
    {
      label: "行为信号",
      tone: "brand",
      items: (Array.isArray(profile?.leadership_signals) ? profile.leadership_signals : []).slice(0, 3).map((item) => ({
        title: shortenResumeText(item.signal || item, 68) || "待识别",
        copy: "系统识别到的推进、主导或跨团队协作信号。"
      }))
    },
    {
      label: "待确认",
      tone: "warning",
      items: (Array.isArray(profile?.uncertainty_layer) ? profile.uncertainty_layer : []).slice(0, 3).map((item) => ({
        title: item.item || "信息缺口",
        copy: [item.reason, item.needed_evidence ? `待补：${item.needed_evidence}` : ""].filter(Boolean).join(" ")
      }))
    }
  ];

  if (!groups.some((group) => group.items.length)) {
    return `<div class="career-list-empty">暂无证据片段</div>`;
  }
  return `<div class="resume-evidence-grid">${groups.map((group) => `
    <section class="resume-evidence-group ${escHtml(group.tone)}">
      <div class="resume-evidence-group-head">
        <p class="resume-evidence-group-title">${escHtml(group.label)}</p>
        <span class="resume-evidence-group-count">${group.items.length}</span>
      </div>
      <div class="resume-evidence-group-list">
        ${group.items.length ? group.items.map((item) => `
          <article class="resume-evidence-entry">
            <p class="resume-evidence-title">${escHtml(item.title)}</p>
            <p class="resume-evidence-copy">${escHtml(shortenResumeText(item.copy, 116))}</p>
          </article>
        `).join("") : `<div class="career-list-empty">暂无内容</div>`}
      </div>
    </section>
  `).join("")}</div>`;
}

function averageResumeScores(values) {
  const numbers = (Array.isArray(values) ? values : [])
    .map((item) => Number(item || 0))
    .filter((item) => Number.isFinite(item) && item > 0);
  if (!numbers.length) return 0;
  return normalizeResumeScore(numbers.reduce((sum, item) => sum + item, 0) / numbers.length);
}

function resumeConfidenceTone(score) {
  const safeScore = normalizeResumeScore(score);
  if (safeScore < 50) {
    return {
      tone: "danger",
      label: "需补强",
      note: "当前差距较大，建议先补足核心经历和岗位证据。"
    };
  }
  if (safeScore < 70) {
    return {
      tone: "warning",
      label: "中等匹配",
      note: "已有一定基础，但还存在可以明确修复的缺口。"
    };
  }
  if (safeScore < 85) {
    return {
      tone: "success",
      label: "较强匹配",
      note: "关键能力基本在线，适合继续优化后优先投递。"
    };
  }
  return {
    tone: "brand",
    label: "高匹配",
    note: "核心信号完整，可以直接进入重点投递或面试准备。"
  };
}

function resumeCapabilityMetrics(profile, analysisMode) {
  const scores = profile?.capability_scores && typeof profile.capability_scores === "object" ? profile.capability_scores : {};
  return [
    {
      key: "matching",
      label: analysisMode === "resume_review" ? "方向适配" : "岗位匹配",
      value: normalizeResumeScore(Number(profile?.confidence || 0) * 100),
      note: analysisMode === "resume_review" ? "和建议方向的贴合度" : "和目标岗位的对齐度"
    },
    {
      key: "execution",
      label: "执行交付",
      value: normalizeResumeScore(scores.execution),
      note: "项目推进、落地和结果产出"
    },
    {
      key: "communication",
      label: "沟通协作",
      value: averageResumeScores([scores.communication, scores.collaboration]),
      note: "表达、协作和跨团队配合"
    },
    {
      key: "resilience",
      label: "抗压稳定",
      value: normalizeResumeScore(scores.stress_resilience),
      note: "面对节奏变化和不确定性的稳定度"
    },
    {
      key: "innovation",
      label: "创新成长",
      value: normalizeResumeScore(scores.innovation),
      note: "学习迁移、新方向理解和吸收速度"
    },
    {
      key: "leadership",
      label: "主动推进",
      value: normalizeResumeScore(scores.leadership),
      note: "主导意识、承担责任和推进能力"
    }
  ];
}

function resumeGaugeCardHtml(profile, matcher, analysisMode, recommendedDirections) {
  const score = normalizeResumeScore(Number(profile?.confidence || 0) * 100);
  const tone = resumeConfidenceTone(score);
  const basics = profile?.basics && typeof profile.basics === "object" ? profile.basics : {};
  const jobOverview = matcher?.job_overview && typeof matcher.job_overview === "object" ? matcher.job_overview : {};
  const matchedCount = Array.isArray(matcher?.matched_keywords) ? matcher.matched_keywords.length : 0;
  const jobCount = Array.isArray(matcher?.job_keywords) ? matcher.job_keywords.length : 0;
  const focusValue = analysisMode === "resume_review"
    ? (recommendedDirections[0] || normalizeResumeBasicValue(basics.target_direction) || "待探索")
    : (jobOverview.job_title || normalizeResumeBasicValue(basics.target_direction) || "待识别");
  const subValue = analysisMode === "resume_review"
    ? (recommendedDirections.length ? `${recommendedDirections.length} 个建议方向` : "待生成建议方向")
    : `${matchedCount}/${jobCount || 0} 关键词命中`;
  return `
    <section class="resume-bento-card resume-bento-span-4 resume-gauge-card">
      <div class="resume-bento-head">
        <div>
          <p class="resume-bento-kicker">Match Gauge</p>
          <p class="resume-bento-title">匹配度仪表盘</p>
        </div>
        <span class="resume-score-chip ${tone.tone}">${escHtml(tone.label)}</span>
      </div>
      <div class="resume-gauge-shell">
        <div class="resume-gauge-ring ${tone.tone}" style="--score-angle:${(score * 3.6).toFixed(1)}deg;">
          <div class="resume-gauge-core">
            <strong>${score}%</strong>
            <span>${analysisMode === "resume_review" ? "综合判断" : "综合匹配度"}</span>
          </div>
        </div>
      </div>
      <p class="resume-gauge-caption">${escHtml(tone.note)}</p>
      <div class="resume-gauge-metrics">
        <article class="resume-gauge-metric">
          <span>目标焦点</span>
          <strong>${escHtml(focusValue)}</strong>
        </article>
        <article class="resume-gauge-metric">
          <span>当前状态</span>
          <strong>${escHtml(subValue)}</strong>
        </article>
        <article class="resume-gauge-metric">
          <span>地点信息</span>
          <strong>${escHtml(normalizeResumeBasicValue(basics.target_city) || jobOverview.location || "未明确")}</strong>
        </article>
      </div>
    </section>
  `;
}

function resumeTargetPanelHtml(profile, matcher, analysisMode, recommendedDirections) {
  const jobOverview = matcher?.job_overview && typeof matcher.job_overview === "object" ? matcher.job_overview : {};
  const matchedKeywords = Array.isArray(matcher?.matched_keywords) ? matcher.matched_keywords : [];
  const missingKeywords = Array.isArray(matcher?.missing_keywords) ? matcher.missing_keywords : [];
  const jobKeywords = Array.isArray(matcher?.job_keywords) ? matcher.job_keywords : [];
  const directionTags = previewTagValues(recommendedDirections, 8);
  const previewMatched = previewTagValues(matchedKeywords, 8);
  const previewMissing = previewTagValues(missingKeywords, 8);
  const fullMatched = previewTagValues(matchedKeywords, 120);
  const fullMissing = previewTagValues(missingKeywords, 120);
  const fullJobKeywords = previewTagValues(jobKeywords, 120);
  if (analysisMode === "resume_review") {
    return `
      <section class="resume-bento-card resume-bento-span-8 resume-target-panel">
        <div class="resume-bento-head">
          <div>
            <p class="resume-bento-kicker">Direction Suggestion</p>
            <p class="resume-bento-title">建议岗位方向</p>
          </div>
          <span class="resume-score-chip muted">无明确 JD</span>
        </div>
        <p class="resume-target-copy">系统会基于简历经历、技能和行为信号给出可尝试方向，并同步指出当前短板与下一步改写重点。</p>
        <div class="resume-target-tags">
          ${directionTags.length ? directionTags.map((tag) => `<span class="resume-analysis-tag">${escHtml(tag)}</span>`).join("") : `<span class="resume-radar-pill">正在生成建议方向</span>`}
        </div>
        <details class="resume-target-details" open>
          <summary>查看全部建议方向</summary>
          <div class="resume-target-detail-content">
            ${recommendedDirections.length ? recommendedDirections.map((item) => `<span class="resume-analysis-tag">${escHtml(item)}</span>`).join("") : `<span class="resume-radar-pill">暂无方向</span>`}
          </div>
        </details>
      </section>
    `;
  }
  return `
    <section class="resume-bento-card resume-bento-span-8 resume-target-panel">
      <div class="resume-bento-head">
        <div>
          <p class="resume-bento-kicker">Role Matching</p>
          <p class="resume-bento-title">岗位匹配要点</p>
        </div>
        <span class="resume-score-chip brand">${matchedKeywords.length}/${jobKeywords.length || 0} 命中</span>
      </div>
      <div class="resume-target-stats">
        <article class="resume-target-stat">
          <span>目标岗位</span>
          <strong>${escHtml(jobOverview.job_title || "未识别")}</strong>
        </article>
        <article class="resume-target-stat">
          <span>公司 / 地点</span>
          <strong>${escHtml(jobOverview.company_name || "--")} · ${escHtml(jobOverview.location || "--")}</strong>
        </article>
        <article class="resume-target-stat">
          <span>缺口数量</span>
          <strong>${missingKeywords.length} 项</strong>
        </article>
      </div>
      <div class="resume-target-group">
        <p class="resume-target-label">命中关键词</p>
        <div class="resume-target-tags">
          ${previewMatched.length ? previewMatched.map((item) => `<span class="resume-analysis-tag">${escHtml(item)}</span>`).join("") : `<span class="resume-radar-pill">暂无命中</span>`}
        </div>
      </div>
      <div class="resume-target-group">
        <p class="resume-target-label">待补强关键词</p>
        <div class="resume-target-tags">
          ${previewMissing.length ? previewMissing.map((item) => `<span class="resume-radar-pill warning">${escHtml(item)}</span>`).join("") : `<span class="resume-radar-pill positive">暂无明显缺口</span>`}
        </div>
      </div>
      <details class="resume-target-details">
        <summary>查看完整关键词清单</summary>
        <div class="resume-target-detail-content stacked">
          <div>
            <p class="resume-target-label">岗位关键词（全部）</p>
            <div class="resume-target-tags">
              ${fullJobKeywords.length ? fullJobKeywords.map((item) => `<span class="resume-analysis-tag">${escHtml(item)}</span>`).join("") : `<span class="resume-radar-pill">暂无</span>`}
            </div>
          </div>
          <div>
            <p class="resume-target-label">命中关键词（全部）</p>
            <div class="resume-target-tags">
              ${fullMatched.length ? fullMatched.map((item) => `<span class="resume-analysis-tag">${escHtml(item)}</span>`).join("") : `<span class="resume-radar-pill">暂无</span>`}
            </div>
          </div>
          <div>
            <p class="resume-target-label">待补强关键词（全部）</p>
            <div class="resume-target-tags">
              ${fullMissing.length ? fullMissing.map((item) => `<span class="resume-radar-pill warning">${escHtml(item)}</span>`).join("") : `<span class="resume-radar-pill positive">暂无</span>`}
            </div>
          </div>
        </div>
      </details>
    </section>
  `;
}

function resumeGaugePlaceholderHtml() {
  return `
    <section class="resume-bento-card resume-bento-span-4 resume-gauge-card is-placeholder">
      <div class="resume-bento-head">
        <div>
          <p class="resume-bento-kicker">Match Gauge</p>
          <p class="resume-bento-title">匹配度仪表盘</p>
        </div>
        <span class="resume-score-chip muted">等待分析</span>
      </div>
      <div class="resume-gauge-shell">
        <div class="resume-gauge-ring muted" style="--score-angle:0deg;">
          <div class="resume-gauge-core">
            <strong>--</strong>
            <span>综合判断</span>
          </div>
        </div>
      </div>
      <p class="resume-gauge-caption">上传简历并开始匹配后，这里会显示综合匹配度、状态分级和关键焦点。</p>
      <div class="resume-gauge-metrics">
        <article class="resume-gauge-metric">
          <span>目标焦点</span>
          <strong>等待识别</strong>
        </article>
        <article class="resume-gauge-metric">
          <span>当前状态</span>
          <strong>等待分析</strong>
        </article>
        <article class="resume-gauge-metric">
          <span>地点信息</span>
          <strong>待补充</strong>
        </article>
      </div>
    </section>
  `;
}

function resumeTargetPlaceholderHtml() {
  return `
    <section class="resume-bento-card resume-bento-span-8 resume-target-panel is-placeholder">
      <div class="resume-bento-head">
        <div>
          <p class="resume-bento-kicker">Direction / Role</p>
          <p class="resume-bento-title">方向或岗位匹配要点</p>
        </div>
        <span class="resume-score-chip muted">等待分析</span>
      </div>
      <p class="resume-target-copy">无目标岗位时会显示建议方向；有岗位文本时会显示命中项、缺口项和完整关键词清单。</p>
      <div class="resume-target-tags">
        <span class="resume-radar-pill">等待解析</span>
      </div>
    </section>
  `;
}

function resumeScoreCardsHtml(profile, analysisMode) {
  const definitions = resumeCapabilityMetrics(profile, analysisMode).filter((item) => ["matching", "execution", "communication", "leadership"].includes(item.key));
  return definitions.map((item) => {
    const toneClass = {
      matching: "brand",
      execution: "success",
      communication: "warning",
      leadership: "muted"
    }[item.key] || "brand";
    const score = normalizeResumeScore(item.value);
    return `
      <article class="resume-score-card ${toneClass}">
        <div class="resume-score-head">
          <p class="resume-score-label">${escHtml(item.label)}</p>
          <span class="resume-score-value">${score}</span>
        </div>
        <div class="resume-score-track">
          <div class="resume-score-fill" style="width:${score}%"></div>
        </div>
        <p class="resume-score-note">${escHtml(item.note)}</p>
      </article>
    `;
  }).join("");
}

function resumeScorePlaceholderHtml() {
  const definitions = [
    ["方向适配", "和建议方向或岗位的贴合度"],
    ["执行交付", "项目推进、落地和结果产出"],
    ["沟通协作", "表达、协作和跨团队配合"],
    ["主动推进", "主导意识和推进能力"]
  ];
  return definitions.map((item) => `
    <article class="resume-score-card muted is-placeholder">
      <div class="resume-score-head">
        <p class="resume-score-label">${escHtml(item[0])}</p>
        <span class="resume-score-value">--</span>
      </div>
      <div class="resume-score-track">
        <div class="resume-score-fill" style="width:0%"></div>
      </div>
      <p class="resume-score-note">${escHtml(item[1])}</p>
    </article>
  `).join("");
}

function resumeStackDeckHtml(deckId, items, options = {}) {
  const safeItems = Array.isArray(items) ? items.filter(Boolean) : [];
  if (!safeItems.length) {
    return `<div class="career-list-empty">${escHtml(options.emptyText || "暂无内容")}</div>`;
  }
  const safeDeckId = String(deckId || "resume-deck").replace(/'/g, "\\'");
  const variantClass = options.variant ? ` ${options.variant}` : "";
  const isSingle = safeItems.length <= 1;
  return `
    <div class="resume-stack-deck${variantClass}" data-resume-deck="${escHtml(deckId)}" data-total="${safeItems.length}">
      <div class="resume-stack-stage">
        ${!isSingle ? `<button type="button" class="resume-stack-arrow prev" onclick="shiftResumeStackDeck('${safeDeckId}', -1)" aria-label="上一张卡片">‹</button>` : ""}
        ${safeItems.map((item, index) => `
          <article
            class="resume-stack-card ${escHtml(item.tone || options.tone || "tone-brand")}"
            data-card-index="${index}"
            data-position="hidden"
            role="button"
            tabindex="0"
            onclick="advanceResumeStackDeck('${safeDeckId}')"
            onkeydown="handleResumeStackDeckKey(event, '${safeDeckId}')"
          >
            <div class="resume-stack-card-head">
              <span class="resume-stack-order">${String(index + 1).padStart(2, "0")}</span>
              ${item.badge ? `<span class="resume-stack-badge">${escHtml(item.badge)}</span>` : ""}
            </div>
            ${item.label ? `<p class="resume-stack-label">${escHtml(item.label)}</p>` : ""}
            <p class="resume-stack-title">${escHtml(item.title || "待生成")}</p>
            <p class="resume-stack-copy">${escHtml(item.copy || "等待生成内容")}</p>
            ${item.note ? `<p class="resume-stack-note">${escHtml(item.note)}</p>` : ""}
          </article>
        `).join("")}
        ${!isSingle ? `<button type="button" class="resume-stack-arrow next" onclick="shiftResumeStackDeck('${safeDeckId}', 1)" aria-label="下一张卡片">›</button>` : ""}
      </div>
      <div class="resume-stack-footer ${isSingle ? "single" : ""}">
        <div class="resume-stack-dots">
          ${safeItems.map((_, index) => `<button type="button" class="resume-stack-dot" data-dot-index="${index}" onclick="setResumeStackDeck('${safeDeckId}', ${index})" aria-label="查看第 ${index + 1} 张卡片"></button>`).join("")}
        </div>
        <span class="resume-stack-progress">1 / ${safeItems.length}</span>
      </div>
    </div>
  `;
}

function getResumeStackDeck(deckId) {
  return document.querySelector(`[data-resume-deck="${String(deckId || "").replace(/"/g, '\\"')}"]`);
}

function updateResumeStackDeck(deckId, nextIndex = 0) {
  const deck = getResumeStackDeck(deckId);
  if (!deck) return;
  const cards = Array.from(deck.querySelectorAll(".resume-stack-card"));
  if (!cards.length) return;
  const total = cards.length;
  const normalizedIndex = ((Number(nextIndex) % total) + total) % total;
  resumeTaskState.deckIndices[deckId] = normalizedIndex;
  cards.forEach((card, index) => {
    const offset = (index - normalizedIndex + total) % total;
    const position = offset === 0 ? "active" : offset === 1 ? "next" : offset === 2 ? "later" : "hidden";
    card.dataset.position = position;
    card.setAttribute("aria-hidden", position === "active" ? "false" : "true");
  });
  deck.querySelectorAll(".resume-stack-dot").forEach((dot, index) => {
    dot.classList.toggle("active", index === normalizedIndex);
  });
  const progress = deck.querySelector(".resume-stack-progress");
  if (progress) progress.textContent = `${normalizedIndex + 1} / ${total}`;
}

function setResumeStackDeck(deckId, nextIndex) {
  updateResumeStackDeck(deckId, nextIndex);
}

function shiftResumeStackDeck(deckId, delta) {
  const current = Number(resumeTaskState.deckIndices[deckId] || 0);
  updateResumeStackDeck(deckId, current + Number(delta || 0));
}

function advanceResumeStackDeck(deckId) {
  shiftResumeStackDeck(deckId, 1);
}

function handleResumeStackDeckKey(event, deckId) {
  if (!event) return;
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    advanceResumeStackDeck(deckId);
  } else if (event.key === "ArrowLeft") {
    event.preventDefault();
    shiftResumeStackDeck(deckId, -1);
  } else if (event.key === "ArrowRight") {
    event.preventDefault();
    shiftResumeStackDeck(deckId, 1);
  }
}

function initResumeStackDecks(root = document) {
  root.querySelectorAll("[data-resume-deck]").forEach((deck) => {
    const deckId = String(deck.dataset.resumeDeck || "").trim();
    if (!deckId) return;
    const savedIndex = Number(resumeTaskState.deckIndices[deckId] || 0);
    updateResumeStackDeck(deckId, savedIndex);
  });
}

function resumeInsightCardsHtml(profile) {
  const items = Array.isArray(profile?.capability_layer) ? profile.capability_layer.slice(0, 3) : [];
  if (!items.length) {
    return `<div class="career-list-empty">等待生成重点判断</div>`;
  }
  const tones = ["tone-brand", "tone-calm", "tone-warm"];
  return resumeStackDeckHtml("resume-insights", items.map((item, index) => ({
    tone: tones[index % tones.length],
    label: item.dimension || "重点判断",
    badge: `${Math.round(Math.max(0, Math.min(1, Number(item.confidence || 0))) * 100)}%`,
    title: item.conclusion || "等待生成结论",
    copy: shortenResumeText(item.reasoning || item.evidence || "", 144),
    note: item.boundary ? `边界：${shortenResumeText(item.boundary, 84)}` : ""
  })), {
    variant: "analysis",
    emptyText: "等待生成重点判断"
  });
}

function resumeInsightPlaceholderHtml() {
  const items = [
    ["岗位理解", "这里会出现系统提炼的第一条重点判断。"],
    ["能力结构", "这里会总结简历最强和最弱的维度。"],
    ["风险判断", "这里会明确告诉你最值得优先修复的问题。"]
  ];
  return resumeStackDeckHtml("resume-insights", items.map((item, index) => ({
    tone: ["tone-brand", "tone-calm", "tone-warm"][index],
    label: item[0],
    badge: "--",
    title: "等待生成判断",
    copy: item[1]
  })), {
    variant: "analysis"
  });
}

function buildResumeGapItems(profile, matcher, analysisMode) {
  const gapItems = [];
  if (analysisMode !== "resume_review") {
    (Array.isArray(matcher?.missing_keywords) ? matcher.missing_keywords : []).slice(0, 4).forEach((item) => {
      gapItems.push({
        title: String(item || "").trim(),
        copy: "岗位侧明确提到，但当前简历没有给出足够证据。"
      });
    });
  }
  (Array.isArray(profile?.uncertainty_layer) ? profile.uncertainty_layer : []).slice(0, 4).forEach((item) => {
    gapItems.push({
      title: String(item?.item || item?.reason || "待确认信息").trim(),
      copy: String(item?.needed_evidence || item?.reason || "建议补充更直接的项目、结果或量化证据。").trim()
    });
  });
  const deduped = [];
  const seen = new Set();
  gapItems.forEach((item) => {
    const key = `${item.title}::${item.copy}`;
    if (!item.title || seen.has(key)) return;
    seen.add(key);
    deduped.push(item);
  });
  return deduped.slice(0, 4);
}

function resumeGapPanelHtml(profile, matcher, analysisMode) {
  const items = buildResumeGapItems(profile, matcher, analysisMode);
  const deckItems = items.length ? items.map((item, index) => ({
    tone: ["tone-warm", "tone-rose", "tone-calm", "tone-brand"][index % 4],
    label: index === 0 ? "优先补强" : "补强项",
    badge: `0${index + 1}`,
    title: item.title,
    copy: shortenResumeText(item.copy, 126),
    note: index === 0 ? "建议优先补齐这张卡，再继续看下一项。" : ""
  })) : [{
    tone: "tone-mint",
    label: "当前状态",
    badge: "OK",
    title: "当前没有明显待补强项",
    copy: "系统暂时没有识别出高优先级缺口，可以把注意力放到投递和面试反馈上。"
  }];
  return `
    <section class="resume-bento-card resume-bento-span-4">
      <div class="resume-bento-head">
        <div>
          <p class="resume-bento-kicker">Gap Focus</p>
          <p class="resume-bento-title">待补强项</p>
        </div>
      </div>
      ${resumeStackDeckHtml("resume-gaps", deckItems, {
        variant: "compact",
        emptyText: "当前没有明显待补强项"
      })}
    </section>
  `;
}

function resumeGapPlaceholderHtml() {
  return `
    <section class="resume-bento-card resume-bento-span-4 is-placeholder">
      <div class="resume-bento-head">
        <div>
          <p class="resume-bento-kicker">Gap Focus</p>
          <p class="resume-bento-title">待补强项</p>
        </div>
      </div>
      ${resumeStackDeckHtml("resume-gaps", [{
        tone: "tone-warm",
        label: "待补强项",
        badge: "01",
        title: "等待分析",
        copy: "系统会把岗位缺口、简历信息空白和待确认风险拆成更直接的补强项。"
      }], {
        variant: "compact"
      })}
    </section>
  `;
}

function buildResumeActionItems(profile, matcher, analysisMode, recommendedDirections) {
  const actions = [];
  const basics = profile?.basics && typeof profile.basics === "object" ? profile.basics : {};
  const missingKeywords = Array.isArray(matcher?.missing_keywords) ? matcher.missing_keywords : [];
  const uncertainty = Array.isArray(profile?.uncertainty_layer) ? profile.uncertainty_layer : [];
  const projectHighlights = Array.isArray(profile?.project_highlights) ? profile.project_highlights : [];
  const leadershipSignals = Array.isArray(profile?.leadership_signals) ? profile.leadership_signals : [];
  const targetDirection = recommendedDirections[0] || normalizeResumeBasicValue(basics.target_direction) || "目标方向";

  if (analysisMode === "resume_review") {
    actions.push({
      label: "方向收敛",
      title: `先验证 ${targetDirection}`,
      copy: "先用 1 到 2 个岗位名称收敛投递范围，再围绕这些岗位改写简历关键词和项目标题。"
    });
  } else if (missingKeywords.length) {
    actions.push({
      label: "补关键词",
      title: `优先补进 ${missingKeywords.slice(0, 2).join(" / ")}`,
      copy: "不要只堆技能词，直接把动作、场景和结果写进经历句子里，让岗位要求和简历证据对上。"
    });
  }

  if (uncertainty.length) {
    actions.push({
      label: "补证据",
      title: `把“${String(uncertainty[0]?.item || uncertainty[0]?.reason || "关键信号").trim()}”写实`,
      copy: "优先补充项目规模、角色边界、具体动作和量化结果，减少 HR 对真实性和深度的疑问。"
    });
  }

  if (projectHighlights.length < 2) {
    actions.push({
      label: "补经历",
      title: "增加一段可量化项目",
      copy: "优先写最能证明执行力和业务理解的经历，格式尽量变成“做了什么 + 结果如何 + 影响多大”。"
    });
  }

  if (leadershipSignals.length < 2) {
    actions.push({
      label: "强化表达",
      title: "把主动动作写在句首",
      copy: "少用参与、协助，多用主导、推进、负责、完成，并补上对象、方法和结果。"
    });
  }

  if (!actions.length) {
    actions.push({
      label: "继续推进",
      title: "保持当前版本并开始投递",
      copy: "当前画像没有明显短板，建议优先投递最匹配的岗位，同时根据面试反馈做小步快改。"
    });
  }

  return actions.slice(0, 3);
}

function resumeActionPanelHtml(profile, matcher, analysisMode, recommendedDirections, wide = false) {
  const items = buildResumeActionItems(profile, matcher, analysisMode, recommendedDirections);
  const deckItems = items.map((item, index) => ({
    tone: ["tone-brand", "tone-mint", "tone-calm"][index % 3],
    label: item.label,
    badge: `0${index + 1}`,
    title: item.title,
    copy: shortenResumeText(item.copy, wide ? 168 : 132),
    note: index === 0 ? "点击卡片可继续看下一条建议，适合一步步执行。" : ""
  }));
  return `
    <section class="resume-bento-card ${wide ? "resume-bento-span-8" : "resume-bento-span-4"} resume-action-panel">
      <div class="resume-bento-head">
        <div>
          <p class="resume-bento-kicker">Action Plan</p>
          <p class="resume-bento-title">操作建议</p>
        </div>
      </div>
      ${resumeStackDeckHtml("resume-actions", deckItems, {
        variant: wide ? "analysis" : "compact"
      })}
    </section>
  `;
}

function resumeActionPlaceholderHtml() {
  return `
    <section class="resume-bento-card resume-bento-span-8 resume-action-panel is-placeholder">
      <div class="resume-bento-head">
        <div>
          <p class="resume-bento-kicker">Action Plan</p>
          <p class="resume-bento-title">操作建议</p>
        </div>
      </div>
      ${resumeStackDeckHtml("resume-actions", [
        {
          tone: "tone-brand",
          label: "上传简历",
          badge: "01",
          title: "先完成简历文本解析",
          copy: "上传 PDF 或 DOCX 后，系统会提取经历、项目、技能和关键信号，开始建立能力画像。"
        },
        {
          tone: "tone-mint",
          label: "补充方向",
          badge: "02",
          title: "JD 可写可不写",
          copy: "如果你没有明确目标岗位，可以先留空，系统会先从简历本身给出方向判断和改写建议。"
        }
      ], {
        variant: "analysis"
      })}
    </section>
  `;
}

function resumeProjectHighlightsHtml(profile) {
  const items = Array.isArray(profile?.project_highlights) ? profile.project_highlights.slice(0, 3) : [];
  if (!items.length) return "";
  return `
    <section class="resume-bento-card resume-bento-span-8">
      <div class="resume-bento-head">
        <div>
          <p class="resume-bento-kicker">Highlights</p>
          <p class="resume-bento-title">亮点经历</p>
        </div>
      </div>
      <div class="resume-project-grid">
        ${items.map((item) => {
          const impactTags = previewTagValues(String(item.impact || "").split(/[、,，]/).map((part) => part.trim()).filter(Boolean), 3);
          return `
            <article class="resume-project-card">
              <div class="resume-project-head">
                <p class="resume-project-title">${escHtml(item.project || "项目亮点")}</p>
                ${item.role ? `<span class="resume-project-role">${escHtml(item.role)}</span>` : ""}
              </div>
              ${impactTags.length ? `<div class="resume-project-tags">${impactTags.map((tag) => `<span class="resume-project-tag">${escHtml(tag)}</span>`).join("")}</div>` : ""}
              <p class="resume-project-copy">${escHtml(shortenResumeText(item.evidence || "等待补充项目说明", 132))}</p>
            </article>
          `;
        }).join("")}
      </div>
    </section>
  `;
}

function resumeEmptyDashboardHtml(state) {
  const status = String(state?.status || "").trim();
  const hasFile = Boolean(state?.file_name);
  const bannerTitle = status === "failed"
    ? "本次分析未生成结果"
    : hasFile
      ? "简历已上传，等待开始匹配"
      : "等待生成诊断报告";
  const bannerCopy = status === "failed"
    ? (humanizeResumeErrorMessage(state?.error_message || state?.analysis_meta?.stage_detail || "") || "当前没有得到可展示的分析结果，建议检查文件内容后重试。")
    : hasFile
      ? "这份简历已经保存到当前账号，但系统还没有开始生成完整报告。点击“开始匹配”后，这里会切换为新的报告式布局。"
      : "上传简历并完成匹配后，这里会直接展示报告式分析，不再是当前这种概览卡片拼盘。";
  return `
    <div class="resume-judge-shell is-placeholder">
      <section class="resume-judge-hero is-placeholder">
        <div class="resume-judge-hero-main">
          <div class="resume-judge-hero-top">
            <div>
              <span class="resume-judge-badge muted">待生成</span>
              <h4 class="resume-judge-title">${escHtml(bannerTitle)}</h4>
              <p class="resume-judge-copy">${escHtml(bannerCopy)}</p>
            </div>
            <div class="resume-judge-actions">
              <button type="button" class="resume-judge-action-btn primary" onclick="pickResumeFile()">上传简历</button>
              <button type="button" class="resume-judge-action-btn" onclick="analyzeResumeMatch()" ${hasFile ? "" : "disabled"}>开始匹配</button>
            </div>
          </div>
          <p class="resume-judge-meta">${hasFile ? `文件：${escHtml(state.file_name || "")}` : "上传 PDF 或 DOCX 后，这里会生成完整分析。"}</p>
          <div class="resume-judge-score-grid">
            <article class="resume-judge-score-card primary"><span class="resume-judge-score-value">--</span><span class="resume-judge-score-label">综合评分</span></article>
            <article class="resume-judge-score-card"><span class="resume-judge-score-value">--</span><span class="resume-judge-score-label">岗位匹配</span></article>
            <article class="resume-judge-score-card warm"><span class="resume-judge-score-value">--</span><span class="resume-judge-score-label">故事线</span></article>
            <article class="resume-judge-score-card success"><span class="resume-judge-score-value">--</span><span class="resume-judge-score-label">技术深度</span></article>
            <article class="resume-judge-score-card"><span class="resume-judge-score-value">--</span><span class="resume-judge-score-label">格式规范</span></article>
          </div>
        </div>
      </section>

      <div class="resume-judge-empty-card">
        <div class="resume-judge-empty-copy">
          <p class="resume-judge-empty-title">${escHtml(status === "failed" ? "请先修正文件后再重新匹配" : "分析完成后，这里会切换成和 2.html 同一类的报告式排版")}</p>
          <p class="resume-judge-empty-text">${escHtml(bannerCopy)}</p>
        </div>
        <div class="resume-judge-tabbar is-placeholder">
          <button type="button" class="resume-judge-tab-btn active" disabled>01 30 秒结论</button>
          <button type="button" class="resume-judge-tab-btn" disabled>02 详细诊断</button>
          <button type="button" class="resume-judge-tab-btn" disabled>03 优化建议</button>
          <button type="button" class="resume-judge-tab-btn" disabled>04 简历范本</button>
          <button type="button" class="resume-judge-tab-btn" disabled>05 最终裁决</button>
        </div>
      </div>
    </div>
  `;
}

function resumeEvidencePlaceholderHtml() {
  const groups = [
    ["来自简历", "系统会从简历原文中截取关键证据片段。"],
    ["行为信号", "这里会聚合推进、主导、沟通协作等行为信号。"],
    ["待确认", "这里会列出需要继续补证据的空白点。"]
  ];
  return `<div class="resume-evidence-grid">${groups.map((item) => `
    <section class="resume-evidence-group neutral is-placeholder">
      <div class="resume-evidence-group-head">
        <p class="resume-evidence-group-title">${escHtml(item[0])}</p>
        <span class="resume-evidence-group-count">--</span>
      </div>
      <div class="resume-evidence-group-list">
        <article class="resume-evidence-entry">
          <p class="resume-evidence-title">等待生成</p>
          <p class="resume-evidence-copy">${escHtml(item[1])}</p>
        </article>
      </div>
    </section>
  `).join("")}</div>`;
}

function resumePlainText(raw) {
  return decodeHtmlEntities(String(raw || "").replace(/<[^>]+>/g, " "))
    .replace(/\s+/g, " ")
    .trim();
}

function resumeMarkdownSections(raw) {
  const lines = String(raw || "").replace(/\r\n/g, "\n").split("\n");
  const blocks = [];
  let paragraphLines = [];
  let listItems = [];
  let listType = "";
  let inCodeBlock = false;
  let codeBlockLines = [];

  function flushParagraph() {
    if (!paragraphLines.length) return;
    blocks.push({
      type: "paragraph",
      html: resumeInlineMarkupHtml(paragraphLines.join(" "))
    });
    paragraphLines = [];
  }

  function flushList() {
    if (!listItems.length) return;
    blocks.push({
      type: "list",
      listType,
      items: [...listItems]
    });
    listItems = [];
    listType = "";
  }

  lines.forEach((rawLine) => {
    const line = String(rawLine || "").trim();
    if (inCodeBlock) {
      if (/^```/.test(line)) {
        inCodeBlock = false;
        blocks.push({ type: "codeblock", code: codeBlockLines.join("\n") });
        codeBlockLines = [];
      } else {
        codeBlockLines.push(rawLine);
      }
      return;
    }
    if (!line) {
      flushParagraph();
      flushList();
      return;
    }
    if (/^```/.test(line)) {
      flushParagraph();
      flushList();
      inCodeBlock = true;
      codeBlockLines = [];
      return;
    }
    if (/^-{3,}$/.test(line)) {
      flushParagraph();
      flushList();
      blocks.push({ type: "divider" });
      return;
    }
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      flushList();
      blocks.push({
        type: "heading",
        level: heading[1].length,
        html: resumeInlineMarkupHtml(heading[2])
      });
      return;
    }
    const ordered = line.match(/^\d+\.\s+(.+)$/);
    if (ordered) {
      flushParagraph();
      if (listType && listType !== "ol") flushList();
      listType = "ol";
      listItems.push(resumeInlineMarkupHtml(ordered[1]));
      return;
    }
    const checklist = line.match(/^[-*]\s+\[( |x)\]\s+(.+)$/i);
    if (checklist) {
      flushParagraph();
      if (listType && listType !== "ul") flushList();
      listType = "ul";
      const checked = checklist[1].toLowerCase() === "x";
      listItems.push(`<span class="resume-checklist-icon">${checked ? "✅" : "⬜"}</span> ${resumeInlineMarkupHtml(checklist[2])}`);
      return;
    }
    const unordered = line.match(/^[-*]\s+(.+)$/);
    if (unordered) {
      flushParagraph();
      if (listType && listType !== "ul") flushList();
      listType = "ul";
      listItems.push(resumeInlineMarkupHtml(unordered[1]));
      return;
    }
    flushList();
    paragraphLines.push(line);
  });

  if (inCodeBlock && codeBlockLines.length) {
    blocks.push({ type: "codeblock", code: codeBlockLines.join("\n") });
  }

  flushParagraph();
  flushList();

  const sectionParts = [];
  let currentSection = null;

  function pushCurrentSection() {
    if (!currentSection) return;
    if (!currentSection.intro && !currentSection.content.length) return;
    sectionParts.push(currentSection);
  }

  blocks.forEach((block) => {
    if (block.type === "heading" && block.level <= 2) {
      pushCurrentSection();
      currentSection = {
        title: block.html,
        intro: "",
        content: []
      };
      return;
    }
    if (!currentSection) {
      currentSection = {
        title: "分析内容",
        intro: "",
        content: []
      };
    }
    if (block.type === "paragraph" && !currentSection.intro) {
      currentSection.intro = block.html;
      return;
    }
    currentSection.content.push(block);
  });

  pushCurrentSection();
  return sectionParts;
}

function resumeSectionsFromState(state) {
  const markdown = String(state?.analysis_result || "").trim();
  if (markdown) return resumeMarkdownSections(markdown);
  const htmlText = resumeAnalysisHtmlToText(state?.analysis_html);
  if (htmlText) return resumeMarkdownSections(htmlText);
  return [];
}

function resumeFindSectionByKeywords(sections, keywords, fallbackIndex = 0) {
  const patterns = (keywords || []).map((item) => String(item || "").toLowerCase()).filter(Boolean);
  const matched = (sections || []).find((section) => {
    const title = resumePlainText(section?.title || "").toLowerCase();
    return patterns.some((pattern) => title.includes(pattern));
  });
  if (matched) return matched;
  return sections?.[fallbackIndex] || null;
}

function resumeFindGroupByKeywords(section, keywords) {
  const patterns = (keywords || []).map((item) => String(item || "").toLowerCase()).filter(Boolean);
  const groups = resumeReportBlocksPartition(section?.content || []).groups;
  return groups.find((group) => {
    const title = resumePlainText(group?.title || "").toLowerCase();
    return patterns.some((pattern) => title.includes(pattern));
  }) || null;
}

function resumeFlattenBlocks(blocks) {
  const items = [];
  (blocks || []).forEach((block) => {
    if (block.type === "paragraph") {
      const text = resumePlainText(block.html);
      if (text) items.push(text);
      return;
    }
    if (block.type === "list") {
      block.items.forEach((item) => {
        const text = resumePlainText(item);
        if (text) items.push(text);
      });
      return;
    }
    if (block.type === "codeblock") {
      const text = String(block.code || "").trim();
      if (text) items.push(text);
    }
  });
  return items;
}

function resumeJudgeVerdictPayload(state, profile, matcher, analysisMode, recommendedDirections, conclusionItems) {
  const overall = resumeJudgeOverallScore(profile, matcher, analysisMode, recommendedDirections);
  let tone = "brand";
  let icon = "→";
  let title = "建议进入下一轮";
  if (overall >= 86) {
    tone = "success";
    icon = "✓";
    title = "建议优先推进";
  } else if (overall < 70) {
    tone = "danger";
    icon = "!";
    title = "建议补强后再投递";
  }
  const overview = matcher?.resume_overview && typeof matcher.resume_overview === "object" ? matcher.resume_overview : {};
  return {
    tone,
    icon,
    title,
    role: overview.headline || profile?.basics?.target_direction || "待识别方向",
    reason: conclusionItems[1] || profile?.candidate_summary || "系统已根据当前简历生成结构化判断。",
    summary: conclusionItems[0] || profile?.candidate_summary || "等待生成总结。"
  };
}

function resumeJudgeQuickStatItems(state, profile, matcher, analysisMode, recommendedDirections) {
  const overview = matcher?.resume_overview && typeof matcher.resume_overview === "object" ? matcher.resume_overview : {};
  const textSources = Array.isArray(state?.analysis_meta?.text_sources) ? state.analysis_meta.text_sources : [];
  return [
    ["综合评分", `${resumeJudgeOverallScore(profile, matcher, analysisMode, recommendedDirections)}%`],
    ["识别角色", overview.headline || "待识别"],
    ["经历段数", `${Number(overview.experience_count || 0)} 段`],
    ["项目数量", `${Number(overview.project_count || 0)} 个`],
    ["技能覆盖", `${Number(overview.skill_count || 0)} 项`],
    ["提取方式", textSources[0] || (state?.analysis_meta?.ocr_used ? "OCR" : "文本解析")]
  ];
}

function resumeJudgeRiskItems(detailSection, matcher, profile) {
  const riskGroup = resumeFindGroupByKeywords(detailSection, ["风险", "缺口", "risk", "gap"]);
  const groupItems = resumeFlattenBlocks(riskGroup?.blocks || []);
  if (groupItems.length) return groupItems.slice(0, 4);
  const uncertainty = Array.isArray(profile?.uncertainty_layer) ? profile.uncertainty_layer : [];
  if (uncertainty.length) {
    return uncertainty.slice(0, 4).map((item) => String(item?.reason || item?.item || "").trim()).filter(Boolean);
  }
  const missing = previewTagValues(matcher?.missing_keywords || [], 4);
  if (missing.length) {
    return missing.map((item) => `缺少与目标岗位强相关的关键词：${item}`);
  }
  return ["当前结果里没有结构化风险项，建议重点补充业务背景、量化结果和个人独立贡献。"];
}

function resumeJudgeModuleAuditItems(state, profile, matcher) {
  const structured = state?.structured_resume && typeof state.structured_resume === "object" ? state.structured_resume : {};
  const education = Array.isArray(structured.education) ? structured.education : [];
  const experiences = Array.isArray(structured.experiences) ? structured.experiences : [];
  const projects = Array.isArray(structured.projects) ? structured.projects : [];
  const skills = Array.isArray(structured.skills) ? structured.skills : [];
  const research = Array.isArray(structured.research_work) ? structured.research_work : [];

  const educationDetails = education.map((item) => {
    const parts = [resumePlainText(item.institution), resumePlainText(item.field_of_study), resumePlainText(item.degree)].filter(Boolean);
    const dateRange = [resumePlainText(item.start_date), resumePlainText(item.end_date)].filter(Boolean).join(" - ");
    return {
      main: parts.join(" · "),
      meta: [dateRange, item.grade ? resumePlainText(item.grade) : ""].filter(Boolean).join(" | "),
      desc: []
    };
  });

  const experienceDetails = experiences.map((item) => {
    const dateRange = [resumePlainText(item.start_date), resumePlainText(item.end_date)].filter(Boolean).join(" - ");
    const descItems = Array.isArray(item.description) ? item.description : [];
    return {
      main: [resumePlainText(item.company), resumePlainText(item.job_title)].filter(Boolean).join(" | "),
      meta: dateRange,
      desc: descItems.slice(0, 2).map((d) => shortenResumeText(resumePlainText(d), 90)).filter(Boolean)
    };
  });

  const projectDetails = projects.map((item) => {
    const dateRange = [resumePlainText(item.start_date), resumePlainText(item.end_date)].filter(Boolean).join(" - ");
    return {
      main: resumePlainText(item.project_name),
      meta: dateRange,
      desc: item.description ? [shortenResumeText(resumePlainText(item.description), 90)] : []
    };
  });

  const skillsByCategory = skills.reduce((acc, item) => {
    const cat = resumePlainText(item.category || "其他");
    if (!acc[cat]) acc[cat] = [];
    const skillName = resumePlainText(item.skill_name);
    if (skillName) acc[cat].push(skillName);
    return acc;
  }, {});
  const skillDetails = Object.entries(skillsByCategory).map(([cat, items]) => ({
    main: cat,
    meta: items.join("、"),
    desc: []
  }));

  const items = [
    {
      title: "教育背景",
      text: education.length
        ? `已识别 ${education.length} 段教育信息。学术项较强，建议把排名、绩点、论文与专利放在更靠前的位置。`
        : "当前没有识别到清晰教育信息，建议补齐学校、专业、时间与核心成绩。",
      details: educationDetails
    },
    {
      title: "实习经历",
      text: experiences.length
        ? `已识别 ${experiences.length} 段实习/工作经历。当前最大的短板通常在于业务背景、个人贡献和结果量化表达不足。`
        : "当前没有识别到稳定的实习或工作经历模块，建议至少补一段真实项目或实习经历。",
      details: experienceDetails
    },
    {
      title: "项目经历",
      text: projects.length
        ? `已识别 ${projects.length} 个项目。项目题材足够强，但需要再向"业务价值、技术决策、可验证结果"三件事收口。`
        : "项目经历过少，难以支撑岗位判断，建议补齐 2 到 3 个高质量项目。",
      details: projectDetails
    },
    {
      title: "技能模块",
      text: skills.length
        ? `已识别 ${skills.length} 项技能。建议按"语言 / 框架 / 技术方向 / 工具"分组，而不是一行平铺。`
        : '技能项过少，建议拆出独立"专业技能"模块并做分组呈现。',
      details: skillDetails
    }
  ];

  if (research.length) {
    const researchDetails = research.map((item) => ({
      main: resumePlainText(item.title),
      meta: resumePlainText(item.publication || item.description || ""),
      desc: []
    }));
    items.push({
      title: "论文 / 专利",
      text: `已识别 ${research.length} 项学术成果。学术背景是竞争优势，建议在简历顶部或教育模块后单独列出。`,
      details: researchDetails
    });
  }

  return items;
}

function resumeJudgeEvidenceAuditItems(profile) {
  const evidence = Array.isArray(profile?.evidence_spans) ? profile.evidence_spans : [];
  if (!evidence.length) {
    return [{
      quote: "等待生成证据片段",
      note: "分析完成后，这里会引用简历原文并指出每条描述还缺什么。",
      tags: []
    }];
  }
  return evidence.map((item) => {
    const quote = String(item?.quote || "").trim();
    const tags = [];
    const notes = [];
    if (!/\d/.test(quote)) { notes.push("建议补充量化结果"); tags.push("缺数据"); }
    if (/负责|协助|参与/.test(quote)) { notes.push("动词偏弱，建议改成主导 / 设计 / 实现"); tags.push("动词弱"); }
    if (!notes.length) { notes.push("建议补充业务背景或边界条件"); tags.push("缺背景"); }
    return {
      quote,
      note: notes.join("；"),
      tags
    };
  });
}

function resumeJudgeQuestionItems(state, profile, riskItems) {
  const questions = [];
  const highlights = Array.isArray(profile?.project_highlights) ? profile.project_highlights.slice(0, 2) : [];
  highlights.forEach((item) => {
    const project = String(item?.project || "").trim();
    if (project) {
      questions.push(`围绕“${project}”，准备一句 STAR 表达：问题背景、你的动作、可验证结果分别是什么？`);
    }
  });
  if (riskItems[0]) questions.push(`如果面试官追问“${riskItems[0]}”，你准备用哪组数据回应？`);
  const uncertainty = Array.isArray(profile?.uncertainty_layer) ? profile.uncertainty_layer : [];
  uncertainty.slice(0, 2).forEach((item) => {
    const title = String(item?.item || "").trim();
    if (title) questions.push(`针对“${title}”，你还能补充哪些证据来降低面试官的不确定感？`);
  });
  return questions.slice(0, 6);
}

function resumeJudgeQuantTips() {
  return [
    ["性能类", "把“优化性能”改成“响应时间从 Xms 降到 Yms，P99 下降 Z%”。"],
    ["规模类", "把“大量数据”改成“日均处理 N 条记录 / 支撑 N 次请求”。"],
    ["效率类", "把“提升开发效率”改成“发布时间从 X 小时缩短到 Y 分钟”。"],
    ["质量类", "把“系统更稳定”改成“MTTR 降低 X%，可用性提升到 Y%”。"]
  ];
}

function resumeJudgeTemplateText(state, profile, matcher) {
  const structured = state?.structured_resume && typeof state.structured_resume === "object" ? state.structured_resume : {};
  const personal = structured.personal_data && typeof structured.personal_data === "object" ? structured.personal_data : {};
  const name = [personal.first_name, personal.last_name].filter(Boolean).join(" ") || profile?.basics?.name || matcher?.resume_overview?.candidate_name || "候选人";
  const contacts = [personal.phone, personal.email, personal.linkedin, personal.portfolio].filter(Boolean);
  const lines = [name];
  if (contacts.length) lines.push(contacts.join(" | "));
  if (profile?.candidate_summary) {
    lines.push("", "【个人摘要】", resumePlainText(profile.candidate_summary));
  }
  const education = Array.isArray(structured.education) ? structured.education : [];
  if (education.length) {
    lines.push("", "【教育背景】");
    education.slice(0, 2).forEach((item) => {
      lines.push(`${resumePlainText(item.institution)} | ${resumePlainText(item.field_of_study)} | ${resumePlainText(item.degree)} | ${resumePlainText(item.start_date)} - ${resumePlainText(item.end_date)}`);
      if (item.grade) lines.push(`- ${resumePlainText(item.grade)}`);
      if (item.description) lines.push(`- ${shortenResumeText(resumePlainText(item.description), 180)}`);
    });
  }
  const experiences = Array.isArray(structured.experiences) ? structured.experiences : [];
  if (experiences.length) {
    lines.push("", "【实习 / 工作经历】");
    experiences.slice(0, 3).forEach((item) => {
      lines.push(`${resumePlainText(item.company)} | ${resumePlainText(item.job_title)} | ${resumePlainText(item.start_date)} - ${resumePlainText(item.end_date)}`);
      (Array.isArray(item.description) ? item.description : []).slice(0, 3).forEach((desc) => {
        lines.push(`- ${shortenResumeText(resumePlainText(desc), 160)}`);
      });
    });
  }
  const projects = Array.isArray(structured.projects) ? structured.projects : [];
  if (projects.length) {
    lines.push("", "【项目经历】");
    projects.slice(0, 3).forEach((item) => {
      lines.push(`${resumePlainText(item.project_name)} | ${resumePlainText(item.start_date)} - ${resumePlainText(item.end_date)}`);
      lines.push(`- ${shortenResumeText(resumePlainText(item.description), 180)}`);
    });
  }
  const research = Array.isArray(structured.research_work) ? structured.research_work : [];
  if (research.length) {
    lines.push("", "【论文 / 专利】");
    research.slice(0, 4).forEach((item) => {
      lines.push(`- ${resumePlainText(item.title)} | ${resumePlainText(item.publication || item.description)}`);
    });
  }
  const skills = Array.isArray(structured.skills) ? structured.skills : [];
  if (skills.length) {
    const byCategory = skills.reduce((acc, item) => {
      const category = resumePlainText(item.category || "技能");
      if (!acc[category]) acc[category] = [];
      acc[category].push(resumePlainText(item.skill_name));
      return acc;
    }, {});
    lines.push("", "【专业技能】");
    Object.entries(byCategory).forEach(([category, items]) => {
      lines.push(`${category}：${items.filter(Boolean).join("、")}`);
    });
  }
  const achievements = Array.isArray(structured.achievements) ? structured.achievements : [];
  if (achievements.length) {
    lines.push("", "【荣誉与获奖】");
    achievements.slice(0, 6).forEach((item) => lines.push(`- ${resumePlainText(item)}`));
  }
  return lines.join("\n");
}

function resumeJudgeComparisonItems(profile, matcher, analysisMode, recommendedDirections) {
  return [
    ["综合评分", resumeJudgeOverallScore(profile, matcher, analysisMode, recommendedDirections), 88],
    ["岗位匹配", resumeJudgeMatchScore(profile, matcher, analysisMode, recommendedDirections), 85],
    ["故事线", resumeJudgeStoryScore(profile, matcher), 82],
    ["技术深度", resumeJudgeTechScore(profile), 84],
    ["格式规范", resumeJudgeFormatScore(profile, matcher), 80]
  ];
}

function resumeJudgeFixedTabsHtml() {
  const tabs = ["第一印象", "深度审计", "修改蓝图", "简历范本", "最终裁决"];
  return tabs.map((label, index) => `
    <button type="button" class="resume-hj-tab-btn ${index === 0 ? "active" : ""}" data-section-index="${index + 1}" onclick="switchResumeJudgeTab(${index + 1})">
      ${String(index + 1).padStart(2, "0")} ${label}
    </button>
  `).join("");
}

function resumeJudgeExactEmptyDashboardHtml(state) {
  const hasFile = Boolean(state?.file_name);
  const copy = hasFile
    ? "简历已经上传，点击“开始匹配”后会生成和 2.html 同构的五步报告。"
    : "先上传 PDF 或 DOCX，然后开始匹配。这里会切换成 2.html 的五步分析页面。";
  return `
    <div id="resumeJudgeShell" class="resume-hj-shell">
      <section class="resume-hj-header-card">
        <div class="resume-hj-header-top">
          <div>
            <div class="resume-hj-badge-row">
              <span class="resume-hj-badge">诊断报告</span>
              <span class="resume-hj-mode">待生成</span>
            </div>
            <h3 class="resume-hj-title">简历诊断报告</h3>
            <p class="resume-hj-subtitle">${escHtml(copy)}</p>
          </div>
          <div class="resume-hj-header-actions">
            <button type="button" class="resume-hj-action-btn primary" onclick="pickResumeFile()">上传简历</button>
            <button type="button" class="resume-hj-action-btn" onclick="analyzeResumeMatch()" ${hasFile ? "" : "disabled"}>开始匹配</button>
          </div>
        </div>
        <div class="resume-hj-score-grid">
          ${["综合评分", "岗位匹配", "故事线", "技术深度", "格式规范"].map((label) => `
            <article class="resume-hj-score-card">
              <div class="resume-hj-score-value">--</div>
              <div class="resume-hj-score-label">${label}</div>
            </article>
          `).join("")}
        </div>
      </section>
      <div class="resume-hj-tabs">${resumeJudgeFixedTabsHtml()}</div>
      <section class="resume-hj-panel active" data-section-index="1">
        <div class="resume-hj-card">
          <h4 class="resume-hj-card-title">等待分析</h4>
          <p class="resume-hj-card-copy">${escHtml(copy)}</p>
        </div>
      </section>
      ${[2, 3, 4, 5].map((index) => `<section class="resume-hj-panel" data-section-index="${index}"></section>`).join("")}
    </div>
  `;
}

function resumeJudgeExactDashboardHtml(state, profile, matcher, analysisMode, recommendedDirections) {
  const sections = resumeSectionsFromState(state);
  const conclusionSection = resumeFindSectionByKeywords(sections, ["30 秒结论", "30秒结论", "30 绉掔粨璁"], 1);
  const detailSection = resumeFindSectionByKeywords(sections, ["详细诊断", "璇︾粏"], 2);
  const adviceSection = resumeFindSectionByKeywords(sections, ["简历优化建议", "优化建议", "可立即执行"], 3);
  const conclusionItems = resumeFlattenBlocks(conclusionSection?.content || []);
  const adviceItems = resumeFlattenBlocks(adviceSection?.content || []);
  const riskItems = resumeJudgeRiskItems(detailSection, matcher, profile);
  const strengthGroup = resumeFindGroupByKeywords(detailSection, ["优势", "strength"]);
  const suggestionGroup = resumeFindGroupByKeywords(detailSection, ["方向", "建议", "suggest"]);
  const verdict = resumeJudgeVerdictPayload(state, profile, matcher, analysisMode, recommendedDirections, conclusionItems);
  const quickStats = resumeJudgeQuickStatItems(state, profile, matcher, analysisMode, recommendedDirections);
  const moduleAuditItems = resumeJudgeModuleAuditItems(state, profile, matcher);
  const evidenceAuditItems = resumeJudgeEvidenceAuditItems(profile);
  const questionItems = resumeJudgeQuestionItems(state, profile, riskItems);
  const quantTips = resumeJudgeQuantTips();
  const templateText = resumeJudgeTemplateText(state, profile, matcher);
  const comparisonItems = resumeJudgeComparisonItems(profile, matcher, analysisMode, recommendedDirections);
  const finalSummaryItems = [
    profile?.candidate_summary || verdict.summary,
    ...resumeFlattenBlocks(strengthGroup?.blocks || []).slice(0, 2),
    ...resumeFlattenBlocks(suggestionGroup?.blocks || []).slice(0, 1)
  ].filter(Boolean).slice(0, 4);
  const modeLabel = analysisMode === "resume_review" ? "简历诊断模式" : "岗位匹配模式";
  const subtitle = state?.analyzed_at
    ? `最近生成于 ${formatUnixTime(state.analyzed_at)}`
    : "等待分析";
  const overallScore = resumeJudgeOverallScore(profile, matcher, analysisMode, recommendedDirections);
  const matchScore = resumeJudgeMatchScore(profile, matcher, analysisMode, recommendedDirections);
  const projectScore = averageResumeScores([resumeJudgeStoryScore(profile, matcher), resumeJudgeTechScore(profile)]);
  const formatScore = resumeJudgeFormatScore(profile, matcher);
  const riskLevel = (() => {
    if (matchScore < 35 || overallScore < 65 || riskItems.length >= 4) return { label: "高", tone: "danger", desc: "建议先补强再推进" };
    if (matchScore < 60 || overallScore < 78 || riskItems.length >= 2) return { label: "中", tone: "warn", desc: "可推进但需重点追问" };
    return { label: "低", tone: "success", desc: "风险可控，可直接推进" };
  })();
  const scoreCards = [
    { label: "综合匹配", value: `${overallScore}%`, tone: "primary", desc: "整体进入下一轮潜力" },
    { label: "岗位命中", value: `${matchScore}%`, tone: matchScore < 45 ? "danger" : (matchScore < 70 ? "warn" : "success"), desc: "JD 关键词贴合程度" },
    { label: "项目相关性", value: `${projectScore}%`, tone: projectScore >= 75 ? "success" : "brand", desc: "项目与目标方向一致性" },
    { label: "风险等级", value: riskLevel.label, tone: riskLevel.tone, desc: riskLevel.desc }
  ];
  const textSources = Array.isArray(state?.analysis_meta?.text_sources) ? state.analysis_meta.text_sources : [];
  const sourceTags = [
    textSources[0] || (state?.analysis_meta?.ocr_used ? "OCR 提取" : "文本解析"),
    state?.analysis_meta?.ocr_used ? "中文+英文识别" : "结构化解析",
    "自动识别角色"
  ];
  const diagnosisText = conclusionItems[2] || profile?.candidate_summary || verdict.reason;
  const highlights = (resumeFlattenBlocks(strengthGroup?.blocks || []).slice(0, 4).length
    ? resumeFlattenBlocks(strengthGroup?.blocks || []).slice(0, 4)
    : (Array.isArray(profile?.project_highlights) ? profile.project_highlights.slice(0, 4).map((item) => item?.highlight || item?.project || "") : [])
  ).filter(Boolean);

  return `
    <div id="resumeJudgeShell" class="resume-hj-shell">
      <section class="resume-hj-header-card">
        <div class="resume-hj-header-top">
          <div>
            <div class="resume-hj-badge-row">
              <span class="resume-hj-badge">诊断报告</span>
              <span class="resume-hj-mode">${modeLabel}</span>
            </div>
            <h3 class="resume-hj-title">简历诊断报告</h3>
            <p class="resume-hj-subtitle">${escHtml(subtitle)}</p>
          </div>
          <div class="resume-hj-header-actions">
            <button type="button" class="resume-hj-action-btn primary" onclick="openResumeReportPage()">查看独立页</button>
            <button type="button" class="resume-hj-action-btn" onclick="analyzeResumeMatch()">重新匹配</button>
          </div>
        </div>
        <div class="resume-hj-score-grid">
          ${scoreCards.map((item) => `
            <article class="resume-hj-score-card ${item.tone || ""}">
              <div class="resume-hj-score-value">${escHtml(item.value)}</div>
              <div class="resume-hj-score-label">${escHtml(item.label)}</div>
              <div class="resume-hj-score-desc">${escHtml(item.desc)}</div>
            </article>
          `).join("")}
        </div>
      </section>

      <div class="resume-hj-tabs">
        ${resumeJudgeFixedTabsHtml()}
      </div>

      <section class="resume-hj-panel active" data-section-index="1">
        <section class="resume-hj-decision-grid">
          <article class="resume-hj-card resume-hj-decision-card ${verdict.tone}">
            <p class="resume-hj-decision-kicker">候选人匹配结论</p>
            <h4 class="resume-hj-decision-title">${escHtml(verdict.title)}</h4>
            <p class="resume-hj-decision-role">${escHtml(verdict.role || "方向识别中")}</p>
            <p class="resume-hj-decision-summary">${escHtml(verdict.summary || profile?.candidate_summary || "系统正在汇总候选人画像结论。")}</p>
            <p class="resume-hj-decision-copy">${escHtml(verdict.reason)}</p>
            <div class="resume-hj-tag-row">
              ${sourceTags.filter(Boolean).map((tag) => `<span class="resume-hj-tag">${escHtml(tag)}</span>`).join("")}
            </div>
          </article>
          <article class="resume-hj-card resume-hj-decision-side">
            <h4 class="resume-hj-side-title">快速扫描</h4>
            <div class="resume-hj-stat-list">
              ${quickStats.map((item) => `
                <div class="resume-hj-stat-row">
                  <span>${item[0]}</span>
                  <strong>${escHtml(String(item[1]))}</strong>
                </div>
              `).join("")}
            </div>
            <article class="resume-hj-alert-card ${riskLevel.tone}">
              <p class="resume-hj-alert-title">风险预警</p>
              <p class="resume-hj-alert-copy">${escHtml(riskLevel.desc)}</p>
            </article>
          </article>
        </section>

        <section class="resume-hj-analysis-grid">
          <div class="resume-hj-stack">
            <article class="resume-hj-card">
              <h4 class="resume-hj-card-title">初步诊断</h4>
              <p class="resume-hj-card-copy">${escHtml(diagnosisText)}</p>
            </article>
            <article class="resume-hj-card">
              <h4 class="resume-hj-card-title">优势亮点</h4>
              <div class="resume-hj-tag-row">
                ${highlights.length ? highlights.map((item) => `<span class="resume-hj-tag success">${escHtml(item)}</span>`).join("") : `<span class="resume-hj-tag">等待提炼优势亮点</span>`}
              </div>
            </article>
            <article class="resume-hj-card danger">
              <h4 class="resume-hj-card-title">关键短板</h4>
              <div class="resume-hj-risk-list">
                ${riskItems.map((item) => `<div class="resume-hj-risk-item">${escHtml(item)}</div>`).join("")}
              </div>
            </article>
          </div>
          <aside class="resume-hj-side-sticky">
            <article class="resume-hj-card">
              <h4 class="resume-hj-side-title">决策辅助栏</h4>
              <div class="resume-hj-action-list">
                ${questionItems.slice(0, 3).map((item, index) => `
                  <div class="resume-hj-action-item">
                    <span>${String(index + 1).padStart(2, "0")}</span>
                    <p>${escHtml(item)}</p>
                  </div>
                `).join("")}
              </div>
            </article>
          </aside>
        </section>
      </section>

      <section class="resume-hj-panel" data-section-index="2">
        <div class="resume-hj-stack">
          <article class="resume-hj-card">
            <h4 class="resume-hj-card-title"><span class="resume-hj-dot brand"></span>证据分析（结论 → 原因 → 证据）</h4>
            <div class="resume-hj-audit-grid">
              <div class="resume-hj-subcard">
                <p class="resume-hj-subcard-title">优势</p>
                <div class="resume-hj-subcard-content">
                  ${resumeReportBlocksHtml(strengthGroup?.blocks || []) || `<p class="resume-report-paragraph">${escHtml("等待生成优势诊断。")}</p>`}
                </div>
              </div>
              <div class="resume-hj-subcard">
                <p class="resume-hj-subcard-title">风险与缺口</p>
                <div class="resume-hj-subcard-content">
                  ${resumeReportBlocksHtml(resumeFindGroupByKeywords(detailSection, ["风险", "缺口", "risk", "gap"])?.blocks || []) || `<p class="resume-report-paragraph">${escHtml(riskItems[0] || "等待生成风险提示。")}</p>`}
                </div>
              </div>
            </div>
            ${(() => {
              const caps = profile?.capability_scores && typeof profile.capability_scores === "object" ? profile.capability_scores : null;
              if (!caps) return "";
              const labels = { communication: "表达沟通", execution: "执行落地", stress_resilience: "抗压韧性", innovation: "创新思维", collaboration: "协作配合", leadership: "领导潜力" };
              const entries = Object.entries(labels).map(([key, label]) => [label, Number(caps[key] || 0)]);
              return `
                <div class="resume-hj-cap-section">
                  <p class="resume-hj-subcard-title" style="margin-bottom:0.7rem">能力维度评分</p>
                  <div class="resume-hj-cap-grid">
                    ${entries.map(([label, score]) => `
                      <div class="resume-hj-cap-item">
                        <div class="resume-hj-cap-head">
                          <span>${escHtml(label)}</span>
                          <strong>${score}</strong>
                        </div>
                        <div class="resume-hj-cap-track">
                          <div class="resume-hj-cap-fill" style="width:${Math.min(100, score)}%"></div>
                        </div>
                      </div>
                    `).join("")}
                  </div>
                </div>
              `;
            })()}
          </article>

          <article class="resume-hj-card">
            <h4 class="resume-hj-card-title"><span class="resume-hj-dot warn"></span>模块逐项审计</h4>
            <div class="resume-hj-module-grid">
              ${moduleAuditItems.map((item) => `
                <article class="resume-hj-module-card">
                  <p class="resume-hj-module-title">${escHtml(item.title)}</p>
                  <p class="resume-hj-module-status ${item.details && item.details.length >= 2 ? "strong" : (item.details && item.details.length ? "weak" : "pending")}">${item.details && item.details.length >= 2 ? "强证据" : (item.details && item.details.length ? "弱证据" : "待补证")}</p>
                  <p class="resume-hj-module-copy">${escHtml(item.text)}</p>
                  ${item.details && item.details.length ? `
                    <div class="resume-hj-module-details">
                      ${item.details.map((d) => `
                        <div class="resume-hj-module-detail-item">
                          <div class="resume-hj-detail-main">${escHtml(d.main)}</div>
                          ${d.meta ? `<div class="resume-hj-detail-meta">${escHtml(d.meta)}</div>` : ""}
                          ${d.desc && d.desc.length ? d.desc.map((line) => `<div class="resume-hj-detail-desc">· ${escHtml(line)}</div>`).join("") : ""}
                        </div>
                      `).join("")}
                    </div>
                  ` : ""}
                </article>
              `).join("")}
            </div>
          </article>

          <article class="resume-hj-card">
            <h4 class="resume-hj-card-title"><span class="resume-hj-dot danger"></span>证据片段拷问</h4>
            <p class="resume-hj-card-copy" style="margin-bottom:0.9rem">系统从简历原文提取了以下 ${evidenceAuditItems.length} 条描述，逐一指出待改进的方向。</p>
            <div class="resume-hj-evidence-audit">
              ${evidenceAuditItems.map((item, idx) => `
                <article class="resume-hj-evidence-card">
                  <div class="resume-hj-evidence-head">
                    <span class="resume-hj-evidence-idx">${String(idx + 1).padStart(2, "0")}</span>
                    ${item.tags && item.tags.length ? item.tags.map((tag) => `<span class="resume-hj-evidence-tag">${escHtml(tag)}</span>`).join("") : ""}
                  </div>
                  <p class="resume-hj-evidence-quote">${escHtml(item.quote)}</p>
                  <p class="resume-hj-evidence-note">${escHtml(item.note)}</p>
                </article>
              `).join("")}
            </div>
          </article>
        </div>
      </section>

      <section class="resume-hj-panel" data-section-index="3">
        <div class="resume-hj-stack">
          <article class="resume-hj-card">
            <h4 class="resume-hj-card-title">写作公式</h4>
            <div class="resume-hj-formula-grid">
              <div class="resume-hj-formula-card">
                <p class="resume-hj-formula-title">STAR / CAR 基础公式</p>
                <ul class="resume-hj-formula-list">
                  <li>Situation: 问题发生在什么场景</li>
                  <li>Task: 你要解决的具体目标</li>
                  <li>Action: 你做了什么关键动作</li>
                  <li>Result: 最终带来了什么结果</li>
                </ul>
              </div>
              <div class="resume-hj-formula-card">
                <p class="resume-hj-formula-title">业务导向表达公式</p>
                <ul class="resume-hj-formula-list">
                  <li>背景: 这个模块解决什么业务问题</li>
                  <li>方案: 为什么选择当前技术路线</li>
                  <li>动作: 你主导了哪些关键环节</li>
                  <li>结果: 指标、效率、成本有什么变化</li>
                </ul>
              </div>
            </div>
          </article>

          <article class="resume-hj-card">
            <h4 class="resume-hj-card-title">修改蓝图</h4>
            <div class="resume-hj-blueprint-grid">
              ${adviceItems.slice(0, 4).map((item, index) => `
                <article class="resume-hj-blueprint-card">
                  <p class="resume-hj-blueprint-index">改法 ${String(index + 1).padStart(2, "0")}</p>
                  <p class="resume-hj-blueprint-copy">${escHtml(item)}</p>
                </article>
              `).join("") || `<article class="resume-hj-blueprint-card"><p class="resume-hj-blueprint-copy">${escHtml("等待生成可执行修改建议。")}</p></article>`}
            </div>
          </article>

          <article class="resume-hj-card">
            <h4 class="resume-hj-card-title">启发式追问清单</h4>
            <div class="resume-hj-question-list">
              ${questionItems.map((item) => `<div class="resume-hj-question-item">${escHtml(item)}</div>`).join("")}
            </div>
          </article>

          <article class="resume-hj-card">
            <h4 class="resume-hj-card-title">量化训练</h4>
            <div class="resume-hj-quant-grid">
              ${quantTips.map((item) => `
                <article class="resume-hj-quant-card">
                  <p class="resume-hj-quant-title">${escHtml(item[0])}</p>
                  <p class="resume-hj-quant-copy">${escHtml(item[1])}</p>
                </article>
              `).join("")}
            </div>
          </article>
        </div>
      </section>

      <section class="resume-hj-panel" data-section-index="4">
        <article class="resume-hj-card">
          <div class="resume-hj-card-head">
            <h4 class="resume-hj-card-title">原始证据 / 简历原文</h4>
            <button type="button" class="resume-hj-copy-btn" onclick="copyResumeCodeBlock('resumeJudgeFullResume')">复制全文</button>
          </div>
          <div class="resume-hj-evidence-tabs">
            <button type="button" id="resumeJudgeEvidenceTabStructured" class="resume-hj-evidence-tab active" onclick="switchResumeJudgeEvidenceView('structured')">结构化视图</button>
            <button type="button" id="resumeJudgeEvidenceTabRaw" class="resume-hj-evidence-tab" onclick="switchResumeJudgeEvidenceView('raw')">原文视图</button>
          </div>
          <div class="resume-hj-code-shell">
            <pre id="resumeJudgeStructuredResumeView" class="resume-hj-code-pre"><code>${escHtml(templateText)}</code></pre>
            <pre id="resumeJudgeRawResumeView" class="resume-hj-code-pre hidden"><code>${escHtml(String(state?.analysis_result || "暂无原文视图内容。").trim() || "暂无原文视图内容。")}</code></pre>
            <pre id="resumeJudgeFullResume" class="hidden"><code>${escHtml(templateText)}</code></pre>
          </div>
          <p class="resume-hj-footnote">结构化视图用于快速判断；原文视图用于逐行核对证据与表达。</p>
        </article>
      </section>

      <section class="resume-hj-panel" data-section-index="5">
        <div class="resume-hj-final-grid">
          <div class="resume-hj-stack">
            <article class="resume-hj-card">
              <h4 class="resume-hj-card-title">整体评价</h4>
              <div class="resume-hj-summary-list">
                ${finalSummaryItems.map((item) => `<div class="resume-hj-summary-item">${escHtml(item)}</div>`).join("")}
              </div>
            </article>
            <article class="resume-hj-card danger">
              <h4 class="resume-hj-card-title">最致命风险点</h4>
              <div class="resume-hj-summary-list">
                ${riskItems.slice(0, 3).map((item) => `<div class="resume-hj-summary-item">${escHtml(item)}</div>`).join("")}
              </div>
            </article>
          </div>
          <div class="resume-hj-stack">
            <article class="resume-hj-card">
              <h4 class="resume-hj-card-title">行动清单</h4>
              <div class="resume-hj-action-list">
                ${adviceItems.slice(0, 3).map((item, index) => `
                  <div class="resume-hj-action-item">
                    <span>${String(index + 1).padStart(2, "0")}</span>
                    <p>${escHtml(item)}</p>
                  </div>
                `).join("")}
              </div>
            </article>
            <article class="resume-hj-card">
              <h4 class="resume-hj-card-title">修改前后对比</h4>
              <div class="resume-hj-compare-list">
                ${comparisonItems.map((item) => `
                  <div class="resume-hj-compare-row">
                    <div class="resume-hj-compare-meta">
                      <span>${item[0]}</span>
                      <strong>${item[1]} / ${item[2]}</strong>
                    </div>
                    <div class="resume-hj-compare-track">
                      <div class="resume-hj-compare-fill" style="width:${Math.min(100, Number(item[1] || 0))}%"></div>
                    </div>
                  </div>
                `).join("")}
              </div>
            </article>
          </div>
        </div>
      </section>
    </div>
  `;
}

function resumeAnalysisDashboardHtml(state, profile, matcher, analysisMode, recommendedDirections) {
  if (!profile) {
    return resumeJudgeExactEmptyDashboardHtml(state);
  }
  return resumeJudgeExactDashboardHtml(state, profile, matcher, analysisMode, recommendedDirections);
}

function renderResumeProfileSection(data) {
  const state = data || emptyResumeProfile();
  const uploadStatus = document.getElementById("resumeUploadStatus");
  const uploadMeta = document.getElementById("resumeUploadMeta");
  const analyzeStatus = document.getElementById("resumeAnalyzeStatus");
  const analyzeMeta = document.getElementById("resumeAnalyzeMeta");
  const confidence = document.getElementById("resumeConfidence");
  const modelHint = document.getElementById("resumeModelHint");
  const summary = document.getElementById("resumeCandidateSummary");
  const roleTags = document.getElementById("resumeRoleTags");
  const matchedTags = document.getElementById("resumeMatchedKeywordTags");
  const missingTags = document.getElementById("resumeMissingKeywordTags");
  const jobTags = document.getElementById("resumeJobKeywordTags");
  const overviewList = document.getElementById("resumeOverviewList");
  const evidenceList = document.getElementById("resumeEvidenceList");
  const analysisResult = document.getElementById("resumeAnalysisResult");
  const analysisResultMeta = document.getElementById("resumeAnalysisResultMeta");
  const quickBoard = document.getElementById("resumeQuickBoard");
  const jobAssist = document.getElementById("resumeJobAssist");
  const profile = state.profile || null;
  const matcher = state.matcher && typeof state.matcher === "object" ? state.matcher : {};
  const analysisMode = String(matcher.analysis_mode || state.analysis_meta?.analysis_mode || "").trim();
  const recommendedDirections = Array.isArray(matcher.recommended_directions) ? matcher.recommended_directions : [];

  setResumeJobDescription(state.job_description || "");
  syncResumeJobInputFrame();
  if (jobAssist) {
    jobAssist.innerHTML = resumeJobAssistHtml(state.job_description || "", analysisMode, recommendedDirections);
  }

  if (uploadStatus) uploadStatus.textContent = state.file_name ? "已上传" : "未上传";
  if (uploadMeta) {
    uploadMeta.textContent = state.file_name
      ? `${state.file_name} · ${String(state.file_type || "pdf").toUpperCase()} · ${(Number(state.file_size || 0) / 1024).toFixed(1)}KB · ${formatUnixTime(state.uploaded_at)}`
      : "请先上传 PDF 或 DOCX 简历";
  }
  if (analyzeStatus) {
    if (state.status === "analyzed") analyzeStatus.textContent = "已完成";
    else if (state.status === "failed") analyzeStatus.textContent = "失败";
    else if (state.status === "analyzing") analyzeStatus.textContent = "分析中";
    else analyzeStatus.textContent = "待分析";
  }
  if (analyzeMeta) {
    const meta = state.analysis_meta || {};
    if (state.status === "analyzed") {
      const matchedCount = Array.isArray(matcher.matched_keywords) ? matcher.matched_keywords.length : 0;
      const jobCount = Array.isArray(matcher.job_keywords) ? matcher.job_keywords.length : 0;
      analyzeMeta.textContent = analysisMode === "resume_review"
        ? `页数 ${meta.page_count || 0} · 字符 ${meta.char_count || 0} · 简历诊断模式${meta.ocr_used ? " · OCR 已启用" : ""}`
        : `页数 ${meta.page_count || 0} · 字符 ${meta.char_count || 0} · 命中 ${matchedCount}/${jobCount}${meta.ocr_used ? " · OCR 已启用" : ""}`;
    } else if (state.status === "analyzing") {
      analyzeMeta.textContent = `${meta.stage_detail || "正在分析中..."}`;
    } else {
      analyzeMeta.textContent = humanizeResumeErrorMessage(state.error_message || meta.stage_detail || "") || "等待简历上传，JD 可选";
    }
  }

  if (confidence) confidence.textContent = profile ? `${Math.round(Number(profile.confidence || 0) * 100)}%` : "--";
  if (modelHint) {
    const model = String(state.analysis_meta?.model || "").trim();
    modelHint.textContent = profile
      ? `${model || "matcher 模型"} · ${formatUnixTime(state.analyzed_at)}`
      : (state.status === "failed"
        ? "本次分析失败，可修正文件后重试"
        : "等待首次匹配结果");
  }
  if (summary) summary.textContent = resumeProfileSummaryText(state, profile);

  if (!resumeTaskState.uploadInFlight) {
    hideResumeProgress("upload");
  }
  if (!resumeTaskState.analyzeInFlight) {
    if (state.status === "analyzing") setResumeProgress("analyze", 100, `${state.analysis_meta?.stage_detail || "分析中"}`, true);
    else hideResumeProgress("analyze");
  }

  if (roleTags) {
    const roles = previewTagValues((profile?.roles_detected || []).map((item) => item.role), 6);
    roleTags.innerHTML = careerTagHtml(roles, "等待识别岗位角色", "accent");
  }
  if (matchedTags) {
    matchedTags.innerHTML = analysisMode === "resume_review"
      ? careerTagHtml([], "当前为简历诊断模式", "primary")
      : careerTagHtml(previewTagValues(matcher.matched_keywords || [], 8), "暂无命中关键词", "primary");
  }
  if (missingTags) {
    missingTags.innerHTML = analysisMode === "resume_review"
      ? careerTagHtml([], "未提供 JD，无待补强项", "soft")
      : careerTagHtml(previewTagValues(matcher.missing_keywords || [], 8), "暂无待补强项", "soft");
  }
  if (jobTags) {
    jobTags.innerHTML = analysisMode === "resume_review"
      ? careerTagHtml(previewTagValues(recommendedDirections, 6), "未提供 JD，系统已给出建议方向", "accent")
      : careerTagHtml(previewTagValues(matcher.job_keywords || [], 10), "等待解析岗位文本", "accent");
  }
  if (quickBoard) {
    quickBoard.innerHTML = profile
      ? resumeQuickBoardHtml(profile, matcher, analysisMode, recommendedDirections)
      : `<div class="career-list-empty">${escHtml(state.file_name ? (state.status === "failed" ? "这份简历本次没有成功生成摘要，请根据上方提示修正后重新开始匹配。" : "简历已上传，点击“开始匹配”后会在这里显示简明概览卡片。") : "上传并分析后会在这里显示简明概览卡片")}</div>`;
  }

  if (overviewList) {
    overviewList.innerHTML = profile
      ? resumeOverviewCardsHtml(profile, matcher, analysisMode, recommendedDirections)
      : `<div class="career-list-empty">${escHtml(state.status === "failed" ? "本次分析失败，暂时没有结构化概览。" : "等待结构化概览")}</div>`;
  }

  if (analysisResultMeta) {
    const matchedCount = Array.isArray(matcher.matched_keywords) ? matcher.matched_keywords.length : 0;
    const jobCount = Array.isArray(matcher.job_keywords) ? matcher.job_keywords.length : 0;
    analysisResultMeta.textContent = state.analyzed_at
      ? (analysisMode === "resume_review"
        ? `最近生成：${formatUnixTime(state.analyzed_at)} · 简历诊断模式`
        : `最近生成：${formatUnixTime(state.analyzed_at)} · 命中 ${matchedCount}/${jobCount}`)
      : "等待分析";
  }
  if (analysisResult) {
    analysisResult.innerHTML = resumeAnalysisDashboardHtml(state, profile, matcher, analysisMode, recommendedDirections);
    initResumeStackDecks(analysisResult);
  }
  renderResumeReportModal(state, profile, matcher, analysisMode, recommendedDirections);

  if (evidenceList) {
    evidenceList.innerHTML = profile
      ? resumeEvidenceCardsHtml(profile)
      : resumeEvidencePlaceholderHtml();
  }
  syncResumeJudgeFlow(state);
}

async function refreshResumeProfile(force = false) {
  try {
    const data = await loadResumeProfile(force);
    renderResumeProfileSection(data);
    refreshUnifiedExperience();
  } catch (error) {
    showToast("简历状态加载失败", error.message, "error", 2000);
  }
}

function pickResumeFile() {
  const input = document.getElementById("resumeFileInput");
  if (input) input.click();
}

function pickResumePdf() {
  pickResumeFile();
}

async function onResumeFileSelected(event) {
  const file = event?.target?.files?.[0];
  if (!file) return;
  const lowerName = String(file.name || "").toLowerCase();
  if (!lowerName.endsWith(".pdf") && !lowerName.endsWith(".docx")) {
    showToast("仅支持 PDF 或 DOCX", "请上传 .pdf 或 .docx 简历文件", "warning", 2000);
    return;
  }
  if (resumeTaskState.uploadInFlight || resumeTaskState.analyzeInFlight) {
    showToast("请稍候", "当前有任务正在执行中。", "warning", 1800);
    return;
  }
  const formData = new FormData();
  formData.append("file", file);
  resumeTaskState.uploadInFlight = true;
  resumeTaskState.forceInputView = true;
  syncResumeJudgeFlow(getResumeProfileFromCache());
  updateResumeActionButtons();
  const uploadStatus = document.getElementById("resumeUploadStatus");
  const uploadMeta = document.getElementById("resumeUploadMeta");
  if (uploadStatus) uploadStatus.textContent = "上传中";
  if (uploadMeta) uploadMeta.textContent = `正在上传：${file.name}`;
  setResumeProgress("upload", 0, "上传中 0%", true);
  try {
    const payload = await new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", resolveApiUrl("/api/resume/upload"), true);
      xhr.withCredentials = true;
      xhr.upload.onprogress = (e) => {
        if (!e.lengthComputable) return;
        const percent = Math.min(99, (e.loaded / e.total) * 100);
        setResumeProgress("upload", percent, `上传中 ${Math.round(percent)}%`, true);
      };
      xhr.onload = () => {
        let data = {};
        try {
          data = JSON.parse(xhr.responseText || "{}");
        } catch (_) {
          data = {};
        }
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(data);
        } else {
          const error = new Error(data.message || `请求失败：${xhr.status}`);
          error.status = xhr.status;
          reject(error);
        }
      };
      xhr.onerror = () => reject(new Error("网络错误，上传失败"));
      xhr.send(formData);
    });
    userWorkspaceState.scopedData.resume_profile = payload.data || emptyResumeProfile();
    userWorkspaceState.scopedDataLoaded.resume_profile = true;
    resumeTaskState.forceInputView = true;
    renderResumeProfileSection(userWorkspaceState.scopedData.resume_profile);
    setResumeProgress("upload", 100, "已上传 100%", false);
    setTimeout(() => {
      if (!resumeTaskState.uploadInFlight) hideResumeProgress("upload");
    }, 1200);
    showToast("上传成功", "简历文件已保存。", "success", 1600);
    refreshUnifiedExperience();
  } catch (error) {
    setResumeProgress("upload", 0, "上传失败", false);
    showToast("上传失败", error.message, "error", 2200);
  } finally {
    resumeTaskState.uploadInFlight = false;
    updateResumeActionButtons();
    if (event?.target) event.target.value = "";
  }
}

async function onResumePdfSelected(event) {
  return onResumeFileSelected(event);
}

async function analyzeResumeMatch() {
  if (resumeTaskState.uploadInFlight || resumeTaskState.analyzeInFlight) {
    showToast("请稍候", "当前有任务正在执行中。", "warning", 1800);
    return;
  }
  const jobDescription = getResumeJobDescription();
  const hasJobDescription = jobDescription.length > 0;
  resumeTaskState.analyzeInFlight = true;
  resumeTaskState.forceInputView = false;
  syncResumeJudgeFlow(getResumeProfileFromCache());
  updateResumeActionButtons();
  startAnalyzeProgressTicker();
  const analyzeStatus = document.getElementById("resumeAnalyzeStatus");
  const analyzeMeta = document.getElementById("resumeAnalyzeMeta");
  if (analyzeStatus) analyzeStatus.textContent = "排队中";
  if (analyzeMeta) analyzeMeta.textContent = "正在创建分析任务...";
  try {
    const startPayload = await requestJson("/api/resume/analyze/start", {
      method: "POST",
      body: { job_description: jobDescription }
    });
    const jobId = String(startPayload.job_id || "").trim();
    if (!jobId) throw new Error("分析任务创建失败：缺少任务 ID");

    const startedAt = Date.now();
    let statusPayload = null;
    for (let round = 0; round < 240; round += 1) {
      statusPayload = await requestJson(`/api/resume/analyze/status?job_id=${encodeURIComponent(jobId)}`);
      const job = statusPayload?.job || {};
      const elapsedSec = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
      const status = String(job.status || "").trim();
      if (status === "success") break;
      if (status === "failed") {
        const resumeError = String(statusPayload?.resume?.error_message || "").trim();
        throw new Error(String(job.message || resumeError || "简历匹配分析失败"));
      }
      applyResumeAnalyzeRuntimeStatus(job, elapsedSec);
      await sleepMs(900);
    }

    const resumeData = statusPayload?.resume || null;
    if (!resumeData || String(statusPayload?.job?.status || "").trim() !== "success") {
      throw new Error("分析超时，请稍后在简历状态中查看结果。");
    }

    userWorkspaceState.scopedData.resume_profile = resumeData;
    userWorkspaceState.scopedDataLoaded.resume_profile = true;
    resumeTaskState.forceInputView = false;
    renderResumeProfileSection(userWorkspaceState.scopedData.resume_profile);
    setResumeProgress("analyze", 100, "分析完成", false);
    showToast("分析完成", hasJobDescription ? "简历匹配结果已更新。" : "简历诊断结果已更新。", "success", 1800);
    refreshUnifiedExperience();
  } catch (error) {
    resumeTaskState.forceInputView = true;
    syncResumeJudgeFlow(getResumeProfileFromCache());
    setResumeProgress("analyze", 0, "分析失败", false);
    showToast("分析失败", error.message, "error", 2600);
  } finally {
    resumeTaskState.analyzeInFlight = false;
    stopAnalyzeProgressTicker();
    updateResumeActionButtons();
  }
}

async function analyzeResumePdf() {
  return analyzeResumeMatch();
}

async function deleteResumeProfile() {
  if (!confirm("确认删除当前简历、JD 和分析结果？")) return;
  try {
    await requestJson("/api/resume/profile", { method: "DELETE" });
    userWorkspaceState.scopedData.resume_profile = null;
    userWorkspaceState.scopedDataLoaded.resume_profile = true;
    resumeTaskState.forceInputView = true;
    renderResumeProfileSection(emptyResumeProfile());
    toggleResumeJobInput(false);
    setResumeJobDescription("");
    showToast("已删除", "简历与分析结果已清空。", "success", 1600);
    refreshUnifiedExperience();
  } catch (error) {
    showToast("删除失败", error.message, "error", 2200);
  }
}

async function fetchManagedLlmConfig(scope, force = false) {
  if (!force && userWorkspaceState.llmConfigs[scope]) {
    return userWorkspaceState.llmConfigs[scope];
  }
  if (!isAuthenticatedUser()) return getDefaultCareerInterviewConfig();
  const payload = await requestJson(`/api/llm-config/${scope}`);
  const config = {
    base_url: String(payload.base_url || "").trim(),
    api_key: String(payload.api_key || "").trim(),
    model: String(payload.model || "gpt-4o-mini").trim() || "gpt-4o-mini",
    configured: Boolean(payload.configured),
    editable: Boolean(payload.editable),
    api_key_masked: String(payload.api_key_masked || "")
  };
  userWorkspaceState.llmConfigs[scope] = config;
  return config;
}

async function fetchActiveLlmRuntimeConfig(force = false) {
  if (!isAuthenticatedUser()) return getDefaultCareerInterviewConfig();
  if (!force && userWorkspaceState.llmConfigs.career_interview) {
    const cached = userWorkspaceState.llmConfigs.career_interview;
    if (cached && (cached.configured || cached.base_url || cached.api_key)) return cached;
  }
  const data = await requestJson("/api/llm-selection");
  const providers = Array.isArray(data.providers) ? data.providers : [];
  const selection = (data && typeof data.selection === "object" && data.selection) ? data.selection : {};
  const selectedProvider = providers.find((p) => p.id === selection.provider_id && p.configured);
  const fallbackProvider = providers.find((p) => p.configured);
  const active = selectedProvider || fallbackProvider || null;
  let model = String(selection.model || "").trim();
  if (!model && active?.base_url) {
    model = String(active.base_url).toLowerCase().includes("deepseek") ? "deepseek-chat" : "gpt-4o-mini";
  }
  const config = {
    base_url: String(active?.base_url || "").trim(),
    api_key: "",
    model: model || "gpt-4o-mini",
    configured: Boolean(active && model),
    editable: isSuperAdminUser(),
    api_key_masked: String(active?.api_key_masked || "")
  };
  userWorkspaceState.llmConfigs.career_interview = config;
  userWorkspaceState.llmConfigs.assessment_hub = config;
  return config;
}

async function saveManagedLlmConfig(scope, config) {
  const payload = await requestJson(`/api/llm-config/${scope}`, {
    method: "PUT",
    body: config
  });
  userWorkspaceState.llmConfigs[scope] = {
    base_url: String(payload.base_url || "").trim(),
    api_key: String(payload.api_key || "").trim(),
    model: String(payload.model || "gpt-4o-mini").trim() || "gpt-4o-mini",
    configured: Boolean(payload.configured),
    editable: Boolean(payload.editable),
    api_key_masked: String(payload.api_key_masked || "")
  };
  return userWorkspaceState.llmConfigs[scope];
}

window.getCurrentUser = getCurrentUser;
window.isAuthenticatedUser = isAuthenticatedUser;
window.isSuperAdminUser = isSuperAdminUser;
window.fetchScopedUserState = fetchScopedUserState;
window.saveScopedUserState = saveScopedUserState;
window.fetchManagedLlmConfig = fetchManagedLlmConfig;
window.fetchActiveLlmRuntimeConfig = fetchActiveLlmRuntimeConfig;
window.saveManagedLlmConfig = saveManagedLlmConfig;
window.appState = appState;
window.userWorkspaceState = userWorkspaceState;
window.resolveApiUrl = resolveApiUrl;
window.requestJson = requestJson;
window.requestFormData = requestFormData;
window.setResumeStackDeck = setResumeStackDeck;
window.shiftResumeStackDeck = shiftResumeStackDeck;
window.advanceResumeStackDeck = advanceResumeStackDeck;
window.handleResumeStackDeckKey = handleResumeStackDeckKey;
window.openResumeReportModal = openResumeReportModal;
window.closeResumeReportModal = closeResumeReportModal;
window.handleResumeReportOverlayClick = handleResumeReportOverlayClick;
window.jumpResumeReportSection = jumpResumeReportSection;
window.getCareerReportStateSafe = getCareerReportStateSafe;
window.startCareerReportGeneration = startCareerReportGeneration;
window.cancelCareerReportGeneration = cancelCareerReportGeneration;
window.pollCareerReportJob = pollCareerReportJob;
window.resumeCareerReportRuntime = resumeCareerReportRuntime;

function readSessionCache(key) {
  let raw = null;
  try {
    raw = sessionStorage.getItem(key);
  } catch (error) {
    console.warn("sessionStorage read failed", error);
    return null;
  }
  const payload = safeJsonParse(raw, null);
  if (!payload || typeof payload !== "object") return null;
  if (Number(payload.expiresAt || 0) < Date.now()) {
    try {
      sessionStorage.removeItem(key);
    } catch (error) {
      console.warn("sessionStorage remove failed", error);
    }
    return null;
  }
  return payload.data ?? null;
}

function isStorageQuotaExceeded(error) {
  if (!error) return false;
  const name = String(error.name || "");
  const code = Number(error.code || 0);
  if (name === "QuotaExceededError" || name === "NS_ERROR_DOM_QUOTA_REACHED") return true;
  if (code === 22 || code === 1014) return true;
  return /quota/i.test(String(error.message || ""));
}

function clearSessionCacheEntries(keysOrPrefixes = []) {
  if (!Array.isArray(keysOrPrefixes) || keysOrPrefixes.length === 0) return;
  const markers = keysOrPrefixes.map((item) => String(item || "")).filter(Boolean);
  if (markers.length === 0) return;
  const targets = [];
  for (let i = 0; i < sessionStorage.length; i += 1) {
    const key = sessionStorage.key(i);
    if (!key) continue;
    if (markers.some((marker) => key === marker || key.startsWith(marker))) {
      targets.push(key);
    }
  }
  targets.forEach((key) => {
    try {
      sessionStorage.removeItem(key);
    } catch (error) {
      console.warn("sessionStorage cleanup failed", error);
    }
  });
}

function writeSessionCache(key, data, ttlMs = JOBS_CACHE_TTL_MS) {
  const payload = JSON.stringify({
    expiresAt: Date.now() + ttlMs,
    data
  });
  try {
    sessionStorage.setItem(key, payload);
    return;
  } catch (error) {
    if (!isStorageQuotaExceeded(error)) {
      console.warn("sessionStorage write failed", error);
      return;
    }
  }

  clearSessionCacheEntries([JOBS_LIST_CACHE_PREFIX, JOBS_DETAIL_CACHE_PREFIX, JOBS_CITIES_CACHE_KEY]);
  try {
    sessionStorage.setItem(key, payload);
  } catch (error) {
    console.warn("sessionStorage quota exceeded, skip cache", error);
  }
}

async function fetchJsonWithSessionCache(url, cacheKey, ttlMs = JOBS_CACHE_TTL_MS) {
  const cached = readSessionCache(cacheKey);
  if (cached) return cached;
  const response = await fetch(resolveApiUrl(url), {
    credentials: "include"
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.message || `Request failed: ${response.status}`);
  }
  writeSessionCache(cacheKey, payload, ttlMs);
  return payload;
}

function buildJobSearchIndex() {
  if (!window.Fuse || fuseIndex || allJobsData.length === 0) return;
  fuseIndex = new Fuse(allJobsData, {
    keys: [
      { name: "岗位名称", weight: 0.4 },
      { name: "公司名称", weight: 0.3 },
      { name: "技能要求", weight: 0.15 },
      { name: "职位类别", weight: 0.1 },
      { name: "公司行业", weight: 0.05 }
    ],
    threshold: 0.7,
    distance: 200,
    includeScore: true,
    ignoreLocation: true,
    minMatchCharLength: 1
  });
}

function scheduleGeoInsightsInit(jobs) {
  if (typeof window.initializeJobGeoInsights !== "function") return;
  const runner = () => window.initializeJobGeoInsights(jobs);
  if (typeof window.requestIdleCallback === "function") {
    window.requestIdleCallback(runner, { timeout: 1200 });
    return;
  }
  window.setTimeout(runner, 16);
}

function scheduleAnalyticsInit(jobs) {
  if (typeof window.initJobsAnalytics !== "function") return;
  const runner = () => window.initJobsAnalytics(jobs);
  if (typeof window.requestIdleCallback === "function") {
    window.requestIdleCallback(runner, { timeout: 2000 });
    return;
  }
  window.setTimeout(runner, 200);
}

async function getJobDetail(jobId) {
  return fetchJsonWithSessionCache(
    `/api/job-detail?id=${encodeURIComponent(jobId)}`,
    `${JOBS_DETAIL_CACHE_PREFIX}${jobId}`
  );
}

function createCareerInterviewDimensionProgress() {
  return CAREER_INTERVIEW_DIMENSION_PLAN.map((item) => ({
    name: item.name,
    target: item.target,
    answered: 0
  }));
}

function normalizeCareerDimensionName(name) {
  const text = String(name || "").trim();
  if (!text) return CAREER_INTERVIEW_DIMENSION_PLAN[0].name;
  const exact = CAREER_INTERVIEW_DIMENSION_PLAN.find((item) => item.name === text);
  if (exact) return exact.name;
  const fuzzy = CAREER_INTERVIEW_DIMENSION_PLAN.find((item) => text.includes(item.name) || item.name.includes(text));
  return fuzzy ? fuzzy.name : CAREER_INTERVIEW_DIMENSION_PLAN[0].name;
}

function getCareerDimensionProgressByName(name) {
  const normalizedName = normalizeCareerDimensionName(name);
  if (!Array.isArray(careerInterviewState.dimensionProgress) || careerInterviewState.dimensionProgress.length === 0) {
    careerInterviewState.dimensionProgress = createCareerInterviewDimensionProgress();
  }
  return careerInterviewState.dimensionProgress.find((item) => item.name === normalizedName) || null;
}

function getCareerInterviewProgressPercent() {
  if (!Array.isArray(careerInterviewState.dimensionProgress) || careerInterviewState.dimensionProgress.length === 0) {
    return 0;
  }
  const total = careerInterviewState.dimensionProgress.reduce((sum, item) => sum + Number(item.target || 0), 0);
  const answered = careerInterviewState.dimensionProgress.reduce((sum, item) => sum + Math.min(Number(item.target || 0), Number(item.answered || 0)), 0);
  if (!total) return 0;
  return Math.round(answered / total * 100);
}

function getNextPendingCareerDimensionName() {
  if (!Array.isArray(careerInterviewState.dimensionProgress) || careerInterviewState.dimensionProgress.length === 0) {
    return CAREER_INTERVIEW_DIMENSION_PLAN[0].name;
  }
  const nextItem = careerInterviewState.dimensionProgress.find((item) => Number(item.answered || 0) < Number(item.target || 0));
  return nextItem ? nextItem.name : null;
}

function getCareerDimensionPrompt(name) {
  const normalizedName = normalizeCareerDimensionName(name);
  const plan = CAREER_INTERVIEW_DIMENSION_PLAN.find((item) => item.name === normalizedName) || CAREER_INTERVIEW_DIMENSION_PLAN[0];
  const progress = getCareerDimensionProgressByName(normalizedName);
  const promptIndex = Math.min(Number(progress?.answered || 0), plan.prompts.length - 1);
  return plan.prompts[promptIndex];
}

function getCareerInterviewGuideConfig(name) {
  const normalizedName = normalizeCareerDimensionName(name);
  return CAREER_INTERVIEW_GUIDE_LIBRARY[normalizedName] || CAREER_INTERVIEW_GUIDE_LIBRARY["职业兴趣"];
}

function getCurrentCareerInterviewQuestion() {
  if (careerInterviewState.isComplete) {
    return "访谈已完成。你仍然可以继续补充新的经历，再点击“发送并继续”让系统更新理解。";
  }
  const assistantMessages = (careerInterviewState.messages || []).filter((item) => item.role === "assistant");
  const lastAssistant = assistantMessages[assistantMessages.length - 1];
  return String(lastAssistant?.content || getCareerDimensionPrompt(careerInterviewState.focusDimension) || "").trim();
}

function renderCareerInterviewHelperAnchor() {
  const anchorEl = document.getElementById("careerInterviewSelectedScene");
  if (!anchorEl) return;
  const anchor = String(careerInterviewState.helperAnchor || "").trim();
  if (!anchor) {
    anchorEl.classList.add("hidden");
    anchorEl.innerHTML = "";
    return;
  }
  anchorEl.classList.remove("hidden");
  anchorEl.innerHTML = `
    <span class="career-chat-anchor-label">当前线索</span>
    <strong>${escHtml(anchor)}</strong>
    <button type="button" class="career-chat-anchor-clear" onclick="clearCareerInterviewHelperAnchor()">清除</button>
  `;
}

function setCareerInterviewComposerDraft(rawText, options = {}) {
  const input = document.getElementById("careerInterviewInput");
  const text = String(rawText || "").trim();
  if (!input || !text) return;
  const append = Boolean(options.append);
  const current = String(input.value || "").trim();
  const nextValue = append && current
    ? `${current}${/[。！？.!?]$/.test(current) ? "" : "。"}\n${text}`
    : text;
  input.value = nextValue;
  careerInterviewState.helperAnchor = String(options.anchorLabel || options.anchor || "").trim();
  renderCareerInterviewHelperAnchor();
  input.focus();
  input.setSelectionRange(input.value.length, input.value.length);
}

async function useCareerInterviewDraft(rawText, options = {}) {
  const draft = String(rawText || "").trim();
  if (!draft) return;
  if (!careerInterviewState.started) {
    await startCareerInterview({
      initialDraft: draft,
      helperAnchor: String(options.anchorLabel || options.anchor || "").trim()
    });
    return;
  }
  setCareerInterviewComposerDraft(draft, {
    append: Boolean(options.append),
    anchorLabel: options.anchorLabel || options.anchor || ""
  });
}

function bindCareerInterviewHelperInteractions() {
  const chipRow = document.getElementById("careerInterviewQuickChips");
  const sceneGrid = document.getElementById("careerInterviewSceneGrid");

  if (chipRow && chipRow.dataset.bound !== "true") {
    chipRow.dataset.bound = "true";
    chipRow.addEventListener("click", (event) => {
      const target = event.target.closest("[data-draft]");
      if (!target) return;
      void useCareerInterviewDraft(target.getAttribute("data-draft"), {
        anchorLabel: target.getAttribute("data-label") || "",
        append: target.getAttribute("data-mode") === "append"
      });
    });
  }

  if (sceneGrid && sceneGrid.dataset.bound !== "true") {
    sceneGrid.dataset.bound = "true";
    sceneGrid.addEventListener("click", (event) => {
      const target = event.target.closest("[data-draft]");
      if (!target) return;
      void useCareerInterviewDraft(target.getAttribute("data-draft"), {
        anchorLabel: target.getAttribute("data-label") || "",
        append: false
      });
    });
  }
}

function getCareerInterviewSpeechApi() {
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

function updateCareerInterviewVoiceButton() {
  const voiceBtn = document.getElementById("careerInterviewVoiceBtn");
  if (!voiceBtn) return;
  if (careerInterviewVoiceState.supported === null) {
    careerInterviewVoiceState.supported = Boolean(getCareerInterviewSpeechApi());
  }
  const supported = Boolean(careerInterviewVoiceState.supported);
  voiceBtn.disabled = !supported || !careerInterviewState.started || careerInterviewState.loading || careerInterviewState.isComplete;
  voiceBtn.classList.toggle("is-listening", careerInterviewVoiceState.listening);
  if (!supported) {
    voiceBtn.textContent = "当前浏览器不支持语音";
    return;
  }
  voiceBtn.textContent = careerInterviewVoiceState.listening ? "停止录音" : "语音输入";
}

function stopCareerInterviewVoice() {
  if (careerInterviewVoiceState.recognition && careerInterviewVoiceState.listening) {
    careerInterviewVoiceState.recognition.stop();
  }
  careerInterviewVoiceState.listening = false;
  updateCareerInterviewVoiceButton();
}

function ensureCareerInterviewVoiceRecognition() {
  if (careerInterviewVoiceState.recognition) return careerInterviewVoiceState.recognition;
  const SpeechApi = getCareerInterviewSpeechApi();
  careerInterviewVoiceState.supported = Boolean(SpeechApi);
  if (!SpeechApi) return null;

  const recognition = new SpeechApi();
  recognition.lang = "zh-CN";
  recognition.continuous = false;
  recognition.interimResults = false;

  recognition.onstart = () => {
    careerInterviewVoiceState.listening = true;
    updateCareerInterviewVoiceButton();
  };

  recognition.onresult = (event) => {
    const transcript = Array.from(event.results || [])
      .map((item) => item[0]?.transcript || "")
      .join("")
      .trim();
    if (transcript) {
      setCareerInterviewComposerDraft(transcript, {
        append: Boolean(document.getElementById("careerInterviewInput")?.value?.trim()),
        anchorLabel: careerInterviewState.helperAnchor || "语音输入"
      });
    }
  };

  recognition.onerror = (event) => {
    careerInterviewVoiceState.listening = false;
    updateCareerInterviewVoiceButton();
    if (event?.error && event.error !== "no-speech") {
      showToast("语音输入失败", "当前浏览器没有成功识别语音，请改用文本输入。", "warning", 2000);
    }
  };

  recognition.onend = () => {
    careerInterviewVoiceState.listening = false;
    updateCareerInterviewVoiceButton();
  };

  careerInterviewVoiceState.recognition = recognition;
  return recognition;
}

function renderCareerInterviewAssistSurface() {
  const config = getCareerInterviewGuideConfig(careerInterviewState.focusDimension);
  const headlineEl = document.getElementById("careerInterviewPromptHeadline");
  const bodyEl = document.getElementById("careerInterviewPromptBody");
  const guideEl = document.getElementById("careerInterviewGuideText");
  const questionEl = document.getElementById("careerInterviewCurrentQuestion");
  const chipRow = document.getElementById("careerInterviewQuickChips");
  const sceneGrid = document.getElementById("careerInterviewSceneGrid");

  if (headlineEl) headlineEl.textContent = config.headline;
  if (bodyEl) bodyEl.textContent = config.body;
  if (guideEl) guideEl.textContent = config.guide;
  if (questionEl) questionEl.textContent = getCurrentCareerInterviewQuestion() || "模型就绪后会在这里显示当前问题。";

  if (sceneGrid) {
    sceneGrid.innerHTML = (config.scenes || []).map((item) => `
      <button type="button" class="career-scene-card${careerInterviewState.helperAnchor === item.title ? " is-active" : ""}" data-draft="${escHtml(item.draft)}" data-label="${escHtml(item.title)}">
        <strong class="career-scene-title">${escHtml(item.title)}</strong>
        <span class="career-scene-copy">${escHtml(item.caption)}</span>
      </button>
    `).join("");
  }

  if (chipRow) {
    chipRow.innerHTML = (config.chips || []).map((item) => `
      <button type="button" class="career-quick-chip${careerInterviewState.helperAnchor === item.label ? " is-active" : ""}" data-draft="${escHtml(item.draft)}" data-label="${escHtml(item.label)}" data-mode="append">
        ${escHtml(item.label)}
      </button>
    `).join("");
  }

  renderCareerInterviewHelperAnchor();
  updateCareerInterviewVoiceButton();
  bindCareerInterviewHelperInteractions();
}

function markCareerDimensionAnswered(name) {
  const target = getCareerDimensionProgressByName(name);
  if (!target) return;
  target.answered = Math.min(Number(target.target || 0), Number(target.answered || 0) + 1);
  careerInterviewState.completionScore = getCareerInterviewProgressPercent();
}

function syncCareerInterviewProgress(result = null) {
  if (!Array.isArray(careerInterviewState.dimensionProgress) || careerInterviewState.dimensionProgress.length === 0) {
    careerInterviewState.dimensionProgress = createCareerInterviewDimensionProgress();
  }

  let focusName = normalizeCareerDimensionName(result?.focus_dimension || careerInterviewState.focusDimension);
  const cur = getCareerDimensionProgressByName(focusName);
  if (cur && !result?.is_complete && Number(cur.answered) >= Number(cur.target)) {
    const nextPending = getNextPendingCareerDimensionName();
    if (nextPending) focusName = nextPending;
  }
  careerInterviewState.focusDimension = focusName;

  if (result?.is_complete) {
    careerInterviewState.dimensionProgress.forEach((item) => {
      item.answered = item.target;
    });
  }

  careerInterviewState.completionScore = Math.max(
    getCareerInterviewProgressPercent(),
    Number(result?.completion_score || 0)
  );
}

function renderCareerInterviewDimensionProgress() {
  const progress = Array.isArray(careerInterviewState.dimensionProgress) ? careerInterviewState.dimensionProgress : [];
  const html = progress.map((item) => {
    const isActive = normalizeCareerDimensionName(careerInterviewState.focusDimension) === item.name;
    const answered = Math.min(Number(item.answered || 0), Number(item.target || 0));
    const ratio = item.target ? Math.round(answered / item.target * 100) : 0;
    return `
      <div class="career-progress-item${isActive ? " active" : ""}">
        <div class="career-progress-head">
          <span>${escHtml(item.name)}</span>
          <span>${answered}/${item.target}</span>
        </div>
        <div class="career-progress-track">
          <span class="career-progress-fill" style="width:${ratio}%"></span>
        </div>
      </div>
    `;
  }).join("");

  ["careerInterviewHeroDimensionProgress", "careerInterviewModalDimensionProgress"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = html;
  });
}

function getStoredCareerInterviewConfig() {
  const fallback = getDefaultCareerInterviewConfig();
  const parsed = userWorkspaceState.llmConfigs.career_interview || fallback;
  return {
    base_url: String(parsed.base_url || parsed.baseUrl || fallback.base_url || "").trim(),
    api_key: String(parsed.api_key || parsed.apiKey || fallback.api_key || "").trim(),
    model: String(parsed.model || fallback.model || "gpt-4o-mini").trim() || "gpt-4o-mini",
    configured: Boolean(parsed.configured ?? (parsed.base_url && parsed.api_key)),
    editable: Boolean(parsed.editable ?? isSuperAdminUser()),
    api_key_masked: String(parsed.api_key_masked || "")
  };
}

function getCareerInterviewConfigFromForm() {
  // 配置输入已移至设置面板，直接返回内存中的配置
  return getStoredCareerInterviewConfig();
}

function fillCareerInterviewConfigForm() {
  // 配置表单已移至头像设置面板，此函数保留以兼容调用链
}

function maskApiKey(apiKey) {
  if (!apiKey) return "未填写";
  if (apiKey.length <= 8) return "已填写";
  return `${apiKey.slice(0, 4)}****${apiKey.slice(-4)}`;
}

function updateCareerInterviewConfigStatus() {
  const config = getStoredCareerInterviewConfig();
  const statusEl = document.getElementById("careerInterviewConfigStatus");
  const notConfiguredText = isSuperAdminUser() ? "未配置" : "等待系统管理员配置";

  if (!statusEl) return;
  if (!config.configured) {
    statusEl.textContent = notConfiguredText;
    return;
  }
  statusEl.textContent = `${config.model} / ${config.api_key_masked || maskApiKey(config.api_key)}`;
}

async function updateProfileFlowModelStatus(force = false) {
  const statusEl = document.getElementById("profileFlowModelStatus");
  if (!statusEl) return;

  if (!isAuthenticatedUser()) {
    statusEl.textContent = "模型：未登录";
    statusEl.classList.remove("bg-emerald-100", "text-emerald-700");
    statusEl.classList.add("bg-slate-100", "text-slate-600");
    return;
  }

  try {
    const data = await requestJson("/api/llm-selection");
    const providers = Array.isArray(data.providers) ? data.providers : [];
    const selection = (data && typeof data.selection === "object" && data.selection) ? data.selection : {};
    const selectedProvider = providers.find((p) => p.id === selection.provider_id && p.configured);
    const fallbackProvider = providers.find((p) => p.configured);
    const activeProvider = selectedProvider || fallbackProvider || null;
    const model = String(selection.model || "").trim();

    if (!activeProvider || !model) {
      statusEl.textContent = "模型：未选择";
      statusEl.classList.remove("bg-emerald-100", "text-emerald-700");
      statusEl.classList.add("bg-slate-100", "text-slate-600");
      return;
    }

    const brand = getProviderBrandMeta(activeProvider);
    statusEl.textContent = `模型：${brand.icon} ${activeProvider.name} · ${model}`;
    statusEl.classList.remove("bg-slate-100", "text-slate-600");
    statusEl.classList.add("bg-emerald-100", "text-emerald-700");
  } catch (error) {
    if (!force) {
      statusEl.textContent = "模型：读取失败";
      statusEl.classList.remove("bg-emerald-100", "text-emerald-700");
      statusEl.classList.add("bg-slate-100", "text-slate-600");
    }
  }
}

function persistCareerInterviewSnapshot() {
  const snapshot = {
    started: careerInterviewState.started,
    loading: false,
    isComplete: careerInterviewState.isComplete,
    messages: careerInterviewState.messages,
    result: careerInterviewState.result,
    completionScore: careerInterviewState.completionScore,
    focusDimension: careerInterviewState.focusDimension,
    dimensionProgress: careerInterviewState.dimensionProgress,
    profileBasics: careerInterviewState.profileBasics
  };
  void saveScopedUserState("career_interview", snapshot).catch((error) => {
    console.error("save career interview snapshot failed", error);
  });
}
function resetCareerInterviewState(options = {}) {
  const preserveBasics = options.preserveBasics !== false;
  const retainedBasics = preserveBasics ? normalizeProfileBasics(careerInterviewState.profileBasics) : getDefaultProfileBasics();
  stopCareerInterviewVoice();
  careerInterviewState.started = false;
  careerInterviewState.loading = false;
  careerInterviewState.isComplete = false;
  careerInterviewState.messages = [];
  careerInterviewState.result = null;
  careerInterviewState.completionScore = 0;
  careerInterviewState.focusDimension = CAREER_INTERVIEW_DIMENSION_PLAN[0].name;
  careerInterviewState.dimensionProgress = createCareerInterviewDimensionProgress();
  careerInterviewState.profileBasics = retainedBasics;
  careerInterviewState.helperAnchor = "";
}
async function saveCareerInterviewConfig() {
  // 配置入口已迁移至头像设置面板
  if (typeof openSettingsPanel === "function") openSettingsPanel();
}

async function loadCareerInterviewConfig(force = false) {
  if (!isAuthenticatedUser()) {
    userWorkspaceState.llmConfigs.career_interview = getDefaultCareerInterviewConfig();
    fillCareerInterviewConfigForm();
    updateCareerInterviewConfigStatus();
    return userWorkspaceState.llmConfigs.career_interview;
  }
  try {
    // 访谈实际走“当前选择的 API+模型”，优先读取运行时选择而非管理员静态配置。
    await fetchActiveLlmRuntimeConfig(force);
  } catch (error) {
    console.error("load career interview config failed", error);
  }
  fillCareerInterviewConfigForm();
  updateCareerInterviewConfigStatus();
  return getStoredCareerInterviewConfig();
}

function updateCareerInterviewHero(result = null) {
  const statusEl = document.getElementById("careerInterviewHeroStatus");
  const hintEl = document.getElementById("careerInterviewHeroHint");
  renderCareerInterviewDimensionProgress();
  if (!statusEl || !hintEl) return;

  const progress = careerInterviewState.completionScore || Number(result?.completion_score || 0) || 0;
  const focusName = normalizeCareerDimensionName(result?.focus_dimension || careerInterviewState.focusDimension);
  const focusProgress = getCareerDimensionProgressByName(focusName);
  const ratioText = focusProgress ? `${Math.min(focusProgress.answered, focusProgress.target)}/${focusProgress.target}` : "0/0";

  if (!careerInterviewState.started && !result) {
    statusEl.textContent = getStoredCareerInterviewConfig().configured ? "可开始访谈" : "等待系统模型配置";
    hintEl.textContent = isSuperAdminUser()
      ? "请先保存系统模型配置，再启动访谈。启动后会按维度同步推进职业兴趣画像。"
      : "当前模型由系统管理员统一配置。配置完成后即可启动访谈，并按维度同步推进职业兴趣画像。";
    return;
  }

  if (careerInterviewState.isComplete || result?.is_complete) {
    statusEl.textContent = "访谈完成";
    hintEl.textContent = "六个核心维度已经补齐，可以直接参考下方的岗位方向、证据和行动建议。";
    return;
  }

  statusEl.textContent = `访谈进行中 ${progress}%`;
  hintEl.textContent = `当前聚焦“${focusName}”，维度进度 ${ratioText}。继续回答即可推进画像。`;
}
function careerTagHtml(items, emptyText, variant = "default") {
  const values = Array.isArray(items) ? items.filter(Boolean) : [];
  if (values.length === 0) {
    return `<span class="career-empty-inline">${escHtml(emptyText)}</span>`;
  }
  return values
    .map((item) => `<span class="career-tag career-tag-${variant}">${escHtml(String(item))}</span>`)
    .join("");
}

function careerListHtml(items, emptyText) {
  const values = Array.isArray(items) ? items.filter(Boolean) : [];
  if (values.length === 0) {
    return `<div class="career-list-empty">${escHtml(emptyText)}</div>`;
  }
  return values
    .map((item) => `<div class="career-list-item"><span class="career-list-dot"></span><span>${escHtml(String(item))}</span></div>`)
    .join("");
}

function careerDimensionHtml(dimensions) {
  const rows = Array.isArray(dimensions) ? dimensions : [];
  return rows
    .map((item) => {
      const name = escHtml(String(item.name || "未命名维度"));
      const score = Number(item.score || 0);
      const evidence = escHtml(String(item.evidence || "等待补充更多证据"));
      return `
        <div class="career-dimension-item">
          <div class="career-dimension-head">
            <span>${name}</span>
            <span>${score}%</span>
          </div>
          <div class="career-dimension-track">
            <div class="career-dimension-fill" style="width: ${Math.max(0, Math.min(100, score))}%"></div>
          </div>
          <p class="career-dimension-evidence">${evidence}</p>
        </div>
      `;
    })
    .join("");
}

function renderCareerInterviewMessages() {
  const thread = document.getElementById("careerInterviewMessages");
  const composer = document.getElementById("careerInterviewComposer");
  const input = document.getElementById("careerInterviewInput");
  const sendBtn = document.getElementById("careerInterviewSendBtn");
  const startBtn = document.getElementById("careerInterviewStartBtn");
  const hintEl = document.getElementById("careerInterviewHint");
  if (!thread) return;

  // 新的主题式进度（旧维度系统仍保留兼容）
  const topicDots = ["角色模型", "生活故事", "工作价值观", "情境应对"];
  const userMessageCount = careerInterviewState.messages.filter(m => m.role === "user").length;
  const exploredCount = Math.min(Math.floor(userMessageCount / 2), 4); // 约每2轮探索一个主题
  const dotsHtml = topicDots.map((t, i) =>
    `<span class="career-chat-topic-dot ${i < exploredCount ? "active" : ""}">${t}</span>`
  ).join("");

  const bannerHtml = careerInterviewState.started ? `
    <div class="career-chat-dimension-banner">
      <div class="career-chat-dimension-title">
        <span>已探索主题</span>
      </div>
      <div class="career-chat-topic-dots">${dotsHtml}</div>
      <div class="career-chat-dimension-meta">${userMessageCount}轮对话</div>
    </div>
  ` : "";

  if (!careerInterviewState.started || careerInterviewState.messages.length === 0) {
    thread.innerHTML = `
      <div class="career-chat-empty">
        <p class="career-chat-empty-title">从上面的场景卡或快捷标签开始，会更容易开口。</p>
        <p class="career-chat-empty-copy">${isSuperAdminUser() ? "请先确认模型配置，然后选一条线索开始第一轮访谈。" : "当前模型由系统管理员统一配置。你可以先点场景卡，系统会自动带着这条线索进入第一轮访谈。"}</p>
      </div>
    `;
  } else {
    thread.innerHTML = bannerHtml + careerInterviewState.messages
      .map((message) => {
        const roleClass = message.role === "user" ? "user" : "assistant";
        const roleLabel = message.role === "user" ? "你的回答" : "访谈代理";
        return `
          <div class="career-chat-item ${roleClass}">
            <div class="career-chat-meta">${roleLabel}</div>
            <div class="career-chat-bubble ${roleClass}">${escHtml(String(message.content || ""))}</div>
          </div>
        `;
      })
      .join("");
    thread.scrollTop = thread.scrollHeight;
  }

  if (composer) composer.classList.toggle("hidden", !careerInterviewState.started);
  if (input) input.disabled = !careerInterviewState.started || careerInterviewState.isComplete || careerInterviewState.loading;
  if (sendBtn) {
    sendBtn.disabled = !careerInterviewState.started || careerInterviewState.isComplete || careerInterviewState.loading;
    sendBtn.textContent = careerInterviewState.loading ? "生成中..." : "发送并继续";
  }
  if (startBtn) {
    startBtn.disabled = careerInterviewState.loading;
    startBtn.textContent = careerInterviewState.loading
      ? "生成中..."
      : careerInterviewState.started
        ? "访谈已启动"
        : (careerInterviewState.helperAnchor ? `围绕「${careerInterviewState.helperAnchor}」开始` : "立即开始访谈");
  }
  if (hintEl) {
    hintEl.textContent = careerInterviewState.isComplete
      ? "访谈已完成，可直接参考同步到能力画像的结果。"
      : `已完成 ${userMessageCount} 轮对话，点击「完成访谈」可随时结束`;
  }

  renderCareerInterviewAssistSurface();
  renderCareerInterviewDimensionProgress();
}
function renderCareerInterviewResult(result) {
  const emptyState = document.getElementById("careerInterviewEmptyState");
  const content = document.getElementById("careerInterviewContent");
  const progressEl = document.getElementById("careerInterviewResultProgress");
  const modalProgressEl = document.getElementById("careerInterviewModalProgress");
  const focusEl = document.getElementById("careerInterviewResultFocus");
  const modalFocusEl = document.getElementById("careerInterviewModalFocus");
  const summaryEl = document.getElementById("careerInterviewSummary");
  const valueTagsEl = document.getElementById("careerInterviewValueTags");
  const interestTagsEl = document.getElementById("careerInterviewInterestTags");
  const roleTagsEl = document.getElementById("careerInterviewRoleTags");
  const dimensionListEl = document.getElementById("careerInterviewDimensionList");
  const evidenceListEl = document.getElementById("careerInterviewEvidenceList");
  const actionListEl = document.getElementById("careerInterviewActionList");

  syncCareerInterviewProgress(result);
  updateCareerInterviewHero(result);

  const progressText = `${careerInterviewState.completionScore || 0}%`;
  const focusName = normalizeCareerDimensionName(result?.focus_dimension || careerInterviewState.focusDimension);

  if (!result || !result.profile) {
    if (emptyState) emptyState.classList.remove("hidden");
    if (content) content.classList.add("hidden");
    if (progressEl) progressEl.textContent = progressText;
    if (modalProgressEl) modalProgressEl.textContent = progressText;
    if (focusEl) focusEl.textContent = focusName;
    if (modalFocusEl) modalFocusEl.textContent = focusName;
    updateProfileRadarChart(null);
    renderCareerInterviewDimensionProgress();
    refreshUnifiedExperience();
    return;
  }

  if (emptyState) emptyState.classList.add("hidden");
  if (content) content.classList.remove("hidden");
  if (progressEl) progressEl.textContent = progressText;
  if (modalProgressEl) modalProgressEl.textContent = progressText;
  if (focusEl) focusEl.textContent = focusName;
  if (modalFocusEl) modalFocusEl.textContent = focusName;

  // 新的profile格式：叙事性摘要
  if (summaryEl) {
    summaryEl.textContent = result.profile?.summary || "访谈进行中，继续探索以完善画像。";
  }

  // 工作价值观
  if (valueTagsEl) {
    const values = result.profile?.work_values || [];
    valueTagsEl.innerHTML = values.length > 0
      ? careerTagHtml(values, "等待补充", "soft")
      : '<span class="text-xs text-gray-400">继续对话，探索你的工作价值观</span>';
  }

  // 角色模型/钦佩的人
  if (interestTagsEl) {
    const roleModel = result.profile?.role_model;
    interestTagsEl.innerHTML = roleModel
      ? `<span class="career-tag primary">${escHtml(roleModel)}</span>`
      : '<span class="text-xs text-gray-400">继续对话，探索你的职业榜样</span>';
  }

  // 领导/协作风格
  if (roleTagsEl) {
    const leadership = result.profile?.leadership_style;
    roleTagsEl.innerHTML = leadership
      ? `<span class="career-tag accent">${escHtml(leadership)}</span>`
      : '<span class="text-xs text-gray-400">继续对话，探索你的协作风格</span>';
  }

  // 关键经历证据
  if (evidenceListEl) {
    const experience = result.profile?.key_experience;
    evidenceListEl.innerHTML = experience
      ? `<div class="career-evidence-item"><span class="career-evidence-icon">&#127908;</span><p>${escHtml(experience)}</p></div>`
      : '<p class="text-xs text-gray-400">继续对话，挖掘你的关键经历</p>';
  }

  // 推荐探索方向
  if (actionListEl) {
    const exploration = result.profile?.recommended_exploration || [];
    actionListEl.innerHTML = exploration.length > 0
      ? careerListHtml(exploration, "")
      : '<p class="text-xs text-gray-400">继续对话，发现更多探索方向</p>';
  }

  // 维度列表（旧格式兼容）
  if (dimensionListEl) {
    const dims = result.profile?.dimensions;
    if (dims && dims.length > 0) {
      dimensionListEl.innerHTML = careerDimensionHtml(dims);
    } else {
      dimensionListEl.innerHTML = "";
    }
  }

  renderCareerInterviewDimensionProgress();
  renderCareerInterviewAssistSurface();
  updateProfileRadarChart(result.profile);
  refreshUnifiedExperience();
}
function updateProfileRadarChart(profile) {
  const chart = appState.profileRadarChart;
  if (!chart) return;

  if (!profile || !Array.isArray(profile.dimensions) || profile.dimensions.length === 0) {
    chart.data.labels = ["专业技能", "证书资质", "沟通能力", "学习能力", "抗压能力", "创新能力", "实习经历", "项目经验"];
    chart.data.datasets[0].label = "能力评分";
    chart.data.datasets[0].data = [75, 60, 82, 88, 70, 65, 60, 55];
    chart.update();
    return;
  }

  chart.data.labels = profile.dimensions.map((item) => item.name);
  chart.data.datasets[0].label = "访谈画像";
  chart.data.datasets[0].data = profile.dimensions.map((item) => Number(item.score || 0));
  chart.update();
}

async function hydrateCareerInterviewState(force = false) {
  await loadCareerInterviewConfig(force);
  if (!isAuthenticatedUser()) {
    resetCareerInterviewState({ preserveBasics: false });
    renderCareerInterviewMessages();
    renderCareerInterviewResult(null);
    return;
  }

  const snapshot = await fetchScopedUserState("career_interview", force);
  if (!snapshot) {
    resetCareerInterviewState({ preserveBasics: false });
    renderCareerInterviewMessages();
    renderCareerInterviewResult(null);
    return;
  }

  careerInterviewState.started = Boolean(snapshot.started);
  careerInterviewState.loading = false;
  careerInterviewState.isComplete = Boolean(snapshot.isComplete);
  careerInterviewState.messages = Array.isArray(snapshot.messages) ? snapshot.messages : [];
  careerInterviewState.result = snapshot.result || null;
  careerInterviewState.completionScore = Number(snapshot.completionScore || 0);
  careerInterviewState.focusDimension = snapshot.focusDimension || CAREER_INTERVIEW_DIMENSION_PLAN[0].name;
  careerInterviewState.profileBasics = normalizeProfileBasics(snapshot.profileBasics);
  careerInterviewState.dimensionProgress = Array.isArray(snapshot.dimensionProgress) && snapshot.dimensionProgress.length > 0
    ? snapshot.dimensionProgress
    : createCareerInterviewDimensionProgress();

  syncCareerInterviewProgress(careerInterviewState.result);
  syncProfileBasicsForm();
  renderCareerInterviewMessages();
  renderCareerInterviewResult(careerInterviewState.result);
}
function openCareerInterviewModal(mode = "chat") {
  fillCareerInterviewConfigForm();
  updateCareerInterviewConfigStatus();
  renderCareerInterviewMessages();
  renderCareerInterviewResult(careerInterviewState.result);
  renderCareerInterviewAssistSurface();
  bindCareerInterviewHelperInteractions();
  const modal = document.getElementById("careerInterviewModal");
  if (!modal) return;
  modal.classList.remove("hidden");
  window.requestAnimationFrame(() => {
    modal.scrollIntoView({ behavior: "smooth", block: "start" });
  });

  window.setTimeout(() => {
    if (mode === "config") {
      // 配置已迁移至头像设置面板
      openSettingsPanel();
    } else if (careerInterviewState.started && !careerInterviewState.isComplete) {
      document.getElementById("careerInterviewInput")?.focus();
    } else {
      document.getElementById("careerInterviewStartBtn")?.focus();
    }
  }, 120);
}

function closeCareerInterviewModal() {
  const modal = document.getElementById("careerInterviewModal");
  if (modal) modal.classList.add("hidden");
  stopCareerInterviewVoice();
}

function handleCareerInterviewOverlayClick(event) {
  if (event.target?.id === "careerInterviewModal") {
    closeCareerInterviewModal();
  }
}

function clearCareerInterviewSession() {
  resetCareerInterviewState({ preserveBasics: true });
  persistCareerInterviewSnapshot();
  renderCareerInterviewMessages();
  renderCareerInterviewResult(null);
  showToast("访谈已清空", "你可以重新开始新的访谈。", "info", 1600);
}

window.clearCareerInterviewHelperAnchor = function clearCareerInterviewHelperAnchor() {
  careerInterviewState.helperAnchor = "";
  renderCareerInterviewAssistSurface();
};

window.toggleCareerInterviewVoice = function toggleCareerInterviewVoice() {
  if (!careerInterviewState.started || careerInterviewState.isComplete || careerInterviewState.loading) return;
  const recognition = ensureCareerInterviewVoiceRecognition();
  if (!recognition) {
    showToast("当前浏览器不支持语音", "请继续使用文本输入。", "warning", 1800);
    return;
  }
  if (careerInterviewVoiceState.listening) {
    recognition.stop();
    return;
  }
  try {
    recognition.start();
  } catch (_) {
    showToast("语音输入暂不可用", "请稍后再试或直接输入文字。", "warning", 1800);
  }
};

function handleCareerInterviewInputKeydown(event) {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    submitCareerInterviewAnswer();
  }
}

async function requestCareerInterview(messages) {
  const config = getStoredCareerInterviewConfig();
  if (!config.configured) {
    throw new Error("职业访谈模型尚未由系统管理员配置。");
  }
  return requestJson("/api/career-interview", {
    method: "POST",
    body: {
      messages: messages.slice(-8),
      focus_dimension: careerInterviewState.focusDimension,
      progress: careerInterviewState.dimensionProgress,
      assessment_context: buildAssessmentContextPayload()
    }
  });
}
async function startCareerInterview(options = {}) {
  if (careerInterviewState.loading) {
    showToast("访谈正在处理中", "请稍候，当前请求尚未完成。", "info", 1600);
    return;
  }

  try {
    await loadCareerInterviewConfig(true);
    const config = getStoredCareerInterviewConfig();
    if (!config.configured) {
      showToast("缺少模型配置", isSuperAdminUser() ? "请先保存系统模型配置。" : "当前模型由系统管理员统一配置，请联系管理员。", "warning", 2200);
      if (typeof openModelPicker === "function") {
        openModelPicker();
      } else {
        openCareerInterviewModal("config");
      }
      return;
    }

    resetCareerInterviewState({ preserveBasics: true });
    careerInterviewState.started = true;
    careerInterviewState.focusDimension = CAREER_INTERVIEW_DIMENSION_PLAN[0].name;
    careerInterviewState.dimensionProgress = createCareerInterviewDimensionProgress();
    careerInterviewState.result = {
      is_complete: false,
      completion_score: 0,
      focus_dimension: careerInterviewState.focusDimension,
      profile: null
    };
    careerInterviewState.messages.push({
      role: "assistant",
      content: getCareerDimensionPrompt(careerInterviewState.focusDimension)
    });
    syncCareerInterviewProgress(careerInterviewState.result);
    persistCareerInterviewSnapshot();
    renderCareerInterviewMessages();
    renderCareerInterviewResult(careerInterviewState.result);
    showToast("访谈已启动", "请先回答第一轮问题。", "success", 1200);
    if (options.initialDraft) {
      setCareerInterviewComposerDraft(options.initialDraft, {
        append: false,
        anchorLabel: options.helperAnchor || ""
      });
    } else {
      document.getElementById("careerInterviewInput")?.focus();
    }
  } catch (error) {
    showToast("启动访谈失败", error?.message || "请稍后重试。", "error", 2200);
  }
}
async function submitCareerInterviewAnswer() {
  if (careerInterviewState.loading || !careerInterviewState.started || careerInterviewState.isComplete) return;
  const input = document.getElementById("careerInterviewInput");
  const answer = (input?.value || "").trim();
  if (!answer) {
    showToast("请先输入回答", "模型需要你的回答才能继续追问。", "warning", 1800);
    return;
  }

  markCareerDimensionAnswered(careerInterviewState.focusDimension);
  careerInterviewState.messages.push({ role: "user", content: answer });
  if (input) input.value = "";

  const currentProgress = getCareerDimensionProgressByName(careerInterviewState.focusDimension);
  const shouldAskLocalFollowUp = currentProgress && currentProgress.answered < currentProgress.target;

  if (shouldAskLocalFollowUp) {
    careerInterviewState.completionScore = getCareerInterviewProgressPercent();
    careerInterviewState.messages.push({
      role: "assistant",
      content: getCareerDimensionPrompt(careerInterviewState.focusDimension)
    });
    persistCareerInterviewSnapshot();
    renderCareerInterviewMessages();
    renderCareerInterviewResult(careerInterviewState.result);
    document.getElementById("careerInterviewInput")?.focus();
    return;
  }

  careerInterviewState.loading = true;
  renderCareerInterviewMessages();
  renderCareerInterviewResult(careerInterviewState.result);

  try {
    const result = await requestCareerInterview(careerInterviewState.messages);
    careerInterviewState.loading = false;
    careerInterviewState.result = result;
    syncCareerInterviewProgress(result);

    // 检查是否是 __FINISH__ 标记（AI认为可以结束）
    const nextQuestion = result.next_question || "";
    const shouldFinish = nextQuestion === "__FINISH__" || Boolean(result.is_complete);

    // 更新完成度（基于对话轮次）
    const userMessageCount = careerInterviewState.messages.filter(m => m.role === "user").length;
    careerInterviewState.completionScore = Math.min(Math.round(userMessageCount / 3 * 100), 95); // 3轮=100%,最多95%
    careerInterviewState.isComplete = shouldFinish;

    if (shouldFinish) {
      careerInterviewState.messages.push({
        role: "assistant",
        content: result.profile?.summary || "访谈完成，我已经整理出你的职业画像。"
      });
    } else {
      careerInterviewState.messages.push({
        role: "assistant",
        content: nextQuestion
      });
    }
    persistCareerInterviewSnapshot();
    renderCareerInterviewMessages();
    renderCareerInterviewResult(result);
    document.getElementById("careerInterviewInput")?.focus();
  } catch (error) {
    careerInterviewState.loading = false;
    renderCareerInterviewMessages();
    renderCareerInterviewResult(careerInterviewState.result);
    showToast("继续访谈失败", error.message, "error", 2400);
  }
}

async function finishCareerInterview() {
  if (careerInterviewState.loading || !careerInterviewState.started) return;
  if (careerInterviewState.messages.length === 0) {
    showToast("还没有开始访谈", "请先开始访谈再完成。", "warning", 1800);
    return;
  }

  careerInterviewState.loading = true;
  renderCareerInterviewMessages();
  renderCareerInterviewResult(careerInterviewState.result);

  try {
    const result = await requestJson("/api/career-interview/finish", {
      method: "POST",
      body: {
        messages: careerInterviewState.messages.slice(-20),
        assessment_context: buildAssessmentContextPayload()
      }
    });

    careerInterviewState.loading = false;
    careerInterviewState.isComplete = true;

    // 更新 result 中的 profile
    if (result.profile) {
      careerInterviewState.result = {
        ...careerInterviewState.result,
        profile: result.profile,
        summary: result.summary || result.profile.summary || "访谈已完成"
      };
    }

    careerInterviewState.messages.push({
      role: "assistant",
      content: result.summary || "感谢你的分享！我已经整理出你的职业画像。"
    });

    persistCareerInterviewSnapshot();
    renderCareerInterviewMessages();
    renderCareerInterviewResult(careerInterviewState.result);
    showToast("访谈已完成", "感谢你的参与！", "success", 1600);
  } catch (error) {
    careerInterviewState.loading = false;
    renderCareerInterviewMessages();
    renderCareerInterviewResult(careerInterviewState.result);
    showToast("完成访谈失败", error.message, "error", 2400);
  }
}

function addLiveActivity(message) {
  const timeLabel = formatClock(new Date());
  ["liveActivityFeed", "liveActivityFeedDisplay"].forEach((id) => {
    const feed = document.getElementById(id);
    if (!feed) return;
    const li = document.createElement("li");
    li.className = "live-feed-item";
    li.innerHTML = `
      <span class="live-feed-dot"></span>
      <div>
        <p class="text-sm text-gray-800">${message}</p>
        <p class="text-xs text-gray-500">${timeLabel}</p>
      </div>
    `;
    feed.insertBefore(li, feed.firstChild);
    while (feed.children.length > 6) feed.removeChild(feed.lastElementChild);
  });
}

const careerNewsState = {
  initialized: false,
  displayLimit: 10,
  visibleCount: 10,
  pageSize: 5,
  items: []
};

function _careerNewsPublishedTs(el) {
  if (!el) return 0;
  const raw = String(el.dataset.published || "").trim();
  const ts = raw ? Date.parse(raw) : NaN;
  if (Number.isFinite(ts)) return ts;
  const label = String(el.querySelector(".career-news-time")?.textContent || "").trim();
  const guess = Date.parse(label);
  return Number.isFinite(guess) ? guess : 0;
}

function _getCareerNewsWorkingItems() {
  const working = [...careerNewsState.items];
  working.sort((a, b) => {
    return _careerNewsPublishedTs(b) - _careerNewsPublishedTs(a);
  });
  return working;
}

function _updateCareerNewsCarouselControls() {
  const track = document.getElementById("careerNewsFeatured");
  const prevBtn = document.getElementById("careerNewsPrevBtn");
  const nextBtn = document.getElementById("careerNewsNextBtn");
  if (!track || !prevBtn || !nextBtn) return;
  const maxScroll = Math.max(0, track.scrollWidth - track.clientWidth);
  const canScroll = maxScroll > 4;
  prevBtn.disabled = !canScroll || track.scrollLeft <= 4;
  nextBtn.disabled = !canScroll || track.scrollLeft >= maxScroll - 4;
}

function _careerNewsScrollStep(track) {
  const first = track?.querySelector(".career-news-item");
  if (!track || !first) return 320;
  const styles = window.getComputedStyle(track);
  const gap = Number.parseFloat(styles.columnGap || styles.gap || "0") || 0;
  return first.getBoundingClientRect().width + gap;
}

function _applyCareerNewsBoard(options = {}) {
  const board = document.getElementById("careerNewsBoard");
  const track = document.getElementById("careerNewsFeatured");
  const parking = document.getElementById("careerNewsListRows");
  const moreBtn = document.getElementById("careerNewsMoreBtn");
  if (!board || !track) return;

  const prevScroll = options.preserveScroll ? track.scrollLeft : 0;
  const working = _getCareerNewsWorkingItems();
  working.forEach((el, idx) => {
    const rank = el.querySelector(".career-news-rank");
    if (rank) rank.textContent = String(idx + 1);
  });

  if (parking) {
    careerNewsState.items.forEach((el) => {
      el.classList.remove("career-news-slide");
      parking.appendChild(el);
    });
  }

  track.innerHTML = "";
  const visibleCount = Math.min(Math.max(0, careerNewsState.visibleCount), working.length);
  working.slice(0, visibleCount).forEach((el) => {
    el.classList.add("career-news-slide");
    track.appendChild(el);
  });

  if (moreBtn) {
    const hasMore = visibleCount < working.length;
    moreBtn.hidden = !hasMore;
    moreBtn.disabled = !hasMore;
    moreBtn.textContent = "More +";
  }

  const countEl = document.getElementById("careerNewsShowingCount");
  if (countEl) {
    countEl.textContent = `当前展示 ${visibleCount} / ${working.length} 条`;
  }

  requestAnimationFrame(() => {
    track.scrollLeft = options.preserveScroll ? prevScroll : 0;
    _updateCareerNewsCarouselControls();
  });
}

function initCareerNewsBoard() {
  const board = document.getElementById("careerNewsBoard");
  if (!board || careerNewsState.initialized) return;
  careerNewsState.initialized = true;
  careerNewsState.displayLimit = Math.max(1, Number(board.dataset.displayLimit || 10));
  careerNewsState.visibleCount = careerNewsState.displayLimit;
  const pool = document.getElementById("careerNewsPool");
  careerNewsState.items = [...(pool || board).querySelectorAll(".career-news-item")];

  document.getElementById("careerNewsPrevBtn")?.addEventListener("click", () => careerNewsSlide(-1));
  document.getElementById("careerNewsNextBtn")?.addEventListener("click", () => careerNewsSlide(1));
  document.getElementById("careerNewsMoreBtn")?.addEventListener("click", () => careerNewsLoadMore());
  document.getElementById("careerNewsFeatured")?.addEventListener("scroll", () => {
    window.requestAnimationFrame(_updateCareerNewsCarouselControls);
  }, { passive: true });
  window.addEventListener("resize", _updateCareerNewsCarouselControls);

  _applyCareerNewsBoard();
}

function careerNewsSlide(direction = 1) {
  if (!careerNewsState.initialized) initCareerNewsBoard();
  const track = document.getElementById("careerNewsFeatured");
  if (!track) return;
  track.scrollBy({ left: _careerNewsScrollStep(track) * direction, behavior: "smooth" });
  window.setTimeout(_updateCareerNewsCarouselControls, 260);
}

function careerNewsLoadMore() {
  if (!careerNewsState.initialized) initCareerNewsBoard();
  const track = document.getElementById("careerNewsFeatured");
  const beforeWidth = track?.scrollWidth || 0;
  careerNewsState.visibleCount += careerNewsState.pageSize;
  _applyCareerNewsBoard({ preserveScroll: true });
  if (track) {
    window.setTimeout(() => {
      track.scrollTo({ left: Math.max(0, beforeWidth), behavior: "smooth" });
      _updateCareerNewsCarouselControls();
    }, 60);
  }
}

// 兼容旧调用
function careerNewsGoPage(page) {
  if (!careerNewsState.initialized) initCareerNewsBoard();
  if (Number(page) > 1) careerNewsLoadMore();
  else careerNewsSlide(-1);
  const board = document.getElementById("careerNewsBoard");
  if (board) board.scrollIntoView({ behavior: "smooth", block: "start" });
}

function toggleCareerNewsMore() { careerNewsLoadMore(); }

function clampPercent(value, fallback = 0) {
  const num = Number(value);
  if (!Number.isFinite(num)) return fallback;
  return Math.max(0, Math.min(100, Math.round(num)));
}

function averageValues(values) {
  const list = Array.isArray(values) ? values.filter((value) => Number.isFinite(Number(value))) : [];
  if (!list.length) return null;
  return Math.round(list.reduce((sum, value) => sum + Number(value), 0) / list.length);
}

function uniqueValues(values, limit = 6) {
  return [...new Set((Array.isArray(values) ? values : []).map((item) => String(item || "").trim()).filter(Boolean))].slice(0, limit);
}

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
    uncertainty.push("当前关键信号来源较一致，这一页更适合作为后续规划模块的画像基底。");
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
  const chips = uniqueValues([
    mbti ? `MBTI ${mbti}` : "",
    holland ? `霍兰德 ${holland}` : "",
    ...(Array.isArray(profile?.assessment?.holland?.top_codes) ? profile.assessment.holland.top_codes.map((item) => `兴趣 ${item}`) : [])
  ], 6);
  const status = mbti && holland ? "complete" : (mbti || holland ? "partial" : "missing");
  const summary = mbti && holland
    ? `测评阶段已经给出人格倾向和职业兴趣锚点，当前人物画像会把 ${mbti} 与 ${holland} 的共同信号作为底层基调。`
    : mbti || holland
      ? `测评阶段只形成了部分锚点，当前会先使用已有结果参与人物画像收敛。`
      : "测评阶段尚未形成稳定输出，人物画像会更多依赖简历和访谈信号。";
  const note = mbti && holland
    ? "这一层主要负责回答“你大致是什么样的人、会被什么工作场景激活”。"
    : "测评没有补齐时，人物画像仍可生成，但人格与兴趣的稳定度会下降。";
  return {
    stepLabel: "01",
    title: "测评输出",
    status,
    summary,
    chips,
    note,
    raw: {
      status,
      summary,
      chips,
      note,
      mbti,
      holland
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

function buildProfileInterviewModuleOutput(profile) {
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
  const chips = uniqueValues([
    ...(interviewProfile?.work_values || []),
    ...(interviewProfile?.recommended_roles || []),
    interviewProfile?.leadership_style || "",
    interviewProfile?.role_model || ""
  ], 6);
  const summary = interviewProfile?.summary
    || (completionScore
      ? `访谈已经形成 ${completionScore}% 的动态画像，但还没有沉淀出稳定摘要。`
      : "访谈阶段尚未形成可用输出。");
  const note = !interviewProfile
    ? "这一层负责补足价值观、关键经历、协作风格和行动证据。"
    : (interviewProfile?.coverage_note
      || (isComplete
        ? "访谈已经形成完整输出，可直接进入人物明信片。"
        : "即使提前结束，只要已经收敛出价值观、经历或协作风格，也可以进入人物明信片首版。"));
  const missingFollowups = uniqueValues(interviewProfile?.missing_followups || [], 4);
  return {
    stepLabel: "03",
    title: "访谈输出",
    status,
    summary,
    chips,
    note,
    raw: {
      status,
      summary,
      chips,
      note,
      completion_score: completionScore,
      usable_for_portrait: usableForPortrait,
      missing_followups: missingFollowups,
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
    ...(brief?.evidence_tags || []).slice(0, 2),
    ...(brief?.value_tags || []).slice(0, 2)
  ], 6);
  const summary = portraitState?.prompt_summary
    || brief?.subtitle
    || synthesis?.thesis
    || "系统会把前 3 步的输出压缩成标题、定位句、主角色、任务句和视觉设定。";
  const note = portraitState?.brief
    ? `系统会先把 1/2/3 步的输出重写成画像 brief，再生成适合白底人物明信片的渲染提示词。当前模式：${promptModeLabel}。`
    : "点击“生成任务海报”后，系统会自动整理三步输出并重写为人物画像提示词。";
  return {
    stepLabel: "AI",
    title: "提示词重写",
    status,
    summary,
    chips,
    note,
    meta: promptModeLabel
  };
}

function buildProfilePortraitOutputCards(profile, roles, synthesis, portraitState, resumeTraits = null) {
  return [
    buildProfileAssessmentModuleOutput(profile),
    buildProfileResumeModuleOutput(profile, resumeTraits),
    buildProfileInterviewModuleOutput(profile),
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
    return `
      <article class="profile-portrait-output-card is-${escHtml(item.status || "missing")}">
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
function renderProfileCapabilityStrip(el, profile) {
  if (!el) return;
  const dims = [
    { key: "professional",     label: "专业技能", icon: "⚙️" },
    { key: "learning",         label: "学习能力", icon: "📖" },
    { key: "communication",    label: "沟通能力", icon: "💬" },
    { key: "innovation",       label: "创新能力", icon: "💡" },
    { key: "stress_tolerance", label: "抗压能力", icon: "🧱" },
    { key: "execution",        label: "执行力",   icon: "🎯" }
  ];

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
function renderProfileEvidenceGaps(el, profile) {
  if (!el) return;
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

function buildProfilePortraitContext(profile, roles, synthesis) {
  const resumeState = userWorkspaceState.scopedData.resume_profile || null;
  const resumeTraits = buildResumePortraitTraits(resumeState);
  const interviewProfile = profile?.interview?.profile || null;
  const assessmentOutput = buildProfileAssessmentModuleOutput(profile);
  const resumeOutput = buildProfileResumeModuleOutput(profile, resumeTraits);
  const interviewOutput = buildProfileInterviewModuleOutput(profile);
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
    module_outputs: {
      assessment: assessmentOutput.raw,
      resume: resumeOutput.raw,
      interview: interviewOutput.raw
    },
    prompt_request: {
      card_style: "人物明信片",
      card_goal: "美观清晰，一眼看懂这个人最像什么岗位、能做什么任务、下一步该补什么。",
      visual_direction: "适合白底页面展示，职业感明确，信息克制，避免宣传海报式堆砌。",
      required_fields: ["标题", "定位句", "主角色", "任务句", "证据标签", "下一步"]
    }
  };
}

const PROFILE_PORTRAIT_LOADING_STAGES = [
  { title: "收敛定位", copy: "从测评、简历与访谈里收敛主角色和职业定位。" },
  { title: "生成名片", copy: "把定位压缩成可对外展示的任务名片结构。" },
  { title: "渲染海报", copy: "沿用当前图片 API 生成 3:4 半写实人物海报。" }
];

function startProfilePortraitLoading(mode = "render") {
  if (profilePortraitTaskState.stageTimer) clearInterval(profilePortraitTaskState.stageTimer);
  profilePortraitTaskState.loading = true;
  profilePortraitTaskState.mode = mode;
  profilePortraitTaskState.stageIndex = 0;
  profilePortraitTaskState.stageTimer = setInterval(() => {
    profilePortraitTaskState.stageIndex = Math.min(PROFILE_PORTRAIT_LOADING_STAGES.length - 1, profilePortraitTaskState.stageIndex + 1);
    const profile = appState.derivedProfile || deriveUnifiedProfile();
    const roles = Array.isArray(appState.matchingRoles) && appState.matchingRoles.length
      ? appState.matchingRoles
      : computeRoleMatches(profile);
    renderProfileWorkspace(profile, roles);
  }, 850);
}

function stopProfilePortraitLoading() {
  if (profilePortraitTaskState.stageTimer) clearInterval(profilePortraitTaskState.stageTimer);
  profilePortraitTaskState.stageTimer = null;
  profilePortraitTaskState.loading = false;
  profilePortraitTaskState.stageIndex = 0;
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
          <span class="profile-portrait-poster-status">生成中</span>
          <div>
            <h4 class="profile-portrait-poster-title">任务海报正在生成</h4>
            <p class="profile-portrait-poster-copy">系统会先收敛职业定位，再把结果压缩成任务名片，最后渲染为半写实人物海报。</p>
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
    ? "职业定位已经收敛完成，但海报渲染失败。你可以直接重试海报，不需要重新分析整套输入。"
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
            <p class="profile-portrait-kicker">任务名片生成中</p>
            <h4 class="profile-portrait-brief-title">正在压缩关键信息</h4>
            <p class="profile-portrait-brief-subtitle">结果页只会保留首屏最重要的信息，避免把分析内容一次性铺满。</p>
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
            <p class="profile-portrait-brief-subtitle">首屏会只保留 5 个关键信息块，让人一眼看懂你是谁、最像什么岗位，以及下一步该做什么。</p>
          </div>
        </div>
        <div class="profile-portrait-brief-grid">
          <section class="profile-portrait-brief-section label-strong">
            <p class="profile-portrait-brief-label">你是谁</p>
            <p class="profile-portrait-brief-body muted">点击“生成任务海报”后，系统会先收敛职业定位，再把结果压缩成任务名片。</p>
          </section>
          <section class="profile-portrait-brief-section">
            <p class="profile-portrait-brief-label">最像岗位</p>
            <div class="profile-portrait-chip-row"><span class="profile-portrait-chip soft">等待生成后展示</span></div>
          </section>
          <section class="profile-portrait-brief-section">
            <p class="profile-portrait-brief-label">你能承担什么任务</p>
            <p class="profile-portrait-brief-body muted">生成后会输出一句清晰的任务描述，而不是整页堆叠分析内容。</p>
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
          <p class="profile-portrait-brief-body muted">${escHtml(safeBrief.mission_line || "系统会把你的主角色压缩成一句任务描述。")}</p>
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
      statusLead.textContent = "系统会按“收敛定位 -> 生成名片 -> 渲染海报”的顺序输出，首屏只保留最关键的职业信息。";
    } else if (portraitState?.status === "brief_ready") {
      statusLead.textContent = "任务名片已经生成，但海报渲染失败。你可以直接重试海报，不需要重新收敛整套输入。";
    } else if (portraitState?.image_url) {
      statusLead.textContent = "首屏现在已经收敛成可对外展示的任务名片，你可以复制定位文案或重新渲染海报。";
    } else if (!hasGeneratedBrief) {
      statusLead.textContent = "这一页默认保持占位态，等你点击生成后再把结果压缩成首屏可读的任务名片。";
    } else {
      statusLead.textContent = "结果页优先展示你是谁、最像什么岗位、为什么这样判断，以及下一步最该做什么。";
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
      const focusRole = brief?.primary_role || (roles || [])[0]?.name || profile?.basics?.target_direction || synthesis?.archetype?.name || "当前职业画像";
      hint.textContent = `系统会先围绕 ${focusRole} 收敛主角色，再生成适合白底页面展示的半写实人物海报。`;
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

function getProfileFlowCompletion(profile) {
  const p = profile || deriveUnifiedProfile();
  const basicsReady = PROFILE_BASIC_FIELDS.every((key) => p?.basics?.[key]);
  const step1Complete = Boolean(p?.assessment?.mbti?.completed && p?.assessment?.holland?.completed);
  const step2Complete = String(p?.resume?.status || "") === "analyzed";
  const step3Complete = Boolean((p?.interview?.isComplete || Number(p?.interview?.completionScore || 0) >= 70) && basicsReady);
  return {
    1: step1Complete,
    2: step2Complete,
    3: step3Complete,
    4: step1Complete || step2Complete || step3Complete
  };
}

function getRecommendedProfileStep(completion) {
  const done = completion || getProfileFlowCompletion();
  for (const step of [1, 2, 3]) {
    if (!done[step] && !profileFlowState.skippedSteps.includes(step)) return step;
  }
  return 4;
}

function normalizeProfileFlowState(profile) {
  const completion = getProfileFlowCompletion(profile);
  profileFlowState.completedSteps = PROFILE_FLOW_STEPS.filter((step) => Boolean(completion[step]));
  profileFlowState.skippedSteps = profileFlowState.skippedSteps
    .filter((step) => PROFILE_FLOW_STEPS.includes(step) && step < 4 && !profileFlowState.completedSteps.includes(step));
  if (!PROFILE_FLOW_STEPS.includes(profileFlowState.currentStep)) profileFlowState.currentStep = 1;
  if (!profileFlowState.touched) profileFlowState.currentStep = getRecommendedProfileStep(completion);
}

function initProfileFlow(force = false) {
  if (force) {
    profileFlowState.currentStep = 1;
    profileFlowState.skippedSteps = [];
    profileFlowState.completedSteps = [];
    profileFlowState.touched = false;
  }
  renderProfileFlow(appState.derivedProfile || deriveUnifiedProfile());
}

function renderProfileFlow(profile) {
  const p = profile || appState.derivedProfile || deriveUnifiedProfile();
  normalizeProfileFlowState(p);
  const progressText = document.getElementById("profileFlowProgressText");
  if (progressText) {
    progressText.textContent = `当前步骤：${profileFlowState.currentStep} / 4`;
  }

  PROFILE_FLOW_STEPS.forEach((step) => {
    const panel = document.getElementById(`profileFlowStep${step}`);
    if (panel) panel.classList.toggle("hidden", step !== profileFlowState.currentStep);
    const navBtn = document.querySelector(`.profile-flow-step[data-step="${step}"]`);
    const statusEl = document.getElementById(`profileFlowStepStatus${step}`);
    const isDone = profileFlowState.completedSteps.includes(step);
    const isSkipped = profileFlowState.skippedSteps.includes(step);
    const isActive = step === profileFlowState.currentStep;
    if (navBtn) {
      navBtn.classList.toggle("is-active", isActive);
      navBtn.classList.toggle("is-done", isDone);
      navBtn.classList.toggle("is-skipped", isSkipped);
    }
    if (statusEl) {
      if (step === 4) {
        statusEl.textContent = "总览";
      } else if (isDone) {
        statusEl.textContent = "已完成";
      } else if (isSkipped) {
        statusEl.textContent = "已跳过";
      } else if (isActive) {
        statusEl.textContent = "进行中";
      } else {
        statusEl.textContent = "待开始";
      }
    }
  });
}

function goProfileStep(step) {
  const target = Number(step || 1);
  if (!PROFILE_FLOW_STEPS.includes(target)) return;
  profileFlowState.currentStep = target;
  profileFlowState.touched = true;
  renderProfileFlow(appState.derivedProfile || deriveUnifiedProfile());
}

function skipProfileStep(step) {
  const target = Number(step || profileFlowState.currentStep || 1);
  if (!PROFILE_FLOW_STEPS.includes(target) || target === 4) return;
  if (!profileFlowState.completedSteps.includes(target) && !profileFlowState.skippedSteps.includes(target)) {
    profileFlowState.skippedSteps.push(target);
  }
  profileFlowState.currentStep = Math.min(4, target + 1);
  profileFlowState.touched = true;
  renderProfileFlow(appState.derivedProfile || deriveUnifiedProfile());
  showToast("已跳过当前步骤", "你可以随时返回补充，结果页会保留缺失提示。", "info", 1500);
}

function nextProfileStep() {
  profileFlowState.currentStep = Math.min(4, Number(profileFlowState.currentStep || 1) + 1);
  profileFlowState.touched = true;
  renderProfileFlow(appState.derivedProfile || deriveUnifiedProfile());
}

function getAssessmentHubSnapshotSafe() {
  try {
    return typeof window.getAssessmentHubSnapshot === "function" ? window.getAssessmentHubSnapshot() : null;
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
      profile: resumeProfile
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

function computeTraitMatch(role, profile) {
  const assessment = profile.assessment;
  const scores = [];
  const reasons = [];
  const mbtiType = assessment?.mbti?.completed ? String(assessment.mbti.final_type || assessment.mbti.raw_type || "") : "";
  if (mbtiType) {
    if ((role.recommendedMbti || []).includes(mbtiType)) {
      scores.push(95);
      reasons.push(`MBTI ${mbtiType} 落在岗位推荐类型内`);
    } else if ((role.recommendedMbti || []).some((code) => code.slice(1, 3) === mbtiType.slice(1, 3))) {
      scores.push(80);
      reasons.push("MBTI 与岗位推荐的核心偏好相近");
    } else {
      scores.push(58);
      reasons.push("MBTI 与岗位偏好存在一定差距");
    }
  }
  const hollandCodes = Array.isArray(assessment?.holland?.top_codes) ? assessment.holland.top_codes : [];
  if (hollandCodes.length) {
    const overlap = (role.recommendedHolland || []).filter((code) => hollandCodes.includes(code)).length;
    if (overlap >= 3) {
      scores.push(95);
      reasons.push("霍兰德代码与岗位画像高度重合");
    } else if (overlap === 2) {
      scores.push(82);
      reasons.push("霍兰德主导兴趣与岗位需求较一致");
    } else if (overlap === 1) {
      scores.push(66);
      reasons.push("霍兰德兴趣部分覆盖岗位画像");
    } else {
      scores.push(45);
      reasons.push("霍兰德兴趣与岗位画像重合度较低");
    }
  }
  return {
    score: averageValues(scores),
    reason: reasons.join("；") || "等待测评结果。"
  };
}

function computeAbilityMatch(role, profile) {
  const capabilityConfig = [
    { key: "professional", label: "专业技能", weight: 0.2 },
    { key: "innovation", label: "创新能力", weight: 0.15 },
    { key: "learning", label: "学习能力", weight: 0.15 },
    { key: "stress_tolerance", label: "抗压能力", weight: 0.12 },
    { key: "communication", label: "沟通能力", weight: 0.18 },
    { key: "internship", label: "实习能力", weight: 0.1 },
    { key: "execution", label: "执行能力", weight: 0.1 }
  ];
  const strengths = [];
  const gaps = [];
  const lines = [];
  let weightedScore = 0;
  let usedWeight = 0;
  capabilityConfig.forEach((item) => {
    const current = profile.capabilities[item.key]?.score;
    const required = Number(role.requirements[item.key] || 0);
    if (current === null || current === undefined || !required) return;
    const fitScore = clampPercent(current / required * 100);
    weightedScore += fitScore * item.weight;
    usedWeight += item.weight;
    lines.push(`${item.label} ${current}/${required}`);
    if (current + 8 < required) gaps.push(`${item.label} ${current}/${required}`);
    if (current >= required) strengths.push(`${item.label} ${current}/${required}`);
  });
  return {
    score: usedWeight ? Math.round(weightedScore / usedWeight) : null,
    coverageWeight: Math.round(usedWeight * 100),
    reason: lines.length ? `已使用 ${lines.join("、")} 计算能力匹配。` : "职业访谈和基础信息尚不足以判断能力匹配。",
    strengths: strengths.slice(0, 3),
    gaps: gaps.slice(0, 4)
  };
}

function computeMajorMatch(role, basics) {
  const major = String(basics.major || "").trim();
  if (!major) {
    return { score: null, reason: "未填写专业，专业匹配待补充。" };
  }
  if ((role.majors || []).includes("不限")) {
    return { score: 82, reason: "该岗位对专业限制较低，可通过能力与作品补足。" };
  }
  if ((role.majors || []).some((item) => major.includes(item) || item.includes(major))) {
    return { score: 100, reason: `${major} 与岗位常见专业背景直接相关。` };
  }
  const relatedGroups = [
    { keywords: ["计算机", "软件", "信息", "网络", "智能"], score: 80 },
    { keywords: ["统计", "数学", "数据", "经管"], score: 78 },
    { keywords: ["设计", "数字媒体", "美术"], score: 82 },
    { keywords: ["新闻", "传播", "中文", "文史"], score: 80 },
    { keywords: ["管理", "心理", "工商", "人力"], score: 76 },
    { keywords: ["会计", "财务", "审计", "经济"], score: 86 }
  ];
  const matchedGroup = relatedGroups.find((group) => group.keywords.some((item) => major.includes(item)) && (role.majors || []).some((item) => group.keywords.includes(item)));
  if (matchedGroup) {
    return { score: matchedGroup.score, reason: `${major} 与岗位专业要求存在相关性，但仍需用课程或项目进一步证明。` };
  }
  return { score: 38, reason: `${major} 与岗位主流专业背景相关性较弱，需要额外的项目和技能证明。` };
}

function computeWillingnessMatch(role, profile) {
  const signals = [];
  const reasons = [];
  if (profile.basics.target_direction) {
    const matched = roleMatchesText(role, profile.basics.target_direction);
    signals.push(matched ? 92 : 52);
    reasons.push(matched ? "目标方向与岗位关键词一致" : "目标方向与岗位未形成明显重合");
  }
  const interviewProfile = profile.interview.profile;
  const recommendedRoles = Array.isArray(interviewProfile?.recommended_roles) ? interviewProfile.recommended_roles : [];
  if (recommendedRoles.length) {
    const matched = recommendedRoles.some((item) => roleMatchesText(role, item));
    signals.push(matched ? 95 : 58);
    reasons.push(matched ? "访谈推荐岗位包含该方向" : "访谈推荐岗位更偏向其他方向");
  }
  const interests = Array.isArray(interviewProfile?.career_interests) ? interviewProfile.career_interests : [];
  if (interests.length) {
    const matched = interests.some((item) => roleMatchesText(role, item));
    signals.push(matched ? 85 : 60);
    reasons.push(matched ? "访谈兴趣点与岗位特征重合" : "兴趣点与岗位仅部分相关");
  }
  return {
    score: averageValues(signals),
    reason: reasons.join("；") || "尚未填写目标方向或完成访谈，意愿匹配待补充。"
  };
}

function computeRoleMatches(profile) {
  const hasSignal = Boolean(
    profile.assessment?.mbti?.completed
    || profile.assessment?.holland?.completed
    || profile.basics.major
    || profile.basics.target_direction
    || profile.interview.profile
  );
  if (!hasSignal) return [];
  return ROLE_LIBRARY.map((role) => {
    const trait = computeTraitMatch(role, profile);
    const ability = computeAbilityMatch(role, profile);
    const major = computeMajorMatch(role, profile.basics);
    const willingness = computeWillingnessMatch(role, profile);
    const weightedParts = [
      { weight: appState.weights["特质匹配"], result: trait },
      { weight: appState.weights["能力匹配"], result: ability },
      { weight: appState.weights["专业匹配"], result: major },
      { weight: appState.weights["意愿匹配"], result: willingness }
    ];
    const coverageWeight = weightedParts.reduce((sum, item) => sum + (item.result.score === null ? 0 : item.weight), 0);
    const weightedScore = weightedParts.reduce((sum, item) => sum + (item.result.score === null ? 0 : item.result.score * item.weight), 0);
    const overallScore = coverageWeight ? Math.round(weightedScore / coverageWeight) : null;
    const confidence = coverageWeight >= 85 ? "高" : coverageWeight >= 55 ? "中" : "低";
    const nextActions = uniqueValues([
      ...ability.gaps.map((item) => `补足 ${item}`),
      major.score !== null && major.score < 60 ? `为 ${role.name} 准备跨专业证明材料` : "",
      willingness.score === null ? "补充目标方向或完成访谈，提升意愿匹配精度" : "",
      `围绕 ${role.name} 的 ${role.requiredSkills.slice(0, 2).join("、")} 产出作品或经历`
    ], 4);
    return {
      ...role,
      trait,
      ability,
      major,
      willingness,
      coverageWeight,
      overallScore,
      confidence,
      summary: [trait.reason, ability.reason, major.reason, willingness.reason].filter(Boolean).slice(0, 2).join("；"),
      nextActions
    };
  }).sort((a, b) => {
    const scoreA = a.overallScore ?? a.trait.score ?? 0;
    const scoreB = b.overallScore ?? b.trait.score ?? 0;
    return scoreB - scoreA;
  });
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
      reason: staticMemoryReady ? "已记录测评结果与基础信息，可作为画像基底。" : "等待 MBTI / 霍兰德结果与基础信息补齐。",
      action_label: staticMemoryReady ? "已同步" : "补充基础信息"
    },
    {
      title: "动态记忆",
      status: dynamicMemoryReady ? "available" : "pending",
      reason: dynamicMemoryReady ? "访谈结果已进入动态画像，可追踪能力与行动证据。" : "接口已保留，等待访谈继续沉淀成长证据。",
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
      reason: "岗位查询已接入；资源推荐、进度追踪和模拟面试先保留规范接口。",
      action_label: "待接入"
    },
    {
      title: "反思模块",
      status: "placeholder",
      reason: "已保留状态字段与展示位，后续可接入月度复盘与推荐修正逻辑。",
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

function renderProfileWorkspace(profile, roles) {
  syncProfileBasicsForm();
  const topRoles = roles.slice(0, 3);
  const synthesis = buildUnifiedProfileSynthesis(profile, roles);
  const resumeTraits = buildResumePortraitTraits(userWorkspaceState.scopedData.resume_profile || null);
  const readinessEl = document.getElementById("profileReadinessValue");
  const archetypeVisualEl = document.getElementById("profileArchetypeVisual");
  const briefCardEl = document.getElementById("profilePortraitBriefCard");
  const portraitOutputBoardEl = document.getElementById("profilePortraitOutputBoard");
  const archetypeNameEl = document.getElementById("profileArchetypeName");
  const archetypeDigestEl = document.getElementById("profileArchetypeDigest");
  const archetypeSummaryEl = document.getElementById("profileArchetypeSummary");
  const summaryEl = document.getElementById("profileUnifiedSummary");
  const assessmentEl = document.getElementById("profileAssessmentDigest");
  const valuesEl = document.getElementById("profileWorkValueTags");
  const roleClusterEl = document.getElementById("profileRoleClusterTags");
  const axisEl = document.getElementById("profileFeatureAxisList");
  const workstyleEl = document.getElementById("profileWorkstyleCards");
  const evidenceEl = document.getElementById("profileEvidenceMatrix");
  const uncertaintyEl = document.getElementById("profileUncertaintyList");
  const topRoleEl = document.getElementById("profileTopRoleTags");
  const nextStepEl = document.getElementById("profileNextStepList");
  const missingEl = document.getElementById("profileMissingList");
  const capabilityEl = document.getElementById("profileCapabilityList");
  const correlationEl = document.getElementById("profileCapabilityCorrelation");
  const modulesEl = document.getElementById("agentModuleGrid");
  const portraitState = getProfilePortraitState();
  const portraitBrief = getResolvedProfilePortraitBrief(profile, roles, synthesis, portraitState);
  const portraitOutputCards = buildProfilePortraitOutputCards(profile, roles, synthesis, portraitState, resumeTraits);
  const assessmentItems = [];
  if (profile.assessment?.mbti?.completed) assessmentItems.push(`MBTI：${profile.assessment.mbti.display_type || profile.assessment.mbti.final_type}`);
  if (profile.assessment?.holland?.completed) assessmentItems.push(`霍兰德：${profile.assessment.holland.code}`);
  if (profile.basics.major) assessmentItems.push(`专业：${profile.basics.major}`);
  if (profile.basics.grade) assessmentItems.push(`学历：${profile.basics.grade}`);
  if (profile.resume?.status === "analyzed") assessmentItems.push("简历：已解析");
  else if (profile.resume?.status === "uploaded") assessmentItems.push("简历：待解析");
  const assessmentDigest = assessmentItems.length ? assessmentItems.join("｜") : "尚未形成足够的基础画像。";

  if (readinessEl) readinessEl.textContent = `${appState.profileCompletion}%`;
  renderProfilePortraitVisual(archetypeVisualEl, portraitState, synthesis, portraitBrief);
  renderProfilePortraitBriefCard(briefCardEl, portraitState, portraitBrief);
  // 输入输出链路移至折叠区
  renderProfilePortraitOutputBoard(portraitOutputBoardEl, portraitOutputCards);
  // 新增：数据来源状态条 / 六维能力速览 / 关键证据&信息缺口
  renderProfileSourcePills(document.getElementById("profileSourcePills"), profile);
  renderProfileCapabilityStrip(document.getElementById("profileCapabilityStrip"), profile);
  renderProfileEvidenceGaps(document.getElementById("profileEvidenceGapsContent"), profile);
  if (archetypeNameEl) archetypeNameEl.textContent = portraitBrief?.title || synthesis.archetype.name;
  if (archetypeDigestEl) archetypeDigestEl.textContent = assessmentDigest;
  if (archetypeSummaryEl) archetypeSummaryEl.textContent = portraitBrief?.positioning || synthesis.thesis;
  if (summaryEl) summaryEl.textContent = profile.summary;
  if (assessmentEl) assessmentEl.textContent = assessmentDigest;
  if (valuesEl) valuesEl.innerHTML = careerTagHtml(profile.workValues, "待补充工作价值观", "soft");
  if (roleClusterEl) roleClusterEl.innerHTML = careerTagHtml(
    uniqueValues([portraitBrief?.primary_role, ...(portraitBrief?.support_roles || []), ...(synthesis.roleCluster || [])], 5),
    "等待角色原型收敛",
    "accent"
  );
  if (axisEl) axisEl.innerHTML = renderUnifiedFeatureAxes(synthesis.axes);
  if (workstyleEl) workstyleEl.innerHTML = renderUnifiedWorkstyleCards(synthesis.workstyleCards);
  if (evidenceEl) evidenceEl.innerHTML = renderUnifiedEvidenceMatrix(synthesis.evidenceRows);
  if (uncertaintyEl) uncertaintyEl.innerHTML = renderUnifiedUncertaintyList(synthesis.uncertainty);
  if (topRoleEl) topRoleEl.innerHTML = careerTagHtml(uniqueValues([...profile.recommendedRoles, ...topRoles.map((item) => item.name)], 5), "待生成岗位方向", "accent");
  if (nextStepEl) nextStepEl.innerHTML = careerListHtml(uniqueValues([...profile.nextSteps, ...(roles[0]?.nextActions || [])], 6), "等待画像完善后生成行动建议");
  if (missingEl) missingEl.innerHTML = careerListHtml(profile.missingItems, "当前画像基础已满足本轮演示范围");
  if (capabilityEl) capabilityEl.innerHTML = renderCapabilityList(profile);
  if (correlationEl) correlationEl.innerHTML = renderCapabilityCorrelation(profile, roles);
  if (modulesEl) {
    modulesEl.innerHTML = buildAgentModuleStates(profile, roles).map((item) => {
      const statusClass = item.status === "available"
        ? "bg-emerald-100 text-emerald-700"
        : item.status === "placeholder"
          ? "bg-amber-100 text-amber-700"
          : "bg-slate-200 text-slate-600";
      return `
        <div class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div class="flex items-center justify-between gap-3 mb-3">
            <h4 class="text-base font-semibold text-slate-900">${escHtml(item.title)}</h4>
            <span class="rounded-full px-3 py-1 text-xs font-medium ${statusClass}">${escHtml(item.action_label)}</span>
          </div>
          <p class="text-sm text-slate-600 leading-6">${escHtml(item.reason)}</p>
        </div>
      `;
    }).join("");
  }
  updateProfileRadarChart({
    dimensions: [
      { name: "专业技能", score: profile.capabilities.professional.score || 0 },
      { name: "学习能力", score: profile.capabilities.learning.score || 0 },
      { name: "沟通能力", score: profile.capabilities.communication.score || 0 },
      { name: "创新能力", score: profile.capabilities.innovation.score || 0 },
      { name: "抗压能力", score: profile.capabilities.stress_tolerance.score || 0 },
      { name: "实践能力", score: profile.capabilities.internship.score || 0 },
      { name: "执行能力", score: profile.capabilities.execution.score || 0 }
    ]
  });
  updateProfilePortraitControls(profile, roles, synthesis);
  renderResumeProfileSection(getResumeProfileFromCache());
  renderProfileFlow(profile);
}

function renderMatchingWorkspace(profile, roles) {
  const topRole = roles[0] || null;
  const focused = roles.find((item) => item.id === appState.focusedRoleId) || topRole;
  const overviewEl = document.getElementById("matchingOverviewCards");
  const listEl = document.getElementById("matchingRoleList");
  const detailEl = document.getElementById("matchingRoleDetail");
  const moduleEl = document.getElementById("matchingPlaceholderModules");
  const totalEl = document.getElementById("weightTotal");
  if (totalEl) totalEl.textContent = `${Object.values(appState.weights).reduce((sum, value) => sum + Number(value || 0), 0)}%`;

  if (overviewEl) {
    const cards = [
      { label: "当前 Top1", value: topRole?.overallScore !== null && topRole?.overallScore !== undefined ? `${topRole.overallScore}%` : "初步推荐", hint: topRole ? `${topRole.name} · 置信度${topRole.confidence}` : "等待画像输入" },
      { label: "岗位覆盖", value: `${roles.length}`, hint: "基于 10 个岗位画像库自动初筛" },
      { label: "关键差距", value: `${focused?.ability?.gaps?.length || 0}`, hint: focused ? `聚焦 ${focused.name}` : "等待选择岗位" },
      { label: "状态提示", value: profile.missingItems.length ? "待补充" : "已就绪", hint: profile.missingItems.length ? profile.missingItems[0] : "可进入报告页查看行动计划" }
    ];
    overviewEl.innerHTML = cards.map((card) => `
      <div class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <p class="text-sm text-slate-500">${escHtml(card.label)}</p>
        <p class="mt-2 text-3xl font-bold text-slate-900">${escHtml(card.value)}</p>
        <p class="mt-2 text-xs text-slate-500 leading-5">${escHtml(card.hint)}</p>
      </div>
    `).join("");
  }

  if (listEl) {
    listEl.innerHTML = roles.map((role) => {
      const active = role.id === focused?.id;
      return `
        <div class="rounded-2xl border ${active ? "border-sky-400 bg-sky-50/70" : "border-slate-200 bg-white"} p-5 shadow-sm">
          <div class="flex items-start justify-between gap-4">
            <div>
              <p class="text-xs font-semibold tracking-[0.18em] text-slate-400 uppercase">${escHtml(role.category)}</p>
              <h4 class="mt-1 text-lg font-semibold text-slate-900">${escHtml(role.name)}</h4>
              <p class="mt-2 text-sm text-slate-600 leading-6">${escHtml(role.summary || "等待更多输入提升解释性。")}</p>
            </div>
            <div class="text-right">
              <p class="text-2xl font-bold text-sky-700">${role.overallScore === null ? "初筛" : `${role.overallScore}%`}</p>
              <p class="text-xs text-slate-500">置信度 ${escHtml(role.confidence)}</p>
            </div>
          </div>
          <div class="mt-4 grid gap-2 md:grid-cols-2">
            <div class="rounded-xl bg-slate-50 px-3 py-2 text-sm text-slate-600">特质匹配：${role.trait.score === null ? "待补充" : `${role.trait.score}%`}</div>
            <div class="rounded-xl bg-slate-50 px-3 py-2 text-sm text-slate-600">能力匹配：${role.ability.score === null ? "待补充" : `${role.ability.score}%`}</div>
            <div class="rounded-xl bg-slate-50 px-3 py-2 text-sm text-slate-600">专业匹配：${role.major.score === null ? "待补充" : `${role.major.score}%`}</div>
            <div class="rounded-xl bg-slate-50 px-3 py-2 text-sm text-slate-600">意愿匹配：${role.willingness.score === null ? "待补充" : `${role.willingness.score}%`}</div>
          </div>
          <div class="mt-4 flex flex-wrap gap-3">
            <button type="button" onclick="focusMatchingRole('${role.id}')" class="rounded-lg border border-sky-500 px-4 py-2 text-sm font-medium text-sky-700 hover:bg-sky-50 transition-all">查看解释</button>
            <button type="button" onclick="openMatchingRoleReport('${role.id}')" class="rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-700 transition-all">写入报告</button>
          </div>
        </div>
      `;
    }).join("");
  }

  if (detailEl) {
    detailEl.innerHTML = focused ? `
      <div class="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div class="flex items-start justify-between gap-4">
          <div>
            <p class="text-xs font-semibold tracking-[0.18em] text-slate-400 uppercase">Focused Role</p>
            <h3 class="mt-1 text-xl font-semibold text-slate-900">${escHtml(focused.name)}</h3>
            <p class="mt-2 text-sm text-slate-600 leading-6">${escHtml(focused.path)}</p>
          </div>
          <div class="text-right">
            <p class="text-3xl font-bold text-slate-900">${focused.overallScore === null ? "初筛" : `${focused.overallScore}%`}</p>
            <p class="text-xs text-slate-500">覆盖权重 ${focused.coverageWeight}%</p>
          </div>
        </div>
        <div class="mt-5 grid gap-5 lg:grid-cols-3">
          <div>
            <p class="text-sm font-semibold text-slate-800">匹配理由</p>
            <div class="mt-3">${careerListHtml([focused.trait.reason, focused.major.reason, focused.willingness.reason], "等待更多解释")}</div>
          </div>
          <div>
            <p class="text-sm font-semibold text-slate-800">能力差距</p>
            <div class="mt-3">${careerListHtml(focused.ability.gaps, "当前没有明显硬缺口，建议继续用经历加固。")}</div>
          </div>
          <div>
            <p class="text-sm font-semibold text-slate-800">建议动作</p>
            <div class="mt-3">${careerListHtml(focused.nextActions, "等待生成行动建议")}</div>
          </div>
        </div>
      </div>
    ` : `
      <div class="rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-6 text-sm text-slate-500">
        当前还没有可解释的岗位结果，请先完成测评并补充基础信息。
      </div>
    `;
  }

  if (moduleEl) {
    const placeholders = [
      { title: "资源推荐工具", reason: "课程/证书/模板推送接口已预留，后续接入真实资源库。", action: "待接入" },
      { title: "趋势分析工具", reason: "行业趋势卡位已保留，后续接入实时岗位市场与更新频率。", action: "待接入" },
      { title: "提醒追踪工具", reason: "行动提醒与任务进度字段已规范化，后续接入调度器。", action: "即将上线" }
    ];
    moduleEl.innerHTML = placeholders.map((item) => `
      <div class="rounded-2xl border border-slate-200 bg-slate-50 p-5">
        <div class="flex items-center justify-between gap-3">
          <h4 class="text-base font-semibold text-slate-900">${escHtml(item.title)}</h4>
          <span class="rounded-full bg-amber-100 px-3 py-1 text-xs font-medium text-amber-700">${escHtml(item.action)}</span>
        </div>
        <p class="mt-3 text-sm text-slate-600 leading-6">${escHtml(item.reason)}</p>
      </div>
    `).join("");
  }
}

function renderMatchingWorkspace(profile, roles) {
  const metricsEl = document.getElementById("careerGraphMetrics");
  const signalsEl = document.getElementById("matchingProfileSignals");
  const summaryEl = document.getElementById("careerGraphProfileSummary");
  const statusEl = document.getElementById("careerGraphStatusBadge");
  const sublineEl = document.getElementById("careerGraphSubline");
  const hintEl = document.getElementById("matchingSectionHint");

  const capabilityCount = Object.values(profile.capabilities || {}).filter((item) => item?.score !== null && item?.score !== undefined).length;
  const topRole = roles[0] || null;
  const cards = [
    {
      label: "画像完整度",
      value: `${Math.max(0, Math.min(100, Number(appState.profileCompletion || 0)))}%`,
      hint: profile.missingItems?.length ? `待补充：${profile.missingItems[0]}` : "已可用于职业图谱匹配"
    },
    {
      label: "方向信号",
      value: `${Math.max(1, (profile.recommendedRoles || []).length)}`,
      hint: (profile.recommendedRoles || []).slice(0, 2).join("、") || "等待从测评、访谈或简历中收敛"
    },
    {
      label: "能力维度",
      value: `${capabilityCount}/7`,
      hint: capabilityCount ? "已接入统一画像能力轴" : "能力轴仍在等待更多输入"
    },
    {
      label: "旧版参考",
      value: topRole?.overallScore != null ? `${topRole.overallScore}%` : "待生成",
      hint: topRole ? `旧版 Top1：${topRole.name}` : "当前页面已切换为图谱驱动模式"
    }
  ];

  if (metricsEl) {
    metricsEl.innerHTML = cards.map((card) => `
      <article class="career-graph-metric-card">
        <span class="career-graph-metric-label">${escHtml(card.label)}</span>
        <strong class="career-graph-metric-value">${escHtml(card.value)}</strong>
        <p class="career-graph-metric-note">${escHtml(card.hint)}</p>
      </article>
    `).join("");
  }

  if (signalsEl) {
    const tags = [
      profile.basics?.target_direction ? `目标方向：${profile.basics.target_direction}` : "",
      profile.basics?.target_city ? `目标城市：${profile.basics.target_city}` : "",
      profile.basics?.major ? `专业：${profile.basics.major}` : "",
      profile.assessment?.mbti?.completed ? `MBTI：${profile.assessment.mbti.display_type || profile.assessment.mbti.final_type}` : "",
      profile.assessment?.holland?.completed ? `霍兰德：${profile.assessment.holland.code}` : "",
      ...(profile.recommendedRoles || []).slice(0, 3)
    ].filter(Boolean);
    signalsEl.innerHTML = tags.length
      ? tags.map((tag) => `<span class="career-graph-signal-chip">${escHtml(tag)}</span>`).join("")
      : `<span class="career-graph-empty-inline">先补充测评、简历或目标方向，匹配结果会更稳。</span>`;
  }

  if (summaryEl) {
    summaryEl.textContent = profile.summary || "图谱会把岗位节点关系、当前画像和推荐方向联动展示在同一页。";
  }
  if (statusEl) {
    statusEl.textContent = "图谱准备中";
    statusEl.dataset.state = profile.missingItems?.length ? "warning" : "ready";
  }
  if (sublineEl) {
    sublineEl.textContent = "岗位全部以节点呈现，支持缩放、拖拽、点击查看详情，并在图谱下方生成 5 条职业方向推荐。";
  }
  if (hintEl) {
    hintEl.textContent = profile.missingItems?.length
      ? `当前仍缺少 ${profile.missingItems.length} 项输入，系统会继续给出结果，但推荐可信度会下降。`
      : "当前画像已满足基础匹配条件，可以直接开始职业匹配。";
  }

  void ensureCareerGraphMatchingAssets()
    .then((api) => api?.render?.({ profile, legacyRoles: roles, currentSection: appState.currentSection }))
    .catch((error) => {
      if (statusEl) {
        statusEl.textContent = "图谱加载失败";
        statusEl.dataset.state = "error";
      }
      const resultsEl = document.getElementById("careerGraphResults");
      if (resultsEl) {
        resultsEl.innerHTML = `<div class="career-graph-results-empty">职业图谱模块加载失败：${escHtml(error.message)}</div>`;
      }
    });
}

function renderMatchingWorkspace(profile, roles) {
  const metricsEl = document.getElementById("careerGraphMetrics");
  const signalsEl = document.getElementById("matchingProfileSignals");
  const summaryEl = document.getElementById("careerGraphProfileSummary");
  const statusEl = document.getElementById("careerGraphStatusBadge");
  const sublineEl = document.getElementById("careerGraphSubline");
  const hintEl = document.getElementById("matchingSectionHint");

  const capabilityCount = Object.values(profile.capabilities || {}).filter((item) => item?.score !== null && item?.score !== undefined).length;
  const topRole = roles[0] || null;
  const cards = [
    {
      label: "画像完整度",
      value: `${Math.max(0, Math.min(100, Number(appState.profileCompletion || 0)))}%`,
      hint: profile.missingItems?.length ? `待补充：${profile.missingItems[0]}` : "已经满足图谱检索的基础条件"
    },
    {
      label: "方向信号",
      value: `${Math.max(1, (profile.recommendedRoles || []).length)}`,
      hint: (profile.recommendedRoles || []).slice(0, 2).join("、") || "等待从测评、访谈或简历中收敛"
    },
    {
      label: "能力维度",
      value: `${capabilityCount}/7`,
      hint: capabilityCount ? "已接入统一画像能力轴" : "能力信号仍在等待更多输入"
    },
    {
      label: "旧版参照",
      value: topRole?.overallScore != null ? `${topRole.overallScore}%` : "待生成",
      hint: topRole ? `旧版 Top1：${topRole.name}` : "当前页面已切换为图谱驱动模式"
    }
  ];

  if (metricsEl) {
    metricsEl.innerHTML = cards.map((card) => `
      <article class="career-graph-metric-card">
        <span class="career-graph-metric-label">${escHtml(card.label)}</span>
        <strong class="career-graph-metric-value">${escHtml(card.value)}</strong>
        <p class="career-graph-metric-note">${escHtml(card.hint)}</p>
      </article>
    `).join("");
  }

  if (signalsEl) {
    const tags = [
      profile.basics?.target_direction ? `目标方向：${profile.basics.target_direction}` : "",
      profile.basics?.target_city ? `目标城市：${profile.basics.target_city}` : "",
      profile.basics?.major ? `专业：${profile.basics.major}` : "",
      profile.assessment?.mbti?.completed ? `MBTI：${profile.assessment.mbti.display_type || profile.assessment.mbti.final_type}` : "",
      profile.assessment?.holland?.completed ? `霍兰德：${profile.assessment.holland.code}` : "",
      ...(profile.recommendedRoles || []).slice(0, 3)
    ].filter(Boolean);
    signalsEl.innerHTML = tags.length
      ? tags.map((tag) => `<span class="career-graph-signal-chip">${escHtml(tag)}</span>`).join("")
      : `<span class="career-graph-empty-inline">先补充测评、简历或目标方向，匹配结果会更稳定。</span>`;
  }

  if (summaryEl) {
    summaryEl.textContent = profile.summary || "系统会把岗位节点关系、当前画像和推荐方向联动展示在同一页。";
  }
  if (statusEl) {
    statusEl.textContent = "图谱准备中";
    statusEl.dataset.state = profile.missingItems?.length ? "warning" : "ready";
  }
  if (sublineEl) {
    sublineEl.textContent = "所有岗位都会作为节点出现在图谱里，支持缩放、拖拽、点击查看详情，并在下方生成 5 条职业方向推荐。";
  }
  if (hintEl) {
    hintEl.textContent = profile.missingItems?.length
      ? `当前仍缺少 ${profile.missingItems.length} 项输入，系统仍会给出结果，但推荐可信度会下降。`
      : "当前画像已经满足基础匹配条件，可以直接开始职业匹配。";
  }

  void ensureCareerGraphMatchingAssets()
    .then((api) => api?.render?.({ profile, legacyRoles: roles, currentSection: appState.currentSection }))
    .catch((error) => {
      if (statusEl) {
        statusEl.textContent = "图谱加载失败";
        statusEl.dataset.state = "error";
      }
      const resultsEl = document.getElementById("careerGraphResults");
      if (resultsEl) {
        resultsEl.innerHTML = `<div class="career-graph-results-empty">职业图谱模块加载失败：${escHtml(error.message)}</div>`;
      }
    });
}

function renderMatchingWorkspace(profile, roles) {
  void ensureCareerGraphMatchingAssets()
    .then((api) => api?.render?.({ profile, legacyRoles: roles, currentSection: appState.currentSection }))
    .catch((error) => {
      const statusEl = document.getElementById("knowledgeBaseStatus");
      const panelBody = document.getElementById("knowledgeBasePanelBody");
      if (statusEl) statusEl.textContent = "图谱加载失败";
      if (panelBody) {
        panelBody.innerHTML = `<p class="kb-empty-copy">职业图谱模块加载失败：${escHtml(error.message)}</p>`;
      }
    });
}

const REPORT_AGENT_FLOW = [
  { key: "profile_fusion", title: "画像输入", role: "Profile Intake", detail: "测评、简历、访谈与目标岗位快照", icon: "profile", x: 72, y: 282 },
  { key: "industry_analysis", title: "行业分析师", role: "Industry Analyst", detail: "外部趋势与需求侧判断", icon: "trend", x: 360, y: 112, aliases: ["trend_intelligence"] },
  { key: "resume_evidence", title: "简历证据分析官", role: "Resume Evidence Analyst", detail: "初筛经历证据与能力线索", icon: "file", x: 360, y: 452, aliases: ["resume_evidence_1"] },
  { key: "career_positioning", title: "职业定位顾问", role: "Career Positioning Advisor", detail: "生成方向假设与硬约束", icon: "target", x: 650, y: 282, aliases: ["role_retrieval"] },
  { key: "competency_assess", title: "能力评估官", role: "Competency Assessor", detail: "构建就业能力画像", icon: "radar", x: 950, y: 112, aliases: ["gap_analysis"] },
  { key: "resume_evidence_2", title: "证据复核", role: "Resume Evidence Analyst", detail: "按 must_prove 二次校验", icon: "verify", x: 950, y: 452 },
  { key: "role_match", title: "岗位匹配官", role: "Role Match Officer", detail: "对齐岗位矩阵与差距项", icon: "match", x: 1240, y: 282 },
  { key: "path_planning", title: "路径规划师", role: "Career Path Planner", detail: "差距驱动行动计划与复查节点", icon: "route", x: 1530, y: 282, aliases: ["stage_planning"] },
  { key: "report_writer", title: "报告合成", role: "Student Report", detail: "合成可阅读职业报告", icon: "report", x: 1810, y: 282, aliases: ["critic"] }
];

const REPORT_AGENT_NODE_WIDTH = 196;
const REPORT_AGENT_NODE_MID_Y = 70;

const REPORT_AGENT_EDGES = [
  ["profile_fusion", "industry_analysis"],
  ["profile_fusion", "resume_evidence"],
  ["industry_analysis", "career_positioning"],
  ["resume_evidence", "career_positioning"],
  ["career_positioning", "competency_assess"],
  ["career_positioning", "resume_evidence_2"],
  ["resume_evidence_2", "competency_assess"],
  ["competency_assess", "role_match"],
  ["role_match", "path_planning"],
  ["path_planning", "report_writer"]
];

function getReportRuntimeState() {
  if (typeof window.getCareerReportStateSafe === "function") return window.getCareerReportStateSafe() || null;
  return appState.careerReportState || null;
}

function getReportProgressMap(state) {
  const map = new Map();
  const progress = Array.isArray(state?.progress) ? state.progress : [];
  progress.forEach((item) => {
    const key = String(item?.key || item?.stage || "").trim();
    if (key) map.set(key, String(item.status || "").trim().toLowerCase());
  });
  return map;
}

function reportAgentIconSvg(icon) {
  const paths = {
    profile: `<path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z"/><path d="M4.5 21a7.5 7.5 0 0 1 15 0"/>`,
    trend: `<path d="M4 19V5"/><path d="M4 19h16"/><path d="m7 15 4-4 3 3 5-7"/>`,
    file: `<path d="M7 3h7l4 4v14H7z"/><path d="M14 3v5h5"/><path d="M9.5 12h5"/><path d="M9.5 16h7"/>`,
    target: `<circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="3"/><path d="M12 2v3"/><path d="M22 12h-3"/><path d="M12 22v-3"/><path d="M2 12h3"/>`,
    radar: `<path d="M12 3 4 20h16L12 3Z"/><path d="m12 8 3.6 8H8.4L12 8Z"/><path d="M12 3v17"/>`,
    verify: `<path d="M12 3 5 6v5c0 4.4 2.8 8.4 7 10 4.2-1.6 7-5.6 7-10V6l-7-3Z"/><path d="m8.5 12.5 2.2 2.2 4.8-5"/>`,
    match: `<path d="M8 7a4 4 0 0 1 8 0c0 4-4 7-4 7s-4-3-4-7Z"/><path d="M12 7h.01"/><path d="M5 21h14"/><path d="m7 17 10-4"/>`,
    route: `<path d="M5 6h4a3 3 0 0 1 0 6H8a3 3 0 0 0 0 6h11"/><circle cx="5" cy="6" r="2"/><circle cx="19" cy="18" r="2"/>`,
    report: `<path d="M6 3h9l3 3v15H6z"/><path d="M15 3v4h4"/><path d="M9 12h6"/><path d="M9 16h6"/><path d="M9 8h3"/>`
  };
  return `<svg viewBox="0 0 24 24" aria-hidden="true">${paths[icon] || paths.report}</svg>`;
}

function reportAgentStatusLabel(status) {
  if (status === "done") return "已完成";
  if (status === "active") return "传递中";
  if (status === "failed") return "失败";
  return "待触发";
}

function getReportUserAvatarHtml() {
  const avatarState = typeof window.getAccountAvatarState === "function" ? window.getAccountAvatarState() : null;
  const imageUrl = String(avatarState?.image_url || "").trim();
  const user = typeof getCurrentUser === "function" ? getCurrentUser() : userWorkspaceState.currentUser;
  const displayName = user?.display_name || user?.displayName || user?.username || "用户";
  if (imageUrl) {
    return `<span class="report-agent-user-avatar"><img src="${escHtml(imageUrl)}" alt="${escHtml(displayName)}"></span>`;
  }
  return `<span class="report-agent-user-avatar fallback">${escHtml(displayName.charAt(0).toUpperCase() || "用")}</span>`;
}

function reportAgentEdgePath(from, to) {
  const x1 = Number(from.x || 0) + REPORT_AGENT_NODE_WIDTH;
  const y1 = Number(from.y || 0) + REPORT_AGENT_NODE_MID_Y;
  const x2 = Number(to.x || 0);
  const y2 = Number(to.y || 0) + REPORT_AGENT_NODE_MID_Y;
  const mid = Math.max(48, Math.abs(x2 - x1) * 0.46);
  return `M ${x1} ${y1} C ${x1 + mid} ${y1}, ${x2 - mid} ${y2}, ${x2} ${y2}`;
}

function renderReportAgentMap(profile, roles) {
  const state = getReportRuntimeState();
  const progressMap = getReportProgressMap(state);
  const status = String(state?.status || "").trim().toLowerCase();
  const activeStage = String(state?.stage || state?.stage_key || "").trim();
  const running = ["queued", "running"].includes(status);
  const completed = !running && (appState.reportGenerated || ["ready", "done", "success", "completed"].includes(status));
  const activeIndex = REPORT_AGENT_FLOW.findIndex((item) => [item.key, ...(item.aliases || [])].includes(activeStage));
  const inputReady = Boolean(
    profile?.assessment?.mbti?.completed
    || profile?.assessment?.holland?.completed
    || profile?.resume?.status === "analyzed"
    || roles?.length
  );

  const nodes = REPORT_AGENT_FLOW.map((item, index) => {
    const keys = [item.key, ...(item.aliases || [])];
    const progressStatus = keys.map((key) => progressMap.get(key)).find(Boolean) || "";
    let nodeStatus = "pending";
    if (completed || progressStatus === "done" || (running && activeIndex >= 0 && index < activeIndex)) {
      nodeStatus = "done";
    } else if (progressStatus === "active" || progressStatus === "running" || index === activeIndex || (running && activeIndex < 0 && index === 0)) {
      nodeStatus = "active";
    } else if (progressStatus === "failed" || status === "failed") {
      nodeStatus = "failed";
    } else if (index === 0 && inputReady) {
      nodeStatus = "done";
    }
    return { ...item, nodeStatus };
  });
  const nodeMap = new Map(nodes.map((item) => [item.key, item]));
  const edges = REPORT_AGENT_EDGES.map(([fromKey, toKey]) => {
    const from = nodeMap.get(fromKey);
    const to = nodeMap.get(toKey);
    if (!from || !to) return "";
    const edgeStatus = to.nodeStatus === "active"
      ? "active"
      : from.nodeStatus === "done" && to.nodeStatus === "done"
        ? "done"
        : "pending";
    return `<path class="report-agent-edge is-${edgeStatus}" d="${reportAgentEdgePath(from, to)}"></path>`;
  }).join("");

  const nodeHtml = nodes.map((item, index) => `
    <article class="report-agent-node is-${escHtml(item.nodeStatus)}" style="left:${Number(item.x || 0)}px; top:${Number(item.y || 0)}px;">
      <span class="report-agent-index">${String(index + 1).padStart(2, "0")}</span>
      <span class="report-agent-icon">${item.key === "profile_fusion" ? getReportUserAvatarHtml() : reportAgentIconSvg(item.icon)}</span>
      <div class="report-agent-copy">
        <h4>${escHtml(item.title)}</h4>
        <p>${escHtml(item.role)}</p>
        <small>${escHtml(item.detail)}</small>
      </div>
      <b>${escHtml(reportAgentStatusLabel(item.nodeStatus))}</b>
    </article>
  `).join("");

  return `
    <div class="report-agent-map-inner">
      <div class="report-agent-phase phase-input">输入</div>
      <div class="report-agent-phase phase-parallel">并行分析</div>
      <div class="report-agent-phase phase-serial">依赖汇合</div>
      <div class="report-agent-phase phase-output">输出</div>
      <svg class="report-agent-edges" viewBox="0 0 2040 720" preserveAspectRatio="none" aria-hidden="true">${edges}</svg>
      ${nodeHtml}
      <div class="report-agent-note">A 组并行：行业趋势与简历证据初筛同时处理；后续阶段按数据依赖汇合，不暴露 agent 内部正文。</div>
    </div>
  `;
}

function renderReportWorkspace(profile, roles) {
  const safeRoles = Array.isArray(roles) ? roles : [];
  const state = getReportRuntimeState();
  const status = String(state?.status || "").trim().toLowerCase();
  const running = ["queued", "running"].includes(status);
  const failed = status === "failed";
  const selected = safeRoles.find((item) => item.id === appState.focusedRoleId) || safeRoles[0] || null;
  const statusTitle = document.getElementById("reportStatusTitle");
  const statusHint = document.getElementById("reportStatusHint");
  const generatedTime = document.getElementById("reportGeneratedTime");
  const launchBtn = document.getElementById("reportLaunchBtn");
  const cancelBtn = document.getElementById("reportCancelBtn");
  const mapEl = document.getElementById("reportAgentMap");
  const missingCount = Array.isArray(profile?.missingItems) ? profile.missingItems.length : 0;
  const focusText = selected?.name ? `当前主线岗位：${selected.name}` : "当前还没有锁定主线岗位";
  const gapCount = Array.isArray(selected?.ability?.gaps) ? selected.ability.gaps.length : 0;

  if (statusTitle) {
    statusTitle.textContent = failed
      ? "多智能体流程启动失败"
      : running
        ? "多智能体正在协作"
        : status === "canceled"
          ? "本次生成已停止"
        : appState.reportGenerated
          ? "流程已完成，报告已同步"
          : "等待启动多智能体流程";
  }
  if (statusHint) {
    statusHint.textContent = failed
      ? (state?.error_message || "请检查画像输入和模型配置后重试。")
      : running
        ? (state?.stage_detail || "当前只展示 agent 之间的传递状态，报告正文不会在本页展开。")
        : status === "canceled"
          ? "旧任务已停止，不会写入报告；可以重新启动一次新的多智能体生成。"
        : missingCount
          ? `${focusText}；仍有 ${missingCount} 项画像信息可补充。`
          : `${focusText}；路径规划师会把 ${gapCount} 个差距项转成阶段行动计划，完成后到个人中心阅读完整报告。`;
  }
  if (generatedTime) {
    generatedTime.textContent = state?.updated_at || state?.finished_at || state?.created_at || new Date().toLocaleString("zh-CN", { hour12: false });
  }
  if (launchBtn) {
    launchBtn.disabled = running;
    launchBtn.textContent = running
      ? "生成中"
      : (appState.reportGenerated || failed || status === "canceled")
        ? "重新生成"
        : "启动生成";
  }
  if (cancelBtn) {
    cancelBtn.classList.toggle("hidden", !running);
    cancelBtn.disabled = !running;
  }
  if (mapEl) mapEl.innerHTML = renderReportAgentMap(profile, safeRoles);
}

const CAREER_REPORT_POLL_MS = 1800;
let careerReportPollTimer = null;
let careerReportPollJobId = "";

function getCareerReportStateSafe() {
  return appState.careerReportState || userWorkspaceState.scopedData.career_report || null;
}

function setScopedCareerReportState(state) {
  userWorkspaceState.scopedData.career_report = state || null;
  userWorkspaceState.scopedDataLoaded.career_report = Boolean(state);
}

function isCareerReportReadyStatus(status) {
  return ["ready", "done", "success", "completed"].includes(String(status || "").trim().toLowerCase());
}

function isCareerReportRunningStatus(status) {
  return ["queued", "running"].includes(String(status || "").trim().toLowerCase());
}

function applyCareerReportRuntimeState(state) {
  if (state && typeof state === "object") {
    appState.careerReportState = state;
    setScopedCareerReportState(state);
    if (isCareerReportReadyStatus(state.status)) {
      appState.reportGenerated = true;
    } else if (!appState.careerReport) {
      appState.reportGenerated = false;
    }
  }
  renderReportWorkspace(appState.derivedProfile || deriveUnifiedProfile(), appState.matchingRoles || []);
  updateDashboardMetrics();
}

function mergeCareerReportStatusPayload(payload) {
  const state = payload?.state && typeof payload.state === "object" ? payload.state : {};
  const job = payload?.job && typeof payload.job === "object" ? payload.job : {};
  const jobStatus = String(job.status || "").trim().toLowerCase();
  const normalizedJobStatus = jobStatus === "completed" ? "ready" : jobStatus;
  const merged = {
    ...state,
    status: normalizedJobStatus && normalizedJobStatus !== "idle" ? normalizedJobStatus : (state.status || ""),
    job_id: job.job_id || state.job_id || "",
    report_id: job.report_id || state.report_id || "",
    stage: job.stage || state.stage || "",
    stage_label: job.stage_label || state.stage_label || "",
    stage_detail: job.stage_detail || job.message || state.stage_detail || "",
    progress: Array.isArray(job.progress) && job.progress.length ? job.progress : (Array.isArray(state.progress) ? state.progress : []),
    generated_at: state.generated_at || "",
    updated_at: new Date().toLocaleString("zh-CN", { hour12: false }),
    model: job.model || state.model || "",
    generation_mode: job.generation_mode || state.generation_mode || "",
    focus_role_id: state.focus_role_id || appState.focusedRoleId || "",
    title: state.title || "",
    summary: state.summary || "",
    error_message: state.error_message || (normalizedJobStatus === "failed" ? job.message || "" : "")
  };
  applyCareerReportRuntimeState(merged);
  return merged;
}

function buildCareerReportGenerationPayload() {
  const profile = appState.derivedProfile && typeof appState.derivedProfile === "object"
    ? appState.derivedProfile
    : deriveUnifiedProfile();
  const roles = Array.isArray(appState.matchingRoles) && appState.matchingRoles.length
    ? appState.matchingRoles
    : computeRoleMatches(profile);
  if (!profile || typeof profile !== "object") return null;
  if (!Array.isArray(roles) || !roles.length) return null;
  appState.derivedProfile = profile;
  appState.matchingRoles = roles;
  if (!roles.some((item) => item.id === appState.focusedRoleId)) {
    appState.focusedRoleId = roles[0]?.id || "";
  }
  return {
    profile_snapshot: profile,
    role_rankings: roles,
    focus_role_id: String(appState.focusedRoleId || roles[0]?.id || "").trim()
  };
}

function stopCareerReportPolling() {
  if (careerReportPollTimer) {
    clearTimeout(careerReportPollTimer);
    careerReportPollTimer = null;
  }
  careerReportPollJobId = "";
}

async function loadCurrentCareerReportForMain() {
  const payload = await requestJson("/api/career-report/current");
  if (payload.state) {
    applyCareerReportRuntimeState(payload.state);
  }
  if (payload.data && payload.data.meta) {
    appState.careerReport = payload.data;
    appState.reportGenerated = Boolean(payload.data.report_document);
    appState.careerReportTracker = payload.state?.tracker || appState.careerReportTracker || null;
    renderReportWorkspace(appState.derivedProfile || deriveUnifiedProfile(), appState.matchingRoles || []);
    updateDashboardMetrics();
  }
  return payload;
}

async function syncCareerReportRuntimeStatus(jobId = "") {
  const suffix = jobId ? `?job_id=${encodeURIComponent(jobId)}` : "";
  const payload = await requestJson(`/api/career-report/generate/status${suffix}`);
  return mergeCareerReportStatusPayload(payload);
}

async function pollCareerReportJob(jobId) {
  const safeJobId = String(jobId || careerReportPollJobId || "").trim();
  if (!safeJobId) return null;
  stopCareerReportPolling();
  careerReportPollJobId = safeJobId;
  try {
    const state = await syncCareerReportRuntimeStatus(safeJobId);
    const status = String(state.status || "").trim().toLowerCase();
    if (isCareerReportRunningStatus(status)) {
      careerReportPollTimer = window.setTimeout(() => {
        void pollCareerReportJob(safeJobId);
      }, CAREER_REPORT_POLL_MS);
      return state;
    }
    if (isCareerReportReadyStatus(status)) {
      stopCareerReportPolling();
      await loadCurrentCareerReportForMain();
      showToast("职业报告已生成", "后端多智能体流程已完成，报告已同步到个人中心。", "success", 2200);
      return state;
    }
    if (status === "failed") {
      stopCareerReportPolling();
      showToast("职业报告生成失败", state.error_message || state.stage_detail || "请检查模型配置后重试。", "error", 2600);
    } else if (status === "canceled") {
      stopCareerReportPolling();
      showToast("已停止生成", "旧任务不会写入报告，可以重新生成。", "info", 2200);
    }
    return state;
  } catch (error) {
    stopCareerReportPolling();
    showToast("同步报告进度失败", error.message || "请稍后重试。", "error", 2400);
    throw error;
  }
}

async function cancelCareerReportGeneration() {
  const state = getCareerReportStateSafe();
  const jobId = String(state?.job_id || careerReportPollJobId || "").trim();
  if (!jobId) {
    stopCareerReportPolling();
    applyCareerReportRuntimeState({
      ...(state || {}),
      status: "canceled",
      stage_detail: "已停止本地等待；当前没有找到可取消的后端任务。",
      updated_at: new Date().toLocaleString("zh-CN", { hour12: false })
    });
    showToast("已停止等待", "当前没有找到可取消的后端任务。", "warning", 2000);
    return;
  }

  const cancelBtn = document.getElementById("reportCancelBtn");
  if (cancelBtn) {
    cancelBtn.disabled = true;
    cancelBtn.textContent = "停止中";
  }
  try {
    const payload = await requestJson("/api/career-report/generate/cancel", {
      method: "POST",
      body: { job_id: jobId }
    });
    stopCareerReportPolling();
    const canceledState = mergeCareerReportStatusPayload({
      job: payload.job || { job_id: jobId, status: "canceled" },
      state: {
        ...(getCareerReportStateSafe() || {}),
        status: "canceled",
        job_id: jobId,
        stage_detail: payload.message || "用户已停止本次生成，旧任务不会写入报告。"
      }
    });
    applyCareerReportRuntimeState(canceledState);
    showToast("已停止生成", "现在可以重新启动一次新的多智能体流程。", "success", 2200);
  } catch (error) {
    showToast("停止失败", error.message || "请稍后重试。", "error", 2400);
  } finally {
    if (cancelBtn) {
      cancelBtn.textContent = "停止生成";
    }
    renderReportWorkspace(appState.derivedProfile || deriveUnifiedProfile(), appState.matchingRoles || []);
  }
}

async function resumeCareerReportRuntime() {
  if (!isAuthenticatedUser()) return;
  try {
    const state = await syncCareerReportRuntimeStatus();
    const jobId = String(state.job_id || "").trim();
    if (isCareerReportRunningStatus(state.status) && jobId) {
      void pollCareerReportJob(jobId);
    } else if (isCareerReportReadyStatus(state.status)) {
      void loadCurrentCareerReportForMain().catch(() => {});
    }
  } catch (error) {
    console.warn("career report status sync failed", error);
  }
}

async function startCareerReportGeneration() {
  if (!isAuthenticatedUser()) {
    showToast("请先登录", "登录后才能启动后端多智能体报告生成。", "warning", 1800);
    return;
  }
  const payload = buildCareerReportGenerationPayload();
  if (!payload) {
    showSection("profile");
    showToast("画像或岗位数据不足", "请先完成画像并生成岗位匹配结果，再启动职业报告。", "warning", 2400);
    return;
  }

  const launchBtn = document.getElementById("reportLaunchBtn");
  if (launchBtn) {
    launchBtn.disabled = true;
    launchBtn.textContent = "启动中";
  }
  try {
    const response = await requestJson("/api/career-report/generate/start", {
      method: "POST",
      body: payload
    });
    const queuedState = {
      ...(getCareerReportStateSafe() || {}),
      status: "queued",
      job_id: response.job_id || "",
      report_id: response.report_id || "",
      stage: "industry_analysis",
      stage_label: "行业分析",
      stage_detail: "任务已提交到后端，等待多智能体编排",
      progress: [],
      updated_at: new Date().toLocaleString("zh-CN", { hour12: false }),
      focus_role_id: payload.focus_role_id
    };
    applyCareerReportRuntimeState(queuedState);
    showToast("职业报告任务已启动", "现在会轮询后端 agent 流程，不再使用前端假完成。", "success", 2200);
    await pollCareerReportJob(response.job_id);
  } catch (error) {
    if (error.status === 409) {
      showToast("已有报告任务在运行", "正在同步后端生成进度。", "warning", 1800);
      const state = await syncCareerReportRuntimeStatus();
      if (state.job_id) {
        await pollCareerReportJob(state.job_id);
      }
      return;
    }
    showToast("职业报告启动失败", error.message || "请稍后重试。", "error", 2600);
  } finally {
    renderReportWorkspace(appState.derivedProfile || deriveUnifiedProfile(), appState.matchingRoles || []);
  }
}

let unifiedRefreshScheduled = false;
let unifiedRefreshRunning = false;
let unifiedRefreshPending = false;

function refreshUnifiedExperience() {
  if (unifiedRefreshRunning) {
    unifiedRefreshPending = true;
    return;
  }
  if (unifiedRefreshScheduled) return;
  unifiedRefreshScheduled = true;
  const runner = () => {
    unifiedRefreshScheduled = false;
    unifiedRefreshRunning = true;
    try {
      refreshUnifiedExperienceNow();
    } finally {
      unifiedRefreshRunning = false;
      if (unifiedRefreshPending) {
        unifiedRefreshPending = false;
        refreshUnifiedExperience();
      }
    }
  };
  if (typeof window !== "undefined" && typeof window.requestAnimationFrame === "function") {
    window.requestAnimationFrame(runner);
  } else {
    setTimeout(runner, 0);
  }
}

function refreshUnifiedExperienceNow() {
  const profile = deriveUnifiedProfile();
  const roles = computeRoleMatches(profile);
  profile.recommendedRoles = uniqueValues([...profile.recommendedRoles, ...roles.slice(0, 3).map((item) => item.name)], 6);
  profile.nextSteps = uniqueValues([...profile.nextSteps, ...(roles[0]?.nextActions || [])], 6);
  profile.moduleStates = buildAgentModuleStates(profile, roles);

  appState.derivedProfile = profile;
  appState.matchingRoles = roles;
  if (!roles.some((item) => item.id === appState.focusedRoleId)) {
    appState.focusedRoleId = roles[0]?.id || "";
  }
  appState.profileCompletion = Math.round(
    (profile.assessment?.mbti?.completed ? 15 : 0)
    + (profile.assessment?.holland?.completed ? 15 : 0)
    + (PROFILE_BASIC_FIELDS.filter((key) => profile.basics[key]).length / PROFILE_BASIC_FIELDS.length) * 30
    + clampPercent(profile.interview.completionScore) * 0.3
    + (profile.resume?.status === "analyzed" ? 10 : 0)
  );
  appState.profileComplete = Boolean(
    profile.assessment?.mbti?.completed
    && profile.assessment?.holland?.completed
    && PROFILE_BASIC_FIELDS.every((key) => profile.basics[key])
  );
  appState.matchingComplete = roles.length > 0 && Boolean(profile.assessment?.mbti?.completed || profile.assessment?.holland?.completed);
  appState.score = roles[0]?.overallScore || roles[0]?.trait?.score || appState.profileCompletion;

  renderProfileWorkspace(profile, roles);
  renderMatchingWorkspace(profile, roles);
  renderReportWorkspace(profile, roles);
  updateDashboardMetrics();
}

function focusMatchingRole(roleId) {
  appState.focusedRoleId = String(roleId || "");
  renderMatchingWorkspace(appState.derivedProfile || deriveUnifiedProfile(), appState.matchingRoles || []);
  renderReportWorkspace(appState.derivedProfile || deriveUnifiedProfile(), appState.matchingRoles || []);
}

function openMatchingRoleReport(roleId) {
  focusMatchingRole(roleId);
  showSection("report");
}

function animateCounter(el, target, suffix = "", duration = 500) {
  if (!el) return;
  const from = Number((el.textContent || "").replace(/[^\d.-]/g, "")) || 0;
  if (from === target) {
    el.textContent = `${target}${suffix}`;
    return;
  }
  if (el.offsetParent === null) {
    el.textContent = `${target}${suffix}`;
    return;
  }
  const start = performance.now();
  function frame(now) {
    const p = Math.min(1, (now - start) / duration);
    const val = Math.round(from + (target - from) * p);
    el.textContent = `${val}${suffix}`;
    if (p < 1) requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

function getRelockReturnTarget() {
  try {
    const url = new URL(window.location.href);
    const raw = String(url.searchParams.get("return_to") || "").trim();
    if (!raw) return "";
    if (/^https?:\/\//i.test(raw)) {
      const parsed = new URL(raw);
      if (parsed.origin !== window.location.origin) return "";
      return `${parsed.pathname}${parsed.search}${parsed.hash}`;
    }
    return raw.startsWith("/") ? raw : `/${raw.replace(/^\/+/, "")}`;
  } catch (_) {
    return "";
  }
}

function shouldForceRelock() {
  try {
    const url = new URL(window.location.href);
    return ["1", "true", "yes"].includes(String(url.searchParams.get("force_lock") || "").trim().toLowerCase());
  } catch (_) {
    return false;
  }
}

function consumeRelockParams() {
  try {
    const url = new URL(window.location.href);
    let changed = false;
    if (url.searchParams.has("force_lock")) {
      url.searchParams.delete("force_lock");
      changed = true;
    }
    if (url.searchParams.has("return_to")) {
      url.searchParams.delete("return_to");
      changed = true;
    }
    if (changed) window.history.replaceState({}, "", url.toString());
  } catch (_) {}
}

function redirectAfterUnlock() {
  const target = getRelockReturnTarget();
  if (!target) return false;
  consumeRelockParams();
  window.location.href = target;
  return true;
}

function fillSuperUser() {
  const u = document.getElementById("loginUsername");
  const p = document.getElementById("loginPassword");
  if (u) u.value = authConfig.superUser.username;
  if (p) p.value = authConfig.superUser.password;
}

function switchAuthTab(tab) {
  const isLogin = tab === "login";
  const loginForm = document.getElementById("loginForm");
  const registerForm = document.getElementById("registerForm");
  const loginBtn = document.getElementById("loginTabBtn");
  const registerBtn = document.getElementById("registerTabBtn");
  if (!loginForm || !registerForm || !loginBtn || !registerBtn) return;
  loginForm.classList.toggle("hidden", !isLogin);
  registerForm.classList.toggle("hidden", isLogin);
  loginBtn.classList.toggle("active", isLogin);
  registerBtn.classList.toggle("active", !isLogin);
  if (isLogin) {
    showAuthMessage("已自动填充预置账号：system，密码：123456。");
  } else if (!authConfig.allowSelfRegister) {
    showAuthMessage("当前环境仅开放预置账号登录，普通用户不支持自助注册。", "warning");
  } else {
    showAuthMessage("创建普通用户账号。");
  }
}

function lockApp() {
  userWorkspaceState.currentUser = null;
  userWorkspaceState.authReadyPromise = null;
  document.body.classList.add("auth-locked");
  const startup = document.getElementById("startupScreen");
  const label = document.getElementById("currentUserLabel");
  const logoutBtn = document.getElementById("logoutBtn");
  const avatar = document.getElementById("currentUserAvatar");
  if (startup) startup.classList.remove("hidden");
  if (label) { label.textContent = "未登录"; label.classList.add("hidden"); }
  if (logoutBtn) logoutBtn.classList.add("hidden");
  if (avatar) avatar.textContent = "人";
}

function unlockAppForUser(user) {
  userWorkspaceState.currentUser = user;
  const startup = document.getElementById("startupScreen");
  const label = document.getElementById("currentUserLabel");
  const logoutBtn = document.getElementById("logoutBtn");
  const avatar = document.getElementById("currentUserAvatar");
  document.body.classList.remove("auth-locked");
  if (startup) startup.classList.add("hidden");
  if (label) { label.textContent = `${user.display_name || user.displayName || user.username} (${user.role === "super_admin" ? "Super Admin" : "User"})`; label.classList.remove("hidden"); }
  if (logoutBtn) logoutBtn.classList.remove("hidden");
  if (avatar) avatar.textContent = user.role === "super_admin" ? "管" : "人";
  addLiveActivity(`User signed in: ${user.username}`);
  showToast("登录成功", `欢迎回来，${user.display_name || user.displayName || user.username}。`, "success", 1800);
  emitAuthStateChange();
  if (redirectAfterUnlock()) return;
}

async function handleLogin(event) {
  event.preventDefault();
  const username = (document.getElementById("loginUsername")?.value || "").trim();
  const password = document.getElementById("loginPassword")?.value || "";
  if (!username || !password) return showAuthMessage("请输入用户名和密码。", "error");
  try {
    await requestJson("/api/auth/login", {
      method: "POST",
      body: { username, password }
    });
    if (shouldForceRelock()) {
      showAuthMessage("解锁成功，正在返回上一界面……", "success");
    } else {
      showAuthMessage("登录成功，正在进入你的独立空间……", "success");
    }
    window.setTimeout(() => window.location.reload(), 180);
  } catch (error) {
    showAuthMessage(error.message || "用户名或密码错误。", "error");
  }
}

function handleRegister(event) {
  event.preventDefault();
  if (!authConfig.allowSelfRegister) return showAuthMessage("当前环境仅开放预置账号登录，不支持自助注册。", "warning");
  showAuthMessage("注册入口后续开放。", "warning");
}

async function logout() {
  try {
    await requestJson("/api/auth/logout", { method: "POST" });
  } catch (_) {
    // ignore logout race
  }
  window.location.reload();
}

async function initAuth() {
  if (userWorkspaceState.authReadyPromise) return userWorkspaceState.authReadyPromise;
  userWorkspaceState.authReadyPromise = (async () => {
    try {
      let payload = null;
      try {
        payload = await requestJson("/api/auth/status?bootstrap=1");
      } catch (bootstrapError) {
        console.warn("bootstrap endpoint unavailable, fallback to auth/status", bootstrapError);
        payload = await requestJson("/api/auth/status");
      }
      if (payload.authenticated && payload.user) {
        if (shouldForceRelock()) {
          lockApp();
          switchAuthTab("login");
          fillSuperUser();
          showAuthMessage("请输入密码解锁后，再返回上一次界面。", "warning");
          emitAuthStateChange();
          return null;
        }
        unlockAppForUser(payload.user);
        const llm = payload.llm || {};
        const scoped = payload.scoped_data || {};
        const ciConfig = llm.configs?.career_interview;
        if (ciConfig && typeof ciConfig === "object") {
          userWorkspaceState.llmConfigs.career_interview = {
            base_url: String(ciConfig.base_url || "").trim(),
            api_key: String(ciConfig.api_key || "").trim(),
            model: String(ciConfig.model || "gpt-4o-mini").trim() || "gpt-4o-mini",
            configured: Boolean(ciConfig.configured),
            editable: Boolean(ciConfig.editable),
            api_key_masked: String(ciConfig.api_key_masked || "")
          };
        }
        if (Object.prototype.hasOwnProperty.call(scoped, "career_interview")) {
          userWorkspaceState.scopedData.career_interview = scoped.career_interview ?? null;
          userWorkspaceState.scopedDataLoaded.career_interview = true;
        }
        if (Object.prototype.hasOwnProperty.call(scoped, "assessment_hub")) {
          userWorkspaceState.scopedData.assessment_hub = scoped.assessment_hub ?? null;
          userWorkspaceState.scopedDataLoaded.assessment_hub = true;
        }
        if (Object.prototype.hasOwnProperty.call(scoped, "resume_profile")) {
          userWorkspaceState.scopedData.resume_profile = scoped.resume_profile || emptyResumeProfile();
          userWorkspaceState.scopedDataLoaded.resume_profile = true;
        }
        if (Object.prototype.hasOwnProperty.call(scoped, "career_report")) {
          userWorkspaceState.scopedData.career_report = scoped.career_report ?? null;
          userWorkspaceState.scopedDataLoaded.career_report = true;
          appState.careerReportState = scoped.career_report ?? null;
          appState.reportGenerated = isCareerReportReadyStatus(scoped.career_report?.status);
        }
        if (Object.prototype.hasOwnProperty.call(scoped, "profile_portrait")) {
          userWorkspaceState.scopedData.profile_portrait = scoped.profile_portrait ?? null;
          userWorkspaceState.scopedDataLoaded.profile_portrait = true;
        }
        await Promise.allSettled([
          loadCareerInterviewConfig(false),
          hydrateCareerInterviewState(false),
          refreshResumeProfile(false),
          loadProfilePortraitState(false)
        ]);
        return payload.user;
      }
    } catch (error) {
      console.error("init auth failed", error);
    }
    lockApp();
    switchAuthTab("login");
    fillSuperUser();
    emitAuthStateChange();
    return null;
  })();
  return userWorkspaceState.authReadyPromise;
}

function setTagState(el, state) {
  if (!el) return;
  el.classList.remove("text-green-600", "text-orange-600", "text-red-600");
  if (state === "done") { el.classList.add("text-green-600"); el.textContent = "已完成"; }
  else if (state === "processing") { el.classList.add("text-orange-600"); el.textContent = "进行中"; }
  else { el.classList.add("text-red-600"); el.textContent = "待完成"; }
}

function updateNotificationCount(count = null) {
  if (typeof count === "number") appState.notifications = Math.max(0, count);
  const el = document.getElementById("notificationCount");
  if (el) el.textContent = String(appState.notifications);
}

function updateReportDates(baseDate = new Date()) {
  const validDate = addMonths(baseDate, 6);
  const generatedTime = document.getElementById("reportGeneratedTime");
  const headerDate = document.getElementById("reportHeaderDate");
  const footerGenerated = document.getElementById("reportFooterGeneratedDate");
  const footerValid = document.getElementById("reportFooterValidDate");
  const footerYear = document.getElementById("footerYear");
  if (generatedTime) generatedTime.textContent = formatDateCN(baseDate, true);
  if (headerDate) headerDate.textContent = formatDateCN(baseDate);
  if (footerGenerated) footerGenerated.textContent = formatDateCN(baseDate);
  if (footerValid) footerValid.textContent = formatDateCN(validDate);
  if (footerYear) footerYear.textContent = String(baseDate.getFullYear());
}

function normalizeGenderLabel(raw) {
  const v = String(raw || "").trim().toLowerCase();
  if (!v) return "";
  if (/^(m|male|man|boy|男|男性|先生)$/i.test(v) || v.includes("男")) return "male";
  if (/^(f|female|woman|girl|女|女性|女士)$/i.test(v) || v.includes("女")) return "female";
  return "";
}

function resolveDashboardPortraitGender() {
  const basicsGender = appState.derivedProfile?.basics?.gender;
  const interviewGender = careerInterviewState?.profileBasics?.gender;
  const userGender = getCurrentUser()?.gender;
  return normalizeGenderLabel(basicsGender || interviewGender || userGender || "");
}

function updateDashboardPortraitVisual() {
  const imageEl = document.getElementById("dashboardPortraitImage");
  const badgeEl = document.getElementById("dashboardPortraitBadge");
  const toneEl = document.getElementById("dashboardPortraitTone");
  const visualEl = document.getElementById("dashboardPortraitVisual");
  if (!imageEl) return;
  const gender = resolveDashboardPortraitGender();
  const isFemale = gender === "female";
  const src = isFemale ? DASHBOARD_PORTRAIT_ASSETS.female : DASHBOARD_PORTRAIT_ASSETS.male;
  if (imageEl.getAttribute("src") !== src) imageEl.setAttribute("src", src);
  imageEl.setAttribute("alt", isFemale ? "女性职业画像" : "男性职业画像");
  if (badgeEl) badgeEl.textContent = isFemale ? "女性画像" : "男性画像";
  if (toneEl) toneEl.textContent = isFemale
    ? "系统结合测评和基础信息，匹配当前女性人物画像。"
    : "系统结合测评和基础信息，匹配当前男性人物画像。";
  if (visualEl) {
    visualEl.classList.toggle("is-female", isFemale);
    visualEl.classList.toggle("is-male", !isFemale);
  }
}

function updateLiveClock() {
  const now = new Date();
  const clockEl = document.getElementById("liveClock");
  if (clockEl) clockEl.textContent = formatClock(now);
  updateDashboardPortraitVisual();
  const greetingKey = `${now.getFullYear()}-${now.getMonth()}-${now.getDate()}-${now.getHours()}`;
  if (appState.lastGreetingKey === greetingKey) return;
  appState.lastGreetingKey = greetingKey;
  const title = document.getElementById("welcomeTitle");
  const subtitle = document.getElementById("welcomeSubtitle");
  const displayName = getCurrentUser()?.display_name || getCurrentUser()?.displayName || getCurrentUser()?.username || "同学";
  const h = now.getHours();
  let greeting = "晚上好";
  if (h >= 6 && h < 12) greeting = "早上好";
  if (h >= 12 && h < 18) greeting = "下午好";
  const dayIndex = Math.ceil((now - new Date(now.getFullYear(), 0, 1)) / 86400000);
  if (title) title.textContent = `${greeting}，${displayName}`;
  if (subtitle) subtitle.textContent = `今天是 ${formatDateCN(now)}，年度第 ${dayIndex} 天，系统正在用最新测评、访谈和基础信息更新你的职业画像。`;
}

function updateTaskPanels(explored) {
  const exploreStatus = document.getElementById("taskJobExploreStatus");
  const exploreStatusCard = document.getElementById("taskJobExploreStatusCard");
  const exploreTag = document.getElementById("taskJobExploreTag");
  const exploreTagCard = document.getElementById("taskJobExploreTagCard");
  const matchingStatus = document.getElementById("taskMatchingStatus");
  const matchingStatusCard = document.getElementById("taskMatchingStatusCard");
  const matchingTag = document.getElementById("taskMatchingTag");
  const matchingTagCard = document.getElementById("taskMatchingTagCard");
  const progressHint = document.getElementById("taskProgressHint");
  const progressHintDisplay = document.getElementById("taskProgressHintDisplay");
  const reportBtn = document.getElementById("generateReportBtn");
  const reportBtnCard = document.getElementById("generateReportBtnCard");
  const exploredDone = explored >= 3;
  const exploreText = `已形成 ${explored} 个初步岗位方向`;
  const matchingText = appState.matchingRoles.length
    ? `已生成 ${appState.matchingRoles.length} 个岗位匹配结果`
    : "等待画像输入生成匹配";
  if (exploreStatus) exploreStatus.textContent = exploreText;
  if (exploreStatusCard) exploreStatusCard.textContent = exploreText;
  setTagState(exploreTag, exploredDone ? "done" : "processing");
  setTagState(exploreTagCard, exploredDone ? "done" : "processing");
  if (matchingStatus) matchingStatus.textContent = matchingText;
  if (matchingStatusCard) matchingStatusCard.textContent = matchingText;
  setTagState(matchingTag, appState.matchingComplete ? "done" : "processing");
  setTagState(matchingTagCard, appState.matchingComplete ? "done" : "processing");
  const doneCount = [appState.profileComplete, exploredDone, appState.matchingComplete, appState.reportGenerated].filter(Boolean).length;
  if (progressHint) progressHint.textContent = `已完成 ${doneCount}/4 个关键任务`;
  if (progressHintDisplay) progressHintDisplay.textContent = `已完成 ${doneCount}/4 个关键任务`;
  [reportBtn, reportBtnCard].forEach((button) => {
    if (!button) return;
    if (appState.reportGenerated) {
      button.textContent = "报告已更新";
      button.classList.add("bg-green-600", "hover:bg-green-700");
      button.classList.remove("bg-purple-600", "hover:bg-purple-700", "bg-violet-600", "hover:bg-violet-700");
    } else {
      button.textContent = "生成当前报告";
      if (button.id === "generateReportBtnCard") {
        button.classList.add("bg-violet-600", "hover:bg-violet-700");
        button.classList.remove("bg-green-600", "hover:bg-green-700");
      } else {
        button.classList.add("bg-purple-600", "hover:bg-purple-700");
        button.classList.remove("bg-green-600", "hover:bg-green-700");
      }
    }
  });
}

function updateDashboardMetrics() {
  const roles = Array.isArray(appState.matchingRoles) ? appState.matchingRoles : [];
  const profile = appState.derivedProfile;
  updateDashboardPortraitVisual();
  const topRoleData = roles[0];
  const explored = roles.slice(0, 3).length;
  const topRate = topRoleData?.overallScore || topRoleData?.trait?.score || 0;
  const topJob = topRoleData?.name || "等待岗位方向";
  const pending = profile ? profile.missingItems.length + (appState.reportGenerated ? 0 : 1) : 4;
  animateCounter(document.getElementById("exploredJobsCount"), explored);
  animateCounter(document.getElementById("profileCompletionRate"), appState.profileCompletion, "%");
  animateCounter(document.getElementById("topMatchRate"), topRate, "%");
  animateCounter(document.getElementById("pendingTaskCount"), pending);
  animateCounter(document.getElementById("dashboardScore"), appState.score, "%");
  const topRole = document.getElementById("topMatchRole");
  const scoreTrend = document.getElementById("scoreTrend");
  const profileHint = document.getElementById("profileCompletionHint");
  const pendingHint = document.getElementById("pendingTaskHint");
  if (topRole) topRole.textContent = topJob;
  if (scoreTrend) scoreTrend.textContent = topRoleData ? `Top1 置信度 ${topRoleData.confidence}` : "等待画像输入";
  if (profileHint) profileHint.textContent = profile?.missingItems?.length ? `待补充 ${profile.missingItems.length} 项` : "画像基础已就绪";
  if (pendingHint) pendingHint.textContent = pending === 0 ? "全部完成" : "优先补基础信息和访谈";
  updateTaskPanels(explored);
}

function markReportGenerated(source = "view") {
  if (!appState.reportGenerated) {
    appState.reportGenerated = true;
    updateReportDates(new Date());
    if (source !== "view") {
      addLiveActivity("Report regenerated with latest profile data");
    }
  }
  renderReportWorkspace(appState.derivedProfile || deriveUnifiedProfile(), appState.matchingRoles || []);
  updateDashboardMetrics();
}

function showSection(sectionId) {
  if (sectionId === appState.currentSection) return;
  const sections = ["dashboard", "jobs", "profile", "matching", "report", "forum"];
  sections.forEach((id) => {
    const section = document.getElementById(id);
    // 优先使用 data-section 选择导航按钮，避免依赖 onclick 选择器。
    const navItem = document.querySelector(`button[data-section="${id}"]`);
    if (!section) return;
    if (id === sectionId) {
      section.classList.remove("hidden");
      section.classList.add("fade-in");
      if (navItem) navItem.classList.add("active");
    } else {
      section.classList.add("hidden");
      section.classList.remove("fade-in");
      if (navItem) navItem.classList.remove("active");
    }
  });
  appState.currentSection = sectionId;
  // 更新 URL hash，让 return-nav 能记录当前 section，返回时恢复正确页面
  try { window.history.replaceState({}, '', '#' + sectionId); } catch (_) {}
  if (sectionId === "report") renderReportWorkspace(appState.derivedProfile || deriveUnifiedProfile(), appState.matchingRoles || []);
  if (sectionId === "jobs" && allJobsData.length === 0) loadJobs();
  if (sectionId === "forum") {
    void ensureCommunityForumLoaded();
  }
  if (sectionId === "profile") {
    initProfileFlow();
    void refreshResumeProfile(true);
  }
  if (sectionId === "matching") {
    const profile = appState.derivedProfile || deriveUnifiedProfile();
    const roles = Array.isArray(appState.matchingRoles) && appState.matchingRoles.length
      ? appState.matchingRoles
      : computeRoleMatches(profile);
    renderMatchingWorkspace(profile, roles);
  }
  if (sectionId === "matching") {
    void ensureCareerGraphMatchingAssets()
      .then((api) => api?.onSectionVisible?.())
      .catch((error) => {
        showToast("职业图谱加载失败", error.message, "warning", 2200);
      });
  }
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function checkReportReadiness() {
  const profile = appState.derivedProfile || deriveUnifiedProfile();
  if (profile.missingItems.length) {
    showToast("可生成初步报告", `当前仍有待补充项：${profile.missingItems.slice(0, 2).join("、")}`, "warning", 2400);
  } else {
    showToast("报告就绪", "统一画像与岗位匹配已同步完成。", "success", 1800);
  }
  showSection("report");
}

function selectTargetJob(jobType) {
  const isNew = !appState.selectedJobs.includes(jobType);
  if (isNew) appState.selectedJobs.push(jobType);
  const name = jobNameMap[jobType] || jobType;
  showToast("Target updated", `${name} added to target list.`, "success", 1800);
  addLiveActivity(`Target selected: ${name}`);
  if (isNew) appState.notifications += 1;
  updateNotificationCount();
  updateDashboardMetrics();
}

function addToReport(jobType) {
  const isNew = !appState.selectedJobs.includes(jobType);
  if (isNew) appState.selectedJobs.push(jobType);
  const name = jobNameMap[jobType] || jobType;
  showToast("Synced to report", `${name} added to report targets.`, "success", 1800);
  addLiveActivity(`Synced to report: ${name}`);
  if (isNew) appState.notifications += 1;
  updateNotificationCount();
  updateDashboardMetrics();
}

function showJobDetail(jobType) {
  const data = {
    ml: { title: "机器学习工程师", company: "明材科技 · 北京" },
    da: { title: "数据分析师", company: "字节跃动 · 上海" },
    pm: { title: "AI 产品经理", company: "腾讯 · 深圳" },
    fe: { title: "前端开发工程师", company: "阿里巴巴 · 杭州" }
  };
  const item = data[jobType] || data.ml;
  const title = document.getElementById("modalJobTitle");
  const company = document.getElementById("modalJobCompany");
  const modal = document.getElementById("jobDetailModal");
  if (title) title.textContent = item.title;
  if (company) company.textContent = item.company;
  if (modal) modal.classList.remove("hidden");
  addLiveActivity(`Viewed job details: ${item.title}`);
}

function closeModal(modalId) {
  const modal = document.getElementById(modalId);
  if (modal) modal.classList.add("hidden");
}

function switchGraphType(type) {
  const verticalGraph = document.getElementById("verticalGraph");
  const horizontalGraph = document.getElementById("horizontalGraph");
  const btns = document.querySelectorAll(".graph-type-btn");
  if (!verticalGraph || !horizontalGraph || btns.length < 2) return;
  if (type === "vertical") {
    verticalGraph.style.display = "block";
    horizontalGraph.style.display = "none";
    btns[0].classList.add("active", "bg-purple-100", "text-purple-600");
    btns[0].classList.remove("bg-gray-100", "text-gray-600");
    btns[1].classList.remove("active", "bg-purple-100", "text-purple-600");
    btns[1].classList.add("bg-gray-100", "text-gray-600");
  } else {
    verticalGraph.style.display = "none";
    horizontalGraph.style.display = "block";
    btns[1].classList.add("active", "bg-purple-100", "text-purple-600");
    btns[1].classList.remove("bg-gray-100", "text-gray-600");
    btns[0].classList.remove("active", "bg-purple-100", "text-purple-600");
    btns[0].classList.add("bg-gray-100", "text-gray-600");
  }
}

function updateWeight(slider, dimension) {
  const value = Number(slider.value);
  appState.weights[dimension] = value;
  const valueLabel = slider.closest(".matching-weight-card")?.querySelector(".matching-weight-value");
  if (valueLabel) valueLabel.textContent = `${value}%`;
  const sliders = Array.from(document.querySelectorAll("input[type='range'][onchange*='updateWeight']"));
  const total = sliders.reduce((sum, item) => sum + Number(item.value || 0), 0);
  const totalEl = document.getElementById("weightTotal");
  if (totalEl) {
    totalEl.textContent = `${total}%`;
    totalEl.classList.toggle("text-orange-600", total !== 100);
    totalEl.classList.toggle("text-sky-600", total === 100);
  }
}

function recalculateMatching() {
  const total = Object.values(appState.weights).reduce((sum, n) => sum + n, 0);
  if (total !== 100) return showToast("权重总和不正确", "四个分项权重之和必须等于 100%。", "warning", 2200);
  refreshUnifiedExperience();
  addLiveActivity("Matching strategy refreshed with new weight settings");
  showToast("匹配结果已刷新", "系统已按最新权重重新排序岗位结果。", "success", 1800);
}

function recalculateProfile() {
  refreshUnifiedExperience();
  addLiveActivity("Profile synthesis refreshed from latest assessment and interview state");
  showToast("画像已重算", "测评、访谈和基础信息已经重新同步。", "success", 1800);
}

function triggerFileUpload() {
  const up = document.getElementById("resumeUpload");
  if (up) up.click();
}

function handleFileUpload(event) {
  const file = event.target.files[0];
  if (!file) return;
  showToast("Parsing resume", `Processing ${file.name}...`, "info", 1200);
  setTimeout(() => {
    appState.profileCompletion = Math.min(96, appState.profileCompletion + 2);
    updateDashboardMetrics();
    addLiveActivity(`Resume parsed: ${file.name}`);
    showToast("Done", "Capability profile updated.", "success", 1600);
  }, 1200);
}

function showManualInput() { showToast("Coming soon", "Manual profile input will be enabled soon.", "info", 1700); }
function editReport() { showToast("报告说明", "当前报告由统一画像实时生成，暂不提供段落级手改。", "info", 1800); }
function saveReport() { markReportGenerated("save"); showToast("报告已保存", "当前草稿状态已刷新到本地会话。", "success", 1500); addLiveActivity("Report draft saved by user"); }

function exportReport() {
  showToast("正在导出", "系统正在准备当前报告内容。", "info", 1000);
  setTimeout(() => {
    markReportGenerated("export");
    showToast("导出完成", "报告内容已整理完成，可继续扩展 PDF 流程。", "success", 1800);
    addLiveActivity("PDF export completed");
  }, 1200);
}

function shareReport() { showToast("Share link ready", "You can now share this report.", "success", 1700); }
function scheduleConsultation() { showToast("Consultation", "Booking flow is now available.", "info", 1700); }
function showNodeDetail(nodeName) { showToast("Node details", `${nodeName} details are available.`, "info", 1700); }

// --------------------------------------------------
//  从服务器加载岗位数据
// --------------------------------------------------
async function loadJobs() {
  const loading = document.getElementById("jobsLoading");
  const grid = document.getElementById("jobGrid");
  const pager = document.getElementById("jobPagination");
  if (loading) loading.classList.remove("hidden");
  if (grid) grid.classList.add("hidden");
  if (pager) pager.classList.add("hidden");

  try {
    const geoAssetsPromise = ensureJobsGeoAssets().catch((error) => {
      console.warn("jobs geo assets failed to load", error);
      return null;
    });
    let jobsBootstrap = null;
    try {
      jobsBootstrap = await fetchJsonWithSessionCache("/api/jobs?view=bootstrap&city=all", `${JOBS_LIST_CACHE_PREFIX}bootstrap`);
    } catch (bootstrapError) {
      console.warn("jobs bootstrap endpoint unavailable, fallback to legacy requests", bootstrapError);
    }
    let cities = [];
    let jobs = [];
    if (Array.isArray(jobsBootstrap?.cities) && Array.isArray(jobsBootstrap?.jobs)) {
      cities = jobsBootstrap.cities;
      jobs = jobsBootstrap.jobs;
    } else {
      const [citiesData, jobsData] = await Promise.all([
        fetchJsonWithSessionCache("/api/cities", JOBS_CITIES_CACHE_KEY, 60 * 60 * 1000),
        fetchJsonWithSessionCache("/api/jobs?city=all&view=summary", `${JOBS_LIST_CACHE_PREFIX}all`)
      ]);
      cities = Array.isArray(citiesData) ? citiesData : [];
      jobs = Array.isArray(jobsData) ? jobsData : [];
    }
    const citySelect = document.getElementById("cityFilter");
    if (citySelect) {
      citySelect.innerHTML = '<option value="all">全部城市</option>';
      cities.forEach((city) => {
        const option = document.createElement("option");
        option.value = city;
        option.textContent = city;
        citySelect.appendChild(option);
      });
    }

    allJobsData = jobs;
    filteredJobsData = [...allJobsData];
    fuseIndex = null;
    appState.lastJobFilterKey = "";

    const industrySet = new Set(allJobsData.map((job) => job["公司行业"]).filter(Boolean));
    const industrySel = document.getElementById("industryFilter");
    if (industrySel) {
      industrySel.innerHTML = '<option value="all">全部行业</option>';
      [...industrySet].sort().forEach((industry) => {
        const option = document.createElement("option");
        option.value = industry;
        option.textContent = industry;
        industrySel.appendChild(option);
      });
    }

    if (loading) loading.classList.add("hidden");
    filterJobs(true);
    geoAssetsPromise.then(() => scheduleGeoInsightsInit(allJobsData));
    scheduleAnalyticsInit(allJobsData);

    const summary = document.getElementById("jobFilterSummary");
    if (summary) summary.textContent = `已加载 ${allJobsData.length} 个岗位摘要`;
  } catch (err) {
    if (loading) {
      loading.innerHTML = `<p class="text-red-500">无法连接数据服务<br><span class="text-xs text-gray-400">${escHtml(err.message)}</span></p>`;
    }
  }
}
function filterJobs(silent = false) {
  if (allJobsData.length === 0) return;
  const query = (document.getElementById("jobSearch")?.value || "").trim();
  const cityVal = document.getElementById("cityFilter")?.value || "all";
  const industryVal = document.getElementById("industryFilter")?.value || "all";
  const filterKey = `${query}__${cityVal}__${industryVal}__${allJobsData.length}`;
  if (filterKey === appState.lastJobFilterKey) return;
  appState.lastJobFilterKey = filterKey;
  if (cityVal !== "all" && typeof window.syncJobGeoSelectionWithCity === "function") {
    window.syncJobGeoSelectionWithCity(cityVal);
  }

  let queryResult = allJobsData;
  if (query) {
    buildJobSearchIndex();
    if (fuseIndex) {
      queryResult = fuseIndex.search(query).map((item) => item.item);
      if (queryResult.length === 0) {
        const lowerQuery = query.toLowerCase();
        queryResult = allJobsData.filter((job) =>
          [job["岗位名称"], job["公司名称"], job["技能要求"], job["职位类别"], job["公司行业"]]
            .join(" ")
            .toLowerCase()
            .includes(lowerQuery)
        );
      }
    }
  }

  filteredJobsData = queryResult.filter((job) => {
    const okCity = cityVal === "all" || (job["采集城市"] || job["城市"] || "") === cityVal;
    const okIndustry = industryVal === "all" || (job["公司行业"] || "") === industryVal;
    return okCity && okIndustry;
  });

  jobCurrentPage = 1;
  renderJobCards();

  const summary = document.getElementById("jobFilterSummary");
  if (summary) summary.textContent = `当前显示 ${filteredJobsData.length} / ${allJobsData.length} 个岗位`;
  if (!silent) {
    addLiveActivity(`岗位筛选完成：共 ${filteredJobsData.length} 个结果`);
  }
}
function renderJobCards() {
  const grid  = document.getElementById("jobGrid");
  const pager = document.getElementById("jobPagination");
  if (!grid) return;

  const total      = filteredJobsData.length;
  const totalPages = Math.ceil(total / JOB_PAGE_SIZE);
  const start      = (jobCurrentPage - 1) * JOB_PAGE_SIZE;
  const pageData   = filteredJobsData.slice(start, start + JOB_PAGE_SIZE);

  if (total === 0) {
    grid.innerHTML = `<div class="col-span-3 py-16 text-center text-gray-400">
      <p class="text-4xl mb-3">馃攳</p>
      <p class="text-lg font-medium text-gray-500">没有找到匹配的岗位</p>
      <p class="text-sm mt-1">试试调整搜索关键词或城市筛选</p>
    </div>`;
    grid.classList.remove("hidden");
    pager.classList.add("hidden");
    return;
  }

  grid.innerHTML = pageData.map((job, i) => {
    const idx     = start + i;
    const skills  = String(job["技能要求"] || "").split(",").map((s) => s.trim()).filter(Boolean);
    const skillTags = skills.slice(0, 5).map(s =>
      `<span class="px-2 py-0.5 bg-purple-50 text-purple-700 text-xs rounded border border-purple-100 whitespace-nowrap">${escHtml(s)}</span>`
    ).join("") + (skills.length > 5 ? `<span class="px-2 py-0.5 bg-gray-50 text-gray-400 text-xs rounded">+${skills.length - 5}</span>` : "");

    const fundingColors = {
      "已上市": "bg-blue-100 text-blue-700",
      "D轮及以上": "bg-indigo-100 text-indigo-700",
      "C轮": "bg-violet-100 text-violet-700",
      "B轮": "bg-purple-100 text-purple-700",
      "A轮": "bg-fuchsia-100 text-fuchsia-700",
      "天使轮": "bg-pink-100 text-pink-700"
    };
    const fundingCls = fundingColors[job["融资阶段"]] || "bg-gray-100 text-gray-500";

    return `
    <div class="job-card-real bg-white rounded-xl glass-surface p-5 shadow-sm cursor-pointer
                border-2 border-transparent hover:border-purple-300 hover:shadow-lg transition-all duration-200"
         onclick="openJobModal(${idx})">
      <!-- 标题 + 薪资 -->
      <div class="flex justify-between items-start mb-2 gap-2">
        <h3 class="text-base font-bold text-gray-800 leading-tight line-clamp-2 flex-1">${escHtml(job["岗位名称"] || "--")}</h3>
        <span class="text-sm font-bold text-emerald-600 flex-shrink-0 mt-0.5">${escHtml(job["薪资"] || "面议")}</span>
      </div>
      <!-- 公司 -->
      <p class="text-sm text-gray-500 mb-3 truncate">${escHtml(job["公司名称"] || "")}</p>
      <!-- 鍩庡競 / 缁忛獙 / 瀛﹀巻 -->
      <div class="flex flex-wrap gap-1.5 mb-3">
        <span class="px-2 py-0.5 bg-blue-50 text-blue-600 text-xs rounded-full whitespace-nowrap">馃搷 ${escHtml(job["城市"] || job["采集城市"] || "")}</span>
        <span class="px-2 py-0.5 bg-gray-100 text-gray-500 text-xs rounded-full whitespace-nowrap">${escHtml(job["经验要求"] || "")}</span>
        <span class="px-2 py-0.5 bg-gray-100 text-gray-500 text-xs rounded-full whitespace-nowrap">馃帗 ${escHtml(job["学历要求"] || "")}</span>
      </div>
      <!-- 技能标签 -->
      <div class="flex flex-wrap gap-1 mb-4">${skillTags}</div>
      <!-- 底部：公司信息 -->
      <div class="flex justify-between items-center pt-3 border-t border-gray-100 text-xs text-gray-400">
        <span class="truncate">${escHtml(job["公司规模"] || "")} 路 ${escHtml(job["公司行业"] || "")}</span>
        <span class="px-2 py-0.5 rounded-full flex-shrink-0 ml-2 ${fundingCls}">${escHtml(job["融资阶段"] || "")}</span>
      </div>
    </div>`;
  }).join("");

  grid.classList.remove("hidden");

  // 分页
  const prevBtn  = document.getElementById("jobPrevBtn");
  const nextBtn  = document.getElementById("jobNextBtn");
  const pageInfo = document.getElementById("jobPageInfo");
  if (pager) {
    pager.classList.remove("hidden");
    if (prevBtn)  prevBtn.disabled  = jobCurrentPage <= 1;
    if (nextBtn)  nextBtn.disabled  = jobCurrentPage >= totalPages;
    if (pageInfo) pageInfo.textContent = `第 ${jobCurrentPage} / ${totalPages} 页 · 共 ${total} 个岗位`;
  }
}

function jobChangePage(delta) {
  const total      = filteredJobsData.length;
  const totalPages = Math.ceil(total / JOB_PAGE_SIZE);
  jobCurrentPage   = Math.max(1, Math.min(totalPages, jobCurrentPage + delta));
  renderJobCards();
  document.getElementById("jobs")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function escHtml(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

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

async function openJobModal(idx) {
  let job = filteredJobsData[idx];
  if (!job) return;

  if (job.job_id) {
    try {
      job = await getJobDetail(job.job_id);
    } catch (error) {
      showToast("岗位详情加载失败", error.message, "warning", 2200);
    }
  }

  const companyName = job["公司名称"] || "--";
  const jobTitle = job["岗位名称"] || "--";

  const avatar = document.getElementById("jobModalAvatar");
  if (avatar) {
    const firstChar = companyName.charAt(0) || "?";
    avatar.textContent = firstChar;
    const hue = (firstChar.charCodeAt(0) * 37) % 360;
    avatar.style.background = `hsla(${hue},55%,55%,0.35)`;
  }

  document.getElementById("jobModalTitle").textContent = jobTitle;
  document.getElementById("jobModalCompany").textContent = companyName;
  document.getElementById("jobModalSalary").textContent = job["薪资"] || "面议";

  const meta = document.getElementById("jobModalMeta");
  const metaItems = [
    ["地点", job["城市"] || job["采集城市"]],
    ["经验", job["经验要求"]],
    ["学历", job["学历要求"]],
    ["行业", job["公司行业"]]
  ].filter(([, value]) => value);
  meta.innerHTML = metaItems.map(([label, text]) =>
    `<span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs text-white/80 whitespace-nowrap"
           style="background:rgba(255,255,255,0.15);border:1px solid rgba(255,255,255,0.2)">
       ${escHtml(label)} ${escHtml(text)}
     </span>`
  ).join("");

  const skills = String(job["技能要求"] || "").split(",").map((item) => item.trim()).filter(Boolean);
  document.getElementById("jobModalSkills").innerHTML = skills.length
    ? skills.map((skill) =>
        `<span class="px-3 py-1 text-xs rounded-full font-medium"
               style="background:#f0ebff;color:#6d28d9;border:1px solid #ddd6fe">${escHtml(skill)}</span>`
      ).join("")
    : `<span class="text-gray-400 text-sm">暂无标签</span>`;

  document.getElementById("jobModalDesc").textContent = job["岗位描述"] || "暂无描述";

  const compInfo = document.getElementById("jobModalCompanyInfo");
  const compFields = [
    { icon: "融资", label: "融资阶段", val: job["融资阶段"] },
    { icon: "规模", label: "公司规模", val: job["公司规模"] },
    { icon: "行业", label: "所属行业", val: job["公司行业"] }
  ];
  compInfo.innerHTML = compFields.map(({ icon, label, val }) => `
    <div class="rounded-xl p-3 text-center" style="background:#f8f5ff;border:1px solid #ede9fe">
      <p class="text-lg mb-0.5">${icon}</p>
      <p class="text-xs font-semibold text-violet-700 leading-tight">${escHtml(val || "--")}</p>
      <p class="text-xs text-gray-400 mt-0.5">${label}</p>
    </div>`).join("");
  document.getElementById("jobModalCompanyDesc").textContent = job["公司简介"] || "";

  const addr = document.getElementById("jobModalAddr");
  if (addr) addr.textContent = job["工作地址"] || "暂无地址信息";

  const welfares = String(job["公司福利"] || "").split(",").map((item) => item.trim()).filter(Boolean);
  document.getElementById("jobModalWelfare").innerHTML = welfares.length
    ? welfares.map((welfare) => {
        const icon = welfareIcons[welfare] || "✓";
        return `<span class="inline-flex items-center gap-1 px-2.5 py-1 text-xs rounded-full font-medium"
                      style="background:#f0fdf4;color:#15803d;border:1px solid #bbf7d0">
                  ${icon} ${escHtml(welfare)}
                </span>`;
      }).join("")
    : `<span class="text-gray-400 text-xs">暂无福利信息</span>`;

  const modal = document.getElementById("jobModal");
  modal.classList.remove("hidden");
  modal.classList.add("flex");
  document.body.style.overflow = "hidden";
}
function closeJobModal() {
  const modal = document.getElementById("jobModal");
  modal.classList.add("hidden");
  modal.classList.remove("flex");
  document.body.style.overflow = "";
}

function initCharts() {
  const radarCanvas = document.getElementById("radarChart");
  const profileRadarCanvas = document.getElementById("profileRadarChart");
  if (radarCanvas && window.Chart) {
    // 防止重复创建（canvas 已被 Chart.js 占用时先销毁旧实例）
    if (appState.dashboardRadarChart) { appState.dashboardRadarChart.destroy(); appState.dashboardRadarChart = null; }
    appState.dashboardRadarChart = new Chart(radarCanvas.getContext("2d"), {
      type: "radar",
      data: {
        labels: ["专业技能", "沟通能力", "学习能力", "抗压能力", "创新能力", "实习经历"],
        datasets: [
          { label: "当前能力", data: [75, 82, 88, 70, 65, 60], backgroundColor: "rgba(102,126,234,0.2)", borderColor: "rgba(102,126,234,1)", borderWidth: 2, pointBackgroundColor: "rgba(102,126,234,1)" },
          { label: "岗位要求", data: [85, 75, 80, 75, 70, 75], backgroundColor: "rgba(118,75,162,0.2)", borderColor: "rgba(118,75,162,1)", borderWidth: 2, pointBackgroundColor: "rgba(118,75,162,1)" }
        ]
      },
      options: { responsive: true, maintainAspectRatio: false, scales: { r: { angleLines: { color: "rgba(0,0,0,0.1)" }, grid: { color: "rgba(0,0,0,0.1)" }, pointLabels: { font: { size: 12 }, color: "#666" }, ticks: { backdropColor: "transparent", max: 100, stepSize: 20 } } }, plugins: { legend: { position: "top", labels: { usePointStyle: true } } } }
    });
  }
  if (profileRadarCanvas && window.Chart) {
    if (appState.profileRadarChart) { appState.profileRadarChart.destroy(); appState.profileRadarChart = null; }
    appState.profileRadarChart = new Chart(profileRadarCanvas.getContext("2d"), {
      type: "radar",
      data: { labels: ["专业技能", "证书资质", "沟通能力", "学习能力", "抗压能力", "创新能力", "实习经历", "项目经验"], datasets: [{ label: "能力评分", data: [75, 60, 82, 88, 70, 65, 60, 55], backgroundColor: "rgba(102,126,234,0.3)", borderColor: "rgba(102,126,234,1)", borderWidth: 2, pointBackgroundColor: "rgba(102,126,234,1)", pointRadius: 4 }] },
      options: { responsive: true, maintainAspectRatio: false, scales: { r: { angleLines: { color: "rgba(0,0,0,0.1)" }, grid: { color: "rgba(0,0,0,0.1)" }, pointLabels: { font: { size: 11 }, color: "#666" }, ticks: { backdropColor: "transparent", max: 100, stepSize: 20 } } }, plugins: { legend: { display: false } } }
    });
  }
}

function initAnimations() {
  const bars = document.querySelectorAll(".progress-bar");
  bars.forEach((bar) => {
    const w = bar.style.width;
    bar.style.width = "0";
    setTimeout(() => { bar.style.width = w; }, 400);
  });
  const modal = document.getElementById("jobDetailModal");
  if (modal) modal.addEventListener("click", function (e) { if (e.target === this) closeModal("jobDetailModal"); });
  if (typeof IntersectionObserver !== "undefined") {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("slide-in");
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12 });
    document.querySelectorAll(".glass-surface, .cs-panel, .cs-feature-card, .career-news-item").forEach((el) => observer.observe(el));
  }
}

function bindGlobalEvents() {
  const notificationBtn = document.getElementById("notificationBtn");
  if (notificationBtn) {
    notificationBtn.addEventListener("click", () => {
      const unread = appState.notifications;
      if (unread > 0) {
        showToast("Notifications", `You have ${unread} new update(s).`, "info", 1600);
        addLiveActivity(`Notification center opened (${unread})`);
      } else {
        showToast("Notifications", "No new updates.", "info", 1400);
      }
      appState.notifications = Math.max(0, unread - 1);
      updateNotificationCount();
    });
  }

  const searchInput = document.getElementById("jobSearch");
  if (searchInput) {
    // 实时输入时直接触发筛选。
    searchInput.addEventListener("input", () => filterJobs());
    searchInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        filterJobs();
      }
    });
  }

  const industryFilter = document.getElementById("industryFilter");
  const cityFilter = document.getElementById("cityFilter");
  if (industryFilter) {
    industryFilter.addEventListener("change", () => filterJobs());
  }
  if (cityFilter) {
    cityFilter.addEventListener("change", () => filterJobs());
  }

  const profileFlowModelStatus = document.getElementById("profileFlowModelStatus");
  if (profileFlowModelStatus && !profileFlowModelStatus.dataset.boundClick) {
    profileFlowModelStatus.addEventListener("click", () => {
      openModelPicker(() => {
        void updateProfileFlowModelStatus(true);
      });
    });
    profileFlowModelStatus.dataset.boundClick = "1";
  }
}

function startRealtimeEngine() {
  if (appState.timersStarted) return;
  appState.timersStarted = true;
  updateLiveClock();
  setInterval(updateLiveClock, 1000);
  setInterval(() => {
    const msg = liveActivityTemplates[Math.floor(Math.random() * liveActivityTemplates.length)];
    addLiveActivity(msg);
    appState.notifications = Math.min(9, appState.notifications + 1);
    updateNotificationCount();
  }, 20000);
}

document.addEventListener("DOMContentLoaded", function () {
  const authReady = initAuth();
  initCharts();
  initAnimations();
  bindGlobalEvents();
  initCommunityForumEvents();
  initCareerNewsBoard();
  startRealtimeEngine();
  updateReportDates(new Date());
  updateNotificationCount();
  syncProfileBasicsForm();
  refreshUnifiedExperience();
  addLiveActivity("System initialized. Dynamic monitoring is active.");
  window.addEventListener("assessment-hub:updated", () => {
    refreshUnifiedExperience();
  });
  Promise.resolve(authReady).finally(() => {
    updateCareerInterviewConfigStatus();
    void updateProfileFlowModelStatus(true);
    renderCareerInterviewMessages();
    renderCareerInterviewResult(careerInterviewState.result);
    refreshUnifiedExperience();
    void resumeCareerReportRuntime();
    // 从 URL hash 恢复上次所在 section（支持 return-nav 返回到正确页面）
    try {
      const VALID_SECTIONS = ["dashboard", "jobs", "profile", "matching", "report", "forum"];
      const hashId = (window.location.hash || "").replace(/^#/, "").trim().toLowerCase();
      if (hashId && VALID_SECTIONS.includes(hashId) && hashId !== (appState.currentSection || "dashboard")) {
        showSection(hashId);
      }
    } catch (_) {}
  });

  // 双保险绑定，避免仅依赖内联 onclick 在部分环境失效。
  const startBtn = document.getElementById("careerInterviewStartBtn");
  if (startBtn && !startBtn.dataset.boundClick) {
    startBtn.addEventListener("click", () => { void startCareerInterview(); });
    startBtn.dataset.boundClick = "1";
  }

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const resumeReportModal = document.getElementById("resumeReportModal");
    if (resumeReportModal && !resumeReportModal.classList.contains("hidden")) {
      closeResumeReportModal();
    }
  });
});

// 职业问答模块
function getCommunityBoardMeta(board) {
  return COMMUNITY_FORUM_BOARD_META[board] || COMMUNITY_FORUM_BOARD_META.all;
}

function getCommunityForumPostById(postId) {
  return (communityForumState.posts || []).find((item) => String(item.id) === String(postId || "")) || null;
}

function upsertCommunityForumPost(updated) {
  const next = [];
  (communityForumState.posts || []).forEach((item) => {
    if (String(item.id) === String(updated.id)) {
      next.push({ ...item, ...updated });
    } else {
      next.push(item);
    }
  });
  communityForumState.posts = next;
}

function applyCommunityForumFeed(payload) {
  communityForumState.posts = Array.isArray(payload?.posts) ? payload.posts : [];
  communityForumState.boards = Array.isArray(payload?.boards) ? payload.boards : [];
  communityForumState.hotTags = Array.isArray(payload?.hot_tags) ? payload.hot_tags : [];
  communityForumState.stats = payload?.stats && typeof payload.stats === "object"
    ? payload.stats : { threads: 0, today_posts: 0, active_users: 0, unanswered: 0 };
  if (!getCommunityForumPostById(communityForumState.selectedPostId)) {
    communityForumState.selectedPostId = communityForumState.posts[0]?.id || "";
  }
}

function getCommunityForumHotScore(post) {
  const views = Number(post?.views || 0);
  const likes = Number(post?.likes || 0);
  const replies = Number(post?.reply_count || 0);
  const ageHours = (Date.now() / 1000 - Number(post?.created_at || 0)) / 3600;
  return (views * 0.5 + likes * 2 + replies * 3) / Math.max(1, Math.pow(ageHours + 2, 1.2));
}

function getCommunityForumFilteredPosts() {
  const query = String(communityForumState.query || "").trim().toLowerCase();
  const board = String(communityForumState.board || "all");
  const sort = String(communityForumState.sort || "hot");
  let posts = Array.isArray(communityForumState.posts) ? [...communityForumState.posts] : [];
  if (board !== "all") {
    posts = posts.filter((p) => String(p.board || "") === board);
  }
  if (query) {
    posts = posts.filter((p) => {
      const text = [p.title, p.content, ...(p.tags || [])].filter(Boolean).join(" ").toLowerCase();
      return text.includes(query);
    });
  }
  posts.sort((a, b) => {
    if (a.pinned && !b.pinned) return -1;
    if (!a.pinned && b.pinned) return 1;
    if (sort === "latest") return Number(b.created_at || 0) - Number(a.created_at || 0);
    if (sort === "unanswered") {
      const replyDiff = Number(a?.reply_count || 0) - Number(b?.reply_count || 0);
      if (replyDiff) return replyDiff;
      return Number(b.updated_at || 0) - Number(a.updated_at || 0);
    }
    return getCommunityForumHotScore(b) - getCommunityForumHotScore(a);
  });
  return posts;
}

// 切换三视图：list / detail / compose
function showForumView(view) {
  communityForumState.view = view;
  const viewMap = { list: "forumListView", detail: "forumDetailView", compose: "forumComposeView" };
  Object.values(viewMap).forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.classList.add("hidden");
  });
  const target = document.getElementById(viewMap[view]);
  if (target) target.classList.remove("hidden");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function renderCommunityForumBoardFilters() {
  const container = document.getElementById("forumBoardFilters");
  if (!container) return;
  const boards = communityForumState.boards.length
    ? communityForumState.boards
    : [{ key: "all", label: "全部", count: 0 }].concat(
        Object.keys(COMMUNITY_FORUM_BOARD_META)
          .filter((key) => key !== "all")
          .map((key) => ({ key, label: key, count: 0 }))
      );
  container.innerHTML = boards.map((item) => {
    const key = String(item.key || item.label || "all");
    const active = key === communityForumState.board;
    const meta = getCommunityBoardMeta(key);
    return `
      <button
        type="button"
        onclick="setCommunityForumBoard('${key}')"
        class="flex items-center gap-2.5 w-full rounded-xl px-3 py-2.5 text-sm font-medium transition-all text-left ${active ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-50"}"
      >
        <span class="flex-none inline-flex h-6 w-6 items-center justify-center rounded-lg text-xs ${active ? "bg-white/20" : "bg-slate-100"}">${escHtml(meta.icon)}</span>
        <span class="flex-1 truncate">${escHtml(String(item.label || key))}</span>
        <span class="text-xs ${active ? "text-white/50" : "text-slate-400"}">${Number(item.count || 0)}</span>
      </button>
    `;
  }).join("");
}

function renderCommunityForumSortFilters() {
  const container = document.getElementById("forumSortFilters");
  if (!container) return;
  const options = [
    { key: "hot", label: "最热" },
    { key: "latest", label: "最新" },
    { key: "unanswered", label: "待回复" }
  ];
  container.innerHTML = options.map((item) => `
    <button
      type="button"
      onclick="setCommunityForumSort('${item.key}')"
      class="rounded-lg border px-3 py-1.5 text-xs font-semibold transition ${communityForumState.sort === item.key ? "border-amber-400 bg-amber-400 text-white" : "border-slate-200 bg-white text-slate-600 hover:border-amber-300 hover:text-amber-700"}"
    >
      ${item.label}
    </button>
  `).join("");
}

function renderCommunityForumHotTags() {
  const container = document.getElementById("forumHotTags");
  if (!container) return;
  if (!communityForumState.hotTags.length) {
    container.innerHTML = '<p class="text-xs text-slate-400">发帖后自动生成热议标签</p>';
    return;
  }
  container.innerHTML = communityForumState.hotTags.map((item) => {
    const tagText = String(item.tag || "");
    const safeTag = JSON.stringify(tagText);
    return `
      <button
        type="button"
        onclick="applyCommunityForumTag(${safeTag})"
        class="rounded-full bg-amber-50 border border-amber-100 px-2.5 py-1 text-[11px] font-medium text-amber-700 transition hover:bg-amber-100"
      >
        #${escHtml(tagText)}<span class="ml-1 text-amber-400">${Number(item.count || 0)}</span>
      </button>
    `;
  }).join("");
}

function renderCommunityForumList() {
  const summaryEl = document.getElementById("forumListSummary");
  const listEl = document.getElementById("forumThreadList");
  if (!summaryEl || !listEl) return;
  if (communityForumState.loading && !communityForumState.loaded) {
    summaryEl.textContent = "正在加载讨论内容...";
    listEl.innerHTML = [1, 2, 3].map(() => `
      <div class="bg-white rounded-2xl border border-slate-100 p-5 animate-pulse">
        <div class="h-3 bg-slate-100 rounded w-1/4 mb-4"></div>
        <div class="h-4 bg-slate-100 rounded w-3/4 mb-2"></div>
        <div class="h-3 bg-slate-100 rounded w-full mb-1"></div>
        <div class="h-3 bg-slate-100 rounded w-2/3"></div>
      </div>
    `).join("");
    return;
  }
  const posts = getCommunityForumFilteredPosts();
  const sortLabel = { hot: "最热", latest: "最新", unanswered: "待回复" }[communityForumState.sort] || "最热";
  summaryEl.textContent = `${posts.length} 条讨论 · ${sortLabel}`;
  if (!posts.length) {
    listEl.innerHTML = `
      <div class="bg-white rounded-2xl border border-dashed border-slate-200 p-10 text-center">
        <p class="text-slate-400 text-sm">这个条件下还没有帖子</p>
        <button type="button" onclick="showForumView('compose')" class="mt-3 text-sm text-amber-600 hover:underline">发起第一条讨论</button>
      </div>
    `;
    return;
  }
  listEl.innerHTML = posts.map((post) => {
    const meta = getCommunityBoardMeta(post.board);
    const excerpt = String(post.content || "").length > 100
      ? `${String(post.content || "").slice(0, 100)}...`
      : String(post.content || "");
    const tags = (post.tags || []).slice(0, 3);
    const isSystem = post.author?.username === "system";
    const cardClass = isSystem
      ? "block w-full rounded-2xl shadow-md p-5 text-left transition hover:shadow-lg group relative overflow-hidden"
      : "block w-full bg-white rounded-2xl border border-slate-100 shadow-sm p-5 text-left transition hover:border-amber-200 hover:shadow-md group";
    const cardStyle = isSystem
      ? "background:#fffdf7; border:1.5px solid transparent; background-clip:padding-box; box-shadow:0 0 0 1.5px rgba(251,191,36,0.55), 0 4px 16px rgba(251,191,36,0.13);"
      : "";
    const authorHtml = isSystem
      ? `<span class="inline-flex items-center gap-1 font-semibold" style="color:#b45309;">
           <span style="display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px;border-radius:50%;background:linear-gradient(135deg,#f59e0b,#d97706);flex-shrink:0;">
             <svg width="9" height="9" viewBox="0 0 10 10" fill="none"><path d="M5 1l1.12 2.27L9 3.635l-2 1.95.472 2.75L5 7.01 2.528 8.335 3 5.585 1 3.635l2.88-.365L5 1z" fill="#fff"/></svg>
           </span>
           官方发起
         </span>`
      : `<span class="font-medium text-slate-600">${escHtml(post.author?.display_name || "匿名同学")}</span>`;
    return `
      <button
        type="button"
        onclick="selectCommunityPost('${post.id}')"
        class="${cardClass}"
        ${cardStyle ? `style="${cardStyle}"` : ""}
      >
        ${isSystem ? `<div style="position:absolute;top:0;left:0;right:0;height:2.5px;background:linear-gradient(90deg,#f59e0b,#fbbf24,#fde68a,#fbbf24,#f59e0b);opacity:0.9;"></div>` : ""}
        <div class="flex items-start gap-3">
          <div class="flex-1 min-w-0">
            <div class="flex flex-wrap items-center gap-1.5 mb-2">
              <span class="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold ${meta.chip}">
                <span class="text-[10px]">${escHtml(meta.icon)}</span>${escHtml(meta.label)}
              </span>
              ${post.pinned ? '<span class="rounded-full bg-slate-900 px-2 py-0.5 text-[11px] font-semibold text-white">置顶</span>' : ""}
              ${Number(post.reply_count || 0) === 0 ? '<span class="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-700">待回复</span>' : ""}
            </div>
            <h4 class="text-base font-bold text-slate-900 leading-snug group-hover:text-amber-700 transition-colors">${escHtml(post.title || "")}</h4>
            <p class="mt-1.5 text-sm text-slate-500 leading-relaxed line-clamp-2">${escHtml(excerpt)}</p>
            ${tags.length ? `<div class="mt-2 flex flex-wrap gap-1">${tags.map((tag) => `<span class="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-500">#${escHtml(tag)}</span>`).join("")}</div>` : ""}
          </div>
          <div class="flex-none text-right space-y-1.5 text-xs text-slate-400 pl-2 min-w-[3rem]">
            <div class="font-medium">${Number(post.reply_count || 0)}<span class="block text-[10px] font-normal">回复</span></div>
            <div>${Number(post.likes || 0)}<span class="block text-[10px]">赞</span></div>
          </div>
        </div>
        <div class="mt-3 flex items-center justify-between gap-2 text-xs text-slate-400 border-t ${isSystem ? "border-amber-100" : "border-slate-50"} pt-3">
          <div class="flex items-center gap-2">
            ${authorHtml}
            <span>·</span>
            <span>${formatRelativeTimeCN(post.updated_at || post.created_at)}</span>
            <span>·</span>
            <span>${Number(post.views || 0)} 浏览</span>
          </div>
          <button
            type="button"
            onclick="event.stopPropagation(); toggleCommunityPostLike('${post.id}')"
            class="flex items-center gap-1 rounded-full px-2.5 py-1 border transition ${post.liked ? 'border-rose-200 bg-rose-50 text-rose-500' : 'border-slate-200 bg-white text-slate-400 hover:border-rose-200 hover:text-rose-500'}"
          >
            ${post.liked ? "❤️" : "🤍"} <span>${Number(post.likes || 0)}</span>
          </button>
        </div>
      </button>
    `;
  }).join("");
}

function renderCommunityForumDetail() {
  const container = document.getElementById("forumThreadDetail");
  const badge = document.getElementById("forumDetailBadge");
  if (!container || !badge) return;
  const post = getCommunityForumPostById(communityForumState.selectedPostId);
  if (!post) {
    badge.textContent = "分区";
    badge.className = "text-xs font-semibold px-2.5 py-1 rounded-full bg-slate-100 text-slate-600";
    container.innerHTML = "";
    return;
  }
  const meta = getCommunityBoardMeta(post.board);
  badge.textContent = meta.label;
  badge.className = `text-xs font-semibold px-2.5 py-1 rounded-full border ${meta.chip}`;
  const replies = Array.isArray(post.replies) ? post.replies : [];
  const replyHtml = replies.length
    ? replies.map((item, idx) => `
        <div class="flex gap-3">
          <div class="flex-none w-7 h-7 rounded-full bg-slate-100 flex items-center justify-center text-xs font-bold text-slate-500">${idx + 1}</div>
          <div class="flex-1 min-w-0 pb-4 ${idx < replies.length - 1 ? "border-b border-slate-100" : ""}">
            <div class="flex flex-wrap items-center gap-2 text-xs text-slate-500 mb-1.5">
              <span class="font-semibold text-slate-700">${escHtml(item.author?.display_name || "匿名同学")}</span>
              <span>·</span>
              <span>${formatRelativeTimeCN(item.created_at)}</span>
            </div>
            <p class="text-sm text-slate-700 leading-relaxed">${escHtml(item.content || "")}</p>
          </div>
        </div>
      `).join("")
    : '<p class="text-sm text-slate-400 text-center py-8">还没有回复，来第一个发言吧</p>';
  container.innerHTML = `
    <div>
      <div class="flex flex-wrap items-start justify-between gap-3 mb-4">
        <h4 class="text-xl font-bold text-slate-900 leading-snug flex-1">${escHtml(post.title || "")}</h4>
        <button
          type="button"
          onclick="toggleCommunityPostLike('${post.id}')"
          class="flex-none inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 border text-xs font-semibold transition ${post.liked ? "border-rose-200 bg-rose-50 text-rose-600" : "border-slate-200 bg-white text-slate-500 hover:border-rose-200 hover:text-rose-600"}"
        >
          ${post.liked ? "❤️" : "🤍"} ${Number(post.likes || 0)}
        </button>
      </div>
      <div class="flex flex-wrap items-center gap-2 text-xs text-slate-500 mb-4">
        <span class="font-medium text-slate-700">${escHtml(post.author?.display_name || "匿名同学")}</span>
        <span>·</span>
        <span>${formatRelativeTimeCN(post.created_at)}</span>
        <span>·</span>
        <span>${Number(post.views || 0)} 浏览</span>
        <span>·</span>
        <span>${Number(post.reply_count || 0)} 回复</span>
      </div>
      ${(post.tags || []).length ? `
        <div class="flex flex-wrap gap-1.5 mb-4">
          ${(post.tags || []).map((tag) => {
            const safeTag = JSON.stringify(String(tag || ""));
            return `<button type="button" onclick="applyCommunityForumTag(${safeTag})" class="rounded-full bg-slate-100 hover:bg-amber-100 px-2.5 py-1 text-xs text-slate-500 hover:text-amber-700 transition">#${escHtml(tag)}</button>`;
          }).join("")}
        </div>` : ""}
      <div class="bg-slate-50 rounded-xl border border-slate-100 px-5 py-4 text-sm leading-7 text-slate-700 whitespace-pre-line mb-6">${escHtml(post.content || "")}</div>
      <div class="mb-4 flex items-center justify-between">
        <h5 class="text-sm font-bold text-slate-700">回复 <span class="text-slate-400 font-normal ml-1">${replies.length}</span></h5>
        <span class="text-xs text-slate-400">最近更新：${formatRelativeTimeCN(post.last_reply_at || post.updated_at || post.created_at)}</span>
      </div>
      <div class="space-y-1 mb-6">${replyHtml}</div>
      <div class="border-t border-slate-100 pt-5">
        <label for="forumReplyInput" class="block text-sm font-medium text-slate-700 mb-2">写回复</label>
        <textarea id="forumReplyInput" rows="4" maxlength="1200"
          placeholder="比如：你目前最缺的是哪一部分、已经投了哪些岗位、卡在什么反馈上？"
          class="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm leading-6 resize-none focus:outline-none focus:ring-2 focus:ring-emerald-200 focus:border-emerald-300 transition"></textarea>
        <div class="mt-3 flex items-center justify-end">
          <button type="button" onclick="submitCommunityReply('${post.id}')"
            class="px-5 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-semibold transition">
            发送回复
          </button>
        </div>
      </div>
    </div>
  `;
}

function renderCommunityForum() {
  const threadCount = document.getElementById("forumThreadCount");
  const todayCount = document.getElementById("forumTodayCount");
  const activeUsers = document.getElementById("forumActiveUsers");
  const unansweredCount = document.getElementById("forumUnansweredCount");
  if (threadCount) threadCount.textContent = String(Number(communityForumState.stats?.threads || 0));
  if (todayCount) todayCount.textContent = String(Number(communityForumState.stats?.today_posts || 0));
  if (activeUsers) activeUsers.textContent = String(Number(communityForumState.stats?.active_users || 0));
  if (unansweredCount) unansweredCount.textContent = String(Number(communityForumState.stats?.unanswered || 0));
  renderCommunityForumBoardFilters();
  renderCommunityForumSortFilters();
  renderCommunityForumHotTags();
  renderCommunityForumList();
  if (communityForumState.view === "detail") {
    renderCommunityForumDetail();
  }
}

async function ensureCommunityForumLoaded(force = false) {
  if (communityForumState.loading) return;
  if (!force && communityForumState.loaded) {
    renderCommunityForum();
    return;
  }
  communityForumState.loading = true;
  renderCommunityForum();
  try {
    const payload = await requestJson("/api/community-feed");
    applyCommunityForumFeed(payload);
    communityForumState.loaded = true;
    renderCommunityForum();
  } catch (error) {
    showToast("论坛加载失败", error.message, "warning", 2200);
  } finally {
    communityForumState.loading = false;
    renderCommunityForum();
  }
}

function setCommunityForumBoard(board) {
  communityForumState.board = String(board || "all");
  showForumView("list");
  renderCommunityForum();
}

function setCommunityForumSort(sort) {
  communityForumState.sort = String(sort || "hot");
  renderCommunityForum();
}

function applyCommunityForumTag(tag) {
  const input = document.getElementById("forumSearchInput");
  const value = String(tag || "").trim();
  communityForumState.query = value;
  if (input) input.value = value;
  showForumView("list");
  renderCommunityForum();
}

async function selectCommunityPost(postId, options = {}) {
  const normalizedId = String(postId || "").trim();
  if (!normalizedId) return;
  communityForumState.selectedPostId = normalizedId;
  showForumView("detail");
  renderCommunityForumDetail();
  if (options.trackView === false || communityForumState.viewedIds[normalizedId]) return;
  communityForumState.viewedIds[normalizedId] = true;
  try {
    const payload = await requestJson(`/api/community-feed/posts/${encodeURIComponent(normalizedId)}/view`, {
      method: "POST"
    });
    if (payload?.post) {
      upsertCommunityForumPost(payload.post);
      renderCommunityForumDetail();
    }
  } catch (error) {
    console.warn("community forum view update failed", error);
  }
}

async function submitCommunityPost() {
  const titleEl = document.getElementById("forumPostTitle");
  const boardEl = document.getElementById("forumPostBoard");
  const tagsEl = document.getElementById("forumPostTags");
  const contentEl = document.getElementById("forumPostContent");
  const title = String(titleEl?.value || "").trim();
  const board = String(boardEl?.value || "面经互助").trim();
  const tags = String(tagsEl?.value || "").trim();
  const content = String(contentEl?.value || "").trim();
  if (title.length < 4) {
    showToast("标题太短", "至少写 4 个字，让大家知道你想讨论什么。", "warning", 1800);
    return;
  }
  if (content.length < 10) {
    showToast("正文太短", "再补充一点背景和你的卡点，回复会更有针对性。", "warning", 1800);
    return;
  }
  try {
    const payload = await requestJson("/api/community-feed/posts", {
      method: "POST",
      body: { title, board, tags, content }
    });
    applyCommunityForumFeed(payload?.feed || payload);
    if (payload?.post?.id) {
      communityForumState.selectedPostId = payload.post.id;
      communityForumState.viewedIds[payload.post.id] = true;
    }
    if (titleEl) titleEl.value = "";
    if (tagsEl) tagsEl.value = "";
    if (contentEl) contentEl.value = "";
    showForumView("detail");
    renderCommunityForumDetail();
    addLiveActivity(`Community post published: ${title}`);
    appState.notifications = Math.min(9, appState.notifications + 1);
    updateNotificationCount();
    showToast("发帖成功", "新的讨论已经进入 Offer 茶水间。", "success", 1800);
  } catch (error) {
    showToast("发帖失败", error.message, "error", 2200);
  }
}

async function submitCommunityReply(postId) {
  const replyEl = document.getElementById("forumReplyInput");
  const content = String(replyEl?.value || "").trim();
  if (content.length < 4) {
    showToast("回复太短", "至少补充一句完整建议再发出去。", "warning", 1800);
    return;
  }
  try {
    const payload = await requestJson(`/api/community-feed/posts/${encodeURIComponent(postId)}/reply`, {
      method: "POST",
      body: { content }
    });
    applyCommunityForumFeed(payload?.feed || payload);
    if (payload?.post?.id) {
      communityForumState.selectedPostId = payload.post.id;
      communityForumState.viewedIds[payload.post.id] = true;
    }
    if (replyEl) replyEl.value = "";
    renderCommunityForumDetail();
    addLiveActivity("Community reply sent");
    appState.notifications = Math.min(9, appState.notifications + 1);
    updateNotificationCount();
    showToast("回复已发送", "你的建议已经出现在帖子详情里。", "success", 1800);
  } catch (error) {
    showToast("回复失败", error.message, "error", 2200);
  }
}

async function toggleCommunityPostLike(postId) {
  try {
    const payload = await requestJson(`/api/community-feed/posts/${encodeURIComponent(postId)}/like`, {
      method: "POST"
    });
    if (payload?.post) {
      upsertCommunityForumPost(payload.post);
      // 同时刷新列表卡片（点赞数/状态）和详情视图
      renderCommunityForumList();
      if (communityForumState.view === "detail") {
        renderCommunityForumDetail();
      }
    }
  } catch (error) {
    showToast("点赞失败", error.message, "warning", 2000);
  }
}

function scrollToForumComposer() {
  showForumView("compose");
  const target = document.getElementById("forumComposerCard");
  if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
}

function initCommunityForumEvents() {
  const searchInput = document.getElementById("forumSearchInput");
  if (searchInput && !searchInput.dataset.boundForumInput) {
    searchInput.addEventListener("input", (event) => {
      communityForumState.query = String(event.target?.value || "").trim();
      renderCommunityForum();
    });
    searchInput.dataset.boundForumInput = "1";
  }
  renderCommunityForum();
}


// ── 设置面板（头像点击） ────────────────────────────────────────────────────────

let _settingsPanelOpen = false;
let _settingsOutsideListener = null;
let _cachedAvailableModels = [];   // 全局缓存：拉取到的模型列表，切换板块后不需重新获取
let _pickerModelsCache = {};        // provider_id -> { models: [], ts: number }

function getProviderBrandMeta(provider) {
  const text = `${provider?.name || ""} ${provider?.base_url || ""}`.toLowerCase();
  if (text.includes("deepseek")) return { icon: "🐋", company: "DeepSeek" };
  if (text.includes("openrouter")) return { icon: "🧭", company: "OpenRouter" };
  if (text.includes("openai")) return { icon: "🌀", company: "OpenAI" };
  if (text.includes("anthropic") || text.includes("claude")) return { icon: "🧠", company: "Anthropic" };
  if (text.includes("google") || text.includes("gemini")) return { icon: "🔷", company: "Google" };
  if (text.includes("qwen") || text.includes("dashscope") || text.includes("aliyun") || text.includes("alibaba")) return { icon: "☁️", company: "Qwen" };
  if (text.includes("zhipu") || text.includes("glm")) return { icon: "🟣", company: "智谱" };
  if (text.includes("moonshot") || text.includes("kimi")) return { icon: "🌙", company: "Moonshot" };
  if (text.includes("groq")) return { icon: "⚡", company: "Groq" };
  return { icon: "🔌", company: "API" };
}

// ══════════════════════════════════════════════════════════════════════════
//  设置面板 — 多 Provider 管理
// ══════════════════════════════════════════════════════════════════════════

function toggleSettingsPanel(event) {
  if (event) event.stopPropagation();
  if (_settingsPanelOpen) { closeSettingsPanel(); } else { openSettingsPanel(); }
}

function openSettingsPanel() {
  if (!isSuperAdminUser()) {
    showToast("已使用管理员配置", "普通用户无需配置 API，可直接在功能区选择模型。", "info", 1800);
    return;
  }
  const panel = document.getElementById("settingsPanel");
  if (!panel) return;
  panel.classList.remove("hidden");
  _settingsPanelOpen = true;
  loadSettingsPanelData();
  setTimeout(() => {
    _settingsOutsideListener = (e) => { if (!panel.contains(e.target)) closeSettingsPanel(); };
    document.addEventListener("click", _settingsOutsideListener);
  }, 30);
}

function closeSettingsPanel() {
  const panel = document.getElementById("settingsPanel");
  if (panel) panel.classList.add("hidden");
  _settingsPanelOpen = false;
  closeAddProviderForm();
  if (_settingsOutsideListener) {
    document.removeEventListener("click", _settingsOutsideListener);
    _settingsOutsideListener = null;
  }
}

async function loadSettingsPanelData() {
  const user = getCurrentUser();
  const labelEl = document.getElementById("settingsPanelUserLabel");
  if (labelEl && user) {
    labelEl.textContent = `${user.display_name || user.username}  ·  ${user.role === "super_admin" ? "系统管理员" : "普通用户"}`;
  }

  const isAdmin = isSuperAdminUser();
  const addBtn = document.getElementById("settingsAdminAddBtn");
  if (addBtn) addBtn.classList.toggle("hidden", !isAdmin);

  const listEl = document.getElementById("settingsProviderList");
  if (listEl) listEl.innerHTML = `<p class="text-xs text-gray-400 text-center py-3">正在加载…</p>`;

  try {
    const data = await requestJson("/api/llm-providers");
    const providers = data.providers || [];
    const selection = data.selection || {};
    _renderProviderList(providers, selection, isAdmin);
  } catch (err) {
    if (listEl) listEl.innerHTML = `<p class="text-xs text-red-400 text-center py-3">加载失败：${escHtml(err.message)}</p>`;
  }
}

function _renderProviderList(providers, selection, isAdmin) {
  const listEl = document.getElementById("settingsProviderList");
  if (!listEl) return;
  if (!providers.length) {
    listEl.innerHTML = `<p class="text-xs text-gray-400 text-center py-4">${isAdmin ? "尚未添加任何 API，点击右上角＋添加" : "系统管理员尚未配置 API"}</p>`;
    return;
  }
  listEl.innerHTML = providers.map(p => {
    const brand = getProviderBrandMeta(p);
    const isSel = selection.provider_id === p.id;
    const badgeCls = isSel ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-500";
    const badge = isSel ? `<span class="text-[10px] px-1.5 py-0.5 rounded-full ${badgeCls}">✓ 已选</span>` : "";
    const deleteBtn = isAdmin ? `<button onclick="deleteProvider('${escHtml(p.id)}')" class="text-[10px] text-red-400 hover:text-red-600 transition-all ml-1" title="删除">✕</button>` : "";
    return `
      <div class="flex items-center gap-2 p-2.5 rounded-xl border ${isSel ? "border-green-200 bg-green-50" : "border-gray-100 bg-gray-50"} transition-all">
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-1.5 flex-wrap">
            <span class="text-xs font-semibold text-gray-800 truncate">${escHtml(brand.icon)} ${escHtml(p.name)}</span>
            <span class="text-[10px] px-1.5 py-0.5 rounded-full bg-slate-100 text-slate-600">${escHtml(brand.company)}</span>
            ${badge}
          </div>
          <p class="text-[10px] text-gray-400 truncate mt-0.5">${escHtml(p.base_url)}</p>
          <p class="text-[10px] text-gray-400">${escHtml(p.api_key_masked || "未配置")}</p>
        </div>
        <div class="flex-shrink-0">${deleteBtn}</div>
      </div>`;
  }).join("");
}

function openAddProviderForm() {
  const form = document.getElementById("settingsAddProviderForm");
  if (form) { form.classList.remove("hidden"); document.getElementById("spfName")?.focus(); }
}
function closeAddProviderForm() {
  const form = document.getElementById("settingsAddProviderForm");
  if (form) {
    form.classList.add("hidden");
    ["spfName","spfBaseUrl","spfApiKey"].forEach(id => { const el = document.getElementById(id); if (el) el.value = ""; });
  }
}

async function submitAddProvider() {
  const name = (document.getElementById("spfName")?.value || "").trim();
  const base_url = (document.getElementById("spfBaseUrl")?.value || "").trim();
  const api_key = (document.getElementById("spfApiKey")?.value || "").trim();
  if (!base_url || !api_key) { showToast("填写不完整", "请填写 Base URL 和 API Key", "warning", 2000); return; }
  try {
    await requestJson("/api/llm-providers", { method: "POST", body: { name: name || "未命名", base_url, api_key } });
    _pickerModelsCache = {};
    showToast("API 已添加", name || "未命名", "success", 1600);
    closeAddProviderForm();
    await loadSettingsPanelData();
  } catch (err) { showToast("添加失败", err.message, "error", 2400); }
}

async function deleteProvider(providerId) {
  if (!confirm("确认删除此 API 配置？")) return;
  try {
    await requestJson(`/api/llm-providers/${providerId}`, { method: "DELETE" });
    _pickerModelsCache = {};
    showToast("已删除", "", "success", 1400);
    await loadSettingsPanelData();
  } catch (err) { showToast("删除失败", err.message, "error", 2400); }
}

// ══════════════════════════════════════════════════════════════════════════
//  模型选择器弹窗（使用点触发）
// ══════════════════════════════════════════════════════════════════════════

let _mpCallback = null;   // 确认后回调

async function openModelPicker(onConfirm) {
  _mpCallback = onConfirm || null;
  const overlay = document.getElementById("modelPickerOverlay");
  if (!overlay) return;
  overlay.classList.remove("hidden");

  // 初始化 Provider 下拉
  const provSel = document.getElementById("mpProviderSelect");
  const modelSel = document.getElementById("mpModelSelect");
  const hintEl = document.getElementById("mpCurrentHint");
  if (provSel) provSel.innerHTML = `<option value="">加载中…</option>`;
  if (modelSel) modelSel.innerHTML = `<option value="">-- 请先选择 API --</option>`;

  try {
    // 使用更轻量的 providers 接口，避免在高频状态写入时被用户态读取拖慢。
    const data = await requestJson("/api/llm-providers");
    const providers = data.providers || [];
    const selection = data.selection || {};

    if (!providers.length) {
      if (provSel) provSel.innerHTML = `<option value="">-- 系统管理员尚未配置 API --</option>`;
      if (hintEl) hintEl.textContent = "请让系统管理员先在「API 配置」中添加 API";
      return;
    }

    if (provSel) {
      provSel.innerHTML = providers.map(p => {
        const brand = getProviderBrandMeta(p);
        return `<option value="${escHtml(p.id)}" ${p.id === selection.provider_id ? "selected" : ""}>${escHtml(brand.icon)} ${escHtml(p.name)} (${escHtml(brand.company)})</option>`;
      }).join("");
    }

    if (hintEl && selection.provider_id) {
      const prov = providers.find(p => p.id === selection.provider_id);
      if (prov) {
        const brand = getProviderBrandMeta(prov);
        hintEl.textContent = `当前：${brand.icon} ${prov.name} · ${selection.model || "未选模型"}`;
      } else {
        hintEl.textContent = "";
      }
    }

    // 若已有已选 provider，自动加载其模型
    if (selection.provider_id) {
      await fetchPickerModels(selection.model, false);
    }
  } catch (err) {
    if (provSel) provSel.innerHTML = `<option value="">加载失败：${escHtml(err.message)}</option>`;
  }
}

function closeModelPicker() {
  const overlay = document.getElementById("modelPickerOverlay");
  if (overlay) overlay.classList.add("hidden");
  _mpCallback = null;
}

async function onPickerProviderChange() {
  const provSel = document.getElementById("mpProviderSelect");
  const modelSel = document.getElementById("mpModelSelect");
  const providerId = (provSel?.value || "").trim();
  if (providerId && _pickerModelsCache[providerId]?.models?.length) {
    const models = _pickerModelsCache[providerId].models;
    if (modelSel) {
      modelSel.innerHTML = models.map((m) => `<option value="${escHtml(m)}">${escHtml(m)}</option>`).join("");
    }
    const btn = document.getElementById("mpFetchBtn");
    if (btn) btn.textContent = `✓ 缓存 ${models.length} 个`;
    return;
  }
  if (modelSel) modelSel.innerHTML = `<option value="">-- 点击「获取列表」加载模型 --</option>`;
}

async function fetchPickerModels(preselect, forceRefresh = false) {
  const provSel = document.getElementById("mpProviderSelect");
  const modelSel = document.getElementById("mpModelSelect");
  const btn = document.getElementById("mpFetchBtn");
  const providerId = provSel?.value;
  if (!providerId) { showToast("请先选择 API", "", "warning", 1800); return; }
  if (!forceRefresh && _pickerModelsCache[providerId]?.models?.length) {
    const models = _pickerModelsCache[providerId].models;
    if (modelSel) {
      modelSel.innerHTML = models.map(m =>
        `<option value="${escHtml(m)}" ${m === preselect ? "selected" : ""}>${escHtml(m)}</option>`
      ).join("");
    }
    if (btn) btn.textContent = `✓ 缓存 ${models.length} 个`;
    return;
  }
  if (btn) btn.textContent = "⏳ 获取中…";
  try {
    const data = await requestJson(`/api/llm-providers/${providerId}/models`);
    const models = data.models || [];
    if (models.length) {
      _pickerModelsCache[providerId] = { models: [...models], ts: Date.now() };
      if (modelSel) {
        modelSel.innerHTML = models.map(m =>
          `<option value="${escHtml(m)}" ${m === preselect ? "selected" : ""}>${escHtml(m)}</option>`
        ).join("");
      }
      if (btn) btn.textContent = `✓ ${models.length} 个`;
    } else {
      showToast("获取模型", data.message || "未获取到模型列表", "warning", 2400);
      if (btn) btn.textContent = "🔄 获取列表";
    }
  } catch (err) {
    showToast("获取失败", err.message, "error", 2400);
    if (btn) btn.textContent = "🔄 获取列表";
  }
}

async function confirmModelPicker() {
  const provSel = document.getElementById("mpProviderSelect");
  const modelSel = document.getElementById("mpModelSelect");
  const providerId = (provSel?.value || "").trim();
  const model = (modelSel?.value || "").trim();
  if (!providerId) { showToast("请选择 API", "", "warning", 1800); return; }
  if (!model) { showToast("请选择模型", "先点击「获取列表」再选择", "warning", 2000); return; }
  try {
    const data = await requestJson("/api/llm-selection", {
      method: "PUT", body: { provider_id: providerId, model }
    });
    await fetchActiveLlmRuntimeConfig(true);
    showToast("已选择", data.message || `${model}`, "success", 1600);
    closeModelPicker();
    if (typeof _mpCallback === "function") _mpCallback({ provider_id: providerId, model });
    _cachedAvailableModels = [];
    updateCareerInterviewConfigStatus();
    void updateProfileFlowModelStatus(true);
    if (typeof window.assessmentHubUpdateConfigStatus === "function") window.assessmentHubUpdateConfigStatus();
  } catch (err) { showToast("保存失败", err.message, "error", 2400); }
}

// 兼容旧代码调用
function saveSettingsAdmin() { openAddProviderForm(); }
function saveSettingsModel() { openModelPicker(); }
function fetchSettingsModels() { fetchPickerModels(undefined, true); }

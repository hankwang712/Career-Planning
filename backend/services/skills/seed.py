"""人工整理的技能同义词与过滤规则，是从招聘数据自动生成技能表时的补充。

招聘标签只能告诉我们“哪些写法常见”，不知道 Golang 和 Go 是同一个东西、K8s 就是 Kubernetes，
也分不清“五险一金”“不接受居家办公”不是技能。这些靠这里的规则补上。
"""

# 每组第一项是标准名称，其余都是别名；category 用于展示与筛选。
ALIAS_GROUPS = [
    ("tech", ["Go", "Golang", "Go语言"]),
    ("tech", ["JavaScript", "JS", "ECMAScript", "ES6"]),
    ("tech", ["TypeScript", "TS"]),
    ("tech", ["Node.js", "NodeJS", "Node"]),
    ("tech", ["Vue", "Vue.js", "Vue2", "Vue3"]),
    ("tech", ["React", "React.js", "ReactJS"]),
    ("tech", ["Kubernetes", "K8s"]),
    ("tech", ["Spring Boot", "SpringBoot"]),
    ("tech", ["Spring Cloud", "SpringCloud"]),
    ("tech", ["PostgreSQL", "Postgres", "PG"]),
    ("tech", ["SQL Server", "MSSQL"]),
    ("tech", ["Python", "Python3", "Python语言"]),
    ("tech", ["C++", "CPP", "C++语言"]),
    ("tech", ["C#", "CSharp"]),
    ("tech", ["HTML", "HTML5"]),
    ("tech", ["CSS", "CSS3"]),
    ("tech", ["Linux", "Linux开发/部署经验", "Linux系统"]),
    ("tech", ["Excel", "Microsoft Excel"]),
    ("tech", ["Office", "Office办公软件", "办公软件", "Microsoft Office"]),
    ("tech", ["PyTorch", "Torch"]),
    ("tech", ["TensorFlow", "TF"]),
    ("tech", ["Unity", "Unity3D"]),
    ("tech", ["Unreal Engine", "UE4", "UE5", "虚幻引擎"]),
    ("tech", ["Photoshop", "PS"]),
    ("tech", ["Git", "GitHub", "GitLab"]),
    ("tech", ["Shell", "Shell脚本", "Bash"]),
    ("ai", ["人工智能", "AI", "Artificial Intelligence"]),
    ("ai", ["机器学习", "Machine Learning", "ML", "机器学习算法"]),
    ("ai", ["深度学习", "Deep Learning", "DL"]),
    ("ai", ["自然语言处理", "NLP"]),
    ("ai", ["计算机视觉", "CV", "Computer Vision"]),
    ("ai", ["大模型", "LLM", "大语言模型", "大型语言模型"]),
    ("ai", ["强化学习", "Reinforcement Learning", "RL"]),
    ("ai", ["推荐算法", "推荐系统", "搜索推荐"]),
    ("ai", ["AI Agent", "Agent", "智能体"]),
    ("ai", ["RAG", "检索增强生成"]),
    ("ai", ["多模态", "多模态算法"]),
    ("data", ["数据分析", "Data Analysis"]),
    ("data", ["数据挖掘", "Data Mining"]),
    ("data", ["数据可视化", "Tableau", "Power BI", "PowerBI"]),
    ("data", ["SQL", "SQL语言"]),
    ("data", ["Spark", "Apache Spark", "PySpark"]),
    ("data", ["Hadoop", "HDFS"]),
    ("engineering", ["微服务", "微服务架构", "微服务经验"]),
    ("engineering", ["分布式", "分布式系统", "分布式技术", "分布式经验"]),
    ("engineering", ["前端开发", "前端", "Web前端"]),
    ("engineering", ["后端开发", "后端", "服务端开发"]),
    ("engineering", ["全栈开发", "全栈", "全栈项目经验"]),
    ("engineering", ["自动化测试", "自动化测试经验", "测试自动化"]),
    ("engineering", ["性能测试", "压力测试", "压测"]),
    ("engineering", ["功能测试", "黑盒测试"]),
    ("engineering", ["嵌入式开发", "嵌入式", "嵌入式软件", "嵌入式软件经验"]),
    ("engineering", ["云计算", "云计算经验", "云原生"]),
    ("engineering", ["网络爬虫", "爬虫", "爬虫经验"]),
    ("engineering", ["数据结构", "数据结构与算法"]),
    ("engineering", ["架构设计", "系统架构", "架构设计经验"]),
    ("engineering", ["运维开发", "DevOps", "运维开发经验"]),
    ("product", ["产品规划", "产品策划"]),
    ("product", ["需求分析", "需求调研"]),
    ("product", ["用户研究", "用户调研"]),
    ("product", ["项目管理", "PMP"]),
    ("business", ["市场营销", "营销"]),
    ("business", ["新媒体运营", "社交媒体运营"]),
    ("business", ["电话销售", "电销"]),
    ("soft", ["沟通能力", "沟通", "沟通交流", "沟通表达", "沟通表达能力", "沟通力", "沟通能力强", "表达能力", "良好的沟通能力"]),
    ("soft", ["团队协作", "团队合作", "协作能力", "沟通协作能力", "跨部门协作", "跨团队协作", "团队协作意识", "跨团队合作", "跨部门合作", "沟通协调", "沟通协调能力"]),
    ("soft", ["学习能力", "快速学习", "学习能力强"]),
    ("soft", ["逻辑思维", "逻辑思维能力", "逻辑分析能力"]),
    ("soft", ["问题分析能力", "分析问题", "解决问题能力", "问题解决能力"]),
    ("soft", ["抗压能力", "抗压", "承压能力"]),
    ("soft", ["团队管理", "团队管理经验", "带团队", "团队领导"]),
    ("soft", ["英语", "英语能力", "英语读写", "英文"]),
]

# 行业/业务领域：作为技能保留（“有金融行业经验”是真实要求），但不在长文本里扫描，因为岗位描述里到处出现。
DOMAIN_TERMS = ["房地产", "金融", "教育", "游戏", "电商", "电商平台", "新能源", "互联网", "汽车", "医疗", "医药", "智能硬件",
                "芯片半导体", "半导体", "生活服务", "短视频", "社交媒体", "软件服务", "物流", "零售", "广告", "制造业",
                "通信", "能源", "直播", "本地生活", "企业服务", "SaaS", "跨境电商", "银行", "保险", "证券"]

# 不是技能的招聘标签：工作形式、福利、学历专业、笼统分类。
NOISE_PATTERNS = [
    r"实习$", r"^全职$", r"^兼职$", r"居家", r"远程办公", r"出差", r"五险", r"一金", r"补贴", r"福利", r"双休", r"弹性",
    r"专业$", r"学历", r"本科", r"硕士", r"博士", r"应届", r"在校", r"^其他$", r"^不限$", r"包住", r"包吃", r"年终奖",
    r"^急招", r"^可转正", r"^周末", r"工作制", r"^\d", r"^[A-Za-z]$",
]

# 单独出现时太容易误伤的别名：只在完整匹配某条技能时使用，不用于在长文本里扫描。
AMBIGUOUS_IN_TEXT = {"go", "c", "r", "ts", "ml", "dl", "cv", "rl", "ps", "pg", "tf", "node", "agent", "前端", "后端",
                     "营销", "沟通", "抗压", "英文", "全栈", "嵌入式", "爬虫", "torch", "es6"}

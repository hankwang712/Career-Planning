# 智航生涯 · Career Planning

一个围绕职业探索、简历分析和求职规划开发的 Web 项目。

项目把测评、岗位数据、个人经历和 AI 分析放在同一个工作台里。用户可以先了解自己的兴趣与偏好，再查岗位、整理简历、比较职业方向，最后把选定的方向拆成具体的学习和求职安排。报告、测评记录和对话会保留下来，方便后续回看和调整。

[![智航生涯工作台](asserts/workspace.png)](asserts/workspace.png)

## 目前可以做什么

| 功能 | 具体内容 |
| --- | --- |
| 测评中心 | 提供 MBTI、霍兰德职业兴趣、深层 MBTI、老友记角色、情绪主导和 SBTI 六项测评，支持进度保存和历史结果查看；基础测评可对比最近两次结果。 |
| 岗位探索 | 按城市和条件浏览岗位，查看岗位详情、薪资分布和地域分布，也可以浏览项目收录的数据集。 |
| 简历分析 | 上传简历并提取文本，分析经历、技能与岗位要求之间的匹配情况，整理已有证据和需要补充的材料。支持 PDF、DOCX 等文档处理，并保留 OCR 识别能力。 |
| 职业规划报告 | 结合简历、目标方向和个人偏好生成报告，支持中途补充信息、确认方向、编辑润色、版本查看，以及 Word / PDF 导出。 |
| 行动与学习计划 | 根据学习阶段、目标方向和可投入时间安排近期任务，补充 1—3 个月、3—12 个月、1—3 年的成长路线；每项准备事项都有交付成果与验收标准。 |
| AI 生涯助手 | 围绕职业选择、简历、面试准备和学习计划进行对话，可结合当前工作台资料、已上传简历和历史记忆回答问题，也支持在聊天中提交图片。 |
| 资讯与社区 | 查看职业资讯和相关新闻，在社区发布求职经验、岗位讨论及回复。 |
| 个人中心与管理 | 管理测评记录、个人资料和报告；管理员可以管理账户及模型接口配置。另有职业画像海报生成功能。 |

测评结果用于提供探索线索；报告会结合简历和岗位材料继续分析，不会只凭一个性格类型决定职业方向。

| 岗位探索：浏览招聘样本与岗位要求 | 测评中心：选择测评并查看历史记录 |
| :---: | :---: |
| [![岗位探索页面](asserts/jobs.png)](asserts/jobs.png) | [![测评中心页面](asserts/assessments.png)](asserts/assessments.png) |

点击图片可查看原图。

## 报告是怎样生成的

报告生成使用 LangGraph 组织工作流，主要包括简历分析、岗位分析、招聘检索、职业决策和行动规划几个阶段。

系统先整理已有材料，分析候选方向；遇到需要补充的信息或需要用户做选择的地方，会暂停等待确认。用户确认目标和时间约束后，再继续生成行动计划。工作流状态保存在 SQLite 中，支持在确认后恢复执行。

正文包括个人画像、目标定位、就业市场、岗位适配、能力差距、成长路径、行动计划、动态评估和参考依据九个部分，另附执行摘要。低年级侧重方向探索和基础实践，高年级及研究生侧重项目、实习与求职准备。招聘样本只用于说明检索到的要求，不据此推算全市场招聘规模或薪资趋势；没有证据的结论会保留为未知。学习打卡记录节奏，任务需按实际成果单独确认完成。

报告也保存生成时使用的资料快照和版本，便于核对某个结论来自哪次输入。这里的 `experiments/news_advisor/` 已有部分代码被主站直接复用，并非完全独立的演示目录。

[![职业规划报告的多智能体协作流](asserts/agent-workflow.png)](asserts/agent-workflow.png)

## 技术栈

| 部分 | 使用的技术 |
| --- | --- |
| Web 后端 | Python、Flask、FastAPI、Uvicorn；Flask 负责主站页面和业务接口，FastAPI 提供聊天接口。 |
| 前端 | 原生 JavaScript、Jinja2 模板、Vite、Tailwind CSS、PostCSS；采用多个页面入口组织登录、工作台、个人中心和测评页面。 |
| AI 与工作流 | OpenAI Python SDK、兼容 OpenAI 的模型接口、LangChain、LangGraph、Pydantic。 |
| 主站存储 | SQLite，用于账户、用户状态、报告、对话和工作流检查点。 |
| 对话记忆 | Redis 缓存、Chroma 向量索引及独立的 embedding 模型配置。 |
| 岗位图谱 | LightRAG、PostgreSQL、pgvector，以及岗位事实库和证据校验逻辑，位于独立的研究模块中。 |
| 图表与交互 | ECharts、Chart.js、Fuse.js、GSAP。 |
| 文档处理 | PyMuPDF、pypdf、pdfplumber、python-docx、docx2pdf、Pillow、pytesseract。 |
| 资讯处理 | feedparser、trafilatura、readability-lxml、lxml。 |
| 工程与部署 | npm workspaces、GitHub Actions、Docker Compose、Nginx 配置及静态站点导出脚本。 |

## 本地运行

建议使用 **Python 3.12** 和 **Node.js 22**，与仓库的 CI 检查环境保持一致。以下命令都在项目根目录执行。

### 1. 安装依赖

建议先建立虚拟环境。以 Windows PowerShell 为例：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt
npm ci
```

macOS / Linux 使用 `python3 -m venv .venv` 创建环境，再执行 `source .venv/bin/activate`，其余安装命令相同。

`backend/requirements.txt` 会引用报告工作流所需的实验模块依赖，安装时请保留完整的项目目录。

### 2. 构建前端并启动

```bash
npm run build
npm start
```

启动后访问 <http://localhost:8080>。

`npm start` 默认运行后端并使用 `frontend/static/dist/` 中的构建资源。前端代码修改后，需要重新构建，或使用下面的热更新方式。

### 3. 前端热更新开发

在 PowerShell 中执行：

```powershell
$env:USE_VITE_DEV_SERVER = "true"
npm start
```

此时会同时启动后端和 Vite，仍从 `http://localhost:8080` 进入主站。Vite 默认使用 `5173` 端口。

如果只需要运行后端，也可以执行：

```bash
python backend/server.py
```

`npm run dev` 只启动 Vite，不会启动后端。

## 模型和服务配置

### 对话模型与管理员

页面浏览、普通测评等功能可以先使用；AI 对话、简历分析和报告生成需要配置可用的模型接口。

首次配置模型前，可以创建管理员账户：

```bash
python backend/scripts/create_admin.py
```

脚本会交互式询问邮箱和密码。登录后，在工作台的模型设置中配置接口地址、API Key 和模型名称，再选择要使用的模型。普通账户使用管理员提供的配置。

聊天助手也支持环境变量作为备用配置，格式见 [backend/chat.env.example](backend/chat.env.example)。工作台已选择的模型优先于备用配置。

### 常用环境变量

| 变量 | 用途 |
| --- | --- |
| `HOST` / `PORT` | 后端监听地址和端口，默认 `0.0.0.0:8080`。 |
| `APP_SECRET_KEY` / `SECRET_KEY` | 会话签名密钥。未设置时使用数据库中保存的密钥；部署时可显式指定。 |
| `USE_VITE_DEV_SERVER` | 设为 `true` 时，由启动脚本同时运行 Vite。 |
| `VITE_DEV_SERVER_URL` | 自定义 Vite 地址，设置后也会启用前端开发模式。 |
| `FRONTEND_ORIGIN` | 前后端分离部署时允许的前端来源。 |
| `SESSION_COOKIE_SECURE` | 在 HTTPS 部署中启用 Secure Cookie。 |
| `AI_CHAT_BASE_URL` / `AI_CHAT_API_KEY` / `AI_CHAT_MODEL` | 聊天助手的备用模型配置。 |
| `AI_EMBEDDING_BASE_URL` / `AI_EMBEDDING_API_KEY` / `AI_EMBEDDING_MODEL` | 对话记忆的向量检索模型。 |
| `CHAT_REDIS_URL` | 聊天缓存地址，默认 `redis://127.0.0.1:6380/0`。 |
| `TEXT_TO_IMAGE_API_KEY` / `TEXT_TO_IMAGE_BASE_URL` / `TEXT_TO_IMAGE_MODEL` | 文生图接口配置。`PROFILE_PORTRAIT_MODEL` 可单独指定职业画像模型。 |
| `NEWS_EMBEDDING_API_KEY` | 新闻语义检索使用的 embedding 接口密钥，见 [backend/news.env.example](backend/news.env.example)。 |
| `TESSERACT_CMD` | Tesseract 可执行文件路径，启用 OCR 时使用。 |

上表变量可设置在启动进程的环境中。`.env.example` 文件仅提供格式参考，不会自动加载。聊天模型和 embedding 配置还会读取 `experiments/.env`，进程环境变量优先。

### 按需启用的服务

- **Redis**：用于近期对话缓存。可以通过 `experiments/compose.memory.yml` 单独启动；缓存不可用时，聊天记录仍由 SQLite 保存。
- **对话语义记忆**：配置 embedding 模型后使用 Chroma 建立本地索引。未配置时，助手仍可使用已保存的记忆和工作台资料。
- **岗位图谱与检索**：需要本地 LightRAG 代码、PostgreSQL / pgvector 及 `artifacts/research/.env` 配置。LightRAG 目录、数据库和本地 JD 文本不随主仓库提交，克隆后需要另行准备。
- **OCR**：除 Python 依赖外，还需要安装 Tesseract 程序。
- **PDF 导出**：当前通过 `docx2pdf` 将 Word 文档转成 PDF；Windows 环境需要安装 Microsoft Word。DOCX 导出由 `python-docx` 生成。

根目录 `compose.yml` 组合了图谱数据库与 Redis 配置，启动前需要准备它引用的环境文件和已有数据卷。它不负责构建或启动主站应用。

## 项目目录

```text
career-agent/
├── backend/
│   ├── server.py                 # Web 服务入口
│   ├── requirements.txt          # 主站依赖
│   ├── services/                 # 账户、聊天、简历、报告、资讯等服务
│   └── scripts/                  # 管理员创建、数据处理与功能检查
├── frontend/
│   ├── src/                      # Vite 页面入口和样式
│   ├── templates/                # Jinja2 页面模板
│   ├── static/                   # 脚本、图片、图标及构建资源
│   └── scripts/                  # 资源同步、前端检查与静态导出
├── experiments/
│   ├── news_advisor/             # 主站复用的 Agent 与报告工作流
│   └── rag_benchmark/            # 检索评估实验
├── artifacts/research/           # 岗位图谱导入、查询与维护工具
├── data/
│   ├── jobs/                     # 城市岗位数据
│   ├── raw/                      # 原始数据及来源说明
│   ├── cleaned/                  # 清洗后的岗位与知识数据
│   ├── knowledge/                # 职业、行业分类资料
│   ├── onet/                     # O*NET 职业资料
│   ├── public/                   # 测评题库等前端可用数据
│   └── app_data/                 # 本地数据库、上传文件、报告和对话记录
├── deploy/                       # Nginx 配置与静态导出目录
├── .github/workflows/            # 自动检查
├── compose.yml                   # 图谱数据库与 Redis 的组合配置
├── package.json                  # 项目脚本和 npm workspace 配置
└── README.md
```

`data/app_data/`、环境配置、依赖目录和构建产物均由 `.gitignore` 排除。迁移运行环境时，需要单独备份数据库、用户上传文件和报告。

## 常用命令

| 命令 | 作用 |
| --- | --- |
| `npm run start:check` | 检查 Python 是否可用及后端语法。 |
| `npm run build` | 同步前端依赖资源并构建页面入口。 |
| `npm run check:report` | 检查报告工作流。 |
| `npm run check:report-development` | 检查成长路线、任务约束和学习计划转换。 |
| `npm run check:report-upload` | 检查报告上传相关逻辑。 |
| `npm run check:chat` | 检查聊天上下文、隐私、图片及前端消息渲染。 |
| `npm run export:static` | 将页面和静态资源导出到 `deploy/static-site/`。 |

静态导出后，登录、AI 对话和报告等功能仍需连接后端 API。仓库提供了 [Nginx 配置示例](deploy/nginx.static-api.conf)，可按实际域名和服务端口调整。

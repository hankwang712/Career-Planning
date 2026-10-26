# 智航生涯

智航生涯是一个面向职业规划场景的智能化 Web 系统，核心目标是把「测评 → 岗位探索 → 能力画像 → AI 匹配 → 规划报告 → 简历分析」串成一条连续的决策链路，而不是只做单点问答。


## 本地启动

### 前置条件

- Python 3.10+
- Node.js 18+
- （可选）Tesseract OCR — 启用简历 OCR 功能时需要
- （可选）Microsoft Word — Windows 下 DOCX/PDF 导出链路

### 第一步：安装依赖

```bash
# Python 依赖
pip install -r requirements.txt

# 前端依赖
npm install
```

### 第二步：启动项目

**最简方式（推荐验证业务逻辑）：**

```bash
python server.py
```

**使用项目脚本（同时启动 Flask + Vite 热更新）：**

```bash
npm start
```

**只做前端开发时（单独启动 Vite）：**

```bash
npm run dev
```

启动后默认访问：`http://localhost:8080`

### 第三步：构建前端（生产用）

```bash
npm run build
```

---

## 环境变量配置

系统支持"可运行"和"增强运行"两种状态，基础配置即可启动，AI 和图像功能需额外配置。

| 变量 | 说明 | 默认值 |
|---|---|---|
| `APP_SECRET_KEY` / `SECRET_KEY` | Flask Session 密钥（生产环境必改） | 内置开发值 |
| `HOST` | 服务监听地址 | `0.0.0.0` |
| `PORT` | 服务端口 | `8080` |
| `TEXT_TO_IMAGE_API_KEY` | 文生图 API 密钥（职业画像海报） | — |
| `TEXT_TO_IMAGE_BASE_URL` | 文生图服务地址 | `https://openrouter.ai/api/v1` |
| `TEXT_TO_IMAGE_MODEL` | 文生图模型 | `google/gemini-3.1-flash-image-preview` |
| `PROFILE_PORTRAIT_MODEL` | 职业画像生成模型 | `google/gemini-3-pro-image-preview` |
| `TESSERACT_CMD` | Tesseract 可执行文件路径 | 系统 PATH |
| `AUTO_OPEN_BROWSER` | 启动后自动打开浏览器 | `false` |
| `SESSION_COOKIE_SECURE` | 生产环境建议开启 | `false` |
| `FRONTEND_ORIGIN` / `VITE_DEV_SERVER_URL` | 前后端联调时使用 | — |

LLM 模型和接口地址也可在系统后台界面（管理员账号）中直接配置，无需重启服务。

---

## 目录结构

```
web/
├── server.py              # Flask 主应用（路由、业务逻辑）
├── requirements.txt       # Python 依赖
├── package.json           # 前端依赖与脚本
├── vite.config.mjs        # Vite 构建配置
│
├── frontend/              # 前端源码
│   └── src/
│       ├── entries/       # Vite 入口文件（login / workspace / user-center 等）
│       └── styles/        # CSS 样式
│
├── templates/             # Jinja2 模板
│   ├── base.html          # 主工作台模板
│   ├── login.html         # 登录页
│   ├── user_center.html   # 用户中心
│   ├── resume_report.html # 简历分析
│   └── partials/          # 可复用片段
│
├── static/                # 静态资源（Vite 构建产物、图片等）
│
├── services/              # 核心业务服务
│   ├── db.py              # SQLite 持久化层
│   ├── report/            # 规划报告生成（多智能体流水线）
│   ├── resume/            # 简历解析与匹配
│   └── news/              # 职业新闻与知识库
│
├── data/                  # 招聘、职业分类与清洗数据
├── boss_info/             # 13 个城市的岗位数据（JSON）
├── app_data/              # 运行时数据
└── scripts/               # 构建与工具脚本
```

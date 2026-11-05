# 最新岗位与行情观察

岗位探索包含「最新岗位」「岗位档案」「城市分析」三个视图。最新岗位使用独立采集库；原有历史数据集不被改写，也不会被标记成刚采集的岗位。

## 已接入的能力

- JobHunter 四类采集器：国家大学生就业服务平台、企业招聘 API、实习僧、企业招聘官网。当前固定版本实际包含 12 家企业 API 配置、140 家公司官网条目；配置存在不代表当前来源可用。
- 默认启用四类来源，每 6 小时更新，按国家平台、企业 API、实习僧、企业官网的顺序执行。管理员可修改来源、间隔、页数、岗位数量、时限和定向条件，也可立即采集、停止任务。普通用户可以刷新已获取的数据。
- 岗位按批次入库，无需等整轮结束；详情补充也按条目写入。采集任务和各来源分别保留状态、失败说明、去重后的首次发现 / 内容变化 / 再次发现数量。
- 关键词、地点、公司、岗位类型、来源、行业、公司性质、学历、计薪周期、薪资、来源发布日期、采集时间范围和排序筛选。
- 原站链接、岗位描述、福利、来源发布日期、首次发现、最近采集和内容变化时间。字段缺失保持未知；类型只作为来源分类或标题推断。
- 依据同一筛选范围展示样本数量、公司数量、近七天首次发现、同周期薪资中位数、发现趋势、地点分布和 JD 技能关键词。统计不调用 LLM 生成市场事实。
- 按当前筛选条件导出 Excel，包含来源与时间信息，最多 10000 条；另附口径说明，并防止来源字符串被当作 Excel 公式执行。

## 本地启动

项目主依赖已引用 `backend/requirements-jobs.txt`。正常安装项目依赖后：

```powershell
python -m pip install -r backend/requirements.txt
python -m playwright install chromium
npm run build
npm start
```

Windows 会优先使用安装的 Chrome / Edge。也可以在独立环境中安装采集依赖，避免改动主服务的环境：

```powershell
python -m venv --system-site-packages data/app_data/jobhunter-runtime
data/app_data/jobhunter-runtime/Scripts/python.exe -m pip install -r backend/requirements-jobs.txt
```

应用自动识别这个运行环境；其他目录可用 `JOBHUNTER_PYTHON` 指定。可配置变量见 `backend/jobs.env.example`。当前开发环境已按上述独立环境安装依赖并验证采集。

服务启动后按数据库中的计划更新；首次空库默认在启动约 15 秒后安排采集。程序停止期间不会运行任务，恢复后会处理已到期的计划。浏览器页面关闭不会影响后端任务。

## 命令行与部署

```powershell
# 使用已保存的计划配置，执行一轮
npm run collect:jobs

# 单独验证一个来源；参数仅影响本轮，不覆盖已保存配置
python -B backend/scripts/collect_jobs.py --once --sources api --companies 腾讯 --max-pages 1 --max-jobs 40 --timeout-seconds 90

# 独立运行定时采集进程
python -B backend/scripts/collect_jobs.py --worker
```

使用独立进程调度时，为 Web 服务设置 `JOB_MARKET_SCHEDULER=0`。所有进程应共享同一个应用数据目录。任务通过 SQLite 写事务和租约互斥，多进程不会重复领取同一轮采集；工作进程定期续租，过期任务会标记为中断。停止或超时会终止该采集子进程及其浏览器子进程，并保留已入库的岗位。

## 存储与统计口径

数据位于 `data/app_data/job_market.sqlite3`，包含 `jobs`、`runs`、`run_sources`、`observations`、`settings`。原始运行日志位于 `data/app_data/job_market_logs/`，不通过普通用户接口暴露。

- 来源内优先用稳定的原站岗位 ID 去重；没有 ID 时使用链接、岗位、公司和地点组合，避免将同一公司列表页下的多个岗位误合并。不同来源不会仅凭相似岗位名强行合并。
- 首次发现是首次进入本系统的时间，不是招聘发布日期。重复采集更新最近采集时间；实际字段变化单独记录。同轮列表和详情补充只算一个发现。
- 采集源只覆盖有限页数，因此本轮未再次发现不等于已关闭。较久未更新的记录会提示核对原站，不将任务失败或缺失记录推断为停止招聘。
- 日薪、月薪、年薪、时薪分别统计，薪资未知不参与。中位数基于区间中点，不能解释为实际录用薪资。未写明周期的「20–30 万」不会擅自当作月薪。
- 趋势按北京时间日期展示。来源覆盖、筛选范围和任务频率会影响采集数量，不将这些变化解读为全市场涨跌。

## 上游复用与修正

上游项目：[Bynlk/JobHunter](https://github.com/Bynlk/JobHunter)，固定提交见 `backend/integrations/jobhunter/UPSTREAM.md`，保留 MIT 版权声明。采集器在独立子进程中运行，不启动上游 Flask 服务，也不导入其账户、页面或数据库层。

接入中修正了 API 无限翻页、offset 分页、嵌套页码、请求头丢失、国家平台小数薪资和过度推断岗位类型等问题。还依据腾讯当前官网的列表和详情接口修正了详情链接，并将招聘项目标签与真实岗位职责分开。2026-11-05 的联网验证从国家平台和腾讯招聘 API 各取得 20 条岗位，腾讯详情接口也已验证；其他来源仍以实际采集状态为准。

## 接口与检查

读接口需登录：`GET /api/job-market/jobs`、`/jobs/{id}`、`/stats`、`/status`、`/export`。管理员写接口：`PUT /api/job-market/settings`、`POST /api/job-market/collect`、`DELETE /api/job-market/collect`，同时校验会话、角色和 CSRF。筛选、状态和页面不会暴露采集环境中的路径或密钥。

```powershell
npm run check:jobs
data/app_data/jobhunter-runtime/Scripts/python.exe -B backend/scripts/check_jobhunter_adapter.py
npm run check:profile
npm run build
```

岗位功能检查使用离线数据，不访问招聘站点。上游适配检查需要安装采集依赖，但也不访问网络。真实来源验证需单独执行采集命令。

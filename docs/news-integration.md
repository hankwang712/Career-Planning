# 新闻模块的轻量开源接入

现有首页、筛选、去重、每日快照和新闻库保持原流程。新增 feedparser 作为 RSS/Atom 解析器，支持命名空间正文等常见订阅格式；未安装时回退到原 XML 解析器。现有 Readability → Trafilatura 正文提取链路继续用于补全缺失摘要，以及新闻库的后台正文抓取。

## 安装

在项目根目录运行：

```powershell
python -m pip install -r backend/requirements.txt
```

不需要模型 API Key，也不需要新增数据库或部署爬虫服务。

## 可选：添加 RSSHub 或其他 RSS 源

通过 `CAREER_NEWS_EXTRA_FEEDS` 环境变量追加来源，值为 JSON 数组。每项包含完整 `url`，可选 `source` 和 `topic`。额外源与内置源使用同一套技术/职业关键词筛选规则。

下面以本机 RSSHub 为例；`/custom/feed` 是占位路径，必须替换为实例实际支持、已验证的路由：

```powershell
$env:CAREER_NEWS_EXTRA_FEEDS = '[{"url":"http://localhost:1200/custom/feed","source":"RSSHub","topic":"程序员就业"}]'
python backend/server.py
```

本次没有部署 RSSHub 实例，也没有默认依赖公共实例。部署方式与可用路由见 [RSSHub 官方文档](https://docs.rsshub.app/)。已有 RSS 地址也可以直接填入，不要求使用 RSSHub。

环境变量要传入运行后端的进程。配置错误会记录警告并保留内置新闻源；重复 URL 会被忽略。某个源抓取失败仍沿用现有失败处理，不影响其他源。

成功的每日快照会复用到下一个更新周期。添加来源后，如需立即更新，在本地已启动服务上请求：

```powershell
Invoke-RestMethod 'http://localhost:8080/api/career-news?refresh=1'
```

以实际服务端口及访问权限为准。刷新仍可能调用所有源并补全摘要，需要等待网络请求完成。接口返回的 `source_stats` 可用于检查各来源状态。

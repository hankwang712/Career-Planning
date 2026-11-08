# 招聘雷达 Agent 测试台

独立测试台与主站多智能体报告共用 `RecruitmentSearchAgent` 和招聘雷达检索、语义初筛、优先核验流程。

```powershell
D:/anaconda3/envs/yolov11/python.exe backend/tools/recruitment_lab/app.py
```

打开 <http://127.0.0.1:8766/>；数据工作台位于 <http://127.0.0.1:8766/radar>，可同步招聘表、采集官网、导入导出及浏览全部记录。

模型读取 `.env` 中的 `AI_CHAT_API_KEY`、`AI_CHAT_BASE_URL`、`AI_CHAT_MODEL`。直接读取失败时可选用本机Chrome渲染候选原文，代理设置为 `RADAR_BROWSER_PROXY_URL`（默认 `http://localhost:3456`）；没有Chrome时仍可检索招聘表及直接读取公开页面。

输入岗位需求即可运行，默认最多5次模型调用、8次工具调用。页面显示召回候选、实际核验目的、原文与投递链接、时间依据及未确认条件，支持停止、补充回答和下载JSON。只核验初筛相关的候选；同类缺项合并展示，已知超出用户时间范围或招聘类别不符的内容不充作推荐。

旧的公众号搜索入口已移除，不再提供渠道切换。历史保存请求中的旧渠道值自动归一到 `radar`，不会调用旧搜索。

完整配置、第三方抽取与CLI导入限制见[招聘雷达说明](../recruitment_radar/README.md)。

离线检查：

```powershell
node --check backend/tools/recruitment_lab/app.js
```

# 技能对齐与岗位混合检索

简历诊断先用对话模型分别从简历、JD 提取技能与连续原文。短语和引文必须出现在对应原文，否定、未来计划和未确认表述不作为已体现技能。之后双方使用同一份 `data/knowledge/skills/taxonomy.json`：明确别名直接对齐；其他短语用字面与 bge-m3 向量召回候选，再由模型选择候选 ID 或返回空。相似度本身不能证明同义，不接受候选外的 ID。词表包括从招聘标签整理的技能与人工维护的别名，重建命令为 `python backend/scripts/build_skill_taxonomy.py`。

技能交集与未体现项按标准 ID 去重，保留原文和抽取状态。未对齐短语单列待核实，不算“不会”。覆盖率 = 简历已体现的标准岗位技能数 / 已识别的标准岗位技能总数。它不是能力、胜任或录用概率，不能衡量熟练度；未知技能不进入分母，因此应连同待核实列表阅读。学习力、执行力、沟通力、综合能力与置信度不再由条目数量或关键词生成分数，材料不足返回 `null`，前端显示待验证。抽取失败时退回明确的词表匹配，状态标记为 `dictionary_fallback`。

## 配置与数据

- 默认复用根目录 `.env` 的 `EMBEDDING_BINDING_HOST`、`EMBEDDING_BINDING_API_KEY`、`EMBEDDING_MODEL`（现有 bge-m3 配置）。也可完整配置独立的 `AI_EMBEDDING_BASE_URL`、`AI_EMBEDDING_API_KEY`、`AI_EMBEDDING_MODEL`；两组凭据不混用。
- 对话模型使用现有 `AI_CHAT_*` 配置。无模型配置或调用失败时保留明确别名与字面检索结果，不把未确认语义候选当成匹配。
- `JOB_JD_SOURCE_PATH` 指向原始 JD 导出，默认项目根目录的 `job_descriptions.txt`。本地语料不提交。
- `JOB_RETRIEVAL_GRAPH_ENABLED=0` 可关闭 LightRAG 通道；默认启用。图服务失败且有本地语料时继续本地混合检索，并在 `scope` 标记降级；没有任何可用语料时明确报错。
- 文档向量按提供商地址、模型、内容缓存于 `data/app_data/retrieval/vectors.sqlite3`，技能向量缓存在 `data/app_data/skills/`。缓存不保存密钥，不提交。超长 JD 向量输入保留前后文共 6000 字符，返回证据仍保留全文。

## 召回与排序

城市、学历、薪资条件先作用于完整候选。LightRAG 新补丁提供 `POST /career/evidence` 的 `candidate_pool=true` 和分页参数，每页最多 1000 条；此模式不做关键词预截断。旧服务会标记 `ledger_status=upgrade_required`，只对实际拿到的图片段与本地完整语料进行保守筛选，不能声称覆盖全事实库；升级补丁后需重启 LightRAG。

关键词通道用 BM25（k1=1.5、b=0.75），中文按双字切分、英文按词切分；向量通道使用归一化向量的余弦相似度。每个通道至少召回前 200 条候选，图候选作为可用的第三通道。按整条 JD 的来源键去重后，用 `sum(1/(60+rank))` 做 RRF 融合。

前 100 条融合结果按以下可检查因子重排：归一化 RRF 0.45、标题覆盖 0.20、标准技能覆盖 0.20、归一化 BM25 0.05、向量余弦 0.05、查询词覆盖 0.05。查询未识别出标准技能时，这一项权重转给 RRF。权重是检索配置，尚未在大规模人工标注集上训练或校准。重排只改变前 100 条的顺序，后续候选不丢弃，因此这一步不改变融合结果的 Recall@100；融合本身仍可能降低相对 BM25 的召回，必须单独评估。

`metadata.retrieval` 返回每条来源的各因子、计算分数和排名；`scope` 返回各通道候选数、向量/图状态、筛选和降级信息。LLM 解释来源相关性、限制与原文，不负责修改这些分数或来源顺序。

## 同时评估质量与召回

```powershell
.venv\Scripts\python.exe backend/scripts/evaluate_job_retrieval.py --corpus backend/tests/fixtures/retrieval_sources.jsonl --cases backend/tests/fixtures/retrieval_judgments.json
# 使用真实配置的向量模型（会调用 embedding 服务）
.venv\Scripts\python.exe backend/scripts/evaluate_job_retrieval.py --corpus backend/tests/fixtures/retrieval_sources.jsonl --cases backend/tests/fixtures/retrieval_judgments.json --dense --output tmp/retrieval-evaluation.json
```

不传 `--corpus` 时使用配置的本地 JD 导出。语料 JSONL 行使用 `JobSource` 结构；标注 JSON 是 `{query, role?, relevance: {来源键: 0到4的相关性等级}}` 的数组。整条 JD 来源键为 `file_path#record=N`，其他片段为 `chunk_id`。应对池化候选人工标注，不能根据检索命中自动生成真实相关性标签。

工具分别报告 BM25、向量、RRF 融合、最终排序的 NDCG@10 和 Recall@100。逐查询检查相对 BM25 的排序/召回回退，以及相对 RRF 的重排质量回退，发生回退退出码为 1。`--dense` 下向量失败同样退出 1，避免把降级结果当作混合检索评估。无向量时其空排序指标为 0，并明确标记 `not_configured`，不用于判断向量模型质量。

仓库的 12 条合成 JD、3 个手工分级查询只用于回归和接线验证，不能作为真实招聘语料质量的结论。另有 240 条候选的自动测试，确保重排不损失融合前 100 条成员；以及一个 NDCG@10=1、Recall@100=0.1 的反例，防止只看前 10 名。

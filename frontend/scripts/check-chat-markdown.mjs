// Offline checks of the renderer used for both streamed and saved chat answers.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { render } = require("../static/chat-markdown.js");

const table = `## AI 岗位大致分五类

| 类别 | 常见岗位 | 主要做什么 | 典型门槛 |
| --- | --- | --- | --- |
| **算法研究型** | NLP、CV | 训练、微调、对齐 | 论文与竞赛 |
| **应用开发型** | Agent 工程师、RAG 工程师 | 编排、工具调用、评测 | Python 与工程经验 |
| **工程/Infra 型** | AI Infra、MLOps | 推理优化、部署 | Linux、CUDA、K8s |
| **数据/评测型** | AI 数据工程师 | 清洗、标注、评测 | 数据处理 |
| **产品/解决方案型** | AI 产品经理、售前 | 需求与方案落地 | 业务理解 |

交叉方向还有：具身智能、AI 医疗等。`;
const html = render(table);
assert.equal((html.match(/<th /g) || []).length, 4);
assert.equal((html.match(/<td /g) || []).length, 20);
assert.match(html, /<strong>算法研究型<\/strong>/);
assert.match(html, /class="message-table"/);
assert.match(html, /<p>交叉方向/);
assert.equal((render(table.replace(/\n\|/g, "\n\n|" )).match(/<td /g) || []).length, 20);

// Pipe characters in inline code or escaped text do not create extra columns.
const pipes = render("| 表达式 | 说明 |\n| --- | --- |\n| `a | b` | 左\\|右 |");
assert.equal((pipes.match(/<td /g) || []).length, 2);
assert.match(pipes, /<code>a \| b<\/code>/);
assert.match(pipes, /左\|右/);
assert.match(render("| 城市 | 年份 |\n| :---: | ---: |\n| 上海 | 2027 |"), /align-center/);

// Partial streamed messages must remain safe and must not throw.
for (let end = 0; end <= table.length; end++) assert.equal(typeof render(table.slice(0, end)), "string");
const fenced = render("```python\nprint('<script>')\n");
assert.match(fenced, /<pre><code class="language-python">/);
assert.ok(!fenced.includes("<script>"));
const malicious = render('<img src=x onerror="alert(1)">\n\n[点击](javascript:alert)\n\n| 字段 | 值 |\n| --- | --- |\n| <script>alert(1)</script> | `**代码**` |');
assert.ok(!malicious.includes("<img"));
assert.ok(!malicious.includes("<script"));
assert.ok(!malicious.includes('href="javascript:'));
assert.match(malicious, /<code>\*\*代码\*\*<\/code>/);
assert.match(render("[说明](https://example.invalid/docs?a=1&b=2)"), /rel="noopener noreferrer"/);
assert.match(render("### 标题\n\n1. 第一项\n2. 第二项\n\n> 引用\n\n---"), /<ol><li>第一项<\/li><li>第二项<\/li><\/ol>/);
assert.match(render("段落\n\n> 引用"), /<blockquote>引用<\/blockquote>/);
console.log("Chat Markdown checks passed: tables, streamed fragments, code, links and escaping.");

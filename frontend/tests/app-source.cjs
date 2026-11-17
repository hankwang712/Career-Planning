// 测试辅助：app.js 拆成了多个普通脚本（顺序见 templates/partials/app_scripts.html）。
// loadTopLevel(names) 按名字取出顶层函数/常量的源码，保持原有的先后顺序，供测试在桩环境里执行。
const fs = require("node:fs");
const path = require("node:path");
const { parseAst } = require("rollup/parseAst");

const staticDir = path.join(__dirname, "../static");
const partial = fs.readFileSync(path.join(__dirname, "../templates/partials/app_scripts.html"), "utf8");
const files = [...partial.matchAll(/"(app-[a-z-]+)"/g)].map((match) => `${match[1]}.js`);
if (!files.length) throw new Error("app_scripts.html 里没有脚本列表");

function declaredNames(node) {
  if (node.type === "FunctionDeclaration") return [node.id.name];
  if (node.type === "VariableDeclaration") return node.declarations.map((declaration) => declaration.id.name).filter(Boolean);
  return [];
}

function loadTopLevel(wanted) {
  const found = new Map();
  for (const file of files) {
    const source = fs.readFileSync(path.join(staticDir, file), "utf8");
    for (const node of parseAst(source).body) {
      for (const name of declaredNames(node)) {
        if (wanted.includes(name)) found.set(name, source.slice(node.start, node.end));
      }
    }
  }
  const missing = wanted.filter((name) => !found.has(name));
  if (missing.length) throw new Error(`找不到顶层声明：${missing.join(", ")}`);
  return wanted.map((name) => found.get(name)).join("\n\n");
}

module.exports = { files, loadTopLevel };

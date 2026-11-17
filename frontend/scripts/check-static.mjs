// 前端静态资源检查：语法、同一作用域内重复定义的函数，以及模板引用的静态文件是否存在。
//
//   node scripts/check-static.mjs            只检查，有问题时以非 0 退出
//   node scripts/check-static.mjs --fix-dups 删除被后面同名定义覆盖的前一个函数（函数声明会提升，
//                                            前一个定义永远不会被调用，删除不改变行为）
//
// 解析器使用 Vite 自带的 Rollup（rollup/parseAst），不需要额外依赖。
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const here = path.dirname(fileURLToPath(import.meta.url));
const frontendDir = path.resolve(here, "..");
const staticDir = path.join(frontendDir, "static");
const templatesDir = path.join(frontendDir, "templates");
const publicDir = path.resolve(frontendDir, "..", "data", "public");
const require = createRequire(import.meta.url);
const { parseAst } = await import(pathToUrl(require.resolve("rollup/parseAst")));

function pathToUrl(file) {
  return new URL(`file:///${file.replace(/\\/g, "/")}`).href;
}

const SKIP_DIRS = new Set(["dist", "vendor", "assets", "img", "brand", "pet"]);

function* walk(dir, extensions) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (!SKIP_DIRS.has(entry.name)) yield* walk(full, extensions);
    } else if (extensions.some((ext) => entry.name.endsWith(ext))) {
      yield full;
    }
  }
}

// 一个作用域里的语句列表：脚本顶层，以及顶层 IIFE 的函数体。
function* scopes(program) {
  yield program.body;
  for (const statement of program.body) {
    const call = statement.type === "ExpressionStatement" ? statement.expression : null;
    const callee = call?.type === "CallExpression" ? call.callee : null;
    if (callee && (callee.type === "FunctionExpression" || callee.type === "ArrowFunctionExpression") && callee.body.type === "BlockStatement") {
      yield callee.body.body;
    }
  }
}

function duplicateDeclarations(code) {
  const program = parseAst(code);
  const duplicates = [];
  for (const body of scopes(program)) {
    const seen = new Map();
    for (const statement of body) {
      if (statement.type !== "FunctionDeclaration") continue;
      const name = statement.id.name;
      if (!seen.has(name)) seen.set(name, []);
      seen.get(name).push(statement);
    }
    for (const [name, nodes] of seen) if (nodes.length > 1) duplicates.push({ name, nodes });
  }
  return duplicates;
}

function removeShadowed(code, duplicates) {
  const ranges = duplicates.flatMap(({ nodes }) => nodes.slice(0, -1).map((node) => [node.start, node.end]));
  ranges.sort((a, b) => b[0] - a[0]);
  let result = code;
  for (const [start, end] of ranges) {
    let from = start;
    let to = end;
    while (from > 0 && (result[from - 1] === " " || result[from - 1] === "\t")) from -= 1;
    while (to < result.length && (result[to] === "\r" || result[to] === "\n")) to += 1;
    result = result.slice(0, from) + result.slice(to);
  }
  return result;
}

const fixDuplicates = process.argv.includes("--fix-dups");
const problems = [];

for (const file of walk(staticDir, [".js"])) {
  const relative = path.relative(staticDir, file).replace(/\\/g, "/");
  let code = fs.readFileSync(file, "utf8");
  let duplicates;
  try {
    duplicates = duplicateDeclarations(code);
  } catch (error) {
    problems.push(`${relative}: 语法错误：${error.message.split("\n")[0]}`);
    continue;
  }
  if (duplicates.length && fixDuplicates) {
    code = removeShadowed(code, duplicates);
    duplicateDeclarations(code); // 修改后必须仍能解析
    fs.writeFileSync(file, code);
    console.log(`${relative}: 已删除 ${duplicates.reduce((sum, item) => sum + item.nodes.length - 1, 0)} 个被覆盖的重复函数`);
    continue;
  }
  for (const { name, nodes } of duplicates) {
    const lines = nodes.map((node) => code.slice(0, node.start).split("\n").length);
    problems.push(`${relative}: 函数 ${name} 在同一作用域内定义了 ${nodes.length} 次（行 ${lines.join("、")}），前面的定义永远不会被调用`);
  }
}

// 工作台主脚本拆成了多个普通脚本（templates/partials/app_scripts.html），它们共享一个全局作用域：
// 文件列表要和目录一致，app-state 在最前、app-boot 在最后；跨文件的重名函数或 const/let 重复声明
// 会在运行时静默覆盖或直接抛 SyntaxError，所以在这里拦住。
{
  const partial = fs.readFileSync(path.join(templatesDir, "partials", "app_scripts.html"), "utf8");
  const listed = [...partial.matchAll(/"(app-[a-z-]+)"/g)].map((match) => `${match[1]}.js`);
  const onDisk = fs.readdirSync(staticDir).filter((name) => /^app-[a-z-]+\.js$/.test(name) && name !== "app-cursor.js");
  for (const name of listed) if (!onDisk.includes(name)) problems.push(`partials/app_scripts.html: 列出的脚本不存在：${name}`);
  for (const name of onDisk) if (!listed.includes(name)) problems.push(`static/${name}: 没有列入 partials/app_scripts.html，页面不会加载它`);
  if (listed[0] !== "app-state.js") problems.push("partials/app_scripts.html: app-state 必须第一个加载");
  if (listed.at(-1) !== "app-boot.js") problems.push("partials/app_scripts.html: app-boot 必须最后加载");

  const declared = new Map(); // name -> [{ file, kind }]
  for (const name of listed.filter((file) => onDisk.includes(file))) {
    let program;
    try {
      program = parseAst(fs.readFileSync(path.join(staticDir, name), "utf8"));
    } catch {
      continue; // 语法错误已在上面报告
    }
    for (const statement of program.body) {
      const entries = statement.type === "FunctionDeclaration" ? [[statement.id.name, "function"]]
        : statement.type === "ClassDeclaration" ? [[statement.id.name, "class"]]
        : statement.type === "VariableDeclaration"
          ? statement.declarations.filter((item) => item.id.type === "Identifier").map((item) => [item.id.name, statement.kind])
          : [];
      for (const [declaredName, kind] of entries) {
        if (!declared.has(declaredName)) declared.set(declaredName, []);
        declared.get(declaredName).push({ file: name, kind });
      }
    }
  }
  for (const [declaredName, places] of declared) {
    const files = [...new Set(places.map((place) => place.file))];
    if (files.length < 2) continue;
    const onlyFunctions = places.every((place) => place.kind === "function");
    problems.push(`${declaredName}: 在 ${files.join("、")} 中重复声明${onlyFunctions ? "（后加载的函数会覆盖前面的）" : "（let/const/class 重复会让后加载的脚本直接报错）"}`);
  }
}

// 模板里引用的静态文件必须存在（Flask 先找 data/public，再找 frontend/static）。
const referenced = new Set();
for (const file of walk(templatesDir, [".html"])) {
  const text = fs.readFileSync(file, "utf8");
  for (const match of text.matchAll(/url_for\(\s*['"]static['"]\s*,\s*filename\s*=\s*['"]([^'"]+)['"]/g)) {
    referenced.add([match[1], path.relative(frontendDir, file).replace(/\\/g, "/")].join("\u0000"));
  }
}
for (const entry of referenced) {
  const [asset, template] = entry.split("\u0000");
  if (!fs.existsSync(path.join(staticDir, asset)) && !fs.existsSync(path.join(publicDir, asset))) {
    problems.push(`${template}: 引用的静态文件不存在：${asset}`);
  }
}

if (problems.length) {
  console.error(problems.join("\n"));
  console.error(`\n共 ${problems.length} 个问题`);
  process.exit(1);
}
console.log("前端静态资源检查通过");

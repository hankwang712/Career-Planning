import assert from "node:assert/strict";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { TextReveal } = require("../static/chat-typing.js");

// A single network delta must still be revealed progressively.
const text = "这是一段一次到达、但需要逐字展示的回答。";
const reveal = new TextReveal();
assert.equal(reveal.advance(text, 0), "这");
const intermediate = reveal.advance(text, 16);
assert.ok(intermediate.length > 1 && intermediate.length < text.length);
assert.ok(text.startsWith(intermediate));
for (let now = 32; now <= 1000; now += 16) reveal.advance(text, now);
assert.equal(reveal.current(text), text);

// Later deltas append to existing text; they never replay the beginning.
const incremental = new TextReveal();
incremental.advance("你好", 0);
assert.equal(incremental.advance("你好", 16), "你好");
assert.equal(incremental.advance("你好，世界", 32), "你好，");
assert.equal(incremental.advance("你好，世界", 48), "你好，世");

// Emoji, combining marks and ZWJ sequences remain complete graphemes.
for (const first of ["👩‍💻", "🇨🇳", "e\u0301", "😀"]) {
  const unicode = new TextReveal();
  assert.equal(unicode.advance(first + "测试", 0), first);
}

// Finishing a large response must not add seconds of presentation delay.
const large = new TextReveal();
const longText = "长回答与表格内容。".repeat(2000);
large.finish(0);
assert.equal(large.advance(longText, 0).length, 1);
assert.ok(large.advance(longText, 200).length < longText.length);
assert.equal(large.advance(longText, 600), longText);
assert.ok(large.complete(longText));

// Background tabs / reduced motion / abort can flush without leaving a queue.
const instant = new TextReveal();
assert.equal(instant.advance(text, 0, true), text);
assert.ok(instant.complete(text));
assert.equal(new TextReveal().advance("", 0), "");
console.log("Chat typing checks passed: incremental output, Unicode, bounded completion and immediate flush.");

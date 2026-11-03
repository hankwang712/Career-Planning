((root, factory) => {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.CareerTyping = api;
})(typeof window === "undefined" ? null : window, () => {
  "use strict";

  class TextReveal {
    constructor() {
      this.position = 0;
      this.lastTime = null;
      this.deadline = null;
      this.segmenter = typeof Intl.Segmenter === "function" ? new Intl.Segmenter("zh", { granularity: "grapheme" }) : null;
    }

    current(source) { return source.slice(0, this.position); }
    complete(source) { return this.position >= source.length; }
    finish(now) { this.deadline = now + 600; }

    advance(source, now, instant = false) {
      if (instant || this.deadline !== null && now >= this.deadline) {
        this.position = source.length;
      } else if (!this.complete(source)) {
        const elapsed = this.lastTime === null ? 16 : Math.min(50, Math.max(0, now - this.lastTime));
        const remaining = source.length - this.position;
        let rate = Math.min(1200, Math.max(60, remaining * 3));
        if (this.deadline !== null) rate = Math.max(rate, remaining * 1000 / Math.max(16, this.deadline - now));
        let count = this.position === 0 ? 1 : Math.max(1, Math.floor(rate * elapsed / 1000));
        const tail = source.slice(this.position);
        const pieces = this.segmenter ? this.segmenter.segment(tail) : Array.from(tail, (segment) => ({ segment }));
        for (const { segment } of pieces) {
          this.position += segment.length;
          if (--count <= 0) break;
        }
      }
      this.lastTime = now;
      return this.current(source);
    }
  }
  return { TextReveal };
});

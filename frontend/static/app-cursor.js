(function () {
  "use strict";
  const media = matchMedia("(any-hover:hover) and (any-pointer:fine)");
  const root = document.documentElement;
  let cursor, surface;
  function hide() { cursor?.classList.remove("is-visible"); }
  function sync() {
    if (!media.matches) {
      delete root.dataset.appCursorOverlay;
      hide();
      return;
    }
    if (!cursor) {
      cursor = document.createElement("div");
      cursor.className = "app-cursor-overlay";
      cursor.setAttribute("aria-hidden", "true");
      // A manual popover can stay above modal dialogs without intercepting input.
      if (typeof cursor.showPopover === "function") cursor.setAttribute("popover", "manual");
      document.body.append(cursor);
      if (cursor.hasAttribute("popover")) cursor.showPopover();
    }
    root.dataset.appCursorOverlay = "";
  }
  document.addEventListener("pointermove", event => {
    if (!media.matches || !cursor || event.pointerType !== "mouse") { hide(); return; }
    const target = event.target instanceof Element ? event.target : null;
    if (!target || getComputedStyle(target).cursor !== "none") { hide(); return; }
    const nextSurface = target.closest("dialog,[popover]");
    if (surface !== nextSurface && cursor.hasAttribute("popover")) {
      cursor.hidePopover();
      cursor.showPopover();
    }
    surface = nextSurface;
    // Match the native image's fingertip hotspot. No animation or easing lag.
    cursor.style.setProperty("--cursor-x", `${event.clientX - 6}px`);
    cursor.style.setProperty("--cursor-y", `${event.clientY - 3}px`);
    cursor.classList.add("is-visible");
  }, { passive: true });
  document.documentElement.addEventListener("pointerleave", hide);
  document.addEventListener("pointerdown", event => { if (event.pointerType !== "mouse") hide(); }, { passive: true });
  window.addEventListener("blur", hide);
  document.addEventListener("visibilitychange", () => { if (document.hidden) hide(); });
  media.addEventListener("change", sync);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", sync, { once: true });
  else sync();
})();

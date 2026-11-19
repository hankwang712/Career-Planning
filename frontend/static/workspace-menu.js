function closeNavWorkspaceMenu() {
  const menu = document.getElementById("navWorkspaceMenu");
  const toggle = document.getElementById("navWorkspaceToggle");
  if (menu) menu.classList.add("hidden");
  if (toggle) {
    toggle.setAttribute("aria-expanded", "false");
    toggle.classList.remove("nav-workspace-menu-open");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const shell = document.getElementById("navWorkspaceShell");
  const toggle = document.getElementById("navWorkspaceToggle");
  const menu = document.getElementById("navWorkspaceMenu");
  if (shell && toggle && menu) {
    toggle.addEventListener("click", () => {
      if (!menu.classList.contains("hidden")) {
        closeNavWorkspaceMenu();
        return;
      }
      menu.classList.remove("hidden");
      toggle.setAttribute("aria-expanded", "true");
      toggle.classList.add("nav-workspace-menu-open");
    });
    document.addEventListener("click", (event) => {
      if (event.target instanceof Node && !shell.contains(event.target)) closeNavWorkspaceMenu();
    });
    shell.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !menu.classList.contains("hidden")) {
        closeNavWorkspaceMenu();
        toggle.focus();
      }
    });
  }
  document.querySelector("[data-workspace-guide-link]")?.addEventListener("click", () => {
    try { sessionStorage.setItem("app_force_workspace_guide", "1"); } catch (_) {}
  });
  const news = document.getElementById("careerNewsBoard");
  if (news) {
    document.querySelector("[data-dashboard-news-link]")?.addEventListener("click", async (event) => {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      await window.showSection?.("dashboard");
      news.scrollIntoView({ behavior: "instant" });
    });
  }

  const clock = document.querySelector("[data-local-clock]");
  if (clock) {
    const format = new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
    const tick = () => { clock.textContent = format.format(new Date()); };
    tick();
    window.setInterval(tick, 1000);
  }
});

"""前端资源完整性：页面引用的脚本/样式必须存在，脚本加载顺序固定，静态检查脚本通过。"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
STATIC = FRONTEND / "static"

# 工作台主脚本（原 app.js）已按功能拆开，列表以 partials/app_scripts.html 为准；app-state 在最前，app-boot 在最后。
APP_SCRIPTS = [f"{name}.js" for name in re.findall(r'"(app-[a-z-]+)"', (FRONTEND / "templates/partials/app_scripts.html").read_text(encoding="utf-8"))]
# 用户中心与报告优化页共用脚本，顺序有依赖（共享全局作用域）。
WORKSPACE_SCRIPTS = ["auth-security.js", *APP_SCRIPTS, "workspace-guide-overlay.js", "report-reader-layout.js",
                     "career-report-workspace.js", "report-link-previews.js"]
RETIRED_NAMES = ("app-hotfix", "workspace-restoration", "ai-polish-parity.css")


def asset_refs(html):
    scripts = re.findall(r'<script[^>]*\ssrc="(/static/[^"?]+)[^"]*"([^>]*)>', html)
    styles = re.findall(r'<link[^>]*rel="stylesheet"[^>]*href="(/static/[^"?]+)', html)
    return scripts, styles


def script_order(html, names):
    scripts, _ = asset_refs(html)
    return [(Path(src).name, "defer" in rest) for src, rest in scripts if Path(src).name in names]


@pytest.mark.parametrize("path", ["/user-center/workspace", "/user-center/resumes", "/user-center/career-report/polish", "/resume-report", "/test-result", "/test-runner", "/sbti"])
def test_every_asset_a_page_references_is_served(make_account, path):
    account = make_account()
    html = account.get(path).get_data(as_text=True)
    scripts, styles = asset_refs(html)
    assert scripts or styles
    for asset in [src for src, _ in scripts] + styles:
        assert account.get(asset).status_code == 200, f"{path} 引用了无法访问的资源：{asset}"


def test_main_workspace_assets_are_served(make_account):
    account = make_account()
    html = account.get("/main.html").get_data(as_text=True)
    scripts, styles = asset_refs(html)
    assert len(scripts) > 5
    for asset in [src for src, _ in scripts] + styles:
        assert account.get(asset).status_code == 200, f"首页引用了无法访问的资源：{asset}"


def test_user_center_loads_workspace_scripts_in_order_without_defer(make_account):
    html = make_account().get("/user-center/workspace").get_data(as_text=True)
    assert script_order(html, set(WORKSPACE_SCRIPTS)) == [(name, False) for name in WORKSPACE_SCRIPTS]


def test_polish_page_loads_the_same_scripts_deferred(make_account):
    html = make_account().get("/user-center/career-report/polish").get_data(as_text=True)
    assert script_order(html, set(WORKSPACE_SCRIPTS)) == [(name, True) for name in WORKSPACE_SCRIPTS]


def test_main_page_loads_the_report_workspace_after_app(make_account):
    html = make_account().get("/main.html").get_data(as_text=True)
    order = [name for name, _ in script_order(html, set(WORKSPACE_SCRIPTS))]
    assert order.index("app-boot.js") < order.index("report-reader-layout.js") < order.index("career-report-workspace.js")


def test_app_scripts_are_listed_state_first_and_boot_last():
    assert APP_SCRIPTS[0] == "app-state.js" and APP_SCRIPTS[-1] == "app-boot.js"
    assert len(APP_SCRIPTS) == len(set(APP_SCRIPTS))
    on_disk = {path.name for path in STATIC.glob("app-*.js")} - {"app-cursor.js"}
    assert on_disk == set(APP_SCRIPTS), "static 目录里的 app-*.js 必须和 partials/app_scripts.html 一致"
    assert not (STATIC / "app.js").exists(), "app.js 已拆分，不要再加回单个巨型脚本"


def test_every_page_with_the_workspace_scripts_loads_the_same_app_scripts(make_account):
    account = make_account()
    for path in ("/main.html", "/user-center/workspace", "/user-center/career-report/polish", "/resume-report"):
        html = account.get(path).get_data(as_text=True)
        loaded = [name for name, _ in script_order(html, set(APP_SCRIPTS))]
        assert loaded == APP_SCRIPTS, path


def test_retired_patch_layer_names_are_gone_from_templates_and_static():
    for folder in (FRONTEND / "templates", STATIC):
        for file in folder.rglob("*"):
            if file.suffix not in {".html", ".js", ".css"} or "dist" in file.parts or "vendor" in file.parts:
                continue
            text = file.read_text(encoding="utf-8", errors="ignore")
            for name in RETIRED_NAMES:
                assert name not in text, f"{file.relative_to(FRONTEND)} 仍引用已改名的 {name}"
    for name in ("app-hotfix.js", "workspace-restoration.js", "ai-polish-parity.css"):
        assert not (STATIC / name).exists()


def test_renamed_files_exist():
    for name in ("workspace-guide-overlay.js", "career-report-workspace.js", "report-editor-overlay.css"):
        assert (STATIC / name).is_file()


def test_vite_entries_declared_in_the_config_exist():
    config = (FRONTEND / "vite.config.mjs").read_text(encoding="utf-8")
    entries = re.findall(r'"src", "entries", "([^"]+)"', config)
    assert entries
    for entry in entries:
        assert (FRONTEND / "src" / "entries" / entry).is_file(), entry


@pytest.mark.skipif(shutil.which("node") is None, reason="需要 Node.js")
def test_static_check_script_passes():
    """全部静态脚本语法正确、没有被覆盖的重复函数、模板引用的文件都存在。"""
    if not (FRONTEND.parent / "node_modules" / "rollup").exists():
        pytest.skip("未安装前端依赖（npm install）")
    result = subprocess.run(["node", "scripts/check-static.mjs"], cwd=FRONTEND, capture_output=True, text=True,
                            encoding="utf-8", timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr

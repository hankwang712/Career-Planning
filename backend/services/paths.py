import os
from pathlib import Path
from .environment import load_environment


load_environment()


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = PROJECT_ROOT / "frontend"
STATIC_DIR = FRONTEND_DIR / "static"
TEMPLATE_DIR = FRONTEND_DIR / "templates"
DATA_DIR = PROJECT_ROOT / "data"
PUBLIC_DATA_DIR = DATA_DIR / "public"
# 运行数据目录；测试和多实例部署可通过 CAREER_APP_DATA_DIR 指向独立目录。
APP_DATA_DIR = Path(os.environ.get("CAREER_APP_DATA_DIR") or DATA_DIR / "app_data")
REPORT_IMAGE_DIR = PUBLIC_DATA_DIR / "img" / "report"

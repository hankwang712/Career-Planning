"""站点统一的跨域策略。

Flask 页面/API 与 FastAPI 聊天接口共用这一份来源判断和响应头，避免两处各写一份后逐渐不一致。
"""
from collections.abc import Iterable

ALLOWED_METHODS = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
ALLOWED_HEADERS = "Content-Type, Authorization, X-CSRF-Token"


def normalize_origins(origins: Iterable[str | None]) -> set[str]:
    """去掉空值和结尾斜杠，得到可比较的来源集合。"""
    return {str(origin).strip().rstrip("/") for origin in origins if origin and str(origin).strip()}


def cors_headers(origin: str | None, allowed: Iterable[str]) -> dict[str, str]:
    """来源在允许集合内时返回需要附加的 CORS 响应头，否则返回空字典。"""
    origin = str(origin or "").strip()
    if not origin or origin not in set(allowed):
        return {}
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": ALLOWED_METHODS,
        "Access-Control-Allow-Headers": ALLOWED_HEADERS,
    }

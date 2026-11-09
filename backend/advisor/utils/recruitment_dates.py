"""Publication-date checks shared by candidate retrieval and final evidence review."""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def publication_state(published_at, *, published_after=None, days=None, now=None):
    if published_after is None and days is None:
        return "unknown"
    now = now or datetime.now(ZoneInfo("Asia/Shanghai"))
    if now.tzinfo is None:
        now = now.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    try:
        instant = datetime.fromisoformat(str(published_at or "").replace("Z", "+00:00"))
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=now.tzinfo)
        if published_after is not None:
            start = published_after if isinstance(published_after, date) else date.fromisoformat(published_after)
            lower = datetime.combine(start, time.min, tzinfo=now.tzinfo)
        else:
            lower = now - timedelta(days=days)
        return "within_window" if lower <= instant <= now + timedelta(minutes=5) else "outside_window"
    except (ValueError, TypeError, OverflowError):
        return "unknown"

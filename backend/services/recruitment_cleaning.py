"""Deterministic, account-scoped screening of stored recruitment listings."""

from hashlib import sha256
import json
import re
from typing import Annotated
from unicodedata import normalize

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from .recruitment_sources import CITIES


STATUSES = ("unreviewed", "passed", "rejected", "review")
CITY_SEPARATOR = re.compile(r"[\s·•/／|,，、;；—-]+")
KNOWN_CITIES = frozenset(CITIES) | {
    "重庆", "天津", "苏州", "无锡", "宁波", "温州", "合肥", "福州", "厦门", "南昌",
    "济南", "青岛", "郑州", "武汉", "长沙", "东莞", "佛山", "珠海", "南宁", "海口",
    "贵阳", "昆明", "西安", "兰州", "大连", "沈阳", "长春", "哈尔滨", "石家庄", "太原",
    "乌鲁木齐", "呼和浩特", "拉萨", "西宁", "银川", "香港", "澳门", "远程", "全国",
}
MONTHLY_PAY = re.compile(
    r"(\d+(?:\.\d+)?)([千万]元?|[k元])?(?:[-~至](\d+(?:\.\d+)?)([千万]元?|[k元])?)?"
    r"(/(?:月|month)|每月)?(?:[·*×x]\d+薪)?", re.I
)
PAY_SCALE = {"k": 1000, "千": 1000, "千元": 1000, "万": 10000, "万元": 10000, "元": 1, None: 1}
RuleTerm = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
SalaryK = Annotated[float, Field(gt=0, le=1000, allow_inf_nan=False)]


class CleaningRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cities: list[RuleTerm] = Field(default_factory=list, max_length=30)
    min_salary_k: SalaryK | None = None
    max_salary_k: SalaryK | None = None
    title_exclusions: list[RuleTerm] = Field(default_factory=list, max_length=50)
    company_exclusions: list[RuleTerm] = Field(default_factory=list, max_length=50)
    auto: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def check_salary_order(self):
        if self.min_salary_k is not None and self.max_salary_k is not None and self.min_salary_k > self.max_salary_k:
            raise ValueError("最低月薪不能高于最高月薪。")
        return self


def init_schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS recruitment_cleaning_rules (
            owner TEXT PRIMARY KEY REFERENCES users(username) ON DELETE CASCADE,
            rules TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS recruitment_cleaning_results (
            owner TEXT NOT NULL, source TEXT NOT NULL, url_key TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('passed', 'rejected', 'review', 'released')),
            reason TEXT NOT NULL,
            PRIMARY KEY(owner, source, url_key),
            FOREIGN KEY(owner, source, url_key) REFERENCES recruitment_listings(owner, source, url_key) ON DELETE CASCADE
        );
        CREATE TRIGGER IF NOT EXISTS recruitment_recheck_changed_listing
        AFTER UPDATE OF title, company, location, salary ON recruitment_listings
        WHEN NEW.title IS NOT OLD.title OR NEW.company IS NOT OLD.company
             OR NEW.location IS NOT OLD.location OR NEW.salary IS NOT OLD.salary
        BEGIN
            DELETE FROM recruitment_cleaning_results
            WHERE owner=NEW.owner AND source=NEW.source AND url_key=NEW.url_key AND status <> 'released';
        END;
    """)


def load_rules(conn, owner):
    row = conn.execute("SELECT rules FROM recruitment_cleaning_rules WHERE owner=?", (owner,)).fetchone()
    return CleaningRules.model_validate_json(row["rules"]) if row else CleaningRules()


def save_rules(conn, owner, rules):
    conn.execute("""
        INSERT INTO recruitment_cleaning_rules VALUES (?, ?)
        ON CONFLICT(owner) DO UPDATE SET rules=excluded.rules
    """, (owner, rules.model_dump_json()))


def comparable_text(value):
    return normalize("NFKC", value).casefold()


def clean_city(value):
    return comparable_text(value).removesuffix("市")


def city_matches(location, allowed):
    tokens = CITY_SEPARATOR.split(comparable_text(location.strip()))
    targets = {clean_city(city) for city in allowed}
    cities = set()
    for token in tokens:
        city, suffix, _ = token.rsplit("省", 1)[-1].partition("市")
        if city and (suffix or city in KNOWN_CITIES or city in targets):
            cities.add(city)
    if not cities or ("全国" in cities and "全国" not in targets):
        return None
    return bool(cities & targets)


def monthly_pay(value):
    text = re.sub(r"\s+", "", comparable_text(value)).replace("–", "-").replace("—", "-")
    match = MONTHLY_PAY.fullmatch(text)
    if not match:
        return None, None
    low, low_unit, high, high_unit, period = match.groups()
    if not period and not {low_unit, high_unit} & {"k", "千", "千元"}:
        return None, None
    minimum = float(low) * PAY_SCALE[low_unit or high_unit]
    maximum = float(high or low) * PAY_SCALE[high_unit or low_unit]
    return (minimum, maximum) if 0 < minimum <= maximum <= 10_000_000 else (None, None)


def evaluate(row, rules):
    if row["status"] == "released":
        return "released", row["reason"]
    missing = []
    for field, label, words in (
        ("title", "标题", rules.title_exclusions),
        ("company", "公司", rules.company_exclusions),
    ):
        value = comparable_text(row[field])
        for term in words:
            if comparable_text(term) in value:
                return "rejected", f"{label}命中排除词「{term}」"
        if words and not value:
            missing.append(f"{label}未知")
    if row["source"] != "xiaohongshu":
        if rules.cities:
            matches = city_matches(row["location"], rules.cities)
            if matches is False:
                return "rejected", f"地点「{row['location']}」不在目标城市"
            if matches is None:
                missing.append("城市无法确认")
        if rules.min_salary_k is not None or rules.max_salary_k is not None:
            low, high = monthly_pay(row["salary"])
            if low is None:
                missing.append("月薪无法确认")
            elif ((rules.min_salary_k is not None and high < rules.min_salary_k * 1000)
                  or (rules.max_salary_k is not None and low > rules.max_salary_k * 1000)):
                return "rejected", f"月薪「{row['salary']}」与目标区间无交集"
    return ("review", "、".join(missing)) if missing else ("passed", "")


def stored_counts(conn, owner):
    counts = dict.fromkeys(STATUSES, 0)
    for row in conn.execute("""
        SELECT COALESCE(r.status, 'unreviewed') AS status, count(*) AS count
        FROM recruitment_listings j
        LEFT JOIN recruitment_cleaning_results r USING(owner, source, url_key)
        WHERE j.owner=? GROUP BY r.status
    """, (owner,)):
        counts["passed" if row["status"] == "released" else row["status"]] += row["count"]
    return counts


LISTINGS = """
    SELECT j.source, j.url_key, j.title, j.company, j.location, j.salary,
           r.status, r.reason
    FROM recruitment_listings j
    LEFT JOIN recruitment_cleaning_results r USING(owner, source, url_key)
    WHERE j.owner=?
"""


def result_rows(rows, rules):
    for row in rows:
        status, reason = evaluate(row, rules)
        yield row["source"], row["url_key"], row["title"], status, reason


def write_results(conn, owner, results):
    conn.executemany("""
        INSERT INTO recruitment_cleaning_results VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(owner, source, url_key) DO UPDATE SET status=excluded.status, reason=excluded.reason
        WHERE recruitment_cleaning_results.status <> 'released'
    """, ((owner, source, url, status, reason) for source, url, _, status, reason in results))


def result_counts(results):
    counts = dict.fromkeys(STATUSES[1:], 0)
    for _, _, _, status, _ in results:
        counts["passed" if status == "released" else status] += 1
    return counts


def preview(conn, owner, rules):
    rows = list(conn.execute(LISTINGS + " ORDER BY j.source, j.url_key", (owner,)))
    results = list(result_rows(rows, rules))
    snapshot = [owner, rules.model_dump(), load_rules(conn, owner).model_dump(), [tuple(row) for row in rows]]
    token = sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    samples = {status: [] for status in STATUSES[1:]}
    for source, _, title, status, reason in results:
        entries = samples["passed" if status == "released" else status]
        if len(entries) < 3:
            entries.append({"source": source, "title": title, "reason": reason})
    return {"token": token, "counts": result_counts(results), "samples": samples}, results


def apply_ingested(conn, owner, source, urls):
    if not urls:
        return {}
    rules = load_rules(conn, owner)
    if not rules.auto:
        return {}
    results = []
    for start in range(0, len(urls), 500):
        batch = urls[start:start + 500]
        placeholders = ", ".join("?" for _ in batch)
        rows = conn.execute(LISTINGS + f" AND j.source=? AND j.url_key IN ({placeholders})", (owner, source, *batch))
        results.extend(result_rows(rows, rules))
    write_results(conn, owner, results)
    return result_counts(results)

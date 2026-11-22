"""Deterministic, account-scoped screening of stored recruitment listings."""

from hashlib import sha256
import json
import re
from typing import Annotated, Literal
from unicodedata import normalize

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from .recruitment_sources import CITIES


STATUSES = ("unreviewed", "passed", "rejected", "review")
Profile = Literal["general", "internship", "full_time"]
DEFAULT_PROFILE = "general"
PROFILES = {"general": "通用", "internship": "实习", "full_time": "正式工作"}
SEMANTIC_JOIN = """LEFT JOIN recruitment_ai_results a
    ON a.owner=j.owner AND a.source=j.source AND a.url_key=j.url_key AND a.kind='semantic'"""
EFFECTIVE_STATUS = "CASE WHEN r.status='passed' AND a.verdict IN ('rejected','review') THEN a.verdict ELSE r.status END"
ZHILIAN_JD_MISSING = "(j.source='zhilian' AND COALESCE(d.description, '')='')"
JD_REQUIRED = "待补齐原站 JD，岗位职责和任职要求尚未获取。"
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
DAILY_PAY = re.compile(r"(\d+(?:\.\d+)?)(?:元)?(?:[-~至](\d+(?:\.\d+)?))?(?:元)?(?:/[天日]|每天|每日)")
INTERNSHIP_WORKDAYS_PER_MONTH = 22
RuleTerm = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
SalaryK = Annotated[float, Field(gt=0, le=1000, allow_inf_nan=False)]
SemanticRule = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]
EDUCATION_TERMS = {
    "初中": "初中", "中专": "中专", "中技": "中专", "高中": "高中", "技校": "中专", "大专": "大专", "专科": "大专",
    "本科": "本科", "学士": "本科", "硕士": "硕士", "研究生": "硕士", "博士": "博士",
}
EDUCATION = re.compile("|".join(EDUCATION_TERMS))
EDUCATION_RANK = {level: rank for rank, level in enumerate(("初中", "高中", "中专", "大专", "本科", "硕士", "博士"))}
EXPERIENCE = re.compile(
    r"(?P<years>\d{1,2})(?:[-~至]\d{1,2})?年(?:及?以上|\+)?(?:的)?(?:相关)?(?:工作|行业|项目|管理|开发)?经验"
)
EXPERIENCE_FIELD = re.compile(r"(?P<years>\d{1,2})(?:[-~至]\d{1,2})?年(?:及?以上|\+)?(?:(?:工作)?经验)?")
SCOUT_EXAMPLES = (
    {"keyword": "单休", "condition": "never", "desc": "识别每周只休一天或双休不固定的安排，包括大小周、单双休、五天半、每周工作六天和月休四至六天。只有轮休、调休等字样时，还需核对实际休息天数。"},
    {"keyword": "外包", "condition": "never", "desc": "识别劳务派遣、人力外包、项目外派、驻场等非招聘公司直接雇佣的情形。仅与外部公司合作、对接外包团队或团队名称含外包时不命中。"},
    {"keyword": "销售", "condition": "never", "desc": "判断岗位本身是否承担获客、拓客、成交等销售职责。电销、网销、面销、BD、客户代表、客户经理等以实际职责为准。只为销售团队提供技术或运营支持时不命中。"},
    {"keyword": "实习", "condition": "never", "desc": "识别招聘实习生、带薪实习、兼职实习或短期实习培训的岗位。只要求有实习经历、实习证明，或写明实习经验非必需时不命中。"},
    {"keyword": "兼职", "condition": "never", "desc": "识别明确的非全日制、小时工、临时工或按项目短期计酬工作。弹性工作时间本身不足以判定兼职，实习和志愿服务也应单独判断。"},
)


class ScoutRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keyword: SemanticRule
    condition: Literal["must", "never"]
    desc: Annotated[str, StringConstraints(strip_whitespace=True, max_length=600)] = ""


class ScoutDescriptionRequest(ScoutRule):
    intent: Annotated[str, StringConstraints(strip_whitespace=True, max_length=600)] = ""


class CleaningRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cities: list[RuleTerm] = Field(default_factory=list, max_length=30)
    min_salary_k: SalaryK | None = None
    max_salary_k: SalaryK | None = None
    min_daily_salary: float | None = Field(default=None, gt=0, le=100000, allow_inf_nan=False)
    max_daily_salary: float | None = Field(default=None, gt=0, le=100000, allow_inf_nan=False)
    experience_years_max: int | None = Field(default=None, ge=1, le=50, strict=True)
    require_education: list[RuleTerm] = Field(default_factory=list, max_length=12)
    exclude_education: list[RuleTerm] = Field(default_factory=list, max_length=12)
    ai_scout_rules: list[ScoutRule] = Field(default_factory=list, max_length=24)
    title_exclusions: list[RuleTerm] = Field(default_factory=list, max_length=50)
    company_exclusions: list[RuleTerm] = Field(default_factory=list, max_length=50)
    semantic_required: list[SemanticRule] = Field(default_factory=list, max_length=12)
    semantic_excluded: list[SemanticRule] = Field(default_factory=list, max_length=12)
    auto: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def check_salary_order(self):
        if self.require_education and self.exclude_education:
            raise ValueError("请在按最低学历筛选和排除指定学历中选择一种。")
        if len({comparable_text(rule.keyword) for rule in self.ai_scout_rules}) != len(self.ai_scout_rules):
            raise ValueError("AI 规则关键词不能重复。")
        if self.min_salary_k is not None and self.max_salary_k is not None and self.min_salary_k > self.max_salary_k:
            raise ValueError("最低月薪不能高于最高月薪。")
        if (self.min_daily_salary is not None and self.max_daily_salary is not None
                and self.min_daily_salary > self.max_daily_salary):
            raise ValueError("最低日薪不能高于最高日薪。")
        return self

    def semantic_config(self):
        return [self.semantic_required, self.semantic_excluded, [rule.model_dump() for rule in self.ai_scout_rules]]


def init_schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS recruitment_cleaning_profiles (
            owner TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
            profile TEXT NOT NULL CHECK (profile IN ('general', 'internship', 'full_time')),
            rules TEXT NOT NULL,
            PRIMARY KEY(owner, profile)
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
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        for table in ("recruitment_listings", "recruitment_runs"):
            if "profile" not in {column[1] for column in conn.execute(f"PRAGMA table_info({table})")}:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN profile TEXT NOT NULL DEFAULT 'general'")
        columns = {column[1] for column in conn.execute("PRAGMA table_info(recruitment_listings)")}
        for column in ("experience", "education"):
            if column not in columns:
                conn.execute(f"ALTER TABLE recruitment_listings ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS recruitment_recheck_requirements
            AFTER UPDATE OF experience, education, description ON recruitment_listings
            WHEN NEW.experience IS NOT OLD.experience OR NEW.education IS NOT OLD.education
                 OR (NEW.description IS NOT OLD.description AND EXISTS (
                    SELECT 1 FROM recruitment_cleaning_profiles p WHERE p.owner=NEW.owner AND p.profile=NEW.profile
                    AND (json_extract(p.rules, '$.experience_years_max') IS NOT NULL
                    OR json_array_length(json_extract(p.rules, '$.require_education')) > 0
                    OR json_array_length(json_extract(p.rules, '$.exclude_education')) > 0)
                 ))
            BEGIN
                DELETE FROM recruitment_cleaning_results
                WHERE owner=NEW.owner AND source=NEW.source AND url_key=NEW.url_key AND status <> 'released';
            END
        """)
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='recruitment_cleaning_rules'").fetchone():
            conn.execute("""
                INSERT OR IGNORE INTO recruitment_cleaning_profiles
                SELECT owner, 'general', rules FROM recruitment_cleaning_rules
            """)
            conn.execute("DROP TABLE recruitment_cleaning_rules")
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS recruitment_recheck_moved_listing
            AFTER UPDATE OF profile ON recruitment_listings WHEN NEW.profile <> OLD.profile
            BEGIN
                DELETE FROM recruitment_cleaning_results WHERE owner=NEW.owner AND source=NEW.source AND url_key=NEW.url_key;
            END
        """)


def load_rules(conn, owner, profile):
    row = conn.execute("SELECT rules FROM recruitment_cleaning_profiles WHERE owner=? AND profile=?", (owner, profile)).fetchone()
    return CleaningRules.model_validate_json(row["rules"]) if row else CleaningRules()


def save_rules(conn, owner, profile, rules):
    conn.execute("""
        INSERT INTO recruitment_cleaning_profiles VALUES (?, ?, ?)
        ON CONFLICT(owner, profile) DO UPDATE SET rules=excluded.rules
    """, (owner, profile, rules.model_dump_json()))


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
    units = {low_unit, high_unit}
    minimum = float(low) * PAY_SCALE[low_unit or high_unit]
    maximum = float(high or low) * PAY_SCALE[high_unit or low_unit]
    if not period:
        if units & {"k", "千", "千元"}:
            pass
        elif units & {"万", "万元"} and maximum < 100_000:
            pass
        else:
            return None, None
    return (minimum, maximum) if 0 < minimum <= maximum <= 10_000_000 else (None, None)


def daily_pay(value):
    text = re.sub(r"\s+", "", comparable_text(value)).replace("–", "-").replace("—", "-")
    match = DAILY_PAY.fullmatch(text)
    if not match:
        return None, None
    low, high = map(float, (match[1], match[2] or match[1]))
    return (low, high) if 0 < low <= high <= 100000 else (None, None)


def internship_salary_decision(salary, rules):
    days = INTERNSHIP_WORKDAYS_PER_MONTH
    if rules.min_daily_salary is not None or rules.max_daily_salary is not None:
        minimum, maximum = rules.min_daily_salary, rules.max_daily_salary
    else:
        minimum, maximum = (round(value * 1000 / days, 2) if value is not None else None
                            for value in (rules.min_salary_k, rules.max_salary_k))
    if minimum is None and maximum is None:
        return "passed", ""
    low, high = daily_pay(salary)
    if low is None:
        low, high = monthly_pay(salary)
        if low is None:
            return "review", "薪资口径或金额待核对"
        low, high = round(low / days, 2), round(high / days, 2)
    if (minimum is not None and high < minimum) or (maximum is not None and low > maximum):
        return "rejected", f"薪资「{salary}」按每月 {days} 个工作日换算后与目标区间无交集"
    return "passed", ""


def salary_decision(salary, rules, *, profile=DEFAULT_PROFILE):
    if profile == "internship":
        return internship_salary_decision(salary, rules)
    configured = False
    for label, parser, minimum, maximum, scale in (
        ("月薪", monthly_pay, rules.min_salary_k, rules.max_salary_k, 1000),
        ("日薪", daily_pay, rules.min_daily_salary, rules.max_daily_salary, 1),
    ):
        if minimum is None and maximum is None:
            continue
        configured = True
        low, high = parser(salary)
        if low is None:
            continue
        if ((minimum is not None and high < minimum * scale) or (maximum is not None and low > maximum * scale)):
            return "rejected", f"{label}「{salary}」与目标区间无交集"
        return "passed", ""
    if configured:
        reason = "月薪无法确认" if rules.min_daily_salary is None and rules.max_daily_salary is None else "薪资口径或金额待核对"
        return "review", reason
    return "passed", ""


def job_experience(row):
    field = re.sub(r"\s+", "", comparable_text(row["experience"])).replace("–", "-").replace("—", "-")
    if any(word in field for word in ("不限", "无经验", "应届", "无需")):
        return None, ""
    if match := EXPERIENCE_FIELD.fullmatch(field):
        return int(match["years"]), row["experience"]
    for clause in re.split(r"[\n。；;，,]", comparable_text(row["description"]).replace("–", "-").replace("—", "-")):
        if any(word in clause for word in ("优先", "无需", "不限", "不要求", "可放宽")):
            continue
        clause = re.sub(r"\s+", "", clause)
        if match := EXPERIENCE_FIELD.fullmatch(clause) or EXPERIENCE.search(clause):
            return int(match["years"]), match[0]
    return None, ""


def education_levels(text):
    return {EDUCATION_TERMS[term] for term in EDUCATION.findall(text)}


def education_rejection(row, rules):
    value = row["education"]
    if not value:
        value = " ".join(
            clause for clause in re.split(r"[\n。；;，,]", row["description"])
            if EDUCATION.fullmatch(clause.strip())
            or (EDUCATION.search(clause) and any(word in clause for word in ("学历", "以上"))
            and not any(word in clause for word in ("优先", "不限", "可放宽"))
            )
        )
    if not value or "不限" in value:
        return ""
    levels = education_levels(value)
    for term in rules.exclude_education:
        if term in value or levels.intersection(education_levels(term)):
            return f"学历要求「{value[:80]}」命中排除项「{term}」"
    if rules.require_education and levels and not any(term in value for term in rules.require_education):
        thresholds = set().union(*(education_levels(term) for term in rules.require_education))
        if thresholds and min(map(EDUCATION_RANK.get, levels)) < min(map(EDUCATION_RANK.get, thresholds)):
            return f"学历要求「{value[:80]}」低于设定的最低学历"
    return ""


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
        status, reason = salary_decision(row["salary"], rules, profile=row["profile"])
        if status == "rejected":
            return status, reason
        if status == "review":
            missing.append(reason)
        if rules.experience_years_max is not None:
            years, evidence = job_experience(row)
            if years is not None and years >= rules.experience_years_max:
                return "rejected", f"经验要求「{evidence}」达到 {rules.experience_years_max} 年上限"
        if rules.require_education or rules.exclude_education:
            if reason := education_rejection(row, rules):
                return "rejected", reason
    return ("review", "、".join(missing)) if missing else ("passed", "")


def stored_counts(conn, owner, profile):
    counts = dict.fromkeys(STATUSES, 0)
    for row in conn.execute(f"""
        SELECT COALESCE({EFFECTIVE_STATUS}, 'unreviewed') AS status, count(*) AS count
        FROM recruitment_listings j
        LEFT JOIN recruitment_cleaning_results r USING(owner, source, url_key)
        {SEMANTIC_JOIN}
        WHERE j.owner=? AND j.profile=? GROUP BY 1
    """, (owner, profile)):
        counts["passed" if row["status"] == "released" else row["status"]] += row["count"]
    return counts


LISTINGS = """
    SELECT j.source, j.url_key, j.title, j.company, j.location, j.salary, j.experience, j.education,
           COALESCE(d.description, j.description) AS description,
           r.status, r.reason, j.profile
    FROM recruitment_listings j
    LEFT JOIN recruitment_cleaning_results r USING(owner, source, url_key)
    LEFT JOIN recruitment_job_details d USING(owner, source, url_key)
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


def preview(conn, owner, profile, rules):
    rows = list(conn.execute(LISTINGS + " AND j.profile=? ORDER BY j.source, j.url_key", (owner, profile)))
    results = list(result_rows(rows, rules))
    snapshot = [owner, profile, rules.model_dump(), load_rules(conn, owner, profile).model_dump(), [tuple(row) for row in rows]]
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
    rules = {profile: load_rules(conn, owner, profile) for profile in PROFILES}
    if not any(rule.auto for rule in rules.values()):
        return {}
    results = []
    for start in range(0, len(urls), 500):
        batch = urls[start:start + 500]
        placeholders = ", ".join("?" for _ in batch)
        rows = conn.execute(LISTINGS + f" AND j.source=? AND j.url_key IN ({placeholders})", (owner, source, *batch))
        for row in rows:
            rule = rules[row["profile"]]
            if rule.auto:
                results.extend(result_rows((row,), rule))
    if not results:
        return {}
    write_results(conn, owner, results)
    return result_counts(results)

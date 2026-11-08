from datetime import date
from io import BytesIO
import json
from typing import Literal

from flask import Blueprint, jsonify, request, send_file
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ..paths import PROJECT_ROOT
from .collector import CollectionSettings
from .store import SOURCES


class JobQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    q: str = Field(default="", max_length=120)
    company_name: str = Field(default="", max_length=100)
    location: str = Field(default="", max_length=100)
    industry: str = Field(default="", max_length=100)
    company_nature: str = Field(default="", max_length=100)
    education: str = Field(default="", max_length=100)
    source: Literal["", "ncss", "api", "shixiseng", "website"] = ""
    job_type: Literal["", "intern", "graduate", "experienced", "unknown"] = ""
    salary_unit: Literal["", "month", "day", "year", "hour", "unknown"] = ""
    salary_min: float | None = Field(default=None, ge=0, le=10000000, allow_inf_nan=False)
    salary_max: float | None = Field(default=None, ge=0, le=10000000, allow_inf_nan=False)
    date_from: date | None = None
    date_to: date | None = None
    days: int = Field(default=30, ge=0, le=3650)
    sort: Literal["recent", "newest", "salary"] = "recent"
    page: int = Field(default=1, ge=1, le=100000)
    page_size: int = Field(default=12, ge=1, le=60)

    @model_validator(mode="after")
    def comparable_salary(self):
        if (self.salary_min is not None or self.salary_max is not None) and self.salary_unit not in {"month", "day", "year", "hour"}:
            raise ValueError("筛选薪资时请选择计薪周期")
        if self.salary_min is not None and self.salary_max is not None and self.salary_min > self.salary_max:
            raise ValueError("薪资下限不能大于上限")
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("起始日期不能晚于结束日期")
        if self.sort == "salary" and not self.salary_unit:
            self.salary_unit = "month"
        return self

    def filters(self):
        return self.model_dump(mode="json", exclude={"page", "page_size", "sort"})


def create_blueprint(collector, login_required, admin_required, current_user):
    bp = Blueprint("job_market", __name__, url_prefix="/api/job-market")
    store = collector.store

    @bp.after_request
    def private(response):
        response.headers["Cache-Control"] = "no-store"
        return response

    @bp.errorhandler(ValidationError)
    def bad_input(error):
        return jsonify(message="请检查筛选条件、日期、计薪周期和采集设置。"), 400

    @bp.get("/jobs")
    @login_required
    def jobs():
        query = JobQuery.model_validate(request.args.to_dict())
        return jsonify(store.jobs(query.filters(), query.page, query.page_size, query.sort))

    @bp.get("/jobs/<job_id>")
    @login_required
    def detail(job_id):
        row = store.detail(job_id)
        return jsonify(data=row) if row else (jsonify(message="岗位记录不存在。"), 404)

    @bp.get("/stats")
    @login_required
    def stats():
        return jsonify(data=store.stats(JobQuery.model_validate(request.args.to_dict()).filters()))

    @bp.get("/status")
    @login_required
    def status():
        companies_path = PROJECT_ROOT / "backend/integrations/jobhunter/vendor/config/company_urls.json"
        companies = json.loads(companies_path.read_text(encoding="utf-8"))
        return jsonify(settings=store.settings(), runs=store.runs(), sources=SOURCES,
            can_manage=current_user()["role"] == "super_admin",
            companies=[{"name": row["name"], "industry": row.get("industry", "")} for row in companies],
            upstream="https://github.com/Bynlk/JobHunter")

    @bp.put("/settings")
    @admin_required
    def settings():
        config = CollectionSettings.model_validate(request.get_json(silent=True)).model_dump()
        store.save_settings(config)
        return jsonify(message="采集计划已保存。", settings=store.settings())

    @bp.post("/collect")
    @admin_required
    def collect():
        run_id = collector.start()
        if not run_id:
            return jsonify(message="已有采集任务正在运行。"), 409
        return jsonify(message="采集已开始，岗位会分批入库。", run_id=run_id), 202

    @bp.delete("/collect")
    @admin_required
    def cancel():
        store.cancel()
        return jsonify(message="已请求停止，已获取的记录会保留。"), 202

    @bp.get("/export")
    @login_required
    def export():
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font, PatternFill
        except ImportError:
            return jsonify(message="导出组件未安装，请安装 requirements.txt。"), 503
        query = JobQuery.model_validate(request.args.to_dict())
        result = store.jobs(query.filters(), page=1, size=10000, sort=query.sort)
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "岗位样本"
        columns = [("job_title", "岗位"), ("company_name", "公司"), ("location", "地点"), ("salary", "薪资原文"),
            ("salary_unit", "计薪周期"), ("job_type", "来源分类"), ("education", "学历"), ("industry", "行业"),
            ("company_nature", "公司性质"), ("company_size", "公司规模"), ("welfare", "福利"), ("publish_date", "来源发布日期"),
            ("first_seen", "首次发现"), ("last_seen", "最近采集"), ("source_label", "来源"), ("job_url", "原始链接"), ("job_desc", "岗位描述")]
        sheet.append([title for _, title in columns])
        for row in result["items"]:
            values = []
            for key, _ in columns:
                value = str(row.get(key) or "")
                if value.lstrip().startswith(("=", "+", "-", "@")):
                    value = "'" + value
                values.append(value)
            sheet.append(values)
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="246D80")
        from openpyxl.utils import get_column_letter
        for index in range(1, len(columns) + 1):
            sheet.column_dimensions[get_column_letter(index)].width = 24 if index < 16 else 60
        notes = workbook.create_sheet("统计说明")
        for text in ("仅代表采集样本，不代表全市场规模或实时在招状态。", "日薪、月薪、年薪分别统计，不默认互相换算。", "岗位类型沿用来源分类或标题推断；请核对原站。", f"匹配 {result['total']} 条，导出 {len(result['items'])} 条；单次最多导出 10000 条。"):
            notes.append([text])
        notes.column_dimensions["A"].width = 100
        output = BytesIO()
        workbook.save(output)
        output.seek(0)
        response = send_file(output, as_attachment=True, download_name="岗位行情样本.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response.headers["X-Export-Total"] = str(result["total"])
        return response

    return bp

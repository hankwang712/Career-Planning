/**
 * 前后端 API 契约。后端为 Python（Flask/FastAPI），这里把前端实际读写的载荷形状固定下来，
 * 作为后续把经典脚本里的裸 fetch 迁到类型化调用的基础。字段以现有接口实际返回为准。
 */

/** 规划报告生成：/api/career-report/generate/* */
export interface ReportGenerationRequest {
  workflow: {
    targets: string[];
    preferences?: string;
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

export interface ReportStartResponse {
  job_id: string;
  report_id: string;
}

export interface ReportRuntimeState {
  status: string;
  job_id?: string;
  report_id?: string;
  stage?: string;
  stage_detail?: string;
  progress?: unknown[];
}

/** 招聘信息采集：/api/job-market/collection */
export type CleaningStatus = "unreviewed" | "passed" | "rejected" | "review" | "released";

export interface RecruitmentListing {
  source: string;
  url_key: string;
  title: string;
  company: string;
  location: string;
  salary: string;
  url: string;
  updated_at: number;
  clean_status?: CleaningStatus;
  [key: string]: unknown;
}

export interface RecruitmentListingsPage {
  items: RecruitmentListing[];
  total: number;
  page: number;
  page_size: number;
  view_counts: Record<string, number>;
}

/** 接口错误载荷（后端统一返回 { message, code? }）。 */
export interface ApiErrorPayload {
  message?: string;
  code?: string;
}

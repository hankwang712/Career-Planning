/**
 * 类型化 fetch 封装，语义对齐旧版 requestJson：携带 cookie、JSON 解析、失败抛带状态码的错误。
 * 迁移时把经典脚本里的裸 fetch 替换为这里的 apiGet/apiPost，即可获得载荷类型检查。
 */
import type { ApiErrorPayload } from "./types";

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

async function request<T>(url: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(url, { credentials: "include", ...options });
  const payload: ApiErrorPayload & T = await response.json().catch(() => ({}) as ApiErrorPayload & T);
  if (!response.ok) {
    throw new ApiError(payload.message || `请求失败：${response.status}`, response.status, payload.code);
  }
  return payload;
}

export function apiGet<T>(url: string): Promise<T> {
  return request<T>(url);
}

export function apiPost<T>(url: string, body: unknown): Promise<T> {
  return request<T>(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
}

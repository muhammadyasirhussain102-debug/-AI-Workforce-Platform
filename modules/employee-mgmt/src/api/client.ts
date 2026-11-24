const DEFAULT_API_BASE_URL = "http://localhost:8000/api/v1";
const DEFAULT_TIMEOUT_MS = 15000;

function resolveApiBaseUrl(): string {
  const meta = import.meta as ImportMeta & {
    env?: Record<string, string | undefined>;
  };
  const configuredUrl = meta.env?.VITE_API_BASE_URL?.trim();
  const baseUrl = configuredUrl || DEFAULT_API_BASE_URL;
  return baseUrl.replace(/\/+$/, "");
}

export const API_BASE_URL = resolveApiBaseUrl();

export class ApiError extends Error {
  public readonly status: number;
  public readonly detail: string;

  constructor(message: string, status: number, detail?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail ?? message;
  }
}

export interface ApiRequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  headers?: Record<string, string>;
  timeoutMs?: number;
  /**
   * Set to true for whistleblower / anonymous endpoints so browser cookies
   * and session credentials are never attached to the request.
   */
  anonymous?: boolean;
}

export interface HealthResponse {
  status: string;
  module?: string;
}

export interface PunchPayload {
  employee_id: string;
  verification_source?: string;
  face_detected?: boolean;
}

export interface PunchResponse {
  id: number;
  tenant_id?: string;
  employee_id: string;
  check_in: string;
  check_out?: string | null;
  verification_source: string;
  status: string;
  message: string;
}

function normalizeEndpoint(endpoint: string): string {
  const trimmed = endpoint.trim();
  if (!trimmed) {
    throw new ApiError("API endpoint cannot be empty.", 400);
  }
  return trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
}

async function parseResponseBody(response: Response): Promise<unknown> {
  if (response.status === 204) {
    return null;
  }

  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    try {
      return await response.json();
    } catch {
      return null;
    }
  }

  const text = await response.text();
  return text ? { detail: text } : null;
}

function extractErrorMessage(data: unknown, fallback: string): string {
  if (data && typeof data === "object" && "detail" in data) {
    const detail = (data as { detail?: unknown }).detail;
    if (typeof detail === "string" && detail.trim()) {
      return detail;
    }
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0];
      if (first && typeof first === "object" && "msg" in first) {
        return String((first as { msg: unknown }).msg);
      }
    }
  }
  return fallback;
}

export async function apiRequest<T>(
  endpoint: string,
  options: ApiRequestOptions = {}
): Promise<T> {
  const {
    method = "GET",
    body,
    headers = {},
    timeoutMs = DEFAULT_TIMEOUT_MS,
    anonymous = false,
  } = options;

  const url = `${API_BASE_URL}${normalizeEndpoint(endpoint)}`;
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);

  const requestHeaders: Record<string, string> = {
    Accept: "application/json",
    ...headers,
  };

  if (body !== undefined && !requestHeaders["Content-Type"]) {
    requestHeaders["Content-Type"] = "application/json";
  }

  try {
    const response = await fetch(url, {
      method,
      headers: requestHeaders,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      credentials: anonymous ? "omit" : "include",
      signal: controller.signal,
    });

    const data = await parseResponseBody(response);

    if (!response.ok) {
      const message = extractErrorMessage(
        data,
        `Request failed with status ${response.status}`
      );
      throw new ApiError(message, response.status, message);
    }

    return data as T;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError("Request timed out. Please try again.", 408);
    }
    throw new ApiError(
      "Unable to reach the server. Check that the backend API is running.",
      0
    );
  } finally {
    window.clearTimeout(timeoutId);
  }
}

export async function checkHealth(): Promise<HealthResponse> {
  return apiRequest<HealthResponse>("/health", { method: "GET" });
}

export async function punchAttendance(
  payload: PunchPayload
): Promise<PunchResponse> {
  const employeeId = payload.employee_id?.trim();
  if (!employeeId) {
    throw new ApiError("Employee ID is required.", 400);
  }

  const verificationSource = (payload.verification_source || "Face ID").trim();
  const faceDetected = payload.face_detected ?? true;

  if (!faceDetected) {
    throw new ApiError(
      "Face ID verification failed: No valid face detected.",
      400
    );
  }

  return apiRequest<PunchResponse>("/attendance/punch", {
    method: "POST",
    body: {
      employee_id: employeeId,
      verification_source: verificationSource,
      face_detected: faceDetected,
    },
  });
}
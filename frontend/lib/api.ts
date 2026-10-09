// The panel's only path to the backend. The token is the session from
// phone sign-in; errors carry the backend's stable English `code`, and the
// UI translates by code (lib/fa.ts `errorText`).

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";
const TOKEN_KEY = "ge_token";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string,
              public extra: Record<string, unknown> = {}) {
    super(message);
  }
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* private mode: the session lasts until the tab closes */
  }
}

type Body = Record<string, unknown> | FormData | undefined;

export async function api<T = unknown>(path: string, method = "GET", body?: Body): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const resp = await fetch(`${API_BASE}/api${path}`, { method, headers, body: payload });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const detail = (data as { detail?: unknown }).detail;
    if (detail && typeof detail === "object" && "code" in detail) {
      const { code, message, ...extra } = detail as { code: string; message: string } & Record<string, unknown>;
      throw new ApiError(resp.status, code, message, extra);
    }
    throw new ApiError(resp.status, resp.status === 422 ? "validation_error" : "request_failed", String(resp.status));
  }
  return data as T;
}

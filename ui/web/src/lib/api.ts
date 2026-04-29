/**
 * Shared API helpers for the TPA UI.
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000/ingress";
export const SUBMISSION_API =
  process.env.NEXT_PUBLIC_SUBMISSION_BASE || "http://localhost:8000/submission";
export const WORKFLOW_API =
  process.env.NEXT_PUBLIC_WORKFLOW_BASE || "http://localhost:8000/workflow";
export const SEARCH_API =
  process.env.NEXT_PUBLIC_SEARCH_BASE || "http://localhost:8000/search";
export const VALIDATOR_API =
  process.env.NEXT_PUBLIC_VALIDATOR_BASE || "http://localhost:8000/validator";
export const PREDICTOR_API =
  process.env.NEXT_PUBLIC_PREDICTOR_BASE || "http://localhost:8000/predictor";
export const CHAT_API =
  process.env.NEXT_PUBLIC_CHAT_BASE || "http://localhost:8000/chat";

/** Build fetch headers, optionally including auth token. */
export function authHeaders(token?: string | null): HeadersInit {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (token) h["Authorization"] = `Bearer ${token}`;
  return h;
}

/** Typed fetch wrapper. */
export async function apiFetch<T>(
  url: string,
  opts?: RequestInit & { token?: string | null },
): Promise<T> {
  const { token, ...init } = opts ?? {};
  const res = await fetch(url, {
    ...init,
    headers: { ...authHeaders(token), ...(init.headers ?? {}) },
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

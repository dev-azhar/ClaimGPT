const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8001";

export interface Claim {
  id: string;
  policy_id: string | null;
  patient_id: string | null;
  status: string;
  source: string | null;
  created_at: string;
  updated_at: string;
}

export interface ClaimListResponse {
  claims: Claim[];
  total: number;
}

export interface ServiceHealth {
  status: string;
  database: string;
}

const SERVICES: Record<string, number> = {
  ingress: 8001,
  ocr: 8002,
  parser: 8003,
  coding: 8004,
  predictor: 8005,
  validator: 8006,
  workflow: 8007,
  submission: 8008,
  chat: 8009,
  search: 8010,
};

async function apiFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!resp.ok) {
    throw new Error(`API error: ${resp.status} ${resp.statusText}`);
  }
  return resp.json();
}

export async function fetchClaims(offset = 0, limit = 20): Promise<ClaimListResponse> {
  return apiFetch(`${API_BASE}/claims?offset=${offset}&limit=${limit}`);
}

export async function fetchClaim(claimId: string): Promise<Claim> {
  return apiFetch(`${API_BASE}/claims/${claimId}`);
}

export async function startWorkflow(claimId: string) {
  const base = API_BASE.replace(/:\d+/, ":8007");
  return apiFetch(`${base}/workflow/start/${claimId}`, { method: "POST" });
}

export async function runValidation(claimId: string) {
  const base = API_BASE.replace(/:\d+/, ":8006");
  return apiFetch(`${base}/validate/${claimId}`, { method: "POST" });
}

export async function submitClaim(claimId: string, payer?: string) {
  const base = API_BASE.replace(/:\d+/, ":8008");
  return apiFetch(`${base}/submit/${claimId}`, {
    method: "POST",
    body: JSON.stringify({ payer: payer || "generic" }),
  });
}

export async function checkHealth(service: string): Promise<ServiceHealth> {
  const port = SERVICES[service] || 8001;
  const base = API_BASE.replace(/:\d+/, `:${port}`);
  return apiFetch(`${base}/health`);
}

export async function checkAllHealth(): Promise<Record<string, ServiceHealth | null>> {
  const results: Record<string, ServiceHealth | null> = {};
  await Promise.all(
    Object.keys(SERVICES).map(async (svc) => {
      try {
        results[svc] = await checkHealth(svc);
      } catch {
        results[svc] = null;
      }
    })
  );
  return results;
}

export { SERVICES };

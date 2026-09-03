import { NextRequest, NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

interface RegisterBody {
  username: string;
  password?: string;
  password_hash?: string;
  role: 'patient' | 'tpa';
  provider?: string;
  first_name?: string;
  last_name?: string;
  phone?: string;
  organization?: string;
  employee_id?: string;
  dob?: string;
  gender?: string;
  policy?: string;
  sum_insured?: string | number;
}

export async function POST(request: NextRequest) {
  try {
    const body = (await request.json()) as RegisterBody;

    const isEntra = body?.provider === 'entra';
    const pwd = (body.password_hash || body.password || '').trim();
    if (!body?.username || !body?.role || (!isEntra && !pwd)) {
      return NextResponse.json({ error: 'Missing required registration fields.' }, { status: 400 });
    }

    const profilePayload: Record<string, unknown> = {
      provider: body.provider || 'local',
      username: body.username,
      password_hash: body.password_hash || pwd || undefined,
      role: body.role === 'patient' ? 'submitter' : 'admin',
      first_name: body.first_name,
      last_name: body.last_name,
      phone: body.phone,
      organization: body.organization,
      employee_id: body.employee_id,
      dob: body.dob,
      gender: body.gender,
      policy: body.policy,
      sum_insured: body.sum_insured,
    };

    const rawBase = process.env.INGRESS_API || process.env.NEXT_PUBLIC_API_BASE || 'http://127.0.0.1:8000/ingress';
    const cleanBase = rawBase.replace(/\/+$/, '');
    const baseWithoutIngress = cleanBase.replace(/\/ingress$/, '');

    const candidateUrls = [
      `${cleanBase}/auth/register`,
      `${baseWithoutIngress}/auth/register`,
      `${cleanBase}/ingress/auth/register`,
      `${baseWithoutIngress}/ingress/auth/register`,
      'http://claimsguru-api-test:8000/ingress/auth/register',
      'http://host.docker.internal:8000/ingress/auth/register',
      'http://127.0.0.1:8000/ingress/auth/register',
      'http://localhost:8000/ingress/auth/register',
    ];

    const urlsToTry = Array.from(new Set(candidateUrls));

    let res: Response | null = null;
    let data: any = null;
    const attemptLog: Array<{ url: string; status?: number; error?: string }> = [];

    for (const url of urlsToTry) {
      try {
        const attempt = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(profilePayload),
        });
        if (attempt.status !== 404) {
          res = attempt;
          data = await attempt.json().catch(() => ({}));
          attemptLog.push({ url, status: attempt.status });
          break;
        } else {
          attemptLog.push({ url, status: 404, error: 'Route not found (404)' });
        }
      } catch (err) {
        attemptLog.push({ url, error: err instanceof Error ? err.message : String(err) });
      }
    }

    if (!res) {
      console.error(
        '[REGISTER ERROR] Could not connect to FastAPI backend for user registration!\n' +
        `Username: ${profilePayload.username}\n` +
        `Configured INGRESS_API: ${process.env.INGRESS_API || '(not set)'}\n` +
        `Configured NEXT_PUBLIC_API_BASE: ${process.env.NEXT_PUBLIC_API_BASE || '(not set)'}\n` +
        'Attempted URLs:\n' +
        attemptLog.map((a) => `  - ${a.url} => ${a.status ? `HTTP ${a.status}` : `Error: ${a.error}`}`).join('\n')
      );

      // Microservice backend is offline — succeed in local standalone mode
      return NextResponse.json({ success: true, is_local_demo: true });
    }

    if (!res.ok) {
      const msg =
        typeof data?.detail === 'string'
          ? data.detail
          : typeof data?.error === 'string'
            ? data.error
            : typeof data?.message === 'string'
              ? data.message
              : 'Registration failed.';

      console.error(`[REGISTER ERROR] Backend returned HTTP ${res.status} for ${profilePayload.username}: ${msg}`);
      return NextResponse.json({ error: msg }, { status: res.status });
    }

    console.info(`[REGISTER SUCCESS] User ${profilePayload.username} registered with backend.`);
    return NextResponse.json({ success: true, detail: data });
  } catch (error) {
    const errorMsg = error instanceof Error ? error.message : String(error);
    console.error(`[REGISTER FATAL] Unexpected error during registration: ${errorMsg}`);
    return NextResponse.json({ error: errorMsg }, { status: 500 });
  }
}
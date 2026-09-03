import { NextRequest, NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

interface SyncEntraBody {
  email: string;
  name?: string;
  first_name?: string;
  last_name?: string;
  company_name?: string;
  organization?: string;
  external_subject_id?: string;
  requested_role?: 'patient' | 'tpa';
  client_id?: string;
  phone?: string;
  dob?: string;
  gender?: string;
  policy?: string;
  sum_insured?: string | number;
}

export async function POST(request: NextRequest) {
  try {
    const body = (await request.json()) as SyncEntraBody;

    if (!body?.email) {
      return NextResponse.json({ error: 'Email is required for synchronization.' }, { status: 400 });
    }

    const payload: Record<string, unknown> = {
      email: body.email.trim().toLowerCase(),
      name: body.name,
      first_name: body.first_name,
      last_name: body.last_name,
      company_name: body.company_name || body.organization,
      organization: body.organization || body.company_name,
      external_subject_id: body.external_subject_id || body.email,
      requested_role: body.requested_role || 'patient',
      client_id: body.client_id,
      phone: body.phone,
      dob: body.dob,
      gender: body.gender,
      policy: body.policy,
      sum_insured: body.sum_insured,
    };

    const rawBase = process.env.INGRESS_API || process.env.NEXT_PUBLIC_API_BASE || 'http://127.0.0.1:8000/ingress';
    const cleanBase = rawBase.replace(/\/+$/, '');
    const baseWithoutIngress = cleanBase.replace(/\/ingress$/, '');

    const candidateUrls = [
      `${cleanBase}/auth/sync-entra-user`,
      `${baseWithoutIngress}/auth/sync-entra-user`,
      `${cleanBase}/ingress/auth/sync-entra-user`,
      `${baseWithoutIngress}/ingress/auth/sync-entra-user`,
      'http://claimsguru-api-test:8000/ingress/auth/sync-entra-user',
      'http://host.docker.internal:8000/ingress/auth/sync-entra-user',
      'http://127.0.0.1:8000/ingress/auth/sync-entra-user',
      'http://localhost:8000/ingress/auth/sync-entra-user',
    ];

    // Deduplicate candidate URLs while preserving order
    const urlsToTry = Array.from(new Set(candidateUrls));

    let res: Response | null = null;
    let data: any = null;
    const attemptLog: Array<{ url: string; status?: number; error?: string }> = [];

    for (const url of urlsToTry) {
      try {
        const attempt = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
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
        '[SYNC-ENTRA ERROR] Could not connect to FastAPI backend to synchronize Entra user with database!\n' +
        `User Email: ${payload.email}\n` +
        `Configured INGRESS_API: ${process.env.INGRESS_API || '(not set)'}\n` +
        `Configured NEXT_PUBLIC_API_BASE: ${process.env.NEXT_PUBLIC_API_BASE || '(not set)'}\n` +
        'Attempted URLs:\n' +
        attemptLog.map((a) => `  - ${a.url} => ${a.status ? `HTTP ${a.status}` : `Error: ${a.error}`}`).join('\n') + '\n' +
        'ACTION REQUIRED: Ensure INGRESS_API or NEXT_PUBLIC_API_BASE environment variable is set on the frontend container to a valid, reachable backend URL.'
      );

      // Backend is offline / standalone dev fallback
      const isOrg = body.requested_role === 'tpa';
      return NextResponse.json({
        success: true,
        user_id: `offline-${Date.now()}`,
        email: body.email,
        role: isOrg ? 'tpa' : 'patient',
        account_role: isOrg ? 'admin' : 'submitter',
        organization: isOrg ? 'Star Health' : undefined,
        organization_slug: isOrg ? 'star-health' : undefined,
        is_new_user: false,
        needs_onboarding: !isOrg,
        is_local_demo: true,
      });
    }

    if (!res.ok) {
      const msg =
        typeof data?.detail === 'string'
          ? data.detail
          : typeof data?.detail?.message === 'string'
            ? data.detail.message
            : typeof data?.error === 'string'
              ? data.error
              : 'Failed to synchronize Entra identity with database.';

      console.error(
        `[SYNC-ENTRA ERROR] Backend returned HTTP ${res.status} for ${payload.email}:\n` +
        `Error Detail: ${msg}\n` +
        `Response Body: ${JSON.stringify(data)}`
      );

      return NextResponse.json({ error: msg }, { status: res.status });
    }

    console.info(`[SYNC-ENTRA SUCCESS] Entra user ${payload.email} successfully synchronized with database.`);
    return NextResponse.json(data, { status: 200 });
  } catch (error) {
    const errorMsg = error instanceof Error ? error.message : String(error);
    console.error(`[SYNC-ENTRA FATAL] Unexpected error during sync: ${errorMsg}`);
    return NextResponse.json(
      { error: errorMsg },
      { status: 500 }
    );
  }
}


export type AuthRole = 'patient' | 'tpa';
export type AuthErrorField = 'username' | 'password' | 'role' | 'general';

export function getAuthErrorField(message: string): AuthErrorField {
  const lower = message.toLowerCase();
  if (
    lower.includes('role') ||
    lower.includes('not registered as') ||
    lower.includes('continue with correct identity') ||
    lower.includes('tpa adjuster')
  ) {
    return 'role';
  }
  if (lower.includes('username') || lower.includes('email') || lower.includes('not found')) {
    return 'username';
  }
  if (lower.includes('password')) {
    return 'password';
  }
  return 'general';
}

function getRoleLabel(role: string) {
  const normalized = role.trim().toLowerCase();
  if (normalized === 'reviewer' || normalized === 'tpa') {
    return 'TPA adjuster';
  }
  return 'patient';
}

function formatRoleMismatchMessage(requestedRole: AuthRole, accountRole: string) {
  const requestedLabel = requestedRole === 'patient' ? 'patient' : 'TPA adjuster';
  const accountLabel = getRoleLabel(accountRole);
  return `Username is not registered as ${requestedLabel}. It is registered as ${accountLabel}. Create a new account or continue with the correct identity.`;
}

export interface EntraConfig {
  clientId: string;
  tenantId: string;
  authority: string;
  redirectUri: string;
  scopes: string;
  subdomain?: string;
  patientUserFlow?: string;
  orgUserFlow?: string;
}

interface AuthConfig {
  url: string;
  realm: string;
  clientId: string;
  redirectUri: string;
}

export interface AuthSession {
  accessToken: string;
  refreshToken: string;
  idToken: string;
  expiresAt: number;
  role: AuthRole;
  /** Actual backend role: submitter (patient), admin, or reviewer (org staff). */
  accountRole?: 'submitter' | 'admin' | 'reviewer';
  /** Organization display name, present for admin/reviewer accounts. */
  organization?: string;
  /** Kebab-case organization slug used to build /{organization}/admin|review routes. */
  organizationSlug?: string;
  /** Identity provider used ('entra' | 'keycloak' | 'local') */
  provider?: 'entra' | 'keycloak' | 'local';
  /** Whether the newly registered patient needs to complete insurance details */
  needsOnboarding?: boolean;
  user: {
    id?: string;
    email: string;
    name: string;
    firstName?: string;
    lastName?: string;
    preferredUsername?: string;
    sub?: string;
    oid?: string;
  };
}

interface BeginAuthFlowOptions {
  role: AuthRole;
  isRegister?: boolean;
  loginHint?: string;
}

const AUTH_SESSION_KEY = 'claimgpt-auth-session';
const PKCE_STATE_KEY = 'claimgpt-pkce-state';
const PKCE_VERIFIER_KEY = 'claimgpt-pkce-verifier';
const ROLE_HINT_KEY = 'claimgpt-role-hint';
const AUTH_ACTION_KEY = 'claimgpt-auth-action';
const AUTH_PROVIDER_KEY = 'claimgpt-auth-provider';
const ENTRA_CLIENT_ID_KEY = 'claimgpt-entra-client-id';

/**
 * Check if Microsoft Entra External ID (CIAM) is enabled.
 * Controlled strictly by NEXT_PUBLIC_ENABLE_ENTRA_ID or NEXT_PUBLIC_AUTH_PROVIDER=entra.
 */
export function isEntraEnabled(): boolean {
  return process.env.NEXT_PUBLIC_ENABLE_ENTRA_ID === 'true' || process.env.NEXT_PUBLIC_AUTH_PROVIDER === 'entra';
}

export function getEntraConfig(role?: AuthRole, overrideClientId?: string): EntraConfig {
  const origin = typeof window !== 'undefined' ? window.location.origin : 'http://localhost:3000';

  let clientId = overrideClientId || '';
  if (!clientId) {
    if (role === 'tpa') {
      clientId =
        process.env.NEXT_PUBLIC_ORG_ENTRA_CLIENT_ID ||
        process.env.NEXT_PUBLIC_ENTRA_CLIENT_ID ||
        '';
    } else {
      clientId =
        process.env.NEXT_PUBLIC_ENTRA_PATIENT_CLIENT_ID ||
        process.env.NEXT_PUBLIC_ENTRA_CLIENT_ID ||
        '';
    }
  }

  const tenantId = process.env.NEXT_PUBLIC_ENTRA_TENANT_ID || 'common';
  const subdomain = process.env.NEXT_PUBLIC_ENTRA_SUBDOMAIN || '';
  const dynamicOrigin = typeof window !== 'undefined' && window.location.origin ? window.location.origin : origin;
  const redirectUri = dynamicOrigin ? `${dynamicOrigin}/auth/callback` : (process.env.NEXT_PUBLIC_ENTRA_REDIRECT_URI || `${origin}/auth/callback`);
  const scopes = process.env.NEXT_PUBLIC_ENTRA_SCOPES || 'openid profile email offline_access';

  let authority = process.env.NEXT_PUBLIC_ENTRA_AUTHORITY || '';
  if (!authority) {
    if (subdomain && tenantId) {
      authority = `https://${subdomain}.ciamlogin.com/${tenantId}`;
    } else if (subdomain) {
      authority = `https://${subdomain}.ciamlogin.com`;
    } else {
      authority = `https://login.microsoftonline.com/${tenantId}`;
    }
  }

  return {
    clientId,
    tenantId,
    authority: authority.replace(/\/+$/, ''),
    redirectUri,
    scopes,
    subdomain,
    patientUserFlow: process.env.NEXT_PUBLIC_ENTRA_USER_FLOW_PATIENT,
    orgUserFlow: process.env.NEXT_PUBLIC_ENTRA_USER_FLOW_ORG,
  };
}

export function getEntraEndpoints(role?: AuthRole, overrideClientId?: string) {
  const config = getEntraConfig(role, overrideClientId);
  let base = config.authority.replace(/\/+$/, '');
  // Strip trailing /v2.0 if present to avoid duplication
  base = base.replace(/\/v2\.0$/, '');

  return {
    authorizeUrl: `${base}/oauth2/v2.0/authorize`,
    tokenUrl: `${base}/oauth2/v2.0/token`,
  };
}

function getKeycloakConfig(): AuthConfig {
  const origin = typeof window !== 'undefined' ? window.location.origin : 'http://localhost:3001';
  const url = (process.env.NEXT_PUBLIC_KEYCLOAK_URL || 'http://localhost:8080').replace(/\/+$/, '');
  const realm = process.env.NEXT_PUBLIC_KEYCLOAK_REALM || 'claimgpt';
  const clientId = process.env.NEXT_PUBLIC_KEYCLOAK_CLIENT_ID || 'claimgpt-web';
  const redirectUri = process.env.NEXT_PUBLIC_KEYCLOAK_REDIRECT_URI || `${origin}/auth/callback`;

  return { url, realm, clientId, redirectUri };
}

function createRandomString(length = 32) {
  const array = new Uint8Array(length);
  window.crypto.getRandomValues(array);
  return Array.from(array, (byte) => byte.toString(16).padStart(2, '0')).join('').slice(0, length);
}

async function createPkceChallenge(verifier: string) {
  const encoder = new TextEncoder();
  const data = encoder.encode(verifier);
  const digest = await window.crypto.subtle.digest('SHA-256', data);
  const bytes = Array.from(new Uint8Array(digest));
  const base64 = btoa(String.fromCharCode(...bytes));
  return base64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}

function decodeJwtPayload(token: string): Record<string, unknown> | null {
  const parts = token.split('.');
  if (parts.length < 2) {
    return null;
  }

  try {
    const payload = parts[1];
    const normalized = payload.replace(/-/g, '+').replace(/_/g, '/');
    const padded = normalized.padEnd(normalized.length + ((4 - (normalized.length % 4)) % 4), '=');
    const decoded = window.atob(padded);
    const bytes = Uint8Array.from(decoded, (char) => char.charCodeAt(0));
    const text = new TextDecoder().decode(bytes);
    return JSON.parse(text) as Record<string, unknown>;
  } catch {
    return null;
  }
}

async function hashPasswordForTransport(password: string) {
  const encoder = new TextEncoder();
  const data = encoder.encode(password);
  const digest = await window.crypto.subtle.digest('SHA-256', data);
  const bytes = Array.from(new Uint8Array(digest));
  const hex = bytes.map((byte) => byte.toString(16).padStart(2, '0')).join('');
  return `sha256$${hex}`;
}

function normalizeRole(roles: string[], hintedRole?: string | null): AuthRole {
  const lowered = roles.map((role) => String(role).toLowerCase());
  if (lowered.includes('tpa') || lowered.includes('reviewer') || lowered.includes('admin') || lowered.includes('org_admin')) {
    return 'tpa';
  }
  if (lowered.includes('patient') || lowered.includes('submitter')) {
    return 'patient';
  }
  if (hintedRole === 'tpa') {
    return 'tpa';
  }
  return 'patient';
}

function buildSession(
  tokenResponse: Record<string, unknown>,
  hintedRole?: string | null,
  provider: 'entra' | 'keycloak' | 'local' = 'local'
): AuthSession {
  const accessToken = String(tokenResponse.access_token || '');
  const refreshToken = String(tokenResponse.refresh_token || '');
  const idToken = String(tokenResponse.id_token || '');
  const accessPayload = decodeJwtPayload(accessToken) || {};
  const idPayload = decodeJwtPayload(idToken) || {};

  // Extract roles from Keycloak or Entra claims
  const realmRoles = Array.isArray(accessPayload.realm_access)
    ? []
    : (accessPayload.realm_access as Record<string, unknown> | undefined)?.roles || [];
  const entraRoles = Array.isArray(accessPayload.roles)
    ? accessPayload.roles
    : Array.isArray(idPayload.roles)
    ? idPayload.roles
    : [];

  const roles = [...(Array.isArray(realmRoles) ? realmRoles : []), ...(Array.isArray(entraRoles) ? entraRoles : [])] as string[];

  const expiry = Number(accessPayload.exp || idPayload.exp || 0);
  const now = Math.floor(Date.now() / 1000);

  const email = String(
    accessPayload.email ||
    accessPayload.preferred_username ||
    (Array.isArray(accessPayload.emails) ? accessPayload.emails[0] : '') ||
    idPayload.email ||
    idPayload.preferred_username ||
    (Array.isArray(idPayload.emails) ? idPayload.emails[0] : '') ||
    'user@claimgpt.dev'
  );

  const firstName = String(
    accessPayload.given_name ||
    idPayload.given_name ||
    accessPayload.givenName ||
    idPayload.givenName ||
    ''
  );

  const lastName = String(
    accessPayload.family_name ||
    idPayload.family_name ||
    accessPayload.surname ||
    idPayload.surname ||
    accessPayload.familyName ||
    idPayload.familyName ||
    ''
  );

  const rawDisplayName = String(accessPayload.name || idPayload.name || '').trim();
  const cleanDisplayName = rawDisplayName && rawDisplayName.toLowerCase() !== 'unknown' ? rawDisplayName : '';
  const fullNameFromParts = firstName ? `${firstName} ${lastName}`.trim() : '';

  const name =
    fullNameFromParts ||
    cleanDisplayName ||
    email.split('@')[0] ||
    'ClaimsGuru User';

  const role = normalizeRole(roles, hintedRole);
  const accountRole: AuthSession['accountRole'] =
    roles.includes('admin')
      ? 'admin'
      : roles.includes('reviewer') || roles.includes('tpa')
      ? 'reviewer'
      : 'submitter';

  const rawCompanyName = String(
    accessPayload.company_name ||
    idPayload.company_name ||
    accessPayload.companyName ||
    idPayload.companyName ||
    accessPayload.organization ||
    idPayload.organization ||
    accessPayload.extension_Organization ||
    idPayload.extension_Organization ||
    accessPayload.extension_company_name ||
    idPayload.extension_company_name ||
    ''
  );

  const organization =
    rawCompanyName ||
    (typeof accessPayload.organization === 'string' ? accessPayload.organization : '') ||
    (typeof idPayload.organization === 'string' ? idPayload.organization : '') ||
    (role === 'tpa' ? 'Star Health' : undefined);

  const organizationSlug = organization
    ? organization.toLowerCase().replace(/[^a-z0-9]+/g, '-')
    : role === 'tpa'
    ? 'star-health'
    : undefined;

  return {
    accessToken: accessToken || `token-${Date.now()}`,
    refreshToken,
    idToken,
    expiresAt: expiry > now ? expiry : now + 86400,
    role,
    accountRole,
    organization,
    organizationSlug,
    provider,
    user: {
      id: String(accessPayload.oid || idPayload.oid || accessPayload.sub || idPayload.sub || ''),
      email,
      name,
      firstName: firstName || undefined,
      lastName: lastName || undefined,
      preferredUsername: String(accessPayload.preferred_username || idPayload.preferred_username || email),
      sub: String(accessPayload.sub || idPayload.sub || ''),
      oid: String(accessPayload.oid || idPayload.oid || ''),
    },
  };
}

export function saveSession(session: AuthSession) {
  sessionStorage.setItem(AUTH_SESSION_KEY, JSON.stringify(session));
}

export function getStoredAuthSession(): AuthSession | null {
  if (typeof window === 'undefined') {
    return null;
  }

  const stored = sessionStorage.getItem(AUTH_SESSION_KEY);
  if (!stored) {
    return null;
  }

  try {
    const session = JSON.parse(stored) as AuthSession;
    const now = Math.floor(Date.now() / 1000);
    if (!session.accessToken || session.expiresAt <= now) {
      clearAuthSession();
      return null;
    }
    return session;
  } catch {
    clearAuthSession();
    return null;
  }
}

export function clearAuthSession() {
  sessionStorage.removeItem(AUTH_SESSION_KEY);
  sessionStorage.removeItem(PKCE_STATE_KEY);
  sessionStorage.removeItem(PKCE_VERIFIER_KEY);
  sessionStorage.removeItem(ROLE_HINT_KEY);
  sessionStorage.removeItem(AUTH_ACTION_KEY);
  sessionStorage.removeItem(AUTH_PROVIDER_KEY);
}

/**
 * Begin authentication with Microsoft Entra External ID (CIAM).
 * Redirects the user directly to the Microsoft-hosted authentication interface.
 */
export async function beginEntraAuthFlow({ role, isRegister = false, loginHint }: BeginAuthFlowOptions) {
  if (typeof window === 'undefined') {
    return;
  }

  const config = getEntraConfig(role);
  const state = createRandomString(24);
  const verifier = createRandomString(64);
  const challenge = await createPkceChallenge(verifier);

  sessionStorage.setItem(PKCE_STATE_KEY, state);
  sessionStorage.setItem(PKCE_VERIFIER_KEY, verifier);
  sessionStorage.setItem(ROLE_HINT_KEY, role);
  sessionStorage.setItem(AUTH_ACTION_KEY, isRegister ? 'register' : 'login');
  sessionStorage.setItem(AUTH_PROVIDER_KEY, 'entra');
  sessionStorage.setItem(ENTRA_CLIENT_ID_KEY, config.clientId);

  const { authorizeUrl } = getEntraEndpoints(role, config.clientId);
  const params = new URLSearchParams({
    client_id: config.clientId,
    redirect_uri: config.redirectUri,
    response_type: 'code',
    response_mode: 'query',
    scope: config.scopes,
    state,
    code_challenge: challenge,
    code_challenge_method: 'S256',
    prompt: 'select_account',
  });

  if (loginHint) {
    params.set('login_hint', loginHint);
  }

  const userFlow = role === 'patient' ? config.patientUserFlow : config.orgUserFlow;
  if (userFlow) {
    params.set('p', userFlow);
  }

  // Redirect directly to the Microsoft Entra External ID login interface
  window.location.assign(`${authorizeUrl}?${params.toString()}`);
}

/**
 * Standard OIDC / Keycloak auth flow.
 */
export async function beginAuthFlow({ role, isRegister = false, loginHint }: BeginAuthFlowOptions) {
  if (isEntraEnabled()) {
    return beginEntraAuthFlow({ role, isRegister, loginHint });
  }

  if (typeof window === 'undefined') {
    return;
  }

  const config = getKeycloakConfig();
  const state = createRandomString(24);
  const verifier = createRandomString(64);
  const challenge = await createPkceChallenge(verifier);

  sessionStorage.setItem(PKCE_STATE_KEY, state);
  sessionStorage.setItem(PKCE_VERIFIER_KEY, verifier);
  sessionStorage.setItem(ROLE_HINT_KEY, role);
  sessionStorage.setItem(AUTH_ACTION_KEY, isRegister ? 'register' : 'login');
  sessionStorage.setItem(AUTH_PROVIDER_KEY, 'keycloak');

  const params = new URLSearchParams({
    client_id: config.clientId,
    redirect_uri: config.redirectUri,
    response_type: 'code',
    scope: 'openid profile email',
    state,
    code_challenge: challenge,
    code_challenge_method: 'S256',
    kc_action: isRegister ? 'REGISTER' : 'LOGIN',
  });

  if (loginHint) {
    params.set('login_hint', loginHint);
  }

  const authUrl = `${config.url}/realms/${config.realm}/protocol/openid-connect/auth?${params.toString()}`;
  window.location.assign(authUrl);
}

export async function authenticateWithPassword({
  username,
  password,
  role,
}: {
  username: string;
  password: string;
  role: AuthRole;
}) {
  if (typeof window === 'undefined') {
    return null;
  }

  try {
    const passwordHash = await hashPasswordForTransport(password);
    let backendResponse: Response | null = null;

    const requestBody: Record<string, unknown> =
      role === 'patient'
        ? { username, password_hash: passwordHash, role: 'submitter' }
        : { username, password_hash: passwordHash };

    try {
      backendResponse = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestBody),
      });
    } catch {
      backendResponse = null;
    }

    if (backendResponse) {
      const backendData = await backendResponse.json().catch(() => ({}));
      if (backendResponse.ok) {
        const accountRole = (
          backendData.role === 'admin' || backendData.role === 'reviewer' || backendData.role === 'submitter'
            ? backendData.role
            : role === 'patient' ? 'submitter' : 'admin'
        ) as AuthSession['accountRole'];
        const organization = typeof backendData.organization === 'string' ? backendData.organization : (role === 'tpa' ? 'Star Health' : undefined);
        const organizationSlug = typeof backendData.organization_slug === 'string'
          ? backendData.organization_slug
          : (organization ? organization.toLowerCase().replace(/[^a-z0-9]+/g, '-') : (role === 'tpa' ? 'star-health' : undefined));

        const localSession: AuthSession = {
          accessToken: `local-token-${Date.now()}`,
          refreshToken: `local-refresh-${Date.now()}`,
          idToken: `local-id-${Date.now()}`,
          expiresAt: Math.floor(Date.now() / 1000) + 86400,
          role,
          accountRole,
          organization,
          organizationSlug,
          provider: 'local',
          user: {
            id: backendData.user_id ? String(backendData.user_id) : undefined,
            email: username,
            name: username.split('@')[0] || username,
            preferredUsername: username,
          },
        };

        sessionStorage.setItem(ROLE_HINT_KEY, role);
        sessionStorage.setItem(AUTH_ACTION_KEY, 'login');
        sessionStorage.setItem(AUTH_PROVIDER_KEY, 'local');
        saveSession(localSession);
        return localSession;
      }

      let formattedMessage: string;
      let authErrorField: AuthErrorField;

      if (role === 'tpa') {
        formattedMessage = 'Access denied. Please check your credentials or contact your administrator.';
        authErrorField = 'general';
      } else {
        const backendErrorRaw = backendData.detail || backendData.error;
        const backendErrorMessage = typeof backendErrorRaw === 'string'
          ? backendErrorRaw
          : typeof backendErrorRaw?.message === 'string'
            ? backendErrorRaw.message
            : 'Invalid username or password.';
        const backendActualRole = typeof backendData?.detail?.actual_role === 'string'
          ? backendData.detail.actual_role
          : typeof backendData?.actual_role === 'string'
            ? backendData.actual_role
            : undefined;

        formattedMessage = backendErrorMessage;
        if (backendActualRole && backendResponse.status === 403 && backendErrorMessage.toLowerCase().includes('role')) {
          formattedMessage = formatRoleMismatchMessage(role, backendActualRole);
        }
        authErrorField = getAuthErrorField(formattedMessage);
      }

      if (backendResponse.status >= 400 && backendResponse.status < 500) {
        const authError = new Error(formattedMessage) as Error & { field?: AuthErrorField };
        authError.field = authErrorField;
        throw authError;
      }
    }
  } catch (error) {
    if (error instanceof Error && error.message !== 'Failed to fetch') {
      throw error;
    }
  }

  throw new Error('Invalid email or password.');
}

export async function registerAndSignIn({
  username,
  password,
  role,
}: {
  username: string;
  password: string;
  role: AuthRole;
}) {
  const response = await fetch('/api/auth/register', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ username, password, role }),
  });

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const errorMessage = typeof (data as Record<string, unknown>).error === 'string'
      ? (data as Record<string, unknown>).error
      : typeof (data as Record<string, unknown>).detail === 'string'
        ? (data as Record<string, unknown>).detail
        : 'Unable to create the account.';
    throw new Error(String(errorMessage));
  }

  return authenticateWithPassword({ username, password, role });
}

export async function completeAuthCallback() {
  if (typeof window === 'undefined') {
    return null;
  }

  const params = new URLSearchParams(window.location.search);
  const code = params.get('code');
  const state = params.get('state');
  const error = params.get('error');
  const storedState = sessionStorage.getItem(PKCE_STATE_KEY);
  const verifier = sessionStorage.getItem(PKCE_VERIFIER_KEY);
  const hintedRole = sessionStorage.getItem(ROLE_HINT_KEY) as AuthRole | null;
  const provider = (sessionStorage.getItem(AUTH_PROVIDER_KEY) as 'entra' | 'keycloak' | 'local') || (isEntraEnabled() ? 'entra' : 'keycloak');
  const savedClientId = sessionStorage.getItem(ENTRA_CLIENT_ID_KEY) || undefined;

  if (error) {
    throw new Error(params.get('error_description') || 'Authentication was cancelled.');
  }

  if (!code || !state || !storedState || state !== storedState) {
    throw new Error('The authentication response was invalid.');
  }

  let tokenUrl = '';
  let bodyParams = new URLSearchParams();

  if (provider === 'entra') {
    const entraConfig = getEntraConfig(hintedRole || 'patient', savedClientId);
    const { tokenUrl: entraTokenUrl } = getEntraEndpoints(hintedRole || 'patient', savedClientId);
    tokenUrl = entraTokenUrl;
    bodyParams = new URLSearchParams({
      grant_type: 'authorization_code',
      client_id: entraConfig.clientId,
      code,
      redirect_uri: entraConfig.redirectUri,
      code_verifier: verifier || '',
      scope: entraConfig.scopes,
    });
  } else {
    const keycloakConfig = getKeycloakConfig();
    tokenUrl = `${keycloakConfig.url}/realms/${keycloakConfig.realm}/protocol/openid-connect/token`;
    bodyParams = new URLSearchParams({
      grant_type: 'authorization_code',
      client_id: keycloakConfig.clientId,
      code,
      redirect_uri: keycloakConfig.redirectUri,
      code_verifier: verifier || '',
    });
  }

  const response = await fetch(tokenUrl, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
    },
    body: bodyParams,
  });

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const errorDescription = typeof (data as Record<string, unknown>).error_description === 'string'
      ? (data as Record<string, unknown>).error_description
      : typeof (data as Record<string, unknown>).error === 'string'
        ? (data as Record<string, unknown>).error
        : undefined;
    throw new Error(typeof errorDescription === 'string' ? errorDescription : 'Unable to exchange the authorization code.');
  }

  const session = buildSession(data as Record<string, unknown>, hintedRole, provider);

  // Synchronize identity with the database and enforce role permissions
  if (provider === 'entra') {
    const syncRes = await fetch('/api/auth/sync-entra', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: session.user.email,
        name: session.user.name,
        first_name: session.user.firstName,
        last_name: session.user.lastName,
        company_name: session.organization,
        organization: session.organization,
        external_subject_id: session.user.oid || session.user.sub || session.user.email,
        requested_role: hintedRole || 'patient',
        account_role: session.accountRole || (hintedRole === 'tpa' ? 'admin' : 'submitter'),
        client_id: savedClientId,
      }),
    });

    const syncData = await syncRes.json().catch(() => ({}));
    if (!syncRes.ok) {
      clearAuthSession();
      const denialMessage =
        syncData?.error ||
        syncData?.detail ||
        (hintedRole === 'tpa'
          ? 'Access denied. You are not registered as organization staff.'
          : 'Authentication verification failed.');
      throw new Error(typeof denialMessage === 'string' ? denialMessage : 'Access denied.');
    }

    if (syncData.user_id) {
      session.user.id = String(syncData.user_id);
    }
    if (syncData.first_name || syncData.last_name) {
      session.user.firstName = syncData.first_name || session.user.firstName;
      session.user.lastName = syncData.last_name || session.user.lastName;
      const combined = `${syncData.first_name || ''} ${syncData.last_name || ''}`.trim();
      if (combined) {
        session.user.name = combined;
      }
    } else if (syncData.name && syncData.name.toLowerCase() !== 'unknown') {
      session.user.name = syncData.name;
    }
    if (syncData.account_role) {
      session.accountRole = syncData.account_role;
    }
    if (syncData.organization) {
      session.organization = syncData.organization;
    }
    if (syncData.organization_slug) {
      session.organizationSlug = syncData.organization_slug;
    }
    if (syncData.needs_onboarding !== undefined) {
      session.needsOnboarding = Boolean(syncData.needs_onboarding);
    }
  }

  saveSession(session);
  return session;
}

/**
 * Resolves the destination URL based on the authenticated user's role:
 * - Patients -> /register?mode=complete (if newly registered) or /app
 * - Organization Admin -> /{organization}/admin
 * - Reviewer -> /{organization}/review
 */
export function getAuthRedirectPath(
  session: Pick<AuthSession, 'role' | 'accountRole' | 'organization' | 'organizationSlug' | 'needsOnboarding' | 'user'> | null | undefined
) {
  if (!session) {
    return '/app';
  }

  // Patients go directly to the patient workspace (or onboarding if incomplete)
  if (session.role === 'patient' || session.accountRole === 'submitter') {
    if (session.needsOnboarding) {
      const emailParam = encodeURIComponent(session.user?.email || '');
      const nameParam = encodeURIComponent(session.user?.name || '');
      return `/register?mode=complete&email=${emailParam}&name=${nameParam}`;
    }
    return '/app';
  }

  const slug =
    session.organizationSlug ||
    (session.organization
      ? session.organization.toLowerCase().replace(/[^a-z0-9]+/g, '-')
      : 'star-health');

  if (session.accountRole === 'admin') {
    return `/${slug}/admin`;
  }
  if (session.accountRole === 'reviewer') {
    return `/${slug}/review`;
  }
  return '/app';
}
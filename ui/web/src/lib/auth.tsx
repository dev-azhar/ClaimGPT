"use client";

import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from "react";

/* ── Types ── */
export interface AuthUser {
  sub: string;
  email?: string;
  name?: string;
  preferred_username?: string;
  given_name?: string;
  family_name?: string;
  roles: string[];
}

export interface SignupPrefill {
  email?: string;
  firstName?: string;
  lastName?: string;
}

interface AuthContextValue {
  user: AuthUser | null;
  token: string | null;
  loading: boolean;
  login: (idpHint?: string) => void;
  signup: (idpHint?: string, prefill?: SignupPrefill) => void;
  logout: () => void;
  isAuthenticated: boolean;
  ssoProviders: SsoProvider[];
  /* RBAC helpers (memoized via current user.roles) */
  hasRole: (role: Role) => boolean;
  hasAnyRole: (roles: Role[]) => boolean;
}

/* ── Roles (mirrors Keycloak realm roles) ── */
export const ROLES = {
  VIEWER: "viewer",
  SUBMITTER: "submitter",
  REVIEWER: "reviewer",
  CHECKER: "checker",      // Maker-checker: validates a reviewer's request
  APPROVER: "approver",    // Authorizes settlement / final sign-off
  ADMIN: "admin",
} as const;
export type Role = typeof ROLES[keyof typeof ROLES];
export const ALL_ROLES: Role[] = Object.values(ROLES) as Role[];

/* Admin implicitly has every privilege */
export function userHasRole(user: AuthUser | null, role: Role): boolean {
  if (!user) return false;
  if (user.roles.includes(ROLES.ADMIN)) return true;
  return user.roles.includes(role);
}
export function userHasAnyRole(user: AuthUser | null, roles: Role[]): boolean {
  if (!user) return false;
  if (user.roles.includes(ROLES.ADMIN)) return true;
  return roles.some((r) => user.roles.includes(r));
}

export interface SsoProvider {
  id: string;          // Keycloak IdP alias (kc_idp_hint)
  label: string;
  hint?: string;       // E.g. "@yourcompany.com"
  icon: "google" | "microsoft" | "okta" | "saml" | "apple" | "keycloak";
  brandColor?: string;
}

/* ── Enterprise SSO providers (configured in Keycloak realm) ── */
export const SSO_PROVIDERS: SsoProvider[] = [
  { id: "google", label: "Google Workspace", icon: "google", brandColor: "#4285F4" },
  { id: "microsoft", label: "Microsoft Entra ID", icon: "microsoft", brandColor: "#0078D4" },
  { id: "okta", label: "Okta", icon: "okta", brandColor: "#007DC1" },
  { id: "saml", label: "SAML SSO (Enterprise)", icon: "saml", brandColor: "#0f4c81" },
];

const AuthContext = createContext<AuthContextValue>({
  user: null,
  token: null,
  loading: true,
  login: () => {},
  signup: () => {},
  logout: () => {},
  isAuthenticated: false,
  ssoProviders: SSO_PROVIDERS,
  hasRole: () => false,
  hasAnyRole: () => false,
});

export const useAuth = () => useContext(AuthContext);

/* ── Config ── */
const KEYCLOAK_URL = process.env.NEXT_PUBLIC_KEYCLOAK_URL || "http://localhost:8080";
const REALM = process.env.NEXT_PUBLIC_KEYCLOAK_REALM || "claimgpt";
const CLIENT_ID = process.env.NEXT_PUBLIC_KEYCLOAK_CLIENT_ID || "claimgpt-web";
const REDIRECT_URI = typeof window !== "undefined" ? window.location.origin : "http://localhost:3000";
const DEV_MODE = process.env.NEXT_PUBLIC_AUTH_DEV_MODE === "true" || process.env.NODE_ENV === "development";

const AUTH_ENDPOINT = `${KEYCLOAK_URL}/realms/${REALM}/protocol/openid-connect/auth`;
const REGISTER_ENDPOINT = `${KEYCLOAK_URL}/realms/${REALM}/protocol/openid-connect/registrations`;
const TOKEN_ENDPOINT = `${KEYCLOAK_URL}/realms/${REALM}/protocol/openid-connect/token`;
const LOGOUT_ENDPOINT = `${KEYCLOAK_URL}/realms/${REALM}/protocol/openid-connect/logout`;
const USERINFO_ENDPOINT = `${KEYCLOAK_URL}/realms/${REALM}/protocol/openid-connect/userinfo`;

/* ── Dev mode mock users ── */
const DEV_USERS: Record<string, AuthUser> = {
  admin:     { sub: "dev-admin-001",     email: "admin@claimgpt.dev",     name: "Admin User",     preferred_username: "admin",     given_name: "Admin",     family_name: "User", roles: [ROLES.ADMIN] },
  approver:  { sub: "dev-approver-001",  email: "approver@claimgpt.dev",  name: "Approver User",  preferred_username: "approver",  given_name: "Approver",  family_name: "User", roles: [ROLES.APPROVER, ROLES.REVIEWER, ROLES.VIEWER] },
  checker:   { sub: "dev-checker-001",   email: "checker@claimgpt.dev",   name: "Checker User",   preferred_username: "checker",   given_name: "Checker",   family_name: "User", roles: [ROLES.CHECKER, ROLES.REVIEWER, ROLES.VIEWER] },
  reviewer:  { sub: "dev-reviewer-001",  email: "reviewer@claimgpt.dev",  name: "Reviewer User",  preferred_username: "reviewer",  given_name: "Reviewer",  family_name: "User", roles: [ROLES.REVIEWER, ROLES.VIEWER] },
  submitter: { sub: "dev-submitter-001", email: "submitter@claimgpt.dev", name: "Submitter User", preferred_username: "submitter", given_name: "Submitter", family_name: "User", roles: [ROLES.SUBMITTER, ROLES.VIEWER] },
  viewer:    { sub: "dev-viewer-001",    email: "viewer@claimgpt.dev",    name: "Viewer User",    preferred_username: "viewer",    given_name: "Viewer",    family_name: "User", roles: [ROLES.VIEWER] },
};

async function isKeycloakReachable(): Promise<boolean> {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 2000);
    const res = await fetch(`${KEYCLOAK_URL}/realms/${REALM}`, { signal: controller.signal, mode: "no-cors" });
    clearTimeout(timeout);
    return true;
  } catch {
    return false;
  }
}

/* ── PKCE helpers ── */
function generateRandomString(length: number): string {
  const array = new Uint8Array(length);
  crypto.getRandomValues(array);
  return Array.from(array, (b) => b.toString(36).padStart(2, "0")).join("").slice(0, length);
}

async function generateCodeChallenge(verifier: string): Promise<string> {
  const encoder = new TextEncoder();
  const data = encoder.encode(verifier);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return btoa(String.fromCharCode(...new Uint8Array(digest)))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

/* ── Token helpers ── */
function parseJwt(token: string): Record<string, unknown> {
  const base64Url = token.split(".")[1];
  const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
  const json = decodeURIComponent(
    atob(base64)
      .split("")
      .map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2))
      .join("")
  );
  return JSON.parse(json);
}

function extractUser(payload: Record<string, unknown>): AuthUser {
  const realmAccess = payload.realm_access as { roles?: string[] } | undefined;
  return {
    sub: (payload.sub as string) || "",
    email: payload.email as string | undefined,
    name: payload.name as string | undefined,
    preferred_username: payload.preferred_username as string | undefined,
    given_name: payload.given_name as string | undefined,
    family_name: payload.family_name as string | undefined,
    roles: realmAccess?.roles?.filter((r) => !r.startsWith("default-roles-")) || [],
  };
}

function isTokenExpired(token: string): boolean {
  try {
    const payload = parseJwt(token);
    const exp = payload.exp as number;
    return Date.now() >= exp * 1000 - 30000; // 30s buffer
  } catch {
    return true;
  }
}

/* ── Provider ── */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [showDevLogin, setShowDevLogin] = useState(false);

  const devLogin = useCallback((username: string) => {
    const devUser = DEV_USERS[username] || DEV_USERS.viewer;
    sessionStorage.setItem("dev_user", JSON.stringify(devUser));
    sessionStorage.setItem("access_token", "dev-token");
    setUser(devUser);
    setToken("dev-token");
    setShowDevLogin(false);
  }, []);

  /* Shared OAuth/PKCE redirect for both sign-in & sign-up */
  const startOAuth = useCallback(async (
    mode: "login" | "signup",
    idpHint?: string,
    prefill?: SignupPrefill,
  ) => {
    /* In dev mode without Keycloak, show mock login (signup falls back to picker too) */
    if (DEV_MODE && !idpHint) {
      const reachable = await isKeycloakReachable();
      if (!reachable) {
        setShowDevLogin(true);
        return;
      }
    }

    const codeVerifier = generateRandomString(64);
    const codeChallenge = await generateCodeChallenge(codeVerifier);
    const state = generateRandomString(32);

    sessionStorage.setItem("pkce_code_verifier", codeVerifier);
    sessionStorage.setItem("oauth_state", state);

    const params = new URLSearchParams({
      response_type: "code",
      client_id: CLIENT_ID,
      redirect_uri: REDIRECT_URI,
      scope: "openid email profile roles",
      state,
      code_challenge: codeChallenge,
      code_challenge_method: "S256",
    });
    /* Enterprise SSO: route directly to selected IdP, skipping Keycloak login UI */
    if (idpHint) params.set("kc_idp_hint", idpHint);

    /* Pre-fill the Keycloak registration form (Keycloak >= 19 supports these) */
    if (mode === "signup" && prefill) {
      if (prefill.email) params.set("login_hint", prefill.email);
      if (prefill.firstName) params.set("firstName", prefill.firstName);
      if (prefill.lastName) params.set("lastName", prefill.lastName);
    }

    const endpoint = mode === "signup" ? REGISTER_ENDPOINT : AUTH_ENDPOINT;
    window.location.href = `${endpoint}?${params.toString()}`;
  }, []);

  const login = useCallback((idpHint?: string) => startOAuth("login", idpHint), [startOAuth]);
  const signup = useCallback(
    (idpHint?: string, prefill?: SignupPrefill) => startOAuth("signup", idpHint, prefill),
    [startOAuth],
  );

  const logout = useCallback(() => {
    const isDev = sessionStorage.getItem("dev_user");
    /* Read id_token BEFORE clearing storage so Keycloak RP-initiated logout works */
    const idToken = sessionStorage.getItem("id_token");

    sessionStorage.removeItem("access_token");
    sessionStorage.removeItem("refresh_token");
    sessionStorage.removeItem("id_token");
    sessionStorage.removeItem("pkce_code_verifier");
    sessionStorage.removeItem("oauth_state");
    sessionStorage.removeItem("dev_user");
    setUser(null);
    setToken(null);

    /* Dev mode: just clear state, no Keycloak redirect */
    if (isDev) return;

    const params = new URLSearchParams({
      client_id: CLIENT_ID,
      post_logout_redirect_uri: REDIRECT_URI,
    });
    if (idToken) params.set("id_token_hint", idToken);

    window.location.href = `${LOGOUT_ENDPOINT}?${params.toString()}`;
  }, []);

  const exchangeCode = useCallback(async (code: string) => {
    const codeVerifier = sessionStorage.getItem("pkce_code_verifier");
    if (!codeVerifier) return;

    const body = new URLSearchParams({
      grant_type: "authorization_code",
      client_id: CLIENT_ID,
      redirect_uri: REDIRECT_URI,
      code,
      code_verifier: codeVerifier,
    });

    const res = await fetch(TOKEN_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body.toString(),
    });

    if (!res.ok) {
      console.error("Token exchange failed:", res.status);
      setLoading(false);
      return;
    }

    const data = await res.json();
    sessionStorage.setItem("access_token", data.access_token);
    sessionStorage.setItem("id_token", data.id_token || "");
    if (data.refresh_token) sessionStorage.setItem("refresh_token", data.refresh_token);

    const payload = parseJwt(data.access_token);
    setToken(data.access_token);
    setUser(extractUser(payload));
    setLoading(false);

    // Clean URL
    window.history.replaceState({}, document.title, window.location.pathname);
  }, []);

  const refreshToken = useCallback(async () => {
    const rt = sessionStorage.getItem("refresh_token");
    if (!rt) return false;

    try {
      const body = new URLSearchParams({
        grant_type: "refresh_token",
        client_id: CLIENT_ID,
        refresh_token: rt,
      });

      const res = await fetch(TOKEN_ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: body.toString(),
      });

      if (!res.ok) return false;

      const data = await res.json();
      sessionStorage.setItem("access_token", data.access_token);
      sessionStorage.setItem("id_token", data.id_token || "");
      if (data.refresh_token) sessionStorage.setItem("refresh_token", data.refresh_token);

      const payload = parseJwt(data.access_token);
      setToken(data.access_token);
      setUser(extractUser(payload));
      return true;
    } catch {
      return false;
    }
  }, []);

  // Initialize: check for auth code callback or existing token
  useEffect(() => {
    const init = async () => {
      /* Restore dev mode user */
      const devUserJson = sessionStorage.getItem("dev_user");
      if (devUserJson) {
        try {
          const devUser: AuthUser = JSON.parse(devUserJson);
          setUser(devUser);
          setToken("dev-token");
          setLoading(false);
          return;
        } catch { /* fall through */ }
      }

      const url = new URL(window.location.href);
      const code = url.searchParams.get("code");
      const state = url.searchParams.get("state");
      const oauthError = url.searchParams.get("error");

      // Handle IdP-side errors (user cancelled, access denied, etc.)
      if (oauthError) {
        const desc = url.searchParams.get("error_description");
        console.warn(`OAuth error: ${oauthError}`, desc || "");
        sessionStorage.removeItem("pkce_code_verifier");
        sessionStorage.removeItem("oauth_state");
        window.history.replaceState({}, document.title, window.location.pathname);
        setLoading(false);
        return;
      }

      // Handle OAuth callback
      if (code && state) {
        const savedState = sessionStorage.getItem("oauth_state");
        if (state !== savedState) {
          console.error("OAuth state mismatch");
          sessionStorage.removeItem("pkce_code_verifier");
          sessionStorage.removeItem("oauth_state");
          setLoading(false);
          return;
        }
        await exchangeCode(code);
        sessionStorage.removeItem("pkce_code_verifier");
        sessionStorage.removeItem("oauth_state");
        return;
      }

      // Check existing token
      const savedToken = sessionStorage.getItem("access_token");
      if (savedToken) {
        if (!isTokenExpired(savedToken)) {
          const payload = parseJwt(savedToken);
          setToken(savedToken);
          setUser(extractUser(payload));
          setLoading(false);
        } else {
          const refreshed = await refreshToken();
          if (!refreshed) {
            sessionStorage.removeItem("access_token");
            sessionStorage.removeItem("refresh_token");
            sessionStorage.removeItem("id_token");
          }
          setLoading(false);
        }
        return;
      }

      setLoading(false);
    };

    init();
  }, [exchangeCode, refreshToken]);

  // Auto-refresh token before expiry (skip for dev tokens)
  useEffect(() => {
    if (!token || token === "dev-token") return;

    const interval = setInterval(async () => {
      if (token && isTokenExpired(token)) {
        const ok = await refreshToken();
        if (!ok) logout();
      }
    }, 60000);

    return () => clearInterval(interval);
  }, [token, refreshToken, logout]);

  const hasRole = useCallback((role: Role) => userHasRole(user, role), [user]);
  const hasAnyRole = useCallback((roles: Role[]) => userHasAnyRole(user, roles), [user]);

  return (
    <AuthContext.Provider value={{ user, token, loading, login, signup, logout, isAuthenticated: !!user, ssoProviders: SSO_PROVIDERS, hasRole, hasAnyRole }}>
      {children}

      {/* Dev mode login modal */}
      {showDevLogin && (
        <div style={{
          position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)",
          display: "flex", alignItems: "center", justifyContent: "center", zIndex: 9999,
          backdropFilter: "blur(4px)",
        }}>
          <div style={{
            background: "#fff", borderRadius: 16, padding: "32px 28px", width: 360,
            boxShadow: "0 24px 80px rgba(0,0,0,0.2)",
          }}>
            <div style={{ textAlign: "center", marginBottom: 20 }}>
              <div style={{ fontSize: 28, marginBottom: 4 }}>🔐</div>
              <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: "#0f172a" }}>Dev Sign In</h2>
              <p style={{ margin: "6px 0 0", fontSize: 13, color: "#64748b" }}>
                Keycloak not available — pick a dev user
              </p>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {Object.entries(DEV_USERS).map(([key, u]) => (
                <button
                  key={key}
                  onClick={() => devLogin(key)}
                  style={{
                    display: "flex", alignItems: "center", gap: 12,
                    padding: "12px 16px", borderRadius: 10,
                    border: "1px solid #e2e8f0", background: "#f8fafc",
                    cursor: "pointer", transition: "all 0.15s",
                    textAlign: "left",
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = "#eff6ff"; e.currentTarget.style.borderColor = "#3b82f6"; }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = "#f8fafc"; e.currentTarget.style.borderColor = "#e2e8f0"; }}
                >
                  <div style={{
                    width: 38, height: 38, borderRadius: "50%",
                    background: key === "admin" ? "#ef4444" : key === "reviewer" ? "#a855f7" : key === "submitter" ? "#3b82f6" : "#6b7280",
                    color: "#fff", display: "flex", alignItems: "center", justifyContent: "center",
                    fontWeight: 700, fontSize: 14, flexShrink: 0,
                  }}>
                    {u.given_name?.[0]}{u.family_name?.[0]}
                  </div>
                  <div>
                    <div style={{ fontWeight: 600, fontSize: 14, color: "#0f172a" }}>{u.name}</div>
                    <div style={{ fontSize: 12, color: "#64748b" }}>{u.email} · {u.roles[0]}</div>
                  </div>
                </button>
              ))}
            </div>
            <button
              onClick={() => setShowDevLogin(false)}
              style={{
                marginTop: 16, width: "100%", padding: "10px",
                border: "none", borderRadius: 8, background: "transparent",
                color: "#64748b", fontSize: 13, cursor: "pointer",
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </AuthContext.Provider>
  );
}

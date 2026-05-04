# SSO Setup — ClaimGPT Enterprise

ClaimGPT supports enterprise Single Sign-On (SSO) via **Keycloak Identity Brokering**.
Users see a polished login screen with one-click sign-in for **Google Workspace**, **Microsoft Entra ID** (Azure AD), **Okta**, and **SAML 2.0** federation.

Smart email-domain routing automatically detects the right provider when a user enters their work email (e.g. `@company.onmicrosoft.com` → Microsoft).

---

## Architecture

```
User → ClaimGPT Web (Next.js)
         │
         │  OAuth 2.0 + PKCE  (kc_idp_hint=<provider>)
         ▼
       Keycloak  (claimgpt realm)
         │
         ├── Google OIDC      ──→ accounts.google.com
         ├── Microsoft OIDC   ──→ login.microsoftonline.com
         ├── Okta OIDC        ──→ <tenant>.okta.com
         └── SAML 2.0         ──→ Customer IdP
```

Keycloak handles the OIDC/SAML translation, JWT issuance, and session management.
The web app only ever sees standard JWTs (`access_token` + `id_token`).

---

## Frontend integration

### Login flow
The login screen is rendered by `ui/web/src/components/SsoLoginScreen.tsx` whenever the user is unauthenticated. It calls:

```ts
const { login } = useAuth();
login("google");      // → redirect with kc_idp_hint=google
login("microsoft");   // → redirect with kc_idp_hint=microsoft
login("okta");        // → redirect with kc_idp_hint=okta
login("saml");        // → redirect with kc_idp_hint=saml
login();              // → standard Keycloak login (username/password)
```

### Email-domain auto-routing
When a user enters their email, the form picks a provider:

| Email domain pattern             | Routes to |
| -------------------------------- | --------- |
| `gmail.com`, `googlemail.com`    | Google    |
| `outlook.com`, `hotmail.com`, `live.com`, `*.onmicrosoft.com`, `office365.com` | Microsoft |
| Everything else (corporate)      | SAML federation |

Customize the mapping in `SsoLoginScreen.tsx` (`onContinue` handler).

---

## Keycloak configuration

The realm `infra/keycloak/claimgpt-realm.json` now ships with placeholder entries for all four providers under `identityProviders`. You need to replace the placeholder client IDs/secrets/URLs and import the realm:

```bash
docker compose -f infra/docker/docker-compose.yml up -d keycloak
# then in Keycloak admin: Realm settings → Action → Partial Import → upload claimgpt-realm.json
```

### 1. Google Workspace

1. Google Cloud Console → APIs & Services → Credentials → **Create OAuth client ID** (Web).
2. Authorized redirect URI: `http://localhost:8080/realms/claimgpt/broker/google/endpoint`
3. Copy **Client ID** + **Client secret** into the realm JSON or Keycloak admin UI:
   - `Identity Providers → google → Settings`
4. (Optional) Restrict to your Google Workspace domain via `hostedDomain`.

### 2. Microsoft Entra ID (Azure AD)

1. Azure Portal → **App registrations** → **New registration**.
2. Redirect URI (Web): `http://localhost:8080/realms/claimgpt/broker/microsoft/endpoint`
3. Certificates & secrets → **New client secret** → copy the **Value**.
4. In the realm JSON / Keycloak UI:
   - `clientId` = Application (client) ID
   - `clientSecret` = the secret value
   - `tenantId` = your tenant ID (or `common` for multi-tenant)

### 3. Okta

1. Okta Admin → **Applications** → Create App Integration → **OIDC Web Application**.
2. Sign-in redirect URI: `http://localhost:8080/realms/claimgpt/broker/okta/endpoint`
3. Replace `YOUR_OKTA_DOMAIN` in the realm JSON with e.g. `dev-12345.okta.com`.
4. Copy Client ID + Client secret.

### 4. SAML 2.0 (Generic Enterprise)

1. In your IdP (ADFS, PingFederate, OneLogin, etc.), create a new SAML application.
2. ACS URL: `http://localhost:8080/realms/claimgpt/broker/saml/endpoint`
3. Entity ID: `http://localhost:8080/realms/claimgpt`
4. Export the IdP's signing certificate (Base64) and paste into `signingCertificate`.
5. Update `singleSignOnServiceUrl` and `singleLogoutServiceUrl`.

---

## Production checklist

- [ ] Replace `localhost:8080` with your production Keycloak URL in **all** redirect URIs.
- [ ] Set `NEXT_PUBLIC_KEYCLOAK_URL` env var in the Next.js app.
- [ ] Disable dev-mode mock users: ensure `NODE_ENV=production` and do **not** set `NEXT_PUBLIC_AUTH_DEV_MODE=true`.
- [ ] Enforce **PKCE** + **HTTPS** on the Keycloak client (`Advanced → Proof Key for Code Exchange Code Challenge Method = S256`).
- [ ] Configure **Web origins** on `claimgpt-web` client to match production frontend URL.
- [ ] Map provider claims to Keycloak roles (e.g. `groups` → `realm_access.roles`).
- [ ] Set short access-token lifespan (5–15 min) and rely on refresh-token rotation.
- [ ] Enable Keycloak audit log streaming → SIEM.
- [ ] For India deployments: deploy Keycloak in **ap-south-1 (Mumbai)** for data residency.

---

## Adding more providers

To add another provider (e.g. LinkedIn, GitHub, OneLogin):

1. Add it to the `identityProviders` array in the realm JSON.
2. Append it to `SSO_PROVIDERS` in `ui/web/src/lib/auth.tsx`:
   ```ts
   { id: "linkedin", label: "LinkedIn", icon: "saml", brandColor: "#0A66C2" },
   ```
3. (Optional) Add a brand SVG to `ProviderIcon` in `SsoLoginScreen.tsx`.

---

## Local dev experience

When `NEXT_PUBLIC_AUTH_DEV_MODE=true` (default in dev) and Keycloak is unreachable, clicking the "Sign in with username & password" button on the login screen falls back to a mock-user picker (admin / reviewer / submitter / viewer). SSO buttons (Google/Microsoft/Okta/SAML) still attempt the real OAuth redirect — they will only work if Keycloak is running and the providers are configured.

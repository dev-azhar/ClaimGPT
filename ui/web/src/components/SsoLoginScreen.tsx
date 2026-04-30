"use client";

import { useEffect, useState } from "react";
import { useAuth, type SsoProvider } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";
import LanguageSwitcher from "@/components/LanguageSwitcher";

/* ── Brand SVG icons ── */
function ProviderIcon({ icon }: { icon: SsoProvider["icon"] }) {
  switch (icon) {
    case "google":
      return (
        <svg width="18" height="18" viewBox="0 0 18 18" xmlns="http://www.w3.org/2000/svg">
          <path d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844a4.14 4.14 0 0 1-1.796 2.716v2.259h2.908c1.702-1.567 2.684-3.875 2.684-6.615z" fill="#4285F4"/>
          <path d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.26c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 0 0 9 18z" fill="#34A853"/>
          <path d="M3.964 10.71A5.41 5.41 0 0 1 3.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 0 0 0 9c0 1.452.348 2.827.957 4.042l3.007-2.332z" fill="#FBBC05"/>
          <path d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z" fill="#EA4335"/>
        </svg>
      );
    case "microsoft":
      return (
        <svg width="18" height="18" viewBox="0 0 23 23" xmlns="http://www.w3.org/2000/svg">
          <path fill="#F25022" d="M1 1h10v10H1z"/>
          <path fill="#7FBA00" d="M12 1h10v10H12z"/>
          <path fill="#00A4EF" d="M1 12h10v10H1z"/>
          <path fill="#FFB900" d="M12 12h10v10H12z"/>
        </svg>
      );
    case "okta":
      return (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <circle cx="12" cy="12" r="11" fill="#007DC1"/>
          <circle cx="12" cy="12" r="5" fill="#fff"/>
        </svg>
      );
    case "saml":
      return (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#0f4c81" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
          <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
        </svg>
      );
    case "apple":
      return (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="#000" xmlns="http://www.w3.org/2000/svg">
          <path d="M16.365 1.43c0 1.14-.493 2.27-1.177 3.08-.744.9-1.99 1.57-2.987 1.57-.12-1.14.486-2.31 1.142-3.08.744-.83 2.024-1.5 3.022-1.57zm4.565 14.83c-.78 1.7-1.6 3.4-2.93 3.42-1.31.04-1.73-.78-3.22-.78-1.5 0-1.96.74-3.2.82-1.27.05-2.24-1.83-3.04-3.52-1.62-3.42-2.86-9.66.62-11.85 1.71-1.07 3.85-.82 4.95-.82 1.05 0 3.13-.27 4.93.82 1.84 1.12 3.04 3.34 2.94 5.6.04.04-1.55 1.92-1.05 6.31z"/>
        </svg>
      );
    default:
      return (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <circle cx="12" cy="7" r="4"/>
          <path d="M5.5 21a6.5 6.5 0 0 1 13 0"/>
        </svg>
      );
  }
}

/* ─────────────────────────────────────────────────────────────────
   Signup modal — popup card opened from "Create account" link
   ───────────────────────────────────────────────────────────────── */
interface SignupModalProps {
  open: boolean;
  onClose: () => void;
  ssoProviders: SsoProvider[];
}

function SignupModal({ open, onClose, ssoProviders }: SignupModalProps) {
  const { signup } = useAuth();
  const [busy, setBusy] = useState<string | null>(null);

  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [signupEmail, setSignupEmail] = useState("");
  const [organization, setOrganization] = useState("");
  const [orgRole, setOrgRole] = useState("Claims Reviewer");
  const [acceptedTerms, setAcceptedTerms] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  /* Esc to close + lock body scroll */
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open, onClose]);

  if (!open) return null;

  const onProviderSignup = (id: string) => {
    setBusy(id);
    signup(id, { email: signupEmail, firstName, lastName });
  };

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);

    if (firstName.trim().length < 2) return setFormError("Please enter your first name.");
    if (lastName.trim().length < 2) return setFormError("Please enter your last name.");
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(signupEmail)) return setFormError("Please enter a valid work email.");
    if (organization.trim().length < 2) return setFormError("Please enter your organization name.");
    if (!acceptedTerms) return setFormError("You must accept the Terms of Service and Privacy Policy.");

    try {
      sessionStorage.setItem(
        "signup_meta",
        JSON.stringify({ organization: organization.trim(), role: orgRole, ts: Date.now() }),
      );
    } catch { /* storage unavailable */ }

    setBusy("default");
    signup(undefined, {
      email: signupEmail.trim(),
      firstName: firstName.trim(),
      lastName: lastName.trim(),
    });
  };

  return (
    <div
      className="signup-modal-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="signup-modal-title"
      onClick={onClose}
    >
      <div className="signup-modal-card" onClick={(e) => e.stopPropagation()}>
        <button
          type="button"
          className="signup-modal-close"
          onClick={onClose}
          aria-label="Close"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>

        <div className="signup-modal-head">
          <span className="signup-modal-icon" aria-hidden>
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/>
              <circle cx="9" cy="7" r="4"/>
              <line x1="19" y1="8" x2="19" y2="14"/>
              <line x1="22" y1="11" x2="16" y2="11"/>
            </svg>
          </span>
          <div className="signup-modal-head-text">
            <span className="signup-modal-step" aria-label="Step 1 of 2">
              <span className="signup-modal-step-num">1</span>
              <span className="signup-modal-step-sep" aria-hidden />
              <span className="signup-modal-step-num signup-modal-step-num-dim">2</span>
              <span className="signup-modal-step-text">Your details</span>
            </span>
            <h2 id="signup-modal-title">Create your ClaimGPT account</h2>
            <p>Tell us a bit about yourself. You&rsquo;ll set a secure password on the next step.</p>
          </div>
        </div>

        <div className="signup-modal-body">
          {/* Quick SSO row */}
          <span className="signup-modal-sso-label">Quick sign-up with</span>
          <div className="signup-modal-sso-row">
            {ssoProviders.slice(0, 3).map((p) => (
              <button
                key={p.id}
                type="button"
                className="signup-modal-sso-btn"
                onClick={() => onProviderSignup(p.id)}
                disabled={busy !== null}
                title={`Sign up with ${p.label}`}
              >
                <ProviderIcon icon={p.icon} />
                <span>{busy === p.id ? "…" : p.label.split(" ")[0]}</span>
              </button>
            ))}
          </div>

          <div className="sso-divider"><span>or use your work email</span></div>

          <form className="sso-signup-form" onSubmit={onSubmit} noValidate>
            <div className="sso-form-grid">
              <div className="sso-field">
                <label htmlFor="su-fname" className="sso-label">First name<span className="sso-req" aria-hidden>*</span></label>
                <input
                  id="su-fname" type="text" autoComplete="given-name" placeholder="Azhar"
                  value={firstName} onChange={(e) => setFirstName(e.target.value)}
                  className="sso-input" required minLength={2}
                />
              </div>
              <div className="sso-field">
                <label htmlFor="su-lname" className="sso-label">Last name<span className="sso-req" aria-hidden>*</span></label>
                <input
                  id="su-lname" type="text" autoComplete="family-name" placeholder="Shaikh"
                  value={lastName} onChange={(e) => setLastName(e.target.value)}
                  className="sso-input" required minLength={2}
                />
              </div>
            </div>

            <div className="sso-field">
              <label htmlFor="su-email" className="sso-label">Work email<span className="sso-req" aria-hidden>*</span></label>
              <input
                id="su-email" type="email" inputMode="email" autoComplete="email"
                placeholder="azhar@yourcompany.com"
                value={signupEmail} onChange={(e) => setSignupEmail(e.target.value)}
                className="sso-input" required
              />
            </div>

            <div className="sso-form-grid">
              <div className="sso-field">
                <label htmlFor="su-org" className="sso-label">Organization<span className="sso-req" aria-hidden>*</span></label>
                <input
                  id="su-org" type="text" autoComplete="organization"
                  placeholder="WCT Insurance Pvt Ltd"
                  value={organization} onChange={(e) => setOrganization(e.target.value)}
                  className="sso-input" required minLength={2}
                />
              </div>
              <div className="sso-field">
                <label htmlFor="su-role" className="sso-label">Role</label>
                <select
                  id="su-role" value={orgRole} onChange={(e) => setOrgRole(e.target.value)}
                  className="sso-input sso-select" autoComplete="organization-title"
                >
                  <option>Claims Reviewer</option>
                  <option>Reviewer</option>
                  <option>Submitter</option>
                  <option>TPA Coordinator</option>
                  <option>Compliance Officer</option>
                  <option>Administrator</option>
                  <option>Other</option>
                </select>
              </div>
            </div>

            <label className="sso-checkbox-row">
              <input
                type="checkbox" checked={acceptedTerms}
                onChange={(e) => setAcceptedTerms(e.target.checked)}
                className="sso-checkbox"
              />
              <span>
                I agree to the <a href="/terms" target="_blank" rel="noreferrer">Terms of Service</a>,{" "}
                <a href="/privacy" target="_blank" rel="noreferrer">Privacy Policy</a>, and consent to
                processing per India&rsquo;s DPDP Act 2023.
              </span>
            </label>

            {formError && (
              <div className="sso-form-error" role="alert">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                  <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
                </svg>
                <span>{formError}</span>
              </div>
            )}

            <div className="signup-modal-actions">
              <button type="button" className="signup-modal-cancel" onClick={onClose} disabled={busy !== null}>
                Cancel
              </button>
              <button type="submit" className="sso-signup-submit" disabled={busy !== null}>
                {busy ? "Redirecting\u2026" : "Continue"}
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="M5 12h14M13 5l7 7-7 7"/></svg>
              </button>
            </div>

            <div className="signup-modal-secure">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                <rect x="3" y="11" width="18" height="11" rx="2"/>
                <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
              </svg>
              <span>You&rsquo;ll set your password on the next, secure step — ClaimGPT never sees it.</span>
            </div>

            <div className="signup-modal-trust">
              <span className="signup-modal-trust-pill">IRDAI</span>
              <span className="signup-modal-trust-pill">ISO 27001</span>
              <span className="signup-modal-trust-pill">DPDP 2023</span>
              <span className="signup-modal-trust-pill">HIPAA-aligned</span>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────
   Main login screen
   ───────────────────────────────────────────────────────────────── */
export default function SsoLoginScreen() {
  const { login, ssoProviders } = useAuth();
  const { t } = useI18n();
  const [busy, setBusy] = useState<string | null>(null);
  const [emailHint, setEmailHint] = useState("");
  const [signupOpen, setSignupOpen] = useState(false);

  const onProvider = (id?: string) => {
    setBusy(id || "default");
    login(id);
  };

  /* Email-domain smart routing for sign-in */
  const onContinue = (e: React.FormEvent) => {
    e.preventDefault();
    const domain = emailHint.split("@")[1]?.toLowerCase().trim();
    if (!domain) return onProvider();
    if (/(gmail|googlemail)\./.test(domain)) return onProvider("google");
    if (/(outlook|hotmail|live|microsoft|office365|onmicrosoft)\./.test(domain)) return onProvider("microsoft");
    return onProvider("saml");
  };

  return (
    <div className="sso-login-page">
      <div className="sso-bg" aria-hidden />
      <div className="sso-container">
        {/* Brand panel (left, hidden on mobile) */}
        <aside className="sso-brand-panel">
          <div className="sso-brand">
            <span className="sso-brand-icon" aria-hidden>
              <svg width="40" height="40" viewBox="0 0 30 30" fill="none">
                <rect width="30" height="30" rx="8" fill="url(#sso-bg-grad)"/>
                <path d="M15 7v16M7 15h16" stroke="#fff" strokeWidth="2.6" strokeLinecap="round"/>
                <defs>
                  <linearGradient id="sso-bg-grad" x1="0" y1="0" x2="30" y2="30">
                    <stop stopColor="#0f4c81"/>
                    <stop offset="1" stopColor="#0d9488"/>
                  </linearGradient>
                </defs>
              </svg>
            </span>
            <div className="sso-brand-text">
              <span className="sso-brand-name">ClaimGPT</span>
              <span className="sso-brand-edition">Enterprise · India</span>
            </div>
          </div>

          <h1 className="sso-headline">
            AI-powered claims<br/>processing for India.
          </h1>
          <p className="sso-subhead">
            One unified workspace for OCR, coding, validation,
            TPA submission, and audit — built for IRDAI-regulated insurers.
          </p>

          <ul className="sso-bullets">
            <li><span className="sso-bullet-dot" /> 74,736 ICD-10-CM codes via on-prem RAG</li>
            <li><span className="sso-bullet-dot" /> SLA-tracked queue · live TPA messaging</li>
            <li><span className="sso-bullet-dot" /> {t("sso.bullet.languages")}</li>
            <li><span className="sso-bullet-dot" /> Data residency: Mumbai (ap-south-1)</li>
          </ul>

          <div className="sso-trust-row">
            <span className="sso-trust-pill">IRDAI</span>
            <span className="sso-trust-pill">ISO 27001</span>
            <span className="sso-trust-pill">DPDP 2023</span>
            <span className="sso-trust-pill">HIPAA-aligned</span>
          </div>
        </aside>

        {/* Sign-in card (right) */}
        <main className="sso-card">
          <div className="sso-card-head sso-card-head-with-lang">
            <div>
              <h2>{t("sso.signIn")}</h2>
              <p>{t("sso.choose")}</p>
            </div>
            <LanguageSwitcher />
          </div>

          <form className="sso-email-form" onSubmit={onContinue}>
            <label htmlFor="sso-email" className="sso-label">{t("sso.workEmail")}</label>
            <div className="sso-input-row">
              <input
                id="sso-email"
                type="email"
                inputMode="email"
                autoComplete="username"
                placeholder="you@yourcompany.com"
                value={emailHint}
                onChange={(e) => setEmailHint(e.target.value)}
                className="sso-input"
              />
              <button type="submit" className="sso-continue-btn" disabled={busy !== null}>
                {t("sso.continue")}
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="M5 12h14M13 5l7 7-7 7"/></svg>
              </button>
            </div>
            <p className="sso-help">We&rsquo;ll route you to the correct SSO provider for your domain.</p>
          </form>

          <div className="sso-divider"><span>{t("sso.orSignIn")}</span></div>

          <div className="sso-providers">
            {ssoProviders.map((p) => (
              <button
                key={p.id}
                className="sso-provider-btn"
                onClick={() => onProvider(p.id)}
                disabled={busy !== null}
                style={{ ["--provider-color" as string]: p.brandColor }}
              >
                <ProviderIcon icon={p.icon} />
                <span>{busy === p.id ? "Redirecting…" : `Continue with ${p.label}`}</span>
                {busy !== p.id && (
                  <svg className="sso-provider-arrow" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M9 18l6-6-6-6"/></svg>
                )}
              </button>
            ))}
          </div>

          <div className="sso-divider"><span>or</span></div>

          <button
            className="sso-default-btn"
            onClick={() => onProvider()}
            disabled={busy !== null}
          >
            Sign in with username & password
          </button>

          <p className="sso-fineprint">
            This portal is for authorized personnel of partner insurers and TPAs only.
            All activity is logged for audit per IRDAI guidelines.
          </p>

          <div className="sso-footer-row">
            <span>
              New to ClaimGPT?{" "}
              <button
                type="button"
                className="sso-link-btn"
                onClick={() => setSignupOpen(true)}
              >
                Create an account
              </button>
            </span>
            <span className="sso-region-tag">🇮🇳 IN · Mumbai</span>
          </div>
        </main>
      </div>

      <SignupModal
        open={signupOpen}
        onClose={() => setSignupOpen(false)}
        ssoProviders={ssoProviders}
      />
    </div>
  );
}

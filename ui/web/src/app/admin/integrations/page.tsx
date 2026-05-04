"use client";

/**
 * Admin → Integrations
 *
 * Stub configuration UI. Server-side wiring is future work; this captures
 * the credentials and toggles needed to connect Outlook (Microsoft Graph)
 * for claim notifications and to enable single sign-on.
 */

import { FormEvent, useState } from "react";

interface OutlookConfig {
  enabled: boolean;
  tenantId: string;
  clientId: string;
  clientSecret: string;
  fromAddress: string;
  notifyOnApproval: boolean;
  notifyOnRejection: boolean;
  notifyOnSettlement: boolean;
}

const SEED_OUTLOOK: OutlookConfig = {
  enabled: false,
  tenantId: "",
  clientId: "",
  clientSecret: "",
  fromAddress: "",
  notifyOnApproval: true,
  notifyOnRejection: true,
  notifyOnSettlement: true,
};

export default function AdminIntegrationsPage() {
  const [outlook, setOutlook] = useState<OutlookConfig>(SEED_OUTLOOK);
  const [saved, setSaved] = useState<"" | "outlook">("");
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState("");

  function patch<K extends keyof OutlookConfig>(key: K, value: OutlookConfig[K]) {
    setOutlook((prev) => ({ ...prev, [key]: value }));
  }

  function saveOutlook(e: FormEvent) {
    e.preventDefault();
    // Stub: persist to backend admin API. For now just flash a confirmation.
    setSaved("outlook");
    setTimeout(() => setSaved(""), 2000);
  }

  async function testOutlook() {
    setTesting(true); setTestResult("");
    // Stub: POST to /admin/integrations/outlook/test
    await new Promise((r) => setTimeout(r, 800));
    setTesting(false);
    setTestResult(
      outlook.tenantId && outlook.clientId && outlook.clientSecret
        ? "✓ Reached Microsoft Graph endpoint (mock)."
        : "✗ Missing tenant ID, client ID or secret.",
    );
  }

  return (
    <div className="admin-page">
      <header className="admin-page-header">
        <div>
          <h1 className="admin-page-title">Integrations</h1>
          <p className="admin-page-sub">
            Connect ClaimGPT to your organisation’s tooling. SSO is configured separately
            in <a href="/docs/sso-setup" className="admin-link">SSO setup</a>.
          </p>
        </div>
      </header>

      <section className="admin-card">
        <div className="admin-integration-header">
          <div>
            <div className="admin-integration-row">
              <span className="admin-integration-logo admin-integration-logo-outlook">
                <svg width="22" height="22" viewBox="0 0 32 32" fill="none">
                  <rect width="14" height="14" x="2"  y="2"  fill="#0078D4" />
                  <rect width="14" height="14" x="16" y="2"  fill="#28A8EA" />
                  <rect width="14" height="14" x="2"  y="16" fill="#0078D4" />
                  <rect width="14" height="14" x="16" y="16" fill="#0078D4" opacity="0.7" />
                </svg>
              </span>
              <div>
                <h2 className="admin-integration-title">Microsoft Outlook</h2>
                <p className="admin-integration-sub">Send claim notifications via your tenant’s Outlook (Microsoft Graph).</p>
              </div>
            </div>
          </div>
          <label className="admin-toggle">
            <input
              type="checkbox"
              checked={outlook.enabled}
              onChange={(e) => patch("enabled", e.target.checked)}
            />
            <span className="admin-toggle-track" />
            <span className="admin-toggle-label">{outlook.enabled ? "Enabled" : "Disabled"}</span>
          </label>
        </div>

        <form onSubmit={saveOutlook} className="admin-integration-body">
          <div className="admin-form-grid">
            <label className="admin-field">
              <span>Microsoft Tenant ID</span>
              <input
                className="admin-input admin-mono"
                placeholder="00000000-0000-0000-0000-000000000000"
                value={outlook.tenantId}
                onChange={(e) => patch("tenantId", e.target.value)}
                disabled={!outlook.enabled}
              />
            </label>
            <label className="admin-field">
              <span>Application (client) ID</span>
              <input
                className="admin-input admin-mono"
                placeholder="00000000-0000-0000-0000-000000000000"
                value={outlook.clientId}
                onChange={(e) => patch("clientId", e.target.value)}
                disabled={!outlook.enabled}
              />
            </label>
            <label className="admin-field admin-field-wide">
              <span>Client secret</span>
              <input
                className="admin-input admin-mono"
                type="password"
                placeholder="••••••••••••"
                value={outlook.clientSecret}
                onChange={(e) => patch("clientSecret", e.target.value)}
                disabled={!outlook.enabled}
              />
            </label>
            <label className="admin-field admin-field-wide">
              <span>Send notifications from</span>
              <input
                className="admin-input"
                type="email"
                placeholder="claims-bot@yourtpa.in"
                value={outlook.fromAddress}
                onChange={(e) => patch("fromAddress", e.target.value)}
                disabled={!outlook.enabled}
              />
            </label>
          </div>

          <fieldset className="admin-field">
            <legend>Trigger an email when…</legend>
            <div className="admin-checkbox-row">
              <label className="admin-checkbox">
                <input
                  type="checkbox"
                  checked={outlook.notifyOnApproval}
                  onChange={(e) => patch("notifyOnApproval", e.target.checked)}
                  disabled={!outlook.enabled}
                />
                <span>Claim is approved</span>
              </label>
              <label className="admin-checkbox">
                <input
                  type="checkbox"
                  checked={outlook.notifyOnRejection}
                  onChange={(e) => patch("notifyOnRejection", e.target.checked)}
                  disabled={!outlook.enabled}
                />
                <span>Claim is rejected</span>
              </label>
              <label className="admin-checkbox">
                <input
                  type="checkbox"
                  checked={outlook.notifyOnSettlement}
                  onChange={(e) => patch("notifyOnSettlement", e.target.checked)}
                  disabled={!outlook.enabled}
                />
                <span>Settlement is authorised</span>
              </label>
            </div>
          </fieldset>

          <div className="admin-help">
            Need help? In Azure, register an app with <code>Mail.Send</code> application permission,
            grant admin consent, then paste the tenant ID, client ID and a secret here.
          </div>

          {testResult && (
            <div className={`admin-test-result ${testResult.startsWith("✓") ? "admin-test-ok" : "admin-test-bad"}`}>
              {testResult}
            </div>
          )}
          {saved === "outlook" && <div className="admin-test-result admin-test-ok">Saved.</div>}

          <footer className="admin-form-actions">
            <button type="button" className="tpa-btn tpa-btn-secondary" onClick={testOutlook} disabled={testing || !outlook.enabled}>
              {testing ? "Testing…" : "Test connection"}
            </button>
            <button type="submit" className="tpa-btn tpa-btn-primary" disabled={!outlook.enabled}>
              Save changes
            </button>
          </footer>
        </form>
      </section>

      <section className="admin-card admin-integration-coming">
        <h3>Coming soon</h3>
        <ul>
          <li><strong>Slack</strong> — claim alerts in a channel of your choice.</li>
          <li><strong>WhatsApp Business</strong> — settlement notifications to insureds.</li>
          <li><strong>Webhooks</strong> — push every status change to your downstream systems.</li>
        </ul>
      </section>
    </div>
  );
}

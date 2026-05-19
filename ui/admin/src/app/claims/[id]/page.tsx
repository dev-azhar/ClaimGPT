"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { startWorkflow, runValidation, submitClaim } from "@/lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8001";

interface ClaimDetail {
  id: string;
  policy_id: string | null;
  patient_id: string | null;
  status: string;
  source: string | null;
  created_at: string;
  updated_at: string;
}

export default function ClaimDetailPage() {
  const params = useParams();
  const claimId = params.id as string;
  const [claim, setClaim] = useState<ClaimDetail | null>(null);
  const [actionLog, setActionLog] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/claims/${claimId}`)
      .then((r) => r.json())
      .then(setClaim)
      .catch(() => setActionLog((prev) => [...prev, "Failed to load claim"]));
  }, [claimId]);

  async function handleAction(label: string, fn: () => Promise<unknown>) {
    setLoading(true);
    setActionLog((prev) => [...prev, `Starting ${label}...`]);
    try {
      const result = await fn();
      setActionLog((prev) => [...prev, `${label}: ${JSON.stringify(result).substring(0, 200)}`]);
      // Reload claim state
      const updated = await fetch(`${API_BASE}/claims/${claimId}`).then((r) => r.json());
      setClaim(updated);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setActionLog((prev) => [...prev, `${label} failed: ${message}`]);
    } finally {
      setLoading(false);
    }
  }

  if (!claim) return <div className="container">Loading claim...</div>;

  return (
    <div className="container">
      <a href="/" style={{ color: "var(--accent)", marginBottom: "1rem", display: "block" }}>
        ← Back to Dashboard
      </a>

      <h1 style={{ fontSize: "1.5rem", marginBottom: "0.5rem" }}>
        Claim {claim.id.substring(0, 8)}...
      </h1>

      <div className="grid-2" style={{ marginBottom: "2rem" }}>
        <div className="card">
          <h3 style={{ fontSize: "0.875rem", color: "var(--muted)" }}>Details</h3>
          <table>
            <tbody>
              <tr><td>ID</td><td style={{ fontFamily: "monospace", fontSize: "0.8rem" }}>{claim.id}</td></tr>
              <tr><td>Status</td><td><span className="badge badge-muted">{claim.status}</span></td></tr>
              <tr><td>Policy</td><td>{claim.policy_id || "—"}</td></tr>
              <tr><td>Patient</td><td>{claim.patient_id || "—"}</td></tr>
              <tr><td>Source</td><td>{claim.source || "—"}</td></tr>
              <tr><td>Created</td><td>{new Date(claim.created_at).toLocaleString()}</td></tr>
            </tbody>
          </table>
        </div>

        <div className="card">
          <h3 style={{ fontSize: "0.875rem", color: "var(--muted)", marginBottom: "1rem" }}>Actions</h3>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
            <button
              className="btn-primary"
              disabled={loading}
              onClick={() => handleAction("Workflow", () => startWorkflow(claimId))}
            >
              Run Full Pipeline
            </button>
            <button
              disabled={loading}
              onClick={() => handleAction("Validation", () => runValidation(claimId))}
            >
              Validate
            </button>
            <button
              disabled={loading}
              onClick={() => handleAction("Submission", () => submitClaim(claimId))}
            >
              Submit to Payer
            </button>
          </div>
        </div>
      </div>

      {/* Action Log */}
      {actionLog.length > 0 && (
        <div className="card">
          <h3 style={{ fontSize: "0.875rem", color: "var(--muted)", marginBottom: "0.5rem" }}>Activity Log</h3>
          <div style={{ fontFamily: "monospace", fontSize: "0.8rem", maxHeight: "300px", overflowY: "auto" }}>
            {actionLog.map((log, i) => (
              <div key={i} style={{ borderBottom: "1px solid var(--border)", padding: "0.25rem 0" }}>
                {log}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000/ingress";
const WORKFLOW_BASE = process.env.NEXT_PUBLIC_WORKFLOW_BASE || "http://localhost:8000/workflow";

export default function ClaimDetailPage() {
  const params = useParams();
  const claimId = params.id as string;
  const [claim, setClaim] = useState<Record<string, unknown> | null>(null);
  const [status, setStatus] = useState("");

  useEffect(() => {
    fetch(`${API_BASE}/claims/${claimId}`)
      .then((r) => r.json())
      .then((data) => {
        setClaim(data);
        setStatus("");
      })
      .catch(() => setStatus("Failed to load claim"));
  }, [claimId]);

  async function handleProcess() {
    setStatus("Starting pipeline...");
    try {
      const resp = await fetch(`${WORKFLOW_BASE}/start/${claimId}`, { method: "POST" });
      const data = await resp.json();
      setStatus(`Pipeline started! Job ID: ${data.job_id}`);
    } catch {
      setStatus("Failed to start pipeline");
    }
  }

  if (!claim) return <div className="container">Loading...</div>;

  return (
    <div className="container">
      <a href="/claims" style={{ color: "var(--accent)", marginBottom: "1rem", display: "block" }}>← Back to Claims</a>

      <h1 style={{ fontSize: "1.5rem", marginBottom: "1rem" }}>Claim Details</h1>

      <div className="card">
        <table style={{ width: "100%" }}>
          <tbody>
            {Object.entries(claim).map(([key, value]) => (
              <tr key={key}>
                <td style={{ fontWeight: 500, width: "30%" }}>{key}</td>
                <td style={{ fontFamily: "monospace", fontSize: "0.875rem" }}>{String(value ?? "—")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div style={{ display: "flex", gap: "1rem", marginTop: "1rem" }}>
        <button className="btn btn-primary" onClick={handleProcess}>
          Process Claim (Full Pipeline)
        </button>
        <a href={`/chat?claim=${claimId}`} className="btn btn-secondary">
          Ask About This Claim
        </a>
      </div>

      {status && (
        <div className="card" style={{ marginTop: "1rem" }}>
          <div style={{ fontSize: "0.875rem" }}>{status}</div>
        </div>
      )}
    </div>
  );
}

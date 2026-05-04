"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000/ingress";
const WORKFLOW_BASE = process.env.NEXT_PUBLIC_WORKFLOW_BASE || "http://localhost:8000/workflow";

type ClaimRecord = Record<string, unknown>;

type ProgressResponse = {
  status: string | null;
  step: string | null;
  percentage: number;
  is_complete: boolean;
};

export default function ClaimDetailPage() {
  const params = useParams();
  const claimId = params.id as string;
  const [claim, setClaim] = useState<ClaimRecord | null>(null);
  const [progress, setProgress] = useState<ProgressResponse | null>(null);
  const [isStarting, setIsStarting] = useState(false);
  const [status, setStatus] = useState("");

  const isProcessing = useMemo(() => {
    if (!progress) return false;
    return !progress.is_complete && progress.status !== "FAILED";
  }, [progress]);

  useEffect(() => {
    fetch(`${API_BASE}/claims/${claimId}`)
      .then((r) => r.json())
      .then((data) => {
        setClaim(data);
        setStatus("");
      })
      .catch(() => setStatus("Failed to load claim"));
  }, [claimId]);

  useEffect(() => {
    let timer: number | undefined;

    async function loadProgress() {
      try {
        const resp = await fetch(`${API_BASE}/claims/${claimId}/progress`);
        const data = (await resp.json()) as ProgressResponse;
        setProgress(data);
      } catch {
        setProgress(null);
      }
    }

    void loadProgress();
    timer = window.setInterval(() => {
      void loadProgress();
    }, 3000);

    return () => {
      if (timer) window.clearInterval(timer);
    };
  }, [claimId]);

  async function handleProcess() {
    setIsStarting(true);
    setStatus("Starting pipeline...");
    try {
      const resp = await fetch(`${WORKFLOW_BASE}/start/${claimId}`, { method: "POST" });
      const data = await resp.json();
      setStatus(`Pipeline started! Job ID: ${data.job_id}`);
      setProgress({ status: "RUNNING", step: "Starting", percentage: 0, is_complete: false });
    } catch {
      setStatus("Failed to start pipeline");
    } finally {
      setIsStarting(false);
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

      <div style={{ display: "flex", gap: "1rem", marginTop: "1rem", flexWrap: "wrap" }}>
        <button className="btn btn-primary" onClick={handleProcess} disabled={isStarting}>
          Process Claim (Full Pipeline)
        </button>
        <a href={`/chat?claim=${claimId}`} className="btn btn-secondary">
          Ask About This Claim
        </a>
      </div>

      {isProcessing && (
        <div className="card" style={{ marginTop: "1rem", border: "1px solid rgba(99, 102, 241, 0.25)" }}>
          <div style={{ fontSize: "0.95rem", fontWeight: 600, marginBottom: "0.4rem" }}>
            Report generation in progress
          </div>
          <div style={{ color: "var(--muted)", fontSize: "0.875rem", marginBottom: "0.75rem" }}>
            Current step: {progress?.step || progress?.status || "Processing"}
          </div>
          <div style={{ width: "100%", height: "8px", borderRadius: "999px", background: "rgba(148, 163, 184, 0.18)" }}>
            <div
              style={{
                width: `${progress?.percentage ?? 0}%`,
                height: "100%",
                borderRadius: "999px",
                background: "linear-gradient(90deg, #2563eb, #22c55e)",
                transition: "width 250ms ease",
              }}
            />
          </div>
          <div style={{ marginTop: "0.5rem", fontSize: "0.8rem", color: "var(--muted)" }}>
            {Math.round(progress?.percentage ?? 0)}% complete
          </div>
        </div>
      )}

      {progress?.status === "FAILED" && (
        <div className="card" style={{ marginTop: "1rem", border: "1px solid rgba(239, 68, 68, 0.25)" }}>
          <div style={{ fontSize: "0.95rem", fontWeight: 600, marginBottom: "0.4rem", color: "var(--error)" }}>
            Processing failed
          </div>
          <div style={{ color: "var(--muted)", fontSize: "0.875rem" }}>
            The latest workflow run did not complete. You can retry the pipeline after checking the logs.
          </div>
        </div>
      )}

      {status && (
        <div className="card" style={{ marginTop: "1rem" }}>
          <div style={{ fontSize: "0.875rem" }}>{status}</div>
        </div>
      )}
    </div>
  );
}

"use client";

import { useEffect, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000/ingress";

interface Claim {
  id: string;
  policy_id: string | null;
  patient_id: string | null;
  status: string;
  created_at: string;
}

export default function ClaimsListPage() {
  const [claims, setClaims] = useState<Claim[]>([]);
  const [total, setTotal] = useState(0);

  useEffect(() => {
    fetch(`${API_BASE}/claims?limit=50`)
      .then((r) => r.json())
      .then((data) => {
        setClaims(data.claims || []);
        setTotal(data.total || 0);
      })
      .catch(() => {});
  }, []);

  return (
    <div className="container">
      <a href="/" style={{ color: "var(--accent)", marginBottom: "1rem", display: "block" }}>← Home</a>
      <h1 style={{ fontSize: "1.5rem", marginBottom: "1rem" }}>My Claims ({total})</h1>

      {claims.length === 0 ? (
        <div className="card" style={{ textAlign: "center", color: "var(--muted)" }}>
          No claims found. <a href="/">Submit your first claim</a>
        </div>
      ) : (
        claims.map((c) => (
          <a
            key={c.id}
            href={`/claims/${c.id}`}
            className="card"
            style={{ display: "block", textDecoration: "none", color: "var(--fg)" }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <div style={{ fontFamily: "monospace", fontSize: "0.8rem" }}>{c.id.substring(0, 8)}...</div>
                <div style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
                  {c.policy_id || "No policy"} · {new Date(c.created_at).toLocaleDateString()}
                </div>
              </div>
              <span className="status-badge" style={{
                background: c.status.includes("FAIL") || c.status === "REJECTED" ? "#fef2f2" : "#f0fdf4",
                color: c.status.includes("FAIL") || c.status === "REJECTED" ? "var(--error)" : "var(--success)",
              }}>
                {c.status}
              </span>
            </div>
          </a>
        ))
      )}
    </div>
  );
}

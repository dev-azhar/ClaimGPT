"use client";

import { useEffect, useState } from "react";
import { fetchClaims, checkAllHealth, type Claim, type ServiceHealth } from "@/lib/api";

export default function AdminDashboard() {
  const [claims, setClaims] = useState<Claim[]>([]);
  const [total, setTotal] = useState(0);
  const [health, setHealth] = useState<Record<string, ServiceHealth | null>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadData();
  }, []);

  async function loadData() {
    setLoading(true);
    try {
      const [claimData, healthData] = await Promise.all([
        fetchClaims(0, 20).catch(() => ({ claims: [], total: 0 })),
        checkAllHealth(),
      ]);
      setClaims(claimData.claims);
      setTotal(claimData.total);
      setHealth(healthData);
    } finally {
      setLoading(false);
    }
  }

  function statusBadge(status: string) {
    if (status === "ok") return "badge badge-success";
    if (status === "degraded") return "badge badge-warning";
    return "badge badge-error";
  }

  function claimStatusBadge(status: string) {
    if (["COMPLETED", "VALIDATED", "SUBMITTED", "APPROVED"].includes(status)) return "badge badge-success";
    if (["PROCESSING", "OCR_PROCESSING", "PARSING"].includes(status)) return "badge badge-warning";
    if (status.includes("FAILED") || status === "REJECTED") return "badge badge-error";
    return "badge badge-muted";
  }

  return (
    <div className="container">
      <header style={{ marginBottom: "2rem" }}>
        <h1 style={{ fontSize: "1.5rem", fontWeight: 700 }}>ClaimGPT Admin Dashboard</h1>
        <p style={{ color: "var(--muted)" }}>Claims management &amp; service monitoring</p>
      </header>

      {/* Service Health Grid */}
      <section style={{ marginBottom: "2rem" }}>
        <h2 style={{ fontSize: "1.125rem", marginBottom: "1rem" }}>Service Health</h2>
        <div className="grid-4">
          {Object.entries(health).map(([svc, h]) => (
            <div key={svc} className="card" style={{ textAlign: "center" }}>
              <div style={{ fontSize: "0.75rem", color: "var(--muted)", marginBottom: "0.5rem" }}>
                {svc.toUpperCase()}
              </div>
              <span className={h ? statusBadge(h.status) : "badge badge-error"}>
                {h ? h.status : "DOWN"}
              </span>
            </div>
          ))}
        </div>
      </section>

      {/* Claims Table */}
      <section>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "1rem" }}>
          <h2 style={{ fontSize: "1.125rem" }}>Claims ({total})</h2>
          <button onClick={loadData} disabled={loading}>
            {loading ? "Loading..." : "Refresh"}
          </button>
        </div>

        <div className="card" style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                <th>Claim ID</th>
                <th>Policy</th>
                <th>Patient</th>
                <th>Status</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {claims.length === 0 ? (
                <tr>
                  <td colSpan={5} style={{ textAlign: "center", color: "var(--muted)" }}>
                    {loading ? "Loading claims..." : "No claims found"}
                  </td>
                </tr>
              ) : (
                claims.map((c) => (
                  <tr key={c.id}>
                    <td>
                      <a href={`/claims/${c.id}`} style={{ fontFamily: "monospace", fontSize: "0.8rem" }}>
                        {c.id.substring(0, 8)}...
                      </a>
                    </td>
                    <td>{c.policy_id || "—"}</td>
                    <td>{c.patient_id || "—"}</td>
                    <td><span className={claimStatusBadge(c.status)}>{c.status}</span></td>
                    <td style={{ color: "var(--muted)", fontSize: "0.875rem" }}>
                      {new Date(c.created_at).toLocaleDateString()}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

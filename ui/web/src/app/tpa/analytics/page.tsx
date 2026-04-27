"use client";

import { useEffect, useState, useCallback } from "react";
import { useAuth } from "@/lib/auth";
import { API_BASE, apiFetch } from "@/lib/api";

interface Claim {
  id: string;
  status: string;
  created_at: string;
}

interface Stats {
  total: number;
  byStatus: Record<string, number>;
  byMonth: { month: string; count: number }[];
  avgPerDay: number;
}

function computeStats(claims: Claim[]): Stats {
  const byStatus: Record<string, number> = {};
  const byMonth: Record<string, number> = {};

  for (const c of claims) {
    byStatus[c.status] = (byStatus[c.status] || 0) + 1;
    const month = c.created_at?.substring(0, 7); // YYYY-MM
    if (month) byMonth[month] = (byMonth[month] || 0) + 1;
  }

  const sortedMonths = Object.entries(byMonth)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([month, count]) => ({ month, count }));

  // Days span
  if (claims.length === 0) {
    return { total: 0, byStatus, byMonth: sortedMonths, avgPerDay: 0 };
  }
  const dates = claims.map((c) => new Date(c.created_at).getTime()).filter(Boolean);
  const span = Math.max(1, (Math.max(...dates) - Math.min(...dates)) / 86400000);
  const avgPerDay = Math.round((claims.length / span) * 10) / 10;

  return { total: claims.length, byStatus, byMonth: sortedMonths, avgPerDay };
}

const STATUS_COLORS: Record<string, string> = {
  COMPLETED: "var(--green)",
  SUBMITTED: "var(--blue)",
  VALIDATED: "#16a34a",
  PREDICTED: "#0ea5e9",
  PROCESSING: "#0ea5e9",
  UPLOADED: "#94a3b8",
  APPROVED: "#059669",
  REJECTED: "#dc2626",
  MODIFICATION_REQUESTED: "#d97706",
  DOCUMENTS_REQUESTED: "#2563eb",
  VALIDATION_FAILED: "var(--red)",
  WORKFLOW_FAILED: "var(--red)",
  MANUAL_REVIEW_REQUIRED: "var(--yellow)",
};

export default function AnalyticsPage() {
  const { token } = useAuth();
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiFetch<{ claims: Claim[]; total: number }>(
        `${API_BASE}/claims?offset=0&limit=500`,
        { token },
      );
      setStats(computeStats(data.claims || []));
    } catch {
      setStats(null);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  if (loading) return <div className="tpa-table-empty">Loading analytics...</div>;
  if (!stats) return <div className="tpa-table-empty">Failed to load data</div>;

  const maxMonthCount = Math.max(...stats.byMonth.map((m) => m.count), 1);
  const maxStatusCount = Math.max(...Object.values(stats.byStatus), 1);

  return (
    <div className="tpa-dashboard">
      {/* KPI Row */}
      <div className="tpa-summary-row">
        <div className="tpa-summary-card">
          <div className="tpa-summary-label">Total Claims</div>
          <div className="tpa-summary-value">{stats.total}</div>
        </div>
        <div className="tpa-summary-card">
          <div className="tpa-summary-label">Avg / Day</div>
          <div className="tpa-summary-value">{stats.avgPerDay}</div>
        </div>
        <div className="tpa-summary-card">
          <div className="tpa-summary-label">Success Rate</div>
          <div className="tpa-summary-value tpa-text-success">
            {stats.total > 0
              ? `${(
                  (((stats.byStatus["COMPLETED"] || 0) + (stats.byStatus["SUBMITTED"] || 0)) /
                    stats.total) *
                  100
                ).toFixed(1)}%`
              : "—"}
          </div>
        </div>
        <div className="tpa-summary-card">
          <div className="tpa-summary-label">Failure Rate</div>
          <div className="tpa-summary-value tpa-text-error">
            {stats.total > 0
              ? `${(
                  (((stats.byStatus["VALIDATION_FAILED"] || 0) +
                    (stats.byStatus["WORKFLOW_FAILED"] || 0)) /
                    stats.total) *
                  100
                ).toFixed(1)}%`
              : "—"}
          </div>
        </div>
      </div>

      <div className="tpa-grid-2">
        {/* Status Distribution */}
        <div className="tpa-card">
          <h3 className="tpa-card-title">Claims by Status</h3>
          <div className="tpa-chart-bars">
            {Object.entries(stats.byStatus)
              .sort(([, a], [, b]) => b - a)
              .map(([status, count]) => (
                <div key={status} className="tpa-bar-row">
                  <span className="tpa-bar-label">{status.replace(/_/g, " ")}</span>
                  <div className="tpa-bar-track">
                    <div
                      className="tpa-bar-fill"
                      style={{
                        width: `${(count / maxStatusCount) * 100}%`,
                        background: STATUS_COLORS[status] || "var(--accent)",
                      }}
                    />
                  </div>
                  <span className="tpa-bar-value">{count}</span>
                </div>
              ))}
          </div>
        </div>

        {/* Monthly Trend */}
        <div className="tpa-card">
          <h3 className="tpa-card-title">Monthly Volume</h3>
          {stats.byMonth.length > 0 ? (
            <div className="tpa-chart-bars">
              {stats.byMonth.slice(-12).map((m) => (
                <div key={m.month} className="tpa-bar-row">
                  <span className="tpa-bar-label">{m.month}</span>
                  <div className="tpa-bar-track">
                    <div
                      className="tpa-bar-fill"
                      style={{
                        width: `${(m.count / maxMonthCount) * 100}%`,
                        background: "var(--accent)",
                      }}
                    />
                  </div>
                  <span className="tpa-bar-value">{m.count}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="tpa-muted">No data yet</p>
          )}
        </div>

        {/* Status breakdown table */}
        <div className="tpa-card" style={{ gridColumn: "1 / -1" }}>
          <h3 className="tpa-card-title">Status Breakdown</h3>
          <table className="tpa-table">
            <thead>
              <tr>
                <th>Status</th>
                <th style={{ textAlign: "right" }}>Count</th>
                <th style={{ textAlign: "right" }}>% of Total</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(stats.byStatus)
                .sort(([, a], [, b]) => b - a)
                .map(([status, count]) => (
                  <tr key={status}>
                    <td>
                      <span
                        style={{
                          display: "inline-block",
                          width: 10,
                          height: 10,
                          borderRadius: "50%",
                          background: STATUS_COLORS[status] || "var(--accent)",
                          marginRight: 8,
                        }}
                      />
                      {status.replace(/_/g, " ")}
                    </td>
                    <td style={{ textAlign: "right" }}>{count}</td>
                    <td style={{ textAlign: "right" }}>
                      {((count / stats.total) * 100).toFixed(1)}%
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

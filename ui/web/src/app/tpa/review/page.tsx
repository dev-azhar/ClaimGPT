"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { API_BASE, SUBMISSION_API, VALIDATOR_API, apiFetch } from "@/lib/api";

interface Claim {
  id: string;
  policy_id: string | null;
  patient_id: string | null;
  status: string;
  created_at: string;
  documents: { id: string; file_name: string }[];
}

interface PreviewSummary {
  claim_id: string;
  status: string;
  billed_total: number;
  predictions: { rejection_score: number; top_reasons: { reason: string; weight?: number; feature?: string }[] }[];
  validations: { rule_name: string; severity: string; passed: boolean; message: string }[];
  summary?: {
    patient_name?: string;
    policy_number?: string;
    hospital?: string;
    diagnosis?: string;
  };
}

interface ReviewItem {
  claim: Claim;
  preview: PreviewSummary | null;
}

export default function ReviewQueuePage() {
  const { token } = useAuth();
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionMsg, setActionMsg] = useState("");

  const loadQueue = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiFetch<{ claims: Claim[]; total: number }>(
        `${API_BASE}/claims?offset=0&limit=100`,
        { token },
      );
      // Filter to claims needing review
      const needsReview = (data.claims || []).filter(
        (c) =>
          c.status === "MANUAL_REVIEW_REQUIRED" ||
          c.status === "VALIDATION_FAILED" ||
          c.status === "WORKFLOW_FAILED" ||
          c.status === "VALIDATED",
      );

      // Load previews in parallel (best-effort)
      const reviewItems: ReviewItem[] = await Promise.all(
        needsReview.map(async (claim) => {
          try {
            const preview = await apiFetch<PreviewSummary>(
              `${SUBMISSION_API}/claims/${claim.id}/preview`,
              { token },
            );
            return { claim, preview };
          } catch {
            return { claim, preview: null };
          }
        }),
      );

      setItems(reviewItems);
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    loadQueue();
  }, [loadQueue]);

  async function handleApprove(claimId: string) {
    setActionMsg(`Submitting claim ${claimId.substring(0, 8)}...`);
    try {
      await apiFetch(`${SUBMISSION_API}/submit/${claimId}`, { method: "POST", token });
      setActionMsg(`Claim ${claimId.substring(0, 8)} submitted`);
      loadQueue();
    } catch {
      setActionMsg("Submission failed");
    }
  }

  async function handleRevalidate(claimId: string) {
    setActionMsg(`Re-validating ${claimId.substring(0, 8)}...`);
    try {
      await apiFetch(`${VALIDATOR_API}/validate/${claimId}`, { method: "POST", token });
      setActionMsg(`Validation complete for ${claimId.substring(0, 8)}`);
      loadQueue();
    } catch {
      setActionMsg("Re-validation failed");
    }
  }

  function riskLevel(score: number | undefined) {
    if (score == null) return { label: "N/A", cls: "tpa-badge-neutral" };
    if (score > 0.7) return { label: "High", cls: "tpa-badge-error" };
    if (score > 0.4) return { label: "Medium", cls: "tpa-badge-warn" };
    return { label: "Low", cls: "tpa-badge-success" };
  }

  function statusClass(status: string) {
    if (status === "VALIDATED") return "tpa-badge-success";
    if (status === "MANUAL_REVIEW_REQUIRED") return "tpa-badge-warn";
    if (status.includes("FAIL")) return "tpa-badge-error";
    return "tpa-badge-neutral";
  }

  return (
    <div className="tpa-dashboard">
      {actionMsg && <div className="tpa-alert">{actionMsg}</div>}

      <div className="tpa-toolbar">
        <div>
          <strong>{items.length}</strong> claim{items.length !== 1 ? "s" : ""} require attention
        </div>
        <button className="tpa-btn tpa-btn-secondary" onClick={loadQueue}>
          Refresh
        </button>
      </div>

      {loading ? (
        <div className="tpa-table-empty">Loading review queue...</div>
      ) : items.length === 0 ? (
        <div className="tpa-table-empty">
          <p>No claims need review right now.</p>
        </div>
      ) : (
        <div className="tpa-review-list">
          {items.map(({ claim, preview }) => {
            const score = preview?.predictions?.[0]?.rejection_score;
            const risk = riskLevel(score);
            const failedValidations = preview?.validations?.filter((v) => !v.passed) || [];

            return (
              <div key={claim.id} className="tpa-review-card">
                <div className="tpa-review-header">
                  <div>
                    <Link href={`/tpa/claims/${claim.id}`} className="tpa-review-id">
                      {claim.id.substring(0, 12)}...
                    </Link>
                    <span className={`tpa-badge ${statusClass(claim.status)}`} style={{ marginLeft: 8 }}>
                      {claim.status.replace(/_/g, " ")}
                    </span>
                  </div>
                  <span className="tpa-muted">
                    {new Date(claim.created_at).toLocaleDateString()}
                  </span>
                </div>

                <div className="tpa-review-body">
                  <div className="tpa-review-meta">
                    <div>
                      <span className="tpa-field-label">Patient</span>
                      <span>{preview?.summary?.patient_name && preview.summary.patient_name !== "N/A" ? preview.summary.patient_name : claim.patient_id?.substring(0, 8) || "—"}</span>
                    </div>
                    <div>
                      <span className="tpa-field-label">Policy</span>
                      <span className="tpa-mono">{preview?.summary?.policy_number && preview.summary.policy_number !== "N/A" ? preview.summary.policy_number : claim.policy_id || "—"}</span>
                    </div>
                    <div>
                      <span className="tpa-field-label">Billed</span>
                      <span>{preview?.billed_total != null ? `$${preview.billed_total.toLocaleString()}` : "—"}</span>
                    </div>
                    <div>
                      <span className="tpa-field-label">Risk</span>
                      <span className={`tpa-badge ${risk.cls}`}>{risk.label}</span>
                    </div>
                  </div>

                  {failedValidations.length > 0 && (
                    <div className="tpa-review-issues">
                      <span className="tpa-field-label">Issues ({failedValidations.length})</span>
                      <ul className="tpa-reason-list">
                        {failedValidations.slice(0, 3).map((v, i) => (
                          <li key={i}>
                            <span className={`tpa-badge tpa-badge-sm ${v.severity === "ERROR" ? "tpa-badge-error" : "tpa-badge-warn"}`}>
                              {v.severity}
                            </span>
                            {" "}{v.message}
                          </li>
                        ))}
                        {failedValidations.length > 3 && (
                          <li className="tpa-muted">+{failedValidations.length - 3} more...</li>
                        )}
                      </ul>
                    </div>
                  )}

                  {(preview?.predictions?.[0]?.top_reasons?.length ?? 0) > 0 && (
                    <div className="tpa-review-issues">
                      <span className="tpa-field-label">Risk Factors</span>
                      <ul className="tpa-reason-list">
                        {preview!.predictions[0].top_reasons.slice(0, 3).map((r, i) => (
                          <li key={i}>{typeof r === "string" ? r : r.reason}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>

                <div className="tpa-review-actions">
                  <Link href={`/tpa/claims/${claim.id}`} className="tpa-btn tpa-btn-sm">
                    Full Details
                  </Link>
                  <button className="tpa-btn tpa-btn-sm tpa-btn-secondary" onClick={() => handleRevalidate(claim.id)}>
                    Re-validate
                  </button>
                  {claim.status === "VALIDATED" && (
                    <button className="tpa-btn tpa-btn-sm tpa-btn-primary" onClick={() => handleApprove(claim.id)}>
                      Approve & Submit
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

"use client";

import { useEffect, useState, useCallback, useRef, FormEvent, MouseEvent as ReactMouseEvent } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";
import {
  API_BASE,
  SUBMISSION_API,
  WORKFLOW_API,
  VALIDATOR_API,
  PREDICTOR_API,
  CHAT_API,
  apiFetch,
} from "@/lib/api";

interface Document {
  id: string;
  file_name: string;
  file_type?: string;
  uploaded_at?: string;
}

interface ClaimPreview {
  claim_id: string;
  status: string;
  parsed_fields: Record<string, string>;
  icd_codes: { code: string; description: string; estimated_cost?: number; is_primary?: boolean }[];
  cpt_codes: { code: string; description: string; estimated_cost?: number }[];
  cost_summary: Record<string, unknown>;
  expenses: { description: string; amount: number }[];
  billed_total: number;
  predictions: { rejection_score: number; top_reasons: { reason: string; weight?: number; feature?: string }[]; model_name?: string }[];
  validations: { rule_name: string; severity: string; message: string; passed: boolean }[];
  documents: Document[];
  scan_analyses: { scan_type: string; body_part: string; findings: string; impression: string }[];
  identity_review: Record<string, unknown>;
  summary: {
    patient_name?: string;
    policy_number?: string;
    age?: string;
    gender?: string;
    hospital?: string;
    doctor?: string;
    admission_date?: string;
    discharge_date?: string;
    diagnosis?: string;
    history_of_present_illness?: string;
    past_history?: string;
    disease_history?: string;
    allergies?: string;
    treatment?: string;
  };
  brain_insights: string;
}

interface AuditEntry {
  id: string;
  actor: string;
  action: string;
  metadata: Record<string, unknown>;
  created_at: string;
}

interface TpaProvider {
  id: string;
  name: string;
  logo?: string;
  type?: string;
}

type Tab = "overview" | "codes" | "validations" | "documents" | "chat" | "audit";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

interface Annotation {
  x: number;
  y: number;
  w: number;
  h: number;
  color: string;
  note: string;
  page?: number;
}

export default function TpaClaimDetail() {
  const { id: claimId } = useParams<{ id: string }>();
  const { token } = useAuth();
  const { lang } = useI18n();

  const [preview, setPreview] = useState<ClaimPreview | null>(null);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [tpas, setTpas] = useState<TpaProvider[]>([]);
  const [tab, setTab] = useState<Tab>("overview");
  const [loading, setLoading] = useState(true);
  const [actionStatus, setActionStatus] = useState("");
  const [selectedTpa, setSelectedTpa] = useState("");
  const [showSubmitModal, setShowSubmitModal] = useState(false);

  /* ── TPA Action state ── */
  type TpaAction = "approve" | "reject" | "send_back" | "request_docs" | null;
  const [showActionModal, setShowActionModal] = useState<TpaAction>(null);
  const [actionReason, setActionReason] = useState("");
  const [requestedDocs, setRequestedDocs] = useState<string[]>([]);
  const [actionSubmitting, setActionSubmitting] = useState(false);

  /* ── Document viewer state ── */
  const [viewingDoc, setViewingDoc] = useState<Document | null>(null);
  const [docBlobUrl, setDocBlobUrl] = useState<string | null>(null);
  const [docLoading, setDocLoading] = useState(false);
  const docBlobRef = useRef<string | null>(null);

  /* ── Annotation / Highlight state ── */
  const [annotationMode, setAnnotationMode] = useState(false);
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [annotationColor, setAnnotationColor] = useState("#FFEB3B");
  const [isDrawing, setIsDrawing] = useState(false);
  const [drawStart, setDrawStart] = useState<{ x: number; y: number } | null>(null);
  const [drawCurrent, setDrawCurrent] = useState<{ x: number; y: number } | null>(null);
  const [editingAnnotation, setEditingAnnotation] = useState<number | null>(null);
  const [annotationNote, setAnnotationNote] = useState("");
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const docContainerRef = useRef<HTMLDivElement>(null);

  /* ── Chat state ── */
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [chatSessionId] = useState(() => `tpa-${claimId}-${Date.now()}`);
  const chatEndRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [previewData, tpaData] = await Promise.all([
        apiFetch<ClaimPreview>(`${SUBMISSION_API}/claims/${claimId}/preview`, { token }),
        apiFetch<{ tpas: TpaProvider[] }>(`${SUBMISSION_API}/tpa-list`, { token }),
      ]);
      setPreview(previewData);
      setTpas(tpaData.tpas || []);
    } catch {
      setActionStatus("Failed to load claim data");
    } finally {
      setLoading(false);
    }
  }, [claimId, token]);

  useEffect(() => {
    load();
  }, [load]);

  async function loadAudit() {
    try {
      const data = await apiFetch<{ audit_trail: AuditEntry[] }>(
        `${SUBMISSION_API}/claims/${claimId}/audit`,
        { token },
      );
      setAudit(data.audit_trail || []);
    } catch {
      /* ignore */
    }
  }

  useEffect(() => {
    if (tab === "audit") loadAudit();
    // Auto-open first document when switching to documents tab
    if (tab === "documents" && preview?.documents?.length && !viewingDoc) {
      openDocument(preview.documents[0]);
    }
  }, [tab]);

  async function handleRerunPipeline() {
    setActionStatus("Starting pipeline...");
    try {
      const data = await apiFetch<{ job_id: string }>(
        `${WORKFLOW_API}/start/${claimId}`,
        { method: "POST", token },
      );
      setActionStatus(`Pipeline started — Job ${data.job_id.substring(0, 8)}`);
    } catch {
      setActionStatus("Failed to start pipeline");
    }
  }

  async function handleRevalidate() {
    setActionStatus("Re-validating...");
    try {
      await apiFetch(`${VALIDATOR_API}/validate/${claimId}`, { method: "POST", token });
      setActionStatus("Validation complete");
      load();
    } catch {
      setActionStatus("Validation failed");
    }
  }

  async function handleRepredict() {
    setActionStatus("Re-predicting...");
    try {
      await apiFetch(`${PREDICTOR_API}/predict/${claimId}`, { method: "POST", token });
      setActionStatus("Prediction complete");
      load();
    } catch {
      setActionStatus("Prediction failed");
    }
  }

  async function handleSubmitToTpa() {
    if (!selectedTpa) return;
    setActionStatus("Submitting to TPA...");
    try {
      const data = await apiFetch<{ status: string; tpa_name: string; reference: string }>(
        `${SUBMISSION_API}/claims/${claimId}/send-to-tpa`,
        { method: "POST", token, body: JSON.stringify({ tpa_id: selectedTpa }) },
      );
      setActionStatus(`Submitted to ${data.tpa_name} — Ref: ${data.reference}`);
      setShowSubmitModal(false);
      load();
    } catch {
      setActionStatus("Submission failed");
    }
  }

  async function handleDownloadPdf(type: "tpa" | "irda") {
    try {
      const url =
        type === "tpa"
          ? `${SUBMISSION_API}/claims/${claimId}/tpa-pdf`
          : `${SUBMISSION_API}/claims/${claimId}/irda-pdf`;
      const res = await fetch(url, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) throw new Error("Download failed");
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${claimId}-${type}.pdf`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch {
      setActionStatus("PDF download failed");
    }
  }

  /* ── TPA Decision Actions ── */
  async function handleTpaAction() {
    if (!showActionModal) return;
    setActionSubmitting(true);
    const labels: Record<string, string> = {
      approve: "Approving",
      reject: "Rejecting",
      send_back: "Sending back",
      request_docs: "Requesting documents",
    };
    setActionStatus(`${labels[showActionModal]}...`);
    try {
      const data = await apiFetch<{ status: string; message: string; new_status: string }>(
        `${SUBMISSION_API}/claims/${claimId}/tpa-action`,
        {
          method: "POST",
          token,
          body: JSON.stringify({
            action: showActionModal,
            reason: actionReason,
            requested_documents: requestedDocs,
            ...(showActionModal === "send_back" && annotations.length > 0 ? { annotations } : {}),
          }),
        },
      );
      setActionStatus(data.message);
      setShowActionModal(null);
      setActionReason("");
      setRequestedDocs([]);
      load(); // refresh claim data
    } catch {
      setActionStatus(`${labels[showActionModal]} failed`);
    } finally {
      setActionSubmitting(false);
    }
  }

  function openActionModal(action: "approve" | "reject" | "send_back" | "request_docs") {
    setShowActionModal(action);
    setActionReason("");
    setRequestedDocs([]);
  }

  function toggleRequestedDoc(docType: string) {
    setRequestedDocs((prev) =>
      prev.includes(docType) ? prev.filter((d) => d !== docType) : [...prev, docType],
    );
  }

  /* ── Chat ── */
  async function sendChatMessage(e?: FormEvent) {
    e?.preventDefault();
    const msg = chatInput.trim();
    if (!msg || chatLoading) return;
    setChatInput("");
    setChatMessages((prev) => [...prev, { role: "user", content: msg }]);
    setChatLoading(true);
    try {
      const res = await fetch(`${CHAT_API}/${chatSessionId}/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ message: msg, claim_id: claimId, language: lang }),
      });
      if (!res.ok) throw new Error("Chat failed");
      const reader = res.body?.getReader();
      const decoder = new TextDecoder();
      let assistantMsg = "";
      setChatMessages((prev) => [...prev, { role: "assistant", content: "" }]);
      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          const chunk = decoder.decode(value, { stream: true });
          for (const line of chunk.split("\n")) {
            if (line.startsWith("data: ")) {
              try {
                const parsed = JSON.parse(line.slice(6));
                const token_text = parsed.token || parsed.content || parsed.text || "";
                assistantMsg += token_text;
                setChatMessages((prev) => {
                  const updated = [...prev];
                  updated[updated.length - 1] = { role: "assistant", content: assistantMsg };
                  return updated;
                });
              } catch { /* skip non-JSON SSE lines */ }
            }
          }
        }
      }
      if (!assistantMsg) {
        // Fallback: try reading as plain JSON
        const data = await res.json().catch(() => null);
        if (data?.reply || data?.response) {
          setChatMessages((prev) => {
            const updated = [...prev];
            updated[updated.length - 1] = { role: "assistant", content: data.reply || data.response };
            return updated;
          });
        }
      }
    } catch {
      setChatMessages((prev) => [...prev, { role: "assistant", content: "Sorry, failed to get a response. Please try again." }]);
    } finally {
      setChatLoading(false);
      chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }

  function sendStarterPrompt(prompt: string) {
    setChatInput(prompt);
    setTimeout(() => {
      const fakeEvent = { preventDefault: () => {} } as FormEvent;
      setChatInput("");
      setChatMessages((prev) => [...prev, { role: "user", content: prompt }]);
      setChatLoading(true);
      fetch(`${CHAT_API}/${chatSessionId}/message`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ message: prompt, claim_id: claimId, language: lang }),
      })
        .then((res) => res.json())
        .then((data) => {
          setChatMessages((prev) => [...prev, { role: "assistant", content: data.reply || data.response || "No response" }]);
        })
        .catch(() => {
          setChatMessages((prev) => [...prev, { role: "assistant", content: "Failed to get response." }]);
        })
        .finally(() => {
          setChatLoading(false);
          chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
        });
    }, 0);
  }

  /* ── Document viewer ── */
  async function openDocument(doc: Document) {
    setViewingDoc(doc);
    setDocLoading(true);
    setAnnotations([]);
    setAnnotationMode(false);
    if (docBlobRef.current) URL.revokeObjectURL(docBlobRef.current);
    try {
      const res = await fetch(`${API_BASE}/claims/${claimId}/file`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) throw new Error("Failed to fetch");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      docBlobRef.current = url;
      setDocBlobUrl(url);
    } catch {
      setDocBlobUrl(null);
      setActionStatus("Failed to load document");
    } finally {
      setDocLoading(false);
    }
  }

  function closeDocViewer() {
    setViewingDoc(null);
    if (docBlobRef.current) { URL.revokeObjectURL(docBlobRef.current); docBlobRef.current = null; }
    setDocBlobUrl(null);
  }

  function isImageFile(name: string) { return /\.(jpg|jpeg|png|gif|webp|bmp|svg)$/i.test(name); }
  function isPdfFile(name: string) { return /\.pdf$/i.test(name); }

  /* ── Annotation drawing helpers ── */
  function getCanvasCoords(e: ReactMouseEvent<HTMLCanvasElement>): { x: number; y: number } {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    return {
      x: ((e.clientX - rect.left) / rect.width) * 100,
      y: ((e.clientY - rect.top) / rect.height) * 100,
    };
  }

  function handleCanvasMouseDown(e: ReactMouseEvent<HTMLCanvasElement>) {
    if (!annotationMode) return;
    const coords = getCanvasCoords(e);
    setIsDrawing(true);
    setDrawStart(coords);
    setDrawCurrent(coords);
  }

  function handleCanvasMouseMove(e: ReactMouseEvent<HTMLCanvasElement>) {
    if (!isDrawing || !annotationMode) return;
    setDrawCurrent(getCanvasCoords(e));
  }

  function handleCanvasMouseUp() {
    if (!isDrawing || !drawStart || !drawCurrent) { setIsDrawing(false); return; }
    const w = Math.abs(drawCurrent.x - drawStart.x);
    const h = Math.abs(drawCurrent.y - drawStart.y);
    if (w > 1 && h > 1) {
      const newAnnotation: Annotation = {
        x: Math.min(drawStart.x, drawCurrent.x),
        y: Math.min(drawStart.y, drawCurrent.y),
        w, h,
        color: annotationColor,
        note: "",
      };
      setAnnotations((prev) => [...prev, newAnnotation]);
      setEditingAnnotation(annotations.length);
      setAnnotationNote("");
    }
    setIsDrawing(false);
    setDrawStart(null);
    setDrawCurrent(null);
  }

  function saveAnnotationNote() {
    if (editingAnnotation === null) return;
    setAnnotations((prev) => prev.map((a, i) =>
      i === editingAnnotation ? { ...a, note: annotationNote } : a
    ));
    setEditingAnnotation(null);
    setAnnotationNote("");
  }

  function removeAnnotation(idx: number) {
    setAnnotations((prev) => prev.filter((_, i) => i !== idx));
    if (editingAnnotation === idx) { setEditingAnnotation(null); setAnnotationNote(""); }
  }

  function undoAnnotation() {
    setAnnotations((prev) => prev.slice(0, -1));
    setEditingAnnotation(null);
  }

  const HIGHLIGHT_COLORS = ["#FFEB3B", "#FF5722", "#4CAF50", "#2196F3", "#E91E63", "#FF9800"];

  function statusClass(status: string) {
    if (status === "COMPLETED" || status === "VALIDATED" || status === "APPROVED") return "tpa-badge-success";
    if (status === "SUBMITTED" || status === "PREDICTED") return "tpa-badge-info";
    if (status.includes("FAIL") || status === "REJECTED") return "tpa-badge-error";
    if (status === "MANUAL_REVIEW_REQUIRED" || status === "MODIFICATION_REQUESTED" || status === "DOCUMENTS_REQUESTED") return "tpa-badge-warn";
    return "tpa-badge-neutral";
  }

  if (loading) return <div className="tpa-table-empty">Loading claim...</div>;
  if (!preview) return <div className="tpa-table-empty">Claim not found</div>;

  const prediction = preview.predictions?.[0];
  const rejectionScore = prediction?.rejection_score ?? null;
  const validationsFailed = preview.validations?.filter((v) => !v.passed).length ?? 0;
  const validationsPassed = preview.validations?.filter((v) => v.passed).length ?? 0;

  return (
    <div className="tpa-detail">
      {/* Breadcrumb */}
      <div className="tpa-breadcrumb">
        <Link href="/tpa">Dashboard</Link>
        <span>/</span>
        <span>
          {preview.summary?.patient_name && preview.summary.patient_name !== "N/A"
            ? preview.summary.patient_name
            : claimId.substring(0, 8) + "..."}
        </span>
      </div>

      {/* Patient + Policy info bar */}
      <div className="tpa-patient-bar">
        <div className="tpa-patient-info">
          <span className="tpa-patient-name">
            {preview.summary?.patient_name && preview.summary.patient_name !== "N/A"
              ? preview.summary.patient_name
              : preview.parsed_fields?.patient_name || preview.parsed_fields?.member_name || "Unknown Patient"}
          </span>
          <span className="tpa-patient-meta">
            {preview.summary?.age && preview.summary.age !== "N/A" && `${preview.summary.age} yrs`}
            {preview.summary?.gender && preview.summary.gender !== "N/A" && ` · ${preview.summary.gender}`}
            {preview.summary?.doctor && preview.summary.doctor !== "N/A" && ` · Dr. ${preview.summary.doctor}`}
          </span>
        </div>
        <div className="tpa-patient-info">
          <span className="tpa-field-label">Policy #</span>
          <span className="tpa-mono" style={{ fontSize: "0.88rem", fontWeight: 600 }}>
            {preview.summary?.policy_number && preview.summary.policy_number !== "N/A"
              ? preview.summary.policy_number
              : preview.parsed_fields?.policy_number || preview.parsed_fields?.policy_id || "—"}
          </span>
        </div>
        <div className="tpa-patient-info">
          <span className="tpa-field-label">Hospital</span>
          <span>{preview.summary?.hospital && preview.summary.hospital !== "N/A" ? preview.summary.hospital : "—"}</span>
        </div>
        <div className="tpa-patient-info">
          <span className="tpa-field-label">Diagnosis</span>
          <span>{preview.summary?.diagnosis && preview.summary.diagnosis !== "N/A" ? preview.summary.diagnosis : "—"}</span>
        </div>
        {(preview.summary?.admission_date || preview.summary?.discharge_date) && (
          <div className="tpa-patient-info">
            <span className="tpa-field-label">Stay</span>
            <span>
              {preview.summary?.admission_date && preview.summary.admission_date !== "N/A"
                ? preview.summary.admission_date : "?"}
              {" → "}
              {preview.summary?.discharge_date && preview.summary.discharge_date !== "N/A"
                ? preview.summary.discharge_date : "?"}
            </span>
          </div>
        )}
      </div>

      {/* Status bar */}
      <div className="tpa-detail-header">
        <div>
          <h2 className="tpa-detail-title">Claim {claimId.substring(0, 12)}...</h2>
          <span className={`tpa-badge ${statusClass(preview.status)}`}>
            {preview.status.replace(/_/g, " ")}
          </span>
        </div>
        <div className="tpa-detail-actions">
          <button className="tpa-btn tpa-btn-approve" onClick={() => openActionModal("approve")}>
            ✓ Approve
          </button>
          <button className="tpa-btn tpa-btn-reject" onClick={() => openActionModal("reject")}>
            ✕ Reject
          </button>
          <button className="tpa-btn tpa-btn-warn" onClick={() => openActionModal("send_back")}>
            ↩ Send Back
          </button>
          <button className="tpa-btn tpa-btn-info" onClick={() => openActionModal("request_docs")}>
            📎 Request Docs
          </button>
          <button className="tpa-btn tpa-btn-secondary" onClick={() => handleDownloadPdf("tpa")}>
            TPA PDF
          </button>
          <button className="tpa-btn tpa-btn-secondary" onClick={() => handleDownloadPdf("irda")}>
            IRDA PDF
          </button>
        </div>
      </div>

      {actionStatus && (
        <div className="tpa-alert">
          {actionStatus}
          <button className="tpa-alert-close" onClick={() => setActionStatus("")} aria-label="Dismiss">×</button>
        </div>
      )}

      {/* Quick stats */}
      <div className="tpa-summary-row">
        <div className="tpa-summary-card">
          <div className="tpa-summary-label">Billed Total</div>
          <div className="tpa-summary-value">
            {preview.billed_total != null ? `$${preview.billed_total.toLocaleString()}` : "—"}
          </div>
        </div>
        <div className="tpa-summary-card">
          <div className="tpa-summary-label">Rejection Risk</div>
          <div className={`tpa-summary-value ${rejectionScore != null && rejectionScore > 0.5 ? "tpa-text-error" : "tpa-text-success"}`}>
            {rejectionScore != null ? `${(rejectionScore * 100).toFixed(1)}%` : "—"}
          </div>
        </div>
        <div className="tpa-summary-card">
          <div className="tpa-summary-label">Validations</div>
          <div className="tpa-summary-value">
            <span className="tpa-text-success">{validationsPassed} passed</span>
            {validationsFailed > 0 && (
              <span className="tpa-text-error"> / {validationsFailed} failed</span>
            )}
          </div>
        </div>
        <div className="tpa-summary-card">
          <div className="tpa-summary-label">Documents</div>
          <div className="tpa-summary-value">{preview.documents?.length || 0}</div>
        </div>
      </div>

      {/* Tabs */}
      <div className="tpa-tabs">
        {(["overview", "codes", "validations", "documents", "chat", "audit"] as Tab[]).map((t) => (
          <button
            key={t}
            className={`tpa-tab ${tab === t ? "tpa-tab-active" : ""}`}
            onClick={() => setTab(t)}
          >
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="tpa-tab-content">
        {tab === "overview" && (
          <div className="tpa-grid-2">
            {/* Patient & Clinical Info — full width */}
            <div className="tpa-card" style={{ gridColumn: "1 / -1" }}>
              <h3 className="tpa-card-title">🩺 Patient & Clinical Information</h3>
              <div className="tpa-clinical-grid">
                <div className="tpa-clinical-section">
                  <h4 className="tpa-clinical-heading">Patient Details</h4>
                  <div className="tpa-field-list">
                    {[
                      ["Patient Name", preview.summary?.patient_name],
                      ["Age / Gender", [preview.summary?.age, preview.summary?.gender].filter(v => v && v !== "N/A").join(" / ") || undefined],
                      ["Policy Number", preview.summary?.policy_number],
                      ["Hospital", preview.summary?.hospital],
                      ["Doctor", preview.summary?.doctor && preview.summary.doctor !== "N/A" ? `Dr. ${preview.summary.doctor}` : undefined],
                      ["Admission", preview.summary?.admission_date],
                      ["Discharge", preview.summary?.discharge_date],
                    ].filter(([, v]) => v && v !== "N/A").map(([label, val]) => (
                      <div key={label as string} className="tpa-field-row">
                        <span className="tpa-field-label">{label}</span>
                        <span className="tpa-field-value">{val}</span>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="tpa-clinical-section">
                  <h4 className="tpa-clinical-heading">Diagnosis & Disease History</h4>
                  <div className="tpa-field-list">
                    {[
                      ["Primary Diagnosis", preview.summary?.diagnosis],
                      ["History of Present Illness", preview.summary?.history_of_present_illness || preview.parsed_fields?.history_of_present_illness || preview.parsed_fields?.present_illness || preview.parsed_fields?.hopi],
                      ["Past Medical History", preview.summary?.past_history || preview.parsed_fields?.past_history || preview.parsed_fields?.medical_history],
                      ["Known Diseases / Comorbidities", preview.summary?.disease_history || preview.parsed_fields?.disease_history || preview.parsed_fields?.known_comorbidities || preview.parsed_fields?.co_morbidities],
                      ["Allergies", preview.summary?.allergies || preview.parsed_fields?.allergies || preview.parsed_fields?.known_allergies],
                      ["Treatment Given", preview.summary?.treatment || preview.parsed_fields?.treatment || preview.parsed_fields?.treatment_given || preview.parsed_fields?.procedure_performed],
                      ["Duration of Illness", preview.parsed_fields?.duration_of_illness || preview.parsed_fields?.past_history_months],
                    ].filter(([, v]) => v && v !== "N/A" && v !== "").map(([label, val]) => (
                      <div key={label as string} className="tpa-field-row">
                        <span className="tpa-field-label">{label}</span>
                        <span className="tpa-field-value tpa-field-value-wrap">{val}</span>
                      </div>
                    ))}
                    {/* fallback: if no clinical history fields exist at all */}
                    {![
                      preview.summary?.diagnosis,
                      preview.summary?.history_of_present_illness,
                      preview.summary?.past_history,
                      preview.summary?.disease_history,
                      preview.parsed_fields?.history_of_present_illness,
                      preview.parsed_fields?.past_history,
                      preview.parsed_fields?.medical_history,
                    ].some(v => v && v !== "N/A" && v !== "") && (
                      <p className="tpa-muted">No clinical history data extracted yet</p>
                    )}
                  </div>
                </div>
              </div>
            </div>

            {/* Attached Documents preview — full width */}
            <div className="tpa-card" style={{ gridColumn: "1 / -1" }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "0.75rem" }}>
                <h3 className="tpa-card-title" style={{ margin: 0 }}>📎 Attached Documents ({preview.documents?.length || 0})</h3>
                <button className="tpa-btn tpa-btn-sm" onClick={() => setTab("documents")}>View All →</button>
              </div>
              {preview.documents?.length > 0 ? (
                <div className="tpa-doc-grid">
                  {preview.documents.map((d) => (
                    <button
                      key={d.id}
                      className="tpa-doc-card"
                      onClick={() => { setTab("documents"); setTimeout(() => openDocument(d), 100); }}
                    >
                      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        {isImageFile(d.file_name) ? (
                          <><rect x="3" y="3" width="18" height="18" rx="2" ry="2" /><circle cx="8.5" cy="8.5" r="1.5" /><polyline points="21 15 16 10 5 21" /></>
                        ) : isPdfFile(d.file_name) ? (
                          <><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" /></>
                        ) : (
                          <><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" /><polyline points="14 2 14 8 20 8" /></>
                        )}
                      </svg>
                      <span className="tpa-doc-name">{d.file_name}</span>
                      <span className="tpa-muted">{d.file_type || "file"}</span>
                    </button>
                  ))}
                </div>
              ) : (
                <p className="tpa-muted">No documents attached to this claim</p>
              )}
            </div>

            {/* Risk Assessment */}
            <div className="tpa-card">
              <h3 className="tpa-card-title">Risk Assessment</h3>
              {prediction ? (
                <>
                  <div className="tpa-risk-meter">
                    <div
                      className="tpa-risk-bar"
                      style={{
                        width: `${(prediction.rejection_score * 100).toFixed(0)}%`,
                        background:
                          prediction.rejection_score > 0.7
                            ? "var(--red)"
                            : prediction.rejection_score > 0.4
                              ? "var(--yellow)"
                              : "var(--green)",
                      }}
                    />
                  </div>
                  <p style={{ margin: "0.5rem 0", fontSize: "0.85rem" }}>
                    Score: <strong>{(prediction.rejection_score * 100).toFixed(1)}%</strong>
                    {prediction.model_name && <span className="tpa-muted"> ({prediction.model_name})</span>}
                  </p>
                  {prediction.top_reasons?.length > 0 && (
                    <div>
                      <p className="tpa-field-label" style={{ marginBottom: "0.25rem" }}>Top Risk Factors</p>
                      <ul className="tpa-reason-list">
                        {prediction.top_reasons.map((r, i) => (
                          <li key={i}>
                            {typeof r === "string" ? r : r.reason}
                            {typeof r !== "string" && r.weight != null && (
                              <span className="tpa-muted"> ({(r.weight * 100).toFixed(0)}%)</span>
                            )}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </>
              ) : (
                <p className="tpa-muted">No prediction data</p>
              )}

              {preview.brain_insights && (
                <div style={{ marginTop: "1rem" }}>
                  <h3 className="tpa-card-title">AI Insights</h3>
                  <p style={{ fontSize: "0.85rem", lineHeight: 1.5 }}>{preview.brain_insights}</p>
                </div>
              )}
            </div>

            {/* Parsed Fields (collapsed — secondary) */}
            <div className="tpa-card">
              <h3 className="tpa-card-title">All Parsed Fields</h3>
              {preview.parsed_fields && Object.keys(preview.parsed_fields).length > 0 ? (
                <div className="tpa-field-list" style={{ maxHeight: "320px", overflowY: "auto" }}>
                  {Object.entries(preview.parsed_fields).map(([key, val]) => (
                    <div key={key} className="tpa-field-row">
                      <span className="tpa-field-label">{key.replace(/_/g, " ")}</span>
                      <span className="tpa-field-value">{val || "—"}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="tpa-muted">No parsed fields available</p>
              )}
            </div>

            {/* Expenses */}
            {preview.expenses?.length > 0 && (
              <div className="tpa-card" style={{ gridColumn: "1 / -1" }}>
                <h3 className="tpa-card-title">Expenses</h3>
                <table className="tpa-table">
                  <thead>
                    <tr><th>Description</th><th style={{ textAlign: "right" }}>Amount</th></tr>
                  </thead>
                  <tbody>
                    {preview.expenses.map((e, i) => (
                      <tr key={i}>
                        <td>{e.description}</td>
                        <td style={{ textAlign: "right" }}>${e.amount?.toLocaleString()}</td>
                      </tr>
                    ))}
                    <tr className="tpa-table-total">
                      <td><strong>Total</strong></td>
                      <td style={{ textAlign: "right" }}>
                        <strong>${preview.billed_total?.toLocaleString()}</strong>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {tab === "codes" && (
          <div className="tpa-grid-2">
            <div className="tpa-card">
              <h3 className="tpa-card-title">ICD-10 Codes (Diagnosis)</h3>
              {preview.icd_codes?.length > 0 ? (
                <table className="tpa-table">
                  <thead>
                    <tr><th>Code</th><th>Description</th><th>Est. Cost</th></tr>
                  </thead>
                  <tbody>
                    {preview.icd_codes.map((c, i) => (
                      <tr key={i}>
                        <td className="tpa-mono">
                          {c.code}
                          {c.is_primary && <span className="tpa-badge tpa-badge-info" style={{ marginLeft: 6 }}>Primary</span>}
                        </td>
                        <td>{c.description}</td>
                        <td>{c.estimated_cost != null ? `$${c.estimated_cost.toLocaleString()}` : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="tpa-muted">No ICD codes found</p>
              )}
            </div>
            <div className="tpa-card">
              <h3 className="tpa-card-title">CPT Codes (Procedures)</h3>
              {preview.cpt_codes?.length > 0 ? (
                <table className="tpa-table">
                  <thead>
                    <tr><th>Code</th><th>Description</th><th>Est. Cost</th></tr>
                  </thead>
                  <tbody>
                    {preview.cpt_codes.map((c, i) => (
                      <tr key={i}>
                        <td className="tpa-mono">{c.code}</td>
                        <td>{c.description}</td>
                        <td>{c.estimated_cost != null ? `$${c.estimated_cost.toLocaleString()}` : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="tpa-muted">No CPT codes found</p>
              )}
            </div>
          </div>
        )}

        {tab === "validations" && (
          <div className="tpa-card">
            <h3 className="tpa-card-title">Validation Results</h3>
            {preview.validations?.length > 0 ? (
              <table className="tpa-table">
                <thead>
                  <tr><th>Rule</th><th>Severity</th><th>Status</th><th>Message</th></tr>
                </thead>
                <tbody>
                  {preview.validations.map((v, i) => (
                    <tr key={i}>
                      <td>{v.rule_name}</td>
                      <td>
                        <span className={`tpa-badge ${v.severity === "ERROR" ? "tpa-badge-error" : v.severity === "WARN" ? "tpa-badge-warn" : "tpa-badge-neutral"}`}>
                          {v.severity}
                        </span>
                      </td>
                      <td>
                        <span className={`tpa-badge ${v.passed ? "tpa-badge-success" : "tpa-badge-error"}`}>
                          {v.passed ? "PASSED" : "FAILED"}
                        </span>
                      </td>
                      <td>{v.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="tpa-muted">No validations run yet</p>
            )}
          </div>
        )}

        {tab === "documents" && (
          <div className="tpa-card">
            <h3 className="tpa-card-title">Uploaded Documents</h3>
            {preview.documents?.length > 0 ? (
              <>
                <div className="tpa-doc-grid">
                  {preview.documents.map((d) => (
                    <button
                      key={d.id}
                      className={`tpa-doc-card ${viewingDoc?.id === d.id ? "tpa-doc-active" : ""}`}
                      onClick={() => openDocument(d)}
                    >
                      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        {isImageFile(d.file_name) ? (
                          <><rect x="3" y="3" width="18" height="18" rx="2" ry="2" /><circle cx="8.5" cy="8.5" r="1.5" /><polyline points="21 15 16 10 5 21" /></>
                        ) : isPdfFile(d.file_name) ? (
                          <><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" /></>
                        ) : (
                          <><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" /><polyline points="14 2 14 8 20 8" /></>
                        )}
                      </svg>
                      <span className="tpa-doc-name">{d.file_name}</span>
                      <span className="tpa-muted">{d.file_type || "file"}</span>
                    </button>
                  ))}
                </div>

                {/* Inline document viewer with annotation overlay */}
                {viewingDoc && (
                  <div className="tpa-doc-viewer">
                    <div className="tpa-doc-viewer-header">
                      <h4>{viewingDoc.file_name}</h4>
                      <div className="tpa-doc-viewer-actions">
                        <button
                          className={`tpa-btn tpa-btn-sm ${annotationMode ? "tpa-btn-highlight-active" : "tpa-btn-highlight"}`}
                          onClick={() => setAnnotationMode(!annotationMode)}
                          title="Toggle highlight mode"
                        >
                          🖍 {annotationMode ? "Done Highlighting" : "Highlight"}
                        </button>
                        {annotations.length > 0 && (
                          <button className="tpa-btn tpa-btn-sm" onClick={undoAnnotation} title="Undo last highlight">
                            ↩ Undo
                          </button>
                        )}
                        <a href={`${API_BASE}/claims/${claimId}/file`} target="_blank" rel="noopener noreferrer" className="tpa-btn tpa-btn-sm">Open in New Tab</a>
                        {docBlobUrl && <a href={docBlobUrl} download={viewingDoc.file_name} className="tpa-btn tpa-btn-sm">Download</a>}
                        <button className="tpa-btn tpa-btn-sm" onClick={closeDocViewer}>Close</button>
                      </div>
                    </div>

                    {/* Annotation color picker toolbar */}
                    {annotationMode && (
                      <div className="tpa-annotation-toolbar">
                        <span className="tpa-annotation-toolbar-label">Highlight Color:</span>
                        <div className="tpa-annotation-colors">
                          {HIGHLIGHT_COLORS.map((c) => (
                            <button
                              key={c}
                              className={`tpa-annotation-color-btn ${annotationColor === c ? "tpa-annotation-color-active" : ""}`}
                              style={{ background: c }}
                              onClick={() => setAnnotationColor(c)}
                              title={c}
                            />
                          ))}
                        </div>
                        <span className="tpa-annotation-toolbar-hint">
                          Click & drag on document to highlight areas
                        </span>
                        {annotations.length > 0 && (
                          <button className="tpa-btn tpa-btn-sm tpa-btn-reject" onClick={() => setAnnotations([])}>
                            Clear All ({annotations.length})
                          </button>
                        )}
                      </div>
                    )}

                    <div className="tpa-doc-viewer-body" ref={docContainerRef} style={{ position: "relative" }}>
                      {docLoading ? (
                        <div className="tpa-table-empty">Loading document...</div>
                      ) : docBlobUrl ? (
                        <>
                          {isImageFile(viewingDoc.file_name) ? (
                            <img src={docBlobUrl} alt={viewingDoc.file_name} className="tpa-doc-image" />
                          ) : isPdfFile(viewingDoc.file_name) ? (
                            <iframe src={docBlobUrl} className="tpa-doc-iframe" title={viewingDoc.file_name} />
                          ) : (
                            <div className="tpa-table-empty">
                              <p>Preview not available for this file type.</p>
                              <a href={docBlobUrl} download={viewingDoc.file_name} className="tpa-btn tpa-btn-primary" style={{ marginTop: "0.5rem" }}>Download File</a>
                            </div>
                          )}

                          {/* Canvas overlay for annotations */}
                          <canvas
                            ref={canvasRef}
                            className={`tpa-annotation-canvas ${annotationMode ? "tpa-annotation-canvas-active" : ""}`}
                            onMouseDown={handleCanvasMouseDown}
                            onMouseMove={handleCanvasMouseMove}
                            onMouseUp={handleCanvasMouseUp}
                            onMouseLeave={handleCanvasMouseUp}
                          />

                          {/* Render saved annotations as overlays */}
                          {annotations.map((ann, idx) => (
                            <div
                              key={idx}
                              className="tpa-annotation-rect"
                              style={{
                                left: `${ann.x}%`,
                                top: `${ann.y}%`,
                                width: `${ann.w}%`,
                                height: `${ann.h}%`,
                                borderColor: ann.color,
                                background: `${ann.color}33`,
                              }}
                              onClick={(e) => { e.stopPropagation(); if (annotationMode) { setEditingAnnotation(idx); setAnnotationNote(ann.note); } }}
                            >
                              <span className="tpa-annotation-badge" style={{ background: ann.color }}>
                                {idx + 1}
                              </span>
                              {annotationMode && (
                                <button
                                  className="tpa-annotation-remove"
                                  onClick={(e) => { e.stopPropagation(); removeAnnotation(idx); }}
                                  title="Remove highlight"
                                >×</button>
                              )}
                            </div>
                          ))}

                          {/* Active drawing preview */}
                          {isDrawing && drawStart && drawCurrent && (
                            <div
                              className="tpa-annotation-rect tpa-annotation-drawing"
                              style={{
                                left: `${Math.min(drawStart.x, drawCurrent.x)}%`,
                                top: `${Math.min(drawStart.y, drawCurrent.y)}%`,
                                width: `${Math.abs(drawCurrent.x - drawStart.x)}%`,
                                height: `${Math.abs(drawCurrent.y - drawStart.y)}%`,
                                borderColor: annotationColor,
                                background: `${annotationColor}33`,
                              }}
                            />
                          )}
                        </>
                      ) : (
                        <div className="tpa-table-empty">Failed to load document</div>
                      )}
                    </div>

                    {/* Annotation note editor popover */}
                    {editingAnnotation !== null && (
                      <div className="tpa-annotation-note-editor">
                        <div className="tpa-annotation-note-header">
                          <span>Note for Highlight #{editingAnnotation + 1}</span>
                          <button onClick={() => { setEditingAnnotation(null); setAnnotationNote(""); }}>×</button>
                        </div>
                        <textarea
                          className="tpa-action-textarea"
                          rows={2}
                          placeholder="Add a note about this highlight..."
                          value={annotationNote}
                          onChange={(e) => setAnnotationNote(e.target.value)}
                          autoFocus
                        />
                        <div style={{ display: "flex", gap: "0.5rem", justifyContent: "flex-end" }}>
                          <button className="tpa-btn tpa-btn-sm tpa-btn-primary" onClick={saveAnnotationNote}>Save Note</button>
                        </div>
                      </div>
                    )}

                    {/* Annotations list panel */}
                    {annotations.length > 0 && (
                      <div className="tpa-annotation-list">
                        <h4 className="tpa-annotation-list-title">
                          Highlights ({annotations.length})
                          {showActionModal !== "send_back" && (
                            <button
                              className="tpa-btn tpa-btn-sm tpa-btn-warn"
                              style={{ marginLeft: "auto" }}
                              onClick={() => openActionModal("send_back")}
                            >
                              ↩ Send Back with Highlights
                            </button>
                          )}
                        </h4>
                        {annotations.map((ann, idx) => (
                          <div key={idx} className="tpa-annotation-list-item">
                            <span className="tpa-annotation-badge" style={{ background: ann.color }}>
                              {idx + 1}
                            </span>
                            <span className="tpa-annotation-list-note">
                              {ann.note || <em className="tpa-muted">No note</em>}
                            </span>
                            <button className="tpa-annotation-remove-sm" onClick={() => removeAnnotation(idx)}>×</button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </>
            ) : (
              <p className="tpa-muted">No documents uploaded</p>
            )}

            {/* Scan Analyses */}
            {preview.scan_analyses?.length > 0 && (
              <>
                <h3 className="tpa-card-title" style={{ marginTop: "1.5rem" }}>Scan Analyses</h3>
                {preview.scan_analyses.map((s, i) => (
                  <div key={i} className="tpa-scan-card">
                    <div className="tpa-field-row">
                      <span className="tpa-field-label">Type</span>
                      <span>{s.scan_type} — {s.body_part}</span>
                    </div>
                    <div className="tpa-field-row">
                      <span className="tpa-field-label">Findings</span>
                      <span>{s.findings}</span>
                    </div>
                    <div className="tpa-field-row">
                      <span className="tpa-field-label">Impression</span>
                      <span>{s.impression}</span>
                    </div>
                  </div>
                ))}
              </>
            )}
          </div>
        )}

        {tab === "chat" && (
          <div className="tpa-card tpa-chat-container">
            <h3 className="tpa-card-title" style={{ padding: "0.75rem 1rem", margin: 0, borderBottom: "1px solid var(--glass-border-light)" }}>AI Claims Assistant</h3>
            <div className="tpa-chat-messages">
              {chatMessages.length === 0 && (
                <div className="tpa-chat-welcome">
                  <div className="tpa-chat-welcome-icon">🧠</div>
                  <h3>Claims AI Assistant</h3>
                  <p className="tpa-muted">Ask questions about this claim, request analysis, or get recommendations.</p>
                  <div className="tpa-chat-starters">
                    <button className="tpa-chat-starter" onClick={() => sendStarterPrompt("Summarize this claim and highlight any concerns")}>Summarize claim</button>
                    <button className="tpa-chat-starter" onClick={() => sendStarterPrompt("What are the top risk factors for rejection?")}>Risk factors</button>
                    <button className="tpa-chat-starter" onClick={() => sendStarterPrompt("Are the ICD and CPT codes consistent with the diagnosis?")}>Code consistency</button>
                    <button className="tpa-chat-starter" onClick={() => sendStarterPrompt("What validation issues should I address first?")}>Fix validations</button>
                  </div>
                </div>
              )}
              {chatMessages.map((m, i) => (
                <div key={i} className={`tpa-chat-msg ${m.role === "user" ? "tpa-chat-user" : "tpa-chat-bot"}`}>
                  <div className="tpa-chat-avatar">{m.role === "user" ? "You" : "AI"}</div>
                  <div className="tpa-chat-bubble">
                    {m.content || (
                      <span className="tpa-chat-typing">
                        <span /><span /><span />
                      </span>
                    )}
                  </div>
                </div>
              ))}
              <div ref={chatEndRef} />
            </div>
            <form className="tpa-chat-input-bar" onSubmit={sendChatMessage}>
              <input
                className="tpa-chat-input"
                placeholder="Ask about this claim..."
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                disabled={chatLoading}
              />
              <button type="submit" className="tpa-btn tpa-btn-primary" disabled={chatLoading || !chatInput.trim()}>
                {chatLoading ? "..." : "Send"}
              </button>
            </form>
          </div>
        )}

        {tab === "audit" && (
          <div className="tpa-card">
            <h3 className="tpa-card-title">Audit Trail</h3>
            {audit.length > 0 ? (
              <div className="tpa-audit-timeline">
                {audit.map((a) => (
                  <div key={a.id} className="tpa-audit-entry">
                    <div className="tpa-audit-dot" />
                    <div className="tpa-audit-body">
                      <div className="tpa-audit-header">
                        <strong>{a.actor}</strong>
                        <span className="tpa-muted">
                          {new Date(a.created_at).toLocaleString()}
                        </span>
                      </div>
                      <div className="tpa-audit-action">{a.action}</div>
                      {a.metadata && Object.keys(a.metadata).length > 0 && (
                        <pre className="tpa-audit-meta">
                          {JSON.stringify(a.metadata, null, 2)}
                        </pre>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="tpa-muted">No audit entries</p>
            )}
          </div>
        )}
      </div>

      {/* Submit to TPA modal */}
      {showSubmitModal && (
        <div className="tpa-modal-overlay" onClick={() => setShowSubmitModal(false)}>
          <div className="tpa-modal" onClick={(e) => e.stopPropagation()}>
            <h3 className="tpa-card-title">Submit to TPA / Insurer</h3>
            <select
              className="tpa-filter-select"
              style={{ width: "100%", marginTop: "1rem" }}
              value={selectedTpa}
              onChange={(e) => setSelectedTpa(e.target.value)}
            >
              <option value="">Select a TPA...</option>
              {tpas.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
            <div style={{ display: "flex", gap: "0.75rem", marginTop: "1.25rem", justifyContent: "flex-end" }}>
              <button className="tpa-btn tpa-btn-secondary" onClick={() => setShowSubmitModal(false)}>
                Cancel
              </button>
              <button
                className="tpa-btn tpa-btn-primary"
                disabled={!selectedTpa}
                onClick={handleSubmitToTpa}
              >
                Submit
              </button>
            </div>
          </div>
        </div>
      )}

      {/* TPA Action Modal (approve/reject/send-back/request-docs) */}
      {showActionModal && (
        <div className="tpa-modal-overlay" onClick={() => { if (!actionSubmitting) setShowActionModal(null); }}>
          <div className="tpa-action-modal" onClick={(e) => e.stopPropagation()}>
            <div className="tpa-action-modal-header">
              <span className="tpa-action-modal-icon">
                {showActionModal === "approve" && "✅"}
                {showActionModal === "reject" && "❌"}
                {showActionModal === "send_back" && "↩️"}
                {showActionModal === "request_docs" && "📎"}
              </span>
              <h3>
                {showActionModal === "approve" && "Approve Claim"}
                {showActionModal === "reject" && "Reject Claim"}
                {showActionModal === "send_back" && "Send Back for Modification"}
                {showActionModal === "request_docs" && "Request Additional Documents"}
              </h3>
            </div>

            <div className="tpa-action-modal-body">
              {/* Claim summary reminder */}
              <div className="tpa-action-claim-info">
                <span>
                  <strong>{preview.summary?.patient_name || "Unknown"}</strong>
                  {" · "}
                  {preview.summary?.policy_number && preview.summary.policy_number !== "N/A"
                    ? preview.summary.policy_number
                    : claimId.substring(0, 8)}
                </span>
                <span className="tpa-mono">
                  {preview.billed_total != null ? `$${preview.billed_total.toLocaleString()}` : ""}
                </span>
              </div>

              {/* Reason textarea (always shown for reject/send_back, optional for approve) */}
              <div className="tpa-action-field">
                <label className="tpa-field-label">
                  {showActionModal === "approve" ? "Notes (optional)" : "Reason *"}
                </label>
                <textarea
                  className="tpa-action-textarea"
                  rows={3}
                  placeholder={
                    showActionModal === "approve"
                      ? "Any notes for this approval..."
                      : showActionModal === "reject"
                        ? "Reason for rejection..."
                        : showActionModal === "send_back"
                          ? "What needs to be modified..."
                          : "Describe what documents are needed..."
                  }
                  value={actionReason}
                  onChange={(e) => setActionReason(e.target.value)}
                />
              </div>

              {/* Document type checklist for request_docs */}
              {showActionModal === "request_docs" && (
                <div className="tpa-action-field">
                  <label className="tpa-field-label">Select document types needed:</label>
                  <div className="tpa-action-doc-checklist">
                    {[
                      "Discharge Summary",
                      "Hospital Bill / Invoice",
                      "Investigation Reports",
                      "Pre-Authorization Letter",
                      "Prescription / Treatment Record",
                      "ID Proof / Policy Copy",
                      "Doctor Referral Letter",
                      "Pharmacy Bills",
                      "Follow-up Notes",
                      "Radiology / Lab Reports",
                    ].map((docType) => (
                      <label key={docType} className="tpa-action-doc-check">
                        <input
                          type="checkbox"
                          checked={requestedDocs.includes(docType)}
                          onChange={() => toggleRequestedDoc(docType)}
                        />
                        <span>{docType}</span>
                      </label>
                    ))}
                  </div>
                </div>
              )}

              {/* Confirmation for reject */}
              {showActionModal === "reject" && (
                <div className="tpa-action-warning">
                  ⚠️ Rejecting a claim is a final decision. The insurer will be notified.
                </div>
              )}

              {/* Annotations summary for send_back */}
              {showActionModal === "send_back" && annotations.length > 0 && (
                <div className="tpa-action-field">
                  <label className="tpa-field-label">Document Highlights Attached</label>
                  <div className="tpa-annotation-summary">
                    {annotations.map((ann, idx) => (
                      <div key={idx} className="tpa-annotation-summary-item">
                        <span className="tpa-annotation-badge" style={{ background: ann.color }}>{idx + 1}</span>
                        <span>{ann.note || "Highlighted area"}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="tpa-action-modal-footer">
              <button
                className="tpa-btn tpa-btn-secondary"
                onClick={() => setShowActionModal(null)}
                disabled={actionSubmitting}
              >
                Cancel
              </button>
              <button
                className={`tpa-btn ${
                  showActionModal === "approve" ? "tpa-btn-approve" :
                  showActionModal === "reject" ? "tpa-btn-reject" :
                  showActionModal === "send_back" ? "tpa-btn-warn" :
                  "tpa-btn-info"
                }`}
                disabled={
                  actionSubmitting ||
                  (showActionModal !== "approve" && !actionReason.trim()) ||
                  (showActionModal === "request_docs" && requestedDocs.length === 0 && !actionReason.trim())
                }
                onClick={handleTpaAction}
              >
                {actionSubmitting ? "Processing..." :
                  showActionModal === "approve" ? "Approve Claim" :
                  showActionModal === "reject" ? "Reject Claim" :
                  showActionModal === "send_back" ? "Send Back" :
                  "Request Documents"
                }
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

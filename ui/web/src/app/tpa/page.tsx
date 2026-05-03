"use client";

import { useEffect, useState, useCallback, useRef, useMemo, FormEvent } from "react";
import Link from "next/link";
import { useAuth, ROLES } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";
import Can from "@/components/Can";
import { useTpaSearch } from "./search-context";
import { API_BASE, SUBMISSION_API, SEARCH_API, CHAT_API, apiFetch } from "@/lib/api";

interface Doc {
  id: string;
  file_name: string;
  file_type?: string;
}

interface Claim {
  id: string;
  policy_id: string | null;
  patient_id: string | null;
  status: string;
  source: string | null;
  created_at: string;
  updated_at: string;
  documents: Doc[];
}

interface ClaimSummary {
  patient_name?: string;
  policy_number?: string;
  hospital?: string;
  diagnosis?: string;
  age?: string;
  gender?: string;
  doctor?: string;
  admission_date?: string;
  discharge_date?: string;
  history_of_present_illness?: string;
  treatment?: string;
}

interface ClaimPreviewData {
  summary?: ClaimSummary;
  billed_total?: number;
  predictions?: { rejection_score: number; top_reasons: { reason: string; weight?: number }[] }[];
  validations?: { rule_name: string; passed: boolean; message: string; severity: string }[];
  documents?: Doc[];
  icd_codes?: { code: string; description: string }[];
  cpt_codes?: { code: string; description: string }[];
}

interface EnrichedClaim extends Claim {
  summary?: ClaimSummary;
  billed_total?: number;
}

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

const STATUS_OPTIONS = [
  "ALL", "UPLOADED", "PROCESSING", "PREDICTED", "VALIDATED",
  "VALIDATION_FAILED", "SUBMITTED", "COMPLETED",
  "APPROVED", "REJECTED", "MODIFICATION_REQUESTED", "DOCUMENTS_REQUESTED",
  "MANUAL_REVIEW_REQUIRED", "WORKFLOW_FAILED",
];

const PAGE_SIZE = 20;

export default function TpaDashboard() {
  const { token, hasAnyRole } = useAuth();
  const { lang } = useI18n();
  const canAuthorize = hasAnyRole([ROLES.APPROVER, ROLES.ADMIN]);
  const { search, setSearch, setSuggestions } = useTpaSearch();
  const [claims, setClaims] = useState<EnrichedClaim[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [loading, setLoading] = useState(true);

  /* ── Expanded card state ── */
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [expandedPreview, setExpandedPreview] = useState<ClaimPreviewData | null>(null);
  const [expandedLoading, setExpandedLoading] = useState(false);
  const [expandedTab, setExpandedTab] = useState<"overview" | "documents" | "chat">("overview");

  /* ── Quick action state ── */
  const [actionClaimId, setActionClaimId] = useState<string | null>(null);
  const [actionType, setActionType] = useState<"approve" | "reject" | "send_back" | null>(null);
  const [actionReason, setActionReason] = useState("");
  const [actionSubmitting, setActionSubmitting] = useState(false);
  const [actionFeedback, setActionFeedback] = useState("");

  /* ── Settlement state (maker-checker payout flow) ── */
  const [sendMoneyClaim, setSendMoneyClaim] = useState<EnrichedClaim | null>(null);
  const [sendMoneyAmount, setSendMoneyAmount] = useState("");
  const [sendMoneySubmitting, setSendMoneySubmitting] = useState(false);
  const [sendMoneyFeedback, setSendMoneyFeedback] = useState("");
  /* Local maker-checker tracking: claim_id -> { requestedBy, requestedAt } */
  const [pendingAuth, setPendingAuth] = useState<Record<string, { by: string; at: string; amount: string }>>({});

  /* ── Summary modal state ── */
  const [summaryClaimId, setSummaryClaimId] = useState<string | null>(null);
  const [summaryData, setSummaryData] = useState<ClaimPreviewData | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);

  /* ── Inline chat state ── */
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const chatSessionRef = useRef<string>("");
  const chatEndRef = useRef<HTMLDivElement>(null);

  /* ── Doc preview state ── */
  const [docBlobUrl, setDocBlobUrl] = useState<string | null>(null);
  const [docFileName, setDocFileName] = useState("");
  const [docPreviewLoading, setDocPreviewLoading] = useState(false);
  const docBlobRef = useRef<string | null>(null);

  /* ── Docs modal state ── */
  const [docsModalClaimId, setDocsModalClaimId] = useState<string | null>(null);
  const [docsModalDocs, setDocsModalDocs] = useState<Doc[]>([]);
  const [docsModalPatient, setDocsModalPatient] = useState("");

  /* ── Message modal state ── */
  const [msgClaim, setMsgClaim] = useState<EnrichedClaim | null>(null);
  const [msgText, setMsgText] = useState("");
  const [msgSending, setMsgSending] = useState(false);
  const [msgSent, setMsgSent] = useState(false);

  /* ── Bank info card state ── */
  const [bankClaimId, setBankClaimId] = useState<string | null>(null);
  const [bankAmounts, setBankAmounts] = useState<Record<string, string>>({});
  const [bankEditing, setBankEditing] = useState<string | null>(null);
  const bankCardRef = useRef<HTMLDivElement>(null);



  async function enrichClaims(rawClaims: Claim[]): Promise<EnrichedClaim[]> {
    return Promise.all(
      rawClaims.map(async (c) => {
        try {
          const prev = await apiFetch<{ summary?: ClaimSummary; billed_total?: number }>(
            `${SUBMISSION_API}/claims/${c.id}/preview`, { token }
          );
          return { ...c, summary: prev.summary, billed_total: prev.billed_total };
        } catch { return c as EnrichedClaim; }
      }),
    );
  }

  const fetchClaims = useCallback(async () => {
    setLoading(true);
    try {
      let rawClaims: Claim[] = [];
      let rawTotal = 0;
      if (search.trim()) {
        const data = await apiFetch<{ results: { claim_id: string }[]; total: number }>(
          `${SEARCH_API}/?q=${encodeURIComponent(search)}&limit=${PAGE_SIZE}`, { token }
        );
        const details = await Promise.all(
          data.results.map((r) => apiFetch<Claim>(`${API_BASE}/claims/${r.claim_id}`, { token }).catch(() => null))
        );
        rawClaims = details.filter(Boolean) as Claim[];
        rawTotal = rawClaims.length;
      } else {
        const data = await apiFetch<{ claims: Claim[]; total: number }>(
          `${API_BASE}/claims?offset=${page * PAGE_SIZE}&limit=${PAGE_SIZE}`, { token }
        );
        rawClaims = data.claims || [];
        rawTotal = data.total || 0;
      }
      if (statusFilter !== "ALL") rawClaims = rawClaims.filter((c) => c.status === statusFilter);
      setClaims(await enrichClaims(rawClaims));
      setTotal(rawTotal);
    } catch { setClaims([]); }
    finally { setLoading(false); }
  }, [token, page, search, statusFilter]);

  useEffect(() => { fetchClaims(); }, [fetchClaims]);

  // Push search suggestions from loaded claims
  useEffect(() => {
    const set = new Set<string>();
    claims.forEach(c => {
      if (c.summary?.patient_name && c.summary.patient_name !== "N/A") set.add(c.summary.patient_name);
      if (c.summary?.policy_number && c.summary.policy_number !== "N/A") set.add(c.summary.policy_number);
      if (c.summary?.hospital && c.summary.hospital !== "N/A") set.add(c.summary.hospital);
      if (c.summary?.diagnosis && c.summary.diagnosis !== "N/A") set.add(c.summary.diagnosis);
      if (c.summary?.doctor && c.summary.doctor !== "N/A") set.add(c.summary.doctor);
      if (c.policy_id) set.add(c.policy_id);
    });
    setSuggestions(Array.from(set));
  }, [claims, setSuggestions]);

  const totalPages = Math.ceil(total / PAGE_SIZE);

  /* ── Helpers ── */
  function statusClass(s: string) {
    if (s === "SETTLED") return "tpa-badge-settled";
    if (s === "COMPLETED" || s === "VALIDATED" || s === "APPROVED") return "tpa-badge-success";
    if (s === "SUBMITTED" || s === "PREDICTED" || s === "PROCESSING") return "tpa-badge-info";
    if (s.includes("FAIL") || s === "REJECTED") return "tpa-badge-error";
    if (s === "MANUAL_REVIEW_REQUIRED" || s === "MODIFICATION_REQUESTED" || s === "DOCUMENTS_REQUESTED") return "tpa-badge-warn";
    return "tpa-badge-neutral";
  }
  function priorityLevel(c: EnrichedClaim): "high" | "medium" | "low" {
    if (["MANUAL_REVIEW_REQUIRED", "VALIDATION_FAILED", "REJECTED"].includes(c.status)) return "high";
    if (["PROCESSING", "MODIFICATION_REQUESTED", "DOCUMENTS_REQUESTED"].includes(c.status)) return "medium";
    return "low";
  }
  function patientName(c: EnrichedClaim) {
    if (c.summary?.patient_name && c.summary.patient_name !== "N/A") return c.summary.patient_name;
    return c.patient_id ? c.patient_id.substring(0, 8) + "..." : "—";
  }
  function policyNum(c: EnrichedClaim) {
    if (c.summary?.policy_number && c.summary.policy_number !== "N/A") return c.summary.policy_number;
    return c.policy_id || "—";
  }
  function isImageFile(n: string) { return /\.(jpg|jpeg|png|gif|webp|bmp|svg)$/i.test(n); }
  function isPdfFile(n: string) { return /\.pdf$/i.test(n); }

  /* ── Expand / collapse ── */
  async function toggleExpand(claimId: string) {
    if (expandedId === claimId) {
      setExpandedId(null); setExpandedPreview(null); setExpandedTab("overview");
      setChatMessages([]); setChatInput(""); closeDocPreview(); return;
    }
    setExpandedId(claimId); setExpandedTab("overview"); setExpandedLoading(true);
    setChatMessages([]); setChatInput(""); closeDocPreview();
    chatSessionRef.current = `dash-${claimId}-${Date.now()}`;
    try { setExpandedPreview(await apiFetch<ClaimPreviewData>(`${SUBMISSION_API}/claims/${claimId}/preview`, { token })); }
    catch { setExpandedPreview(null); }
    finally { setExpandedLoading(false); }
  }

  /* ── Bank info card ── */
  function toggleBankCard(claimId: string, e: React.MouseEvent) {
    e.stopPropagation();
    e.preventDefault();
    setBankClaimId(prev => prev === claimId ? null : claimId);
    setBankEditing(null);
  }
  function closeBankCard() { setBankClaimId(null); setBankEditing(null); }
  function getBankAmount(claimId: string, original: number | null | undefined) {
    if (bankAmounts[claimId] !== undefined) return bankAmounts[claimId];
    return original != null ? original.toString() : "";
  }
  function saveBankAmount(claimId: string) {
    const val = parseFloat(bankAmounts[claimId] || "0");
    if (!isNaN(val)) {
      setClaims(prev => prev.map(c => c.id === claimId ? { ...c, billed_total: val } : c));
    }
    setBankEditing(null);
  }
  useEffect(() => {
    if (!bankClaimId) return;
    function handleClickOutside(e: MouseEvent) {
      if (bankCardRef.current && !bankCardRef.current.contains(e.target as Node)) {
        setBankClaimId(null);
        setBankEditing(null);
      }
    }
    // Delay to avoid catching the same click that opened the card
    const timer = setTimeout(() => document.addEventListener("mousedown", handleClickOutside), 0);
    return () => { clearTimeout(timer); document.removeEventListener("mousedown", handleClickOutside); };
  }, [bankClaimId]);

  /* ── Summary modal ── */
  async function openSummary(claimId: string, e: React.MouseEvent) {
    e.stopPropagation();
    setSummaryClaimId(claimId); setSummaryData(null); setSummaryLoading(true);
    try { setSummaryData(await apiFetch<ClaimPreviewData>(`${SUBMISSION_API}/claims/${claimId}/preview`, { token })); }
    catch { setSummaryData(null); }
    finally { setSummaryLoading(false); }
  }
  function closeSummary() { setSummaryClaimId(null); setSummaryData(null); }
  async function handleDownloadPdf(claimId: string, type: "irda" | "tpa") {
    try {
      const url = type === "irda" ? `${SUBMISSION_API}/claims/${claimId}/irda-pdf` : `${SUBMISSION_API}/claims/${claimId}/tpa-pdf`;
      const res = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
      if (!res.ok) throw new Error("Download failed");
      const blob = await res.blob();
      const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
      a.download = `${claimId.substring(0, 8)}-${type.toUpperCase()}.pdf`; a.click(); URL.revokeObjectURL(a.href);
    } catch { /* ignore */ }
  }

  /* ── View form PDF inline ── */
  async function viewFormPdf(claimId: string, type: "irda" | "tpa") {
    const label = type === "irda" ? "IRDA Form.pdf" : "TPA Claim Form.pdf";
    setDocPreviewLoading(true); setDocFileName(label);
    if (docBlobRef.current) URL.revokeObjectURL(docBlobRef.current);
    try {
      const url = type === "irda" ? `${SUBMISSION_API}/claims/${claimId}/irda-pdf` : `${SUBMISSION_API}/claims/${claimId}/tpa-pdf`;
      const res = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
      if (!res.ok) throw new Error("Failed to load");
      const blob = await res.blob();
      const blobUrl = URL.createObjectURL(blob);
      docBlobRef.current = blobUrl; setDocBlobUrl(blobUrl);
    } catch { setDocBlobUrl(null); }
    finally { setDocPreviewLoading(false); }
  }

  /* ── Quick actions ── */
  function openQuickAction(claimId: string, action: "approve" | "reject" | "send_back", e: React.MouseEvent) {
    e.stopPropagation(); setActionClaimId(claimId); setActionType(action); setActionReason(""); setActionFeedback("");
  }
  async function submitQuickAction() {
    if (!actionClaimId || !actionType) return;
    setActionSubmitting(true); setActionFeedback("");
    try {
      const data = await apiFetch<{ message: string; new_status: string }>(
        `${SUBMISSION_API}/claims/${actionClaimId}/tpa-action`,
        { method: "POST", token, body: JSON.stringify({ action: actionType, reason: actionReason }) }
      );
      setActionFeedback(data.message);
      setClaims(prev => prev.map(c => c.id === actionClaimId ? { ...c, status: data.new_status } : c));
      setTimeout(() => { setActionClaimId(null); setActionType(null); setActionFeedback(""); }, 1500);
    } catch { setActionFeedback("Action failed. Try again."); }
    finally { setActionSubmitting(false); }
  }

  /* ── Settlement (maker-checker) ──
     Reviewer flow:  claim status APPROVED -> click "Request Settlement" -> stored locally as PENDING_AUTH
     Approver flow:  PENDING_AUTH -> click "Authorize Settlement" -> backend tpa-action(send_money) -> SETTLED
     Note: no money is moved from this UI; we hand off to the downstream finance system. */
  function openSendMoney(c: EnrichedClaim, e: React.MouseEvent) {
    e.stopPropagation();
    setSendMoneyClaim(c);
    setSendMoneyAmount(bankAmounts[c.id] !== undefined ? bankAmounts[c.id] : (c.billed_total ?? 0).toString());
    setSendMoneyFeedback("");
  }
  function requestSettlement(c: EnrichedClaim, e: React.MouseEvent) {
    e.stopPropagation();
    const amt = bankAmounts[c.id] !== undefined ? bankAmounts[c.id] : (c.billed_total ?? 0).toString();
    setPendingAuth(prev => ({
      ...prev,
      [c.id]: { by: "You", at: new Date().toISOString(), amount: amt },
    }));
  }
  async function submitSendMoney() {
    if (!sendMoneyClaim) return;
    setSendMoneySubmitting(true); setSendMoneyFeedback("");
    try {
      const data = await apiFetch<{ message: string; new_status: string }>(
        `${SUBMISSION_API}/claims/${sendMoneyClaim.id}/tpa-action`,
        { method: "POST", token, body: JSON.stringify({ action: "send_money", reason: `Settlement authorized: ₹${parseFloat(sendMoneyAmount).toLocaleString()}` }) }
      );
      setSendMoneyFeedback("Settlement authorized — forwarded to finance for processing.");
      setClaims(prev => prev.map(c => c.id === sendMoneyClaim.id ? { ...c, status: data.new_status } : c));
      setPendingAuth(prev => { const u = { ...prev }; delete u[sendMoneyClaim.id]; return u; });
      setTimeout(() => { setSendMoneyClaim(null); setSendMoneyFeedback(""); }, 1800);
    } catch { setSendMoneyFeedback("Authorization failed. Try again."); }
    finally { setSendMoneySubmitting(false); }
  }

  /* ── Message to person ── */
  function openMsgModal(c: EnrichedClaim, e: React.MouseEvent) {
    e.stopPropagation();
    setMsgClaim(c); setMsgText(""); setMsgSent(false);
  }
  async function sendMessage() {
    if (!msgClaim || !msgText.trim()) return;
    setMsgSending(true);
    try {
      await apiFetch(`${SUBMISSION_API}/claims/${msgClaim.id}/tpa-action`, {
        method: "POST", token,
        body: JSON.stringify({ action: "request_docs", reason: msgText }),
      });
      setMsgSent(true);
      setClaims(prev => prev.map(c => c.id === msgClaim.id ? { ...c, status: "DOCUMENTS_REQUESTED" } : c));
      setTimeout(() => { setMsgClaim(null); setMsgSent(false); }, 1800);
    } catch { /* ignore */ }
    finally { setMsgSending(false); }
  }

  /* ── Docs modal ── */
  function openDocsModal(c: EnrichedClaim, e: React.MouseEvent) {
    e.stopPropagation();
    setDocsModalClaimId(c.id);
    setDocsModalDocs(c.documents || []);
    setDocsModalPatient(patientName(c));
    closeDocPreview();
  }
  function closeDocsModal() {
    setDocsModalClaimId(null);
    setDocsModalDocs([]);
    setDocsModalPatient("");
    closeDocPreview();
  }

  /* ── Doc preview ── */
  async function openDocPreview(claimId: string, fileName: string) {
    setDocPreviewLoading(true); setDocFileName(fileName);
    if (docBlobRef.current) URL.revokeObjectURL(docBlobRef.current);
    try {
      const res = await fetch(`${API_BASE}/claims/${claimId}/file`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
      if (!res.ok) throw new Error("Failed");
      const blob = await res.blob(); const url = URL.createObjectURL(blob);
      docBlobRef.current = url; setDocBlobUrl(url);
    } catch { setDocBlobUrl(null); }
    finally { setDocPreviewLoading(false); }
  }
  function closeDocPreview() {
    if (docBlobRef.current) { URL.revokeObjectURL(docBlobRef.current); docBlobRef.current = null; }
    setDocBlobUrl(null); setDocFileName("");
  }

  /* ── Inline chat ── */
  async function sendInlineChat(e?: FormEvent) {
    e?.preventDefault();
    const msg = chatInput.trim();
    if (!msg || chatLoading || !expandedId) return;
    setChatInput("");
    setChatMessages(prev => [...prev, { role: "user", content: msg }]);
    setChatLoading(true);
    try {
      const res = await fetch(`${CHAT_API}/${chatSessionRef.current}/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({ message: msg, claim_id: expandedId, language: lang }),
      });
      if (!res.ok) throw new Error("Chat failed");
      const reader = res.body?.getReader();
      const decoder = new TextDecoder();
      let assistantMsg = "";
      setChatMessages(prev => [...prev, { role: "assistant", content: "" }]);
      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          for (const line of decoder.decode(value, { stream: true }).split("\n")) {
            if (line.startsWith("data: ")) {
              try {
                const parsed = JSON.parse(line.slice(6));
                assistantMsg += parsed.token || parsed.content || parsed.text || "";
                setChatMessages(prev => { const u = [...prev]; u[u.length - 1] = { role: "assistant", content: assistantMsg }; return u; });
              } catch { /* skip */ }
            }
          }
        }
      }
      if (!assistantMsg) {
        const data = await res.json().catch(() => null);
        if (data?.reply || data?.response) setChatMessages(prev => { const u = [...prev]; u[u.length - 1] = { role: "assistant", content: data.reply || data.response }; return u; });
      }
    } catch {
      setChatMessages(prev => [...prev, { role: "assistant", content: "Failed to get response." }]);
    } finally { setChatLoading(false); chatEndRef.current?.scrollIntoView({ behavior: "smooth" }); }
  }

  /* ── Counts ── */
  const pendingCount = claims.filter(c => ["MANUAL_REVIEW_REQUIRED", "MODIFICATION_REQUESTED", "DOCUMENTS_REQUESTED"].includes(c.status)).length;
  const processingCount = claims.filter(c => c.status === "PROCESSING").length;
  const approvedCount = claims.filter(c => ["APPROVED", "COMPLETED", "SUBMITTED"].includes(c.status)).length;
  const rejectedCount = claims.filter(c => c.status === "REJECTED").length;

  /* ── Filter chip definitions (status chip strip below KPIs) ── */
  const filterChips: { key: string; label: string; count: number; tone: string }[] = [
    { key: "ALL",                     label: "All",          count: total,           tone: "neutral" },
    { key: "MANUAL_REVIEW_REQUIRED",  label: "Pending",      count: pendingCount,    tone: "warn" },
    { key: "PROCESSING",              label: "Processing",   count: processingCount, tone: "info" },
    { key: "APPROVED",                label: "Approved",     count: approvedCount,   tone: "success" },
    { key: "REJECTED",                label: "Rejected",     count: rejectedCount,   tone: "danger" },
  ];

  return (
    <div className="tpa-dashboard">

      {/* ── Page Header ── */}
      <div className="tpa-page-header">
        <div className="tpa-page-header-text">
          <h1 className="tpa-page-title">Claims Dashboard</h1>
          <p className="tpa-page-sub">
            Review, authorize and manage claims across all policies and TPAs.
          </p>
        </div>
        <div className="tpa-page-header-meta">
          <span className="tpa-page-meta-pill">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
            Live · auto-refreshing
          </span>
        </div>
      </div>

      {/* ── KPI Cards ── */}
      <div className="tpa-kpi-row">
        <div className="tpa-kpi-card">
          <div className="tpa-kpi-icon tpa-kpi-icon-total">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
          </div>
          <div className="tpa-kpi-body">
            <span className="tpa-kpi-value">{total}</span>
            <span className="tpa-kpi-label">Total Claims</span>
          </div>
        </div>
        <div className="tpa-kpi-card">
          <div className="tpa-kpi-icon tpa-kpi-icon-pending">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
          </div>
          <div className="tpa-kpi-body">
            <span className="tpa-kpi-value tpa-text-warn">{pendingCount}</span>
            <span className="tpa-kpi-label">Pending Review</span>
          </div>
        </div>
        <div className="tpa-kpi-card">
          <div className="tpa-kpi-icon tpa-kpi-icon-approved">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
          </div>
          <div className="tpa-kpi-body">
            <span className="tpa-kpi-value tpa-text-success">{approvedCount}</span>
            <span className="tpa-kpi-label">Approved / Done</span>
          </div>
        </div>
        <div className="tpa-kpi-card">
          <div className="tpa-kpi-icon tpa-kpi-icon-rejected">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
          </div>
          <div className="tpa-kpi-body">
            <span className="tpa-kpi-value tpa-text-error">{rejectedCount}</span>
            <span className="tpa-kpi-label">Rejected</span>
          </div>
        </div>
        <div className="tpa-kpi-card">
          <div className="tpa-kpi-icon tpa-kpi-icon-processing">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 11-2.12-9.36L23 10"/></svg>
          </div>
          <div className="tpa-kpi-body">
            <span className="tpa-kpi-value tpa-text-info">{processingCount}</span>
            <span className="tpa-kpi-label">Processing</span>
          </div>
        </div>
      </div>

      {/* ── Status Filter Chips ── */}
      <div className="tpa-filter-bar" role="tablist" aria-label="Filter by status">
        <div className="tpa-chip-group">
          {filterChips.map(chip => (
            <button
              key={chip.key}
              role="tab"
              aria-selected={statusFilter === chip.key}
              className={`tpa-chip tpa-chip-${chip.tone} ${statusFilter === chip.key ? "tpa-chip-active" : ""}`}
              onClick={() => { setStatusFilter(chip.key); setPage(0); }}
            >
              <span className="tpa-chip-dot" aria-hidden />
              <span className="tpa-chip-label">{chip.label}</span>
              <span className="tpa-chip-count">{chip.count}</span>
            </button>
          ))}
        </div>
        {statusFilter !== "ALL" && (
          <button className="tpa-chip-clear" onClick={() => { setStatusFilter("ALL"); setPage(0); }}>
            Clear filter
          </button>
        )}
      </div>

      {/* ── Claims Table ── */}
      <div className="tpa-table-wrap">
        {loading ? (
          <div className="tpa-table-empty"><div className="tpa-loader" /><p>Loading claims...</p></div>
        ) : claims.length === 0 ? (
          <div className="tpa-table-empty">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" opacity="0.25"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            <p style={{ marginTop: "0.5rem" }}>No claims match your criteria</p>
          </div>
        ) : (
          <table className="tpa-table tpa-table-enterprise">
            <thead>
              <tr>
                <th style={{ width: 36 }}>#</th>
                <th style={{ width: 6 }}></th>
                <th>Claim / Patient</th>
                <th>Policy</th>
                <th>Hospital</th>
                <th>Amount</th>
                <th>Status</th>
                <th>Docs</th>
                <th>Filed</th>
                <th className="tpa-th-actions">Decision</th>
                <th style={{ width: 36, textAlign: 'center' }}>Chat</th>
                <th style={{ width: 36, textAlign: 'center' }}>Bank</th>
                <th className="tpa-th-view">View</th>
              </tr>
            </thead>
            {claims.map((c, idx) => {
              const priority = priorityLevel(c);
              return (
              <tbody key={c.id}>
                <tr
                  className="tpa-row-clickable"
                >
                  {/* Row number */}
                  <td className="tpa-cell-rownum">{page * 20 + idx + 1}</td>
                  {/* Priority */}
                  <td className="tpa-td-priority"><span className={`tpa-priority-dot tpa-priority-${priority}`} title={`${priority} priority`} /></td>

                  {/* Patient */}
                  <td>
                    <div className="tpa-cell-primary">{patientName(c)}</div>
                    <div className="tpa-cell-sub">
                      <span className="tpa-mono">{c.id.substring(0, 8)}</span>
                      {c.summary?.diagnosis && c.summary.diagnosis !== "N/A" && (
                        <span className="tpa-cell-diagnosis"> · {c.summary.diagnosis.length > 35 ? c.summary.diagnosis.substring(0, 35) + "..." : c.summary.diagnosis}</span>
                      )}
                    </div>
                  </td>

                  <td><span className="tpa-mono tpa-cell-policy">{policyNum(c)}</span></td>
                  <td className="tpa-cell-hospital">{c.summary?.hospital && c.summary.hospital !== "N/A" ? c.summary.hospital : "—"}</td>
                  <td><span className="tpa-cell-amount">{c.billed_total != null ? `₹${c.billed_total.toLocaleString()}` : "—"}</span></td>
                  <td><span className={`tpa-badge ${statusClass(c.status)}`}>{c.status.replace(/_/g, " ")}</span></td>
                  <td><button className="tpa-cell-docs" onClick={(e) => openDocsModal(c, e)} title="View attached documents">{c.documents?.length || 0}</button></td>
                  <td className="tpa-cell-date">{new Date(c.created_at).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "2-digit" })}</td>

                  {/* Decision (maker-checker for settlement) */}
                  <td>
                    <div className="tpa-decision-actions" onClick={(e) => e.stopPropagation()}>
                      {c.status === "APPROVED" ? (
                        pendingAuth[c.id] ? (
                          canAuthorize ? (
                            <button className="tpa-decision-btn tpa-decision-sendmoney" title="Authorize Settlement" onClick={(e) => openSendMoney(c, e)}>
                              Authorize
                            </button>
                          ) : (
                            <span className="tpa-pending-auth-pill" title={`Requested by ${pendingAuth[c.id].by} — awaiting Approver`}>
                              ⏳ Awaiting Approver
                            </span>
                          )
                        ) : canAuthorize ? (
                          <button className="tpa-decision-btn tpa-decision-sendmoney" title="Authorize Settlement (skip request)" onClick={(e) => openSendMoney(c, e)}>
                            Authorize Settlement
                          </button>
                        ) : (
                          <button className="tpa-decision-btn tpa-decision-request" title="Request Settlement (Approver will authorize)" onClick={(e) => requestSettlement(c, e)}>
                            Request Settlement
                          </button>
                        )
                      ) : c.status === "SETTLED" ? (
                        <span className="tpa-settled-badge">✓ Settled</span>
                      ) : (
                        <>
                          <button className="tpa-decision-btn tpa-decision-approve" title="Approve" onClick={(e) => openQuickAction(c.id, "approve", e)}>
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
                          </button>
                          <button className="tpa-decision-btn tpa-decision-reject" title="Reject" onClick={(e) => openQuickAction(c.id, "reject", e)}>
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                          </button>
                          <button className="tpa-decision-btn tpa-decision-sendback" title="Send Back" onClick={(e) => openQuickAction(c.id, "send_back", e)}>
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 102.13-9.36L1 10"/></svg>
                          </button>
                        </>
                      )}
                    </div>
                  </td>

                  {/* Chat / Message */}
                  <td style={{ textAlign: 'center' }}>
                    <button className="tpa-msg-btn" title={`Message ${patientName(c)}`} onClick={(e) => openMsgModal(c, e)}>
                      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>
                    </button>
                  </td>

                  {/* Bank Info */}
                  <td style={{ textAlign: 'center', position: 'relative' }}>
                    <button className="tpa-bank-btn" title="Banking Details" onClick={(e) => toggleBankCard(c.id, e)}>
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 21h18"/><path d="M3 10h18"/><path d="M5 6l7-3 7 3"/><path d="M4 10v11"/><path d="M20 10v11"/><path d="M8 14v3"/><path d="M12 14v3"/><path d="M16 14v3"/></svg>
                    </button>
                    {bankClaimId === c.id && (
                      <div className="tpa-bank-card" ref={bankCardRef} onClick={(e) => e.stopPropagation()}>
                        <div className="tpa-bank-card-header">
                          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 21h18"/><path d="M3 10h18"/><path d="M5 6l7-3 7 3"/><path d="M4 10v11"/><path d="M20 10v11"/><path d="M8 14v3"/><path d="M12 14v3"/><path d="M16 14v3"/></svg>
                          <span>Banking Details</span>
                          <button className="tpa-bank-card-close" onClick={closeBankCard}>✕</button>
                        </div>
                        <div className="tpa-bank-card-body">
                          <div className="tpa-bank-field"><span className="tpa-bank-label">Account Holder</span><span className="tpa-bank-value">{patientName(c)}</span></div>
                          <div className="tpa-bank-field"><span className="tpa-bank-label">Bank Name</span><span className="tpa-bank-value">SBI / HDFC</span></div>
                          <div className="tpa-bank-field"><span className="tpa-bank-label">Account No.</span><span className="tpa-bank-value tpa-mono">XXXX-XXXX-{c.id.substring(0, 4).toUpperCase()}</span></div>
                          <div className="tpa-bank-field"><span className="tpa-bank-label">IFSC Code</span><span className="tpa-bank-value tpa-mono">SBIN00{c.id.substring(0, 5).toUpperCase()}</span></div>
                          <div className="tpa-bank-field"><span className="tpa-bank-label">Claim ID</span><span className="tpa-bank-value tpa-mono">{c.id.substring(0, 8)}</span></div>
                          <div className="tpa-bank-divider" />
                          <div className="tpa-bank-field tpa-bank-field-amount">
                            <span className="tpa-bank-label">Settlement Amount</span>
                            {bankEditing === c.id ? (
                              <div className="tpa-bank-edit">
                                <span className="tpa-bank-currency">₹</span>
                                <input
                                  className="tpa-bank-input"
                                  type="number"
                                  autoFocus
                                  value={getBankAmount(c.id, c.billed_total)}
                                  onChange={(e) => setBankAmounts(prev => ({ ...prev, [c.id]: e.target.value }))}
                                  onKeyDown={(e) => { if (e.key === "Enter") saveBankAmount(c.id); if (e.key === "Escape") setBankEditing(null); }}
                                />
                                <button className="tpa-bank-save" onClick={() => saveBankAmount(c.id)}>✓</button>
                              </div>
                            ) : (
                              <button className="tpa-bank-amount-btn" onClick={() => { setBankEditing(c.id); setBankAmounts(prev => ({ ...prev, [c.id]: (c.billed_total ?? 0).toString() })); }}>
                                <span>₹{(c.billed_total ?? 0).toLocaleString("en-IN")}</span>
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                              </button>
                            )}
                          </div>
                          <div className="tpa-bank-field"><span className="tpa-bank-label">Status</span><span className={`tpa-badge ${c.status === 'APPROVED' ? 'tpa-badge-success' : 'tpa-badge-pending'}`} style={{fontSize:'0.65rem',padding:'0.15rem 0.5rem'}}>{c.status === 'APPROVED' ? 'Ready for Settlement' : 'Pending'}</span></div>
                        </div>
                      </div>
                    )}
                  </td>

                  {/* View */}
                  <td>
                    <button className="tpa-view-btn" onClick={(e) => openSummary(c.id, e)}>View</button>
                  </td>
                </tr>

              </tbody>
            ); })}
          </table>
        )}
      </div>

      {/* ── Pagination ── */}
      {totalPages > 1 && (
        <div className="tpa-pagination">
          <button className="tpa-btn tpa-btn-sm" disabled={page === 0} onClick={() => setPage(page - 1)}>← Previous</button>
          <span className="tpa-page-info">Page {page + 1} of {totalPages}</span>
          <button className="tpa-btn tpa-btn-sm" disabled={page >= totalPages - 1} onClick={() => setPage(page + 1)}>Next →</button>
        </div>
      )}

      {/* ── Quick Action Modal ── */}
      {actionType && actionClaimId && (
        <div className="tpa-modal-overlay" onClick={() => { if (!actionSubmitting) { setActionClaimId(null); setActionType(null); } }}>
          <div className="tpa-action-modal tpa-quick-action-modal" onClick={(e) => e.stopPropagation()}>
            <div className="tpa-action-modal-header">
              <span className="tpa-action-modal-icon">{actionType === "approve" ? "✅" : actionType === "reject" ? "❌" : "↩️"}</span>
              <h3>{actionType === "approve" ? "Approve Claim" : actionType === "reject" ? "Reject Claim" : "Send Back for Modification"}</h3>
            </div>
            <div className="tpa-action-modal-body">
              <div className="tpa-action-claim-info">
                <span><strong>{claims.find(x => x.id === actionClaimId)?.summary?.patient_name || actionClaimId.substring(0, 8)}</strong></span>
                <span className="tpa-mono">{claims.find(x => x.id === actionClaimId)?.billed_total != null ? `₹${claims.find(x => x.id === actionClaimId)!.billed_total!.toLocaleString()}` : ""}</span>
              </div>
              <div className="tpa-action-field">
                <label className="tpa-field-label">{actionType === "approve" ? "Notes (optional)" : "Reason *"}</label>
                <textarea className="tpa-action-textarea" rows={3} placeholder={actionType === "approve" ? "Any notes for approval..." : actionType === "reject" ? "Reason for rejection..." : "What needs to be modified..."} value={actionReason} onChange={(e) => setActionReason(e.target.value)} autoFocus />
              </div>
              {actionType === "reject" && <div className="tpa-action-warning">⚠️ Rejecting a claim is a final decision. The insurer will be notified.</div>}
              {actionFeedback && <div className="tpa-action-feedback">{actionFeedback}</div>}
            </div>
            <div className="tpa-action-modal-footer">
              <button className="tpa-btn tpa-btn-secondary" onClick={() => { setActionClaimId(null); setActionType(null); }} disabled={actionSubmitting}>Cancel</button>
              <button className={`tpa-btn ${actionType === "approve" ? "tpa-btn-approve" : actionType === "reject" ? "tpa-btn-reject" : "tpa-btn-warn"}`} disabled={actionSubmitting || (actionType !== "approve" && !actionReason.trim())} onClick={submitQuickAction}>
                {actionSubmitting ? "Processing..." : actionType === "approve" ? "Approve" : actionType === "reject" ? "Reject" : "Send Back"}
              </button>
            </div>
          </div>
        </div>
      )}
      {/* ── Authorize Settlement Modal (maker-checker payout) ── */}
      {sendMoneyClaim && (
        <div className="tpa-modal-overlay" onClick={() => { if (!sendMoneySubmitting) setSendMoneyClaim(null); }}>
          <div className="tpa-action-modal tpa-sendmoney-modal" onClick={(e) => e.stopPropagation()}>
            <div className="tpa-action-modal-header tpa-sendmoney-header">
              <span className="tpa-action-modal-icon">✓</span>
              <h3>Authorize Settlement</h3>
            </div>
            <div className="tpa-action-modal-body">
              <div className="tpa-action-claim-info">
                <span><strong>{sendMoneyClaim.summary?.patient_name || sendMoneyClaim.id.substring(0, 8)}</strong></span>
                <span className="tpa-mono">Claim: {sendMoneyClaim.id.substring(0, 8)}</span>
              </div>
              <div className="tpa-sendmoney-bank-info">
                <div className="tpa-sendmoney-bank-row"><span>Beneficiary</span><span>{sendMoneyClaim.summary?.patient_name || "—"}</span></div>
                <div className="tpa-sendmoney-bank-row"><span>Bank</span><span>SBI / HDFC</span></div>
                <div className="tpa-sendmoney-bank-row"><span>Account No.</span><span className="tpa-mono">XXXX-XXXX-{sendMoneyClaim.id.substring(0, 4).toUpperCase()}</span></div>
                <div className="tpa-sendmoney-bank-row"><span>IFSC</span><span className="tpa-mono">SBIN00{sendMoneyClaim.id.substring(0, 5).toUpperCase()}</span></div>
              </div>
              {pendingAuth[sendMoneyClaim.id] && (
                <div className="tpa-makerchecker-note">
                  Requested by <strong>{pendingAuth[sendMoneyClaim.id].by}</strong> at {new Date(pendingAuth[sendMoneyClaim.id].at).toLocaleString("en-IN")}
                </div>
              )}
              <div className="tpa-sendmoney-amount-section">
                <label className="tpa-field-label">Settlement Amount</label>
                <div className="tpa-sendmoney-amount-input">
                  <span className="tpa-sendmoney-currency">₹</span>
                  <input type="number" value={sendMoneyAmount} onChange={(e) => setSendMoneyAmount(e.target.value)} className="tpa-sendmoney-input" autoFocus />
                </div>
                {sendMoneyClaim.billed_total != null && (
                  <div className="tpa-sendmoney-original">Original billed: ₹{sendMoneyClaim.billed_total.toLocaleString()}</div>
                )}
              </div>
              <div className="tpa-sendmoney-disclaimer">
                Authorization hands the claim off to the downstream finance system for fund transfer. No money moves from this UI.
              </div>
              {sendMoneyFeedback && <div className="tpa-action-feedback">{sendMoneyFeedback}</div>}
            </div>
            <div className="tpa-action-modal-footer">
              <button className="tpa-btn tpa-btn-secondary" onClick={() => setSendMoneyClaim(null)} disabled={sendMoneySubmitting}>Cancel</button>
              <button className="tpa-btn tpa-btn-sendmoney" disabled={sendMoneySubmitting || !sendMoneyAmount || parseFloat(sendMoneyAmount) <= 0} onClick={submitSendMoney}>
                {sendMoneySubmitting ? "Processing..." : `Authorize ₹${parseFloat(sendMoneyAmount || "0").toLocaleString()}`}
              </button>
            </div>
          </div>
        </div>
      )}
      {/* ── Message Modal ── */}
      {msgClaim && (
        <div className="tpa-modal-overlay" onClick={() => { if (!msgSending) setMsgClaim(null); }}>
          <div className="tpa-msg-modal" onClick={(e) => e.stopPropagation()}>
            <div className="tpa-msg-modal-header">
              <div className="tpa-msg-modal-person">
                <div className="tpa-msg-modal-avatar">{(msgClaim.summary?.patient_name || "?")[0].toUpperCase()}</div>
                <div>
                  <h3>{msgClaim.summary?.patient_name || msgClaim.patient_id?.substring(0, 8) || "Patient"}</h3>
                  <div className="tpa-msg-modal-meta">
                    {msgClaim.summary?.policy_number && msgClaim.summary.policy_number !== "N/A" && <span>Policy: {msgClaim.summary.policy_number}</span>}
                    {msgClaim.summary?.hospital && msgClaim.summary.hospital !== "N/A" && <span>{msgClaim.summary.hospital}</span>}
                    <span>Claim: {msgClaim.id.substring(0, 8)}</span>
                  </div>
                </div>
              </div>
              <button className="tpa-docs-modal-close" onClick={() => setMsgClaim(null)}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </button>
            </div>
            <div className="tpa-msg-modal-body">
              {msgSent ? (
                <div className="tpa-msg-modal-sent">
                  <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#10b981" strokeWidth="2"><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
                  <p>Message sent to {msgClaim.summary?.patient_name || "patient"}</p>
                </div>
              ) : (
                <>
                  <div className="tpa-msg-modal-quick">
                    {["Please submit missing documents", "Clarification needed on diagnosis", "Policy details incomplete", "Please provide discharge summary"].map(t => (
                      <button key={t} className="tpa-msg-quick-btn" onClick={() => setMsgText(t)}>{t}</button>
                    ))}
                  </div>
                  <textarea
                    className="tpa-msg-textarea"
                    rows={4}
                    placeholder={`Write a message to ${msgClaim.summary?.patient_name || "the claimant"}...`}
                    value={msgText}
                    onChange={(e) => setMsgText(e.target.value)}
                    autoFocus
                  />
                </>
              )}
            </div>
            {!msgSent && (
              <div className="tpa-msg-modal-footer">
                <button className="tpa-btn tpa-btn-secondary" onClick={() => setMsgClaim(null)} disabled={msgSending}>Cancel</button>
                <button className="tpa-btn tpa-btn-primary" disabled={msgSending || !msgText.trim()} onClick={sendMessage}>
                  {msgSending ? "Sending..." : "Send Message"}
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Summary Modal ── */}
      {summaryClaimId && (() => {
        const sc = claims.find(c => c.id === summaryClaimId);
        return (
          <div className="tpa-modal-overlay" onClick={closeSummary}>
            <div className="tpa-summary-modal" onClick={(e) => e.stopPropagation()}>
              <div className="tpa-summary-header">
                <div>
                  <h2 className="tpa-summary-title">Claim Summary</h2>
                  <p className="tpa-summary-sub">{summaryClaimId.substring(0, 8)} · {sc?.status?.replace(/_/g, " ") || ""}</p>
                </div>
                <button className="tpa-modal-close" onClick={closeSummary}>✕</button>
              </div>

              {summaryLoading ? (
                <div className="tpa-summary-loading"><div className="tpa-loader" /><p>Loading claim details...</p></div>
              ) : summaryData ? (
                <div className="tpa-summary-body">
                  {/* Patient & Policy */}
                  <div className="tpa-summary-grid">
                    <div className="tpa-summary-section">
                      <h4 className="tpa-summary-heading">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
                        Patient Details
                      </h4>
                      <div className="tpa-summary-fields">
                        {([
                          ["Patient", summaryData.summary?.patient_name],
                          ["Age / Gender", [summaryData.summary?.age, summaryData.summary?.gender].filter(v => v && v !== "N/A").join(" / ") || undefined],
                          ["Policy", summaryData.summary?.policy_number],
                          ["Hospital", summaryData.summary?.hospital],
                          ["Doctor", summaryData.summary?.doctor],
                        ] as [string, string | undefined][]).filter(([, v]) => v && v !== "N/A").map(([l, v]) => (
                          <div key={l} className="tpa-summary-field"><span className="tpa-summary-label">{l}</span><span className="tpa-summary-value">{v}</span></div>
                        ))}
                      </div>
                    </div>

                    <div className="tpa-summary-section">
                      <h4 className="tpa-summary-heading">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
                        Admission Info
                      </h4>
                      <div className="tpa-summary-fields">
                        {([
                          ["Admission", summaryData.summary?.admission_date],
                          ["Discharge", summaryData.summary?.discharge_date],
                          ["Amount", sc?.billed_total != null ? `₹${sc.billed_total.toLocaleString("en-IN")}` : undefined],
                          ["Documents", `${sc?.documents?.length || 0} files`],
                        ] as [string, string | undefined][]).filter(([, v]) => v && v !== "N/A").map(([l, v]) => (
                          <div key={l} className="tpa-summary-field"><span className="tpa-summary-label">{l}</span><span className="tpa-summary-value">{v}</span></div>
                        ))}
                      </div>
                    </div>
                  </div>

                  {/* Diagnosis & Treatment */}
                  <div className="tpa-summary-section tpa-summary-section-full">
                    <h4 className="tpa-summary-heading">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
                      Diagnosis & Treatment
                    </h4>
                    <div className="tpa-summary-fields">
                      {summaryData.summary?.diagnosis && summaryData.summary.diagnosis !== "N/A" && (
                        <div className="tpa-summary-field tpa-summary-field-wide"><span className="tpa-summary-label">Diagnosis</span><span className="tpa-summary-value">{summaryData.summary.diagnosis}</span></div>
                      )}
                      {summaryData.summary?.treatment && summaryData.summary.treatment !== "N/A" && (
                        <div className="tpa-summary-field tpa-summary-field-wide"><span className="tpa-summary-label">Treatment</span><span className="tpa-summary-value">{summaryData.summary.treatment}</span></div>
                      )}
                      {summaryData.summary?.history_of_present_illness && summaryData.summary.history_of_present_illness !== "N/A" && (
                        <div className="tpa-summary-field tpa-summary-field-wide"><span className="tpa-summary-label">History</span><span className="tpa-summary-value">{summaryData.summary.history_of_present_illness}</span></div>
                      )}
                    </div>
                  </div>

                  {/* Risk & Predictions */}
                  {summaryData.predictions?.[0] && (
                    <div className="tpa-summary-section tpa-summary-section-full">
                      <h4 className="tpa-summary-heading">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                        Risk Assessment
                      </h4>
                      <div className="tpa-summary-risk-bar">
                        <div className="tpa-summary-risk-fill" style={{ width: `${Math.min(summaryData.predictions[0].rejection_score * 100, 100)}%`, background: summaryData.predictions[0].rejection_score > 0.5 ? 'var(--error)' : 'var(--success)' }} />
                      </div>
                      <div className="tpa-summary-risk-label">
                        Rejection Risk: <strong className={summaryData.predictions[0].rejection_score > 0.5 ? "tpa-text-error" : "tpa-text-success"}>{(summaryData.predictions[0].rejection_score * 100).toFixed(1)}%</strong>
                      </div>
                      {summaryData.predictions[0].top_reasons?.length > 0 && (
                        <div className="tpa-summary-reasons">
                          {summaryData.predictions[0].top_reasons.slice(0, 4).map((r, i) => (
                            <div key={i} className="tpa-summary-reason">
                              <span className="tpa-summary-reason-num">{i + 1}</span>
                              <span>{r.reason}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Validations */}
                  {summaryData.validations && summaryData.validations.length > 0 && (
                    <div className="tpa-summary-section tpa-summary-section-full">
                      <h4 className="tpa-summary-heading">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"/></svg>
                        Validations
                      </h4>
                      <div className="tpa-summary-validations">
                        {summaryData.validations.slice(0, 8).map((v, i) => (
                          <div key={i} className={`tpa-summary-validation ${v.passed ? "tpa-summary-val-pass" : "tpa-summary-val-fail"}`}>
                            <span className="tpa-summary-val-icon">{v.passed ? "✓" : "✕"}</span>
                            <span className="tpa-summary-val-name">{v.rule_name}</span>
                            {v.message && <span className="tpa-summary-val-msg">{v.message}</span>}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* ICD / CPT codes */}
                  {(summaryData.icd_codes?.length || summaryData.cpt_codes?.length) ? (
                    <div className="tpa-summary-grid">
                      {summaryData.icd_codes?.length ? (
                        <div className="tpa-summary-section">
                          <h4 className="tpa-summary-heading">ICD Codes</h4>
                          <div className="tpa-summary-codes">
                            {summaryData.icd_codes.map((c, i) => (
                              <span key={i} className="tpa-summary-code"><strong>{c.code}</strong> {c.description}</span>
                            ))}
                          </div>
                        </div>
                      ) : null}
                      {summaryData.cpt_codes?.length ? (
                        <div className="tpa-summary-section">
                          <h4 className="tpa-summary-heading">CPT Codes</h4>
                          <div className="tpa-summary-codes">
                            {summaryData.cpt_codes.map((c, i) => (
                              <span key={i} className="tpa-summary-code"><strong>{c.code}</strong> {c.description}</span>
                            ))}
                          </div>
                        </div>
                      ) : null}
                    </div>
                  ) : null}

                </div>
              ) : (
                <div className="tpa-summary-loading"><p>Failed to load claim data</p></div>
              )}
            </div>
          </div>
        );
      })()}

      {/* ── Docs Modal ── */}
      {docsModalClaimId && (
        <div className="tpa-modal-overlay" onClick={closeDocsModal}>
          <div className="tpa-docs-modal" onClick={(e) => e.stopPropagation()}>
            <div className="tpa-docs-modal-header">
              <div>
                <h3>Documents</h3>
                <span className="tpa-docs-modal-sub">{docsModalPatient} · {docsModalDocs.length} file{docsModalDocs.length !== 1 ? "s" : ""}</span>
              </div>
              <button className="tpa-docs-modal-close" onClick={closeDocsModal}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </button>
            </div>
            <div className="tpa-docs-modal-body">
              {docsModalDocs.length === 0 ? (
                <div className="tpa-docs-modal-empty">
                  <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" opacity="0.25"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                  <p>No documents attached</p>
                </div>
              ) : (
                <div className="tpa-docs-modal-layout">
                  <div className="tpa-docs-modal-list">
                    {docsModalDocs.map((d) => (
                      <button key={d.id} className={`tpa-docs-modal-item ${docFileName === d.file_name ? "tpa-docs-modal-item-active" : ""}`} onClick={() => openDocPreview(docsModalClaimId!, d.file_name)}>
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          {isImageFile(d.file_name)
                            ? <><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></>
                            : <><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></>}
                        </svg>
                        <div className="tpa-docs-modal-item-info">
                          <span className="tpa-docs-modal-item-name">{d.file_name}</span>
                          <span className="tpa-docs-modal-item-type">{d.file_type || "Document"}</span>
                        </div>
                      </button>
                    ))}
                    <div className="tpa-docs-modal-divider"><span>Generated Forms</span></div>
                    <button className={`tpa-docs-modal-item ${docFileName === "IRDA Form.pdf" ? "tpa-docs-modal-item-active" : ""}`} onClick={() => viewFormPdf(docsModalClaimId!, "irda")}>
                      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18"/><path d="M9 21V9"/></svg>
                      <div className="tpa-docs-modal-item-info">
                        <span className="tpa-docs-modal-item-name">IRDA Form</span>
                        <span className="tpa-docs-modal-item-type">IRDA compliance PDF</span>
                      </div>
                    </button>
                    <button className={`tpa-docs-modal-item ${docFileName === "TPA Claim Form.pdf" ? "tpa-docs-modal-item-active" : ""}`} onClick={() => viewFormPdf(docsModalClaimId!, "tpa")}>
                      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
                      <div className="tpa-docs-modal-item-info">
                        <span className="tpa-docs-modal-item-name">TPA Claim Form</span>
                        <span className="tpa-docs-modal-item-type">Claim submission PDF</span>
                      </div>
                    </button>
                  </div>
                  <div className="tpa-docs-modal-preview">
                    {docPreviewLoading ? (
                      <div className="tpa-docs-modal-empty"><div className="tpa-loader" /><p>Loading...</p></div>
                    ) : docBlobUrl ? (
                      <div className="tpa-docs-modal-viewer">
                        <div className="tpa-docs-modal-viewer-bar">
                          <span>{docFileName}</span>
                          <a href={docBlobUrl} download={docFileName} className="tpa-btn tpa-btn-sm">Download</a>
                        </div>
                        {isImageFile(docFileName) ? (
                          <img src={docBlobUrl} alt={docFileName} className="tpa-docs-modal-img" />
                        ) : isPdfFile(docFileName) ? (
                          <iframe src={docBlobUrl} className="tpa-docs-modal-pdf" title={docFileName} />
                        ) : (
                          <div className="tpa-docs-modal-empty"><p>Preview not available</p><a href={docBlobUrl} download={docFileName} className="tpa-btn tpa-btn-primary tpa-btn-sm">Download</a></div>
                        )}
                      </div>
                    ) : (
                      <div className="tpa-docs-modal-empty">
                        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" opacity="0.2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                        <p className="tpa-muted">Select a document to preview</p>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

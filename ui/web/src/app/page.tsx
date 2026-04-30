"use client";

import { useState, useRef, useEffect, DragEvent, FormEvent } from "react";
import { useAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";
import UserAvatarDisplay from "@/components/UserAvatarDisplay";
import LanguageSwitcher from "@/components/LanguageSwitcher";
import SsoLoginScreen from "@/components/SsoLoginScreen";

/* ── Types ── */
interface DocInfo {
  id: string;
  file_name: string;
  file_type: string | null;
  uploaded_at: string;
}

interface Claim {
  id: string;
  status: string;
  created_at: string;
  policy_id?: string | null;
  patient_id?: string | null;
  documents: DocInfo[];
}

interface FieldAction {
  action: string;
  field_name: string;
  old_value?: string | null;
  new_value?: string | null;
}

interface Message {
  role: "user" | "bot";
  text: string;
  suggestions?: string[];
  fieldActions?: FieldAction[];
}

interface CodeInfo {
  code: string;
  description: string;
  confidence: number;
  estimated_cost?: number | null;
}

interface AuditEntry {
  id: string;
  actor: string | null;
  action: string;
  metadata: Record<string, unknown> | null;
  created_at: string | null;
}

interface ProgressState {
  status: string;
  step: string;
  percentage: number;
}

interface PreviewData {
  claim_id: string;
  status: string;
  policy_id: string | null;
  parsed_fields: Record<string, string>;
  icd_codes: CodeInfo[];
  cpt_codes: CodeInfo[];
  cost_summary?: { icd_total: number; cpt_total: number; grand_total: number };
  expenses?: Array<{ category: string; amount: number }>;
  expense_total?: number;
  billed_total?: number;
  predictions: Array<{ rejection_score: number; top_reasons: Array<{ reason: string; weight: number; feature: string }>; model_name: string }>;
  validations: Array<{ rule_name: string; severity: string; message: string; passed: boolean }>;
  ocr_excerpt: string;
  brain_insights?: string[];
  reimbursement_brain?: {
    documents_analyzed: Array<{
      file_name: string;
      doc_type: string;
      fields_found: Record<string, string>;
      text_length: number;
    }>;
    cross_references: Array<{
      field: string;
      sources: Array<{ doc: string; doc_type: string; value: string }>;
      status: string;
    }>;
    reimbursement_checklist: Array<{
      item: string;
      status: string;
      reason: string;
    }>;
    insights: Array<{
      type: string;
      category: string;
      text: string;
    }>;
    completeness_pct: number;
  };
  scan_analyses?: Array<{
    id: string;
    scan_type: string;
    body_part: string;
    modality: string;
    findings: Array<{ finding: string; severity: string; confidence: number }>;
    impression: string;
    recommendation: string;
    confidence: number;
    is_abnormal: boolean;
    file_name: string;
  }>;
  summary: {
    patient_name: string;
    age: string;
    gender: string;
    hospital: string;
    doctor: string;
    admission_date: string;
    discharge_date: string;
    diagnosis: string;
    total_amount: string;
    icd_count: number;
    cpt_count: number;
    risk_score: number | null;
    validation_passed: number;
    validation_total: number;
  };
}

const STATUS_CLASS: Record<string, string> = {
  UPLOADED: "status-processing",
  PROCESSING: "status-processing",
  OCR_PROCESSING: "status-processing",
  OCR_DONE: "status-processing",
  PARSING: "status-processing",
  PARSED: "status-processing",
  PREDICTED: "status-processing",
  COMPLETED: "status-completed",
  CODED: "status-coded",
  VALIDATED: "status-validated",
  SUBMITTED: "status-submitted",
  WORKFLOW_FAILED: "status-failed",
  OCR_FAILED: "status-failed",
  PARSE_FAILED: "status-failed",
  VALIDATION_FAILED: "status-failed",
  APPROVED: "status-approved",
  REJECTED: "status-failed",
  DOCUMENTS_REQUESTED: "status-docs-requested",
  MODIFICATION_REQUESTED: "status-mod-requested",
};

const PIPELINE_ACTIVE_STATUSES = new Set([
  "UPLOADED",
  "PROCESSING",
  "OCR_PROCESSING",
  "OCR_DONE",
  "PARSING",
  "PARSED",
  "PREDICTED",
]);

// Statuses where the Preview button should be enabled (parsed enough to show summary)
const PIPELINE_READY_STATUSES = new Set([
  "CODED",
  "VALIDATED",
  "COMPLETED",
  "SUBMITTED",
  "APPROVED",
  "REJECTED",
  "DOCUMENTS_REQUESTED",
  "MODIFICATION_REQUESTED",
]);

const API = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000/ingress";
const CHAT_API = process.env.NEXT_PUBLIC_CHAT_BASE || "http://localhost:8000/chat";
const SUBMISSION_API = process.env.NEXT_PUBLIC_SUBMISSION_BASE || "http://localhost:8000/submission";

/**
 * Build a short, human-friendly claim ID for display.
 *
 * Plain `slice(0, 8)` collides for any IDs that share a common prefix
 * (e.g. seeded test data like `d0000001-aaaa-4000-b000-…0001`,
 * `…0002`, …, all of which start with the same 8 chars).
 *
 * Strategy: strip dashes and use the LAST 8 hex chars of the UUID,
 * which carry the most entropy in both real uuid4 ids and in our
 * sequence-suffixed seed ids.
 */
function shortClaimId(id: string | null | undefined): string {
  if (!id) return "";
  const hex = id.replace(/-/g, "");
  return hex.length <= 8 ? hex : hex.slice(-8);
}

/* ── Rich markdown renderer (ChatGPT-style) ── */
function renderMarkdown(text: string): string {
  let html = text
    // Escape HTML
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  // Code blocks (```...```)
  html = html.replace(/```(\w*)\n?([\s\S]*?)```/g, (_m, lang, code) =>
    `<pre class="code-block" data-lang="${lang}"><code>${code.trim()}</code></pre>`
  );

  // Inline code
  html = html.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>');

  // Headers
  html = html.replace(/^#### (.+)$/gm, '<h5 class="md-h">$1</h5>');
  html = html.replace(/^### (.+)$/gm, '<h4 class="md-h">$1</h4>');
  html = html.replace(/^## (.+)$/gm, '<h3 class="md-h">$1</h3>');
  html = html.replace(/^# (.+)$/gm, '<h2 class="md-h">$1</h2>');

  // Bold and italic
  html = html.replace(/\*\*\*(.+?)\*\*\*/g, "<strong><em>$1</em></strong>");
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*(.+?)\*/g, "<em>$1</em>");

  // Horizontal rule
  html = html.replace(/^---$/gm, '<hr class="md-hr"/>');

  // Bullet lists (handle nested with indentation)
  html = html.replace(/^(\s*)[-•]\s+(.+)$/gm, (_m, indent, content) => {
    const depth = Math.floor((indent?.length || 0) / 2);
    return `<div class="md-li" style="padding-left:${depth * 1.2}rem">• ${content}</div>`;
  });

  // Numbered lists
  html = html.replace(/^\s*(\d+)\.\s+(.+)$/gm, '<div class="md-li"><span class="md-num">$1.</span> $2</div>');

  // Blockquotes
  html = html.replace(/^&gt;\s?(.+)$/gm, '<blockquote class="md-quote">$1</blockquote>');

  // Tables (simple: | col | col |)
  html = html.replace(
    /(?:^\|.+\|$\n?)+/gm,
    (table) => {
      const rows = table.trim().split("\n").filter((r) => !r.match(/^\|[\s-|]+\|$/));
      if (rows.length === 0) return table;
      let t = '<table class="md-table"><tbody>';
      rows.forEach((row, ri) => {
        const cells = row.split("|").filter(Boolean).map((c) => c.trim());
        const tag = ri === 0 ? "th" : "td";
        t += "<tr>" + cells.map((c) => `<${tag}>${c}</${tag}>`).join("") + "</tr>";
      });
      t += "</tbody></table>";
      return t;
    }
  );

  // Line breaks (but not inside pre/table blocks)
  html = html.replace(/\n/g, "<br/>");

  // Clean up double <br/> after block elements
  html = html.replace(/<\/(pre|table|blockquote|div|h[2-5])><br\/>/g, "</$1>");
  html = html.replace(/<br\/><(pre|table|blockquote|h[2-5])/g, "<$1");

  return html;
}

export default function Home() {
  /* ── auth ── */
  const { token, user, logout, loading: authLoading, isAuthenticated, hasRole } = useAuth();
  const { t, lang } = useI18n();

  /* helper: build Authorization header if token is available */
  const authHeaders = (): Record<string, string> =>
    token ? { Authorization: `Bearer ${token}` } : {};

  /* ── state ── */
  const [claims, setClaims] = useState<Claim[]>([]);
  const [activeClaim, setActiveClaim] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [typing, setTyping] = useState(false);
  const [autoSuggestions, setAutoSuggestions] = useState<string[]>([]);
  const [showAutoSuggest, setShowAutoSuggest] = useState(false);
  const [selectedSuggestIdx, setSelectedSuggestIdx] = useState(-1);
  const [llmProvider, setLlmProvider] = useState<string>("");
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [preview, setPreview] = useState<PreviewData | null>(null);
  const [showPreview, setShowPreview] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [pdfPreviewUrl, setPdfPreviewUrl] = useState<string | null>(null);
  const [pdfDownloadUrl, setPdfDownloadUrl] = useState<string>("");
  const [pdfLoading, setPdfLoading] = useState(false);
  const [pdfKind, setPdfKind] = useState<"tpa" | "irda">("tpa");
  const [irdaLoading, setIrdaLoading] = useState(false);
  const [collapsedSections, setCollapsedSections] = useState<Record<string, boolean>>({});
  const [editedFields, setEditedFields] = useState<Record<string, string>>({});
  const [fieldsSaving, setFieldsSaving] = useState(false);
  const [fieldsSaved, setFieldsSaved] = useState(false);

  /* ── Right-panel detail cards / audit history ── */
  const [auditTrail, setAuditTrail] = useState<AuditEntry[]>([]);
  const [auditLoading, setAuditLoading] = useState(false);
  const [historyExpanded, setHistoryExpanded] = useState(false);

  /* ── Floating chat dock (bottom-right corner) ── */
  const [chatOpen, setChatOpen] = useState(false);
  const [chatUnread, setChatUnread] = useState(0);

  const [claimNames, setClaimNames] = useState<Record<string, string>>({});
  // Per-claim lowercased search blob built from preview metadata
  // (patient_name + hospital + doctor + diagnosis). Powers the queue search
  // box so users can find claims by patient name, hospital, etc.
  const [claimSearchIndex, setClaimSearchIndex] = useState<Record<string, string>>({});
  const [claimProgress, setClaimProgress] = useState<Record<string, ProgressState>>({});
  const [lastStepChangeTime, setLastStepChangeTime] = useState<Record<string, number>>({});
  const [pollingClaims, setPollingClaims] = useState<Set<string>>(new Set());
  const [cameraOpen, setCameraOpen] = useState(false);
  const [showTpaModal, setShowTpaModal] = useState(false);
  const [tpaList, setTpaList] = useState<{id: string; name: string; logo: string; type: string; email: string; phone: string; website: string}[]>([]);
  const [tpaSending, setTpaSending] = useState(false);
  const [tpaSent, setTpaSent] = useState<{tpa_name: string; reference: string} | null>(null);
  const [tpaSearch, setTpaSearch] = useState("");
  const [plusMenuOpen, setPlusMenuOpen] = useState(false);
  const [tpaMessages, setTpaMessages] = useState<Record<string, string>>({});
  const [cameraReady, setCameraReady] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [claimSearch, setClaimSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("ALL");
  /* ── B2B Enterprise: Command palette, notifications, user menu ── */
  const [cmdOpen, setCmdOpen] = useState(false);
  const [cmdQuery, setCmdQuery] = useState("");
  const [notifOpen, setNotifOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [density, setDensity] = useState<"comfortable" | "compact">("comfortable");
  const fileRef = useRef<HTMLInputElement>(null);
  const chatFileRef = useRef<HTMLInputElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const msgEnd = useRef<HTMLDivElement>(null);

  /* ── camera functions ── */
  const openCamera = async () => {
    setCameraError(null);
    setCameraOpen(true);
    setCameraReady(false);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment", width: { ideal: 1920 }, height: { ideal: 1080 } },
        audio: false,
      });
      streamRef.current = stream;
      // Wait for the video element to be in the DOM
      setTimeout(() => {
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          videoRef.current.onloadedmetadata = () => setCameraReady(true);
        }
      }, 100);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Camera access denied";
      setCameraError(msg);
    }
  };

  const closeCamera = () => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    setCameraOpen(false);
    setCameraReady(false);
    setCameraError(null);
  };

  const capturePhoto = () => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;

    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.drawImage(video, 0, 0);

    canvas.toBlob((blob) => {
      if (!blob) return;
      const now = new Date();
      const ts = `${now.getFullYear()}${(now.getMonth()+1).toString().padStart(2,"0")}${now.getDate().toString().padStart(2,"0")}_${now.getHours().toString().padStart(2,"0")}${now.getMinutes().toString().padStart(2,"0")}${now.getSeconds().toString().padStart(2,"0")}`;
      const file = new File([blob], `camera_capture_${ts}.jpg`, { type: "image/jpeg" });
      closeCamera();
      upload([file], true);
    }, "image/jpeg", 0.92);
  };

  const captureScreenshot = async () => {
    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({ video: { displaySurface: "monitor" } as any });
      const video = document.createElement("video");
      video.srcObject = stream;
      await video.play();
      const c = document.createElement("canvas");
      c.width = video.videoWidth;
      c.height = video.videoHeight;
      c.getContext("2d")!.drawImage(video, 0, 0);
      stream.getTracks().forEach((t) => t.stop());
      const blob = await new Promise<Blob | null>((res) => c.toBlob(res, "image/png"));
      if (!blob) return;
      const now = new Date();
      const ts = `${now.getFullYear()}${(now.getMonth()+1).toString().padStart(2,"0")}${now.getDate().toString().padStart(2,"0")}_${now.getHours().toString().padStart(2,"0")}${now.getMinutes().toString().padStart(2,"0")}${now.getSeconds().toString().padStart(2,"0")}`;
      const file = new File([blob], `screenshot_${ts}.png`, { type: "image/png" });
      upload([file], true);
    } catch {
      /* user cancelled the screen picker */
    }
  };

  /* ── auto-scroll messages ── */
  useEffect(() => {
    msgEnd.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  /* ── Track unread bot messages while chat dock is closed ── */
  useEffect(() => {
    if (chatOpen) {
      setChatUnread(0);
      return;
    }
    const last = messages[messages.length - 1];
    if (last && last.role === "bot") {
      setChatUnread((n) => n + 1);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages.length]);

  /* ── load claims on mount ── */
  const refreshClaims = () => {
    fetch(`${API}/claims?limit=100&t=${Date.now()}`, { cache: "no-store" })
      .then((r) => r.json())
      .then((data) => {
        if (data?.claims && Array.isArray(data.claims)) {
          const newClaims: Claim[] = data.claims;
          // Check if any claim just changed from UPLOADED/PROCESSING → COMPLETED
          setClaims((prev) => {
            for (const nc of newClaims) {
              const old = prev.find((p) => p.id === nc.id);
              if (
                old &&
                PIPELINE_ACTIVE_STATUSES.has(old.status) &&
                PIPELINE_READY_STATUSES.has(nc.status) &&
                old.status !== nc.status &&
                nc.id === activeClaim
              ) {
                // Claim just finished processing — auto-load preview & notify
                loadPreview(nc.id);
                setMessages((msgs) => [
                  ...msgs,
                  { role: "bot", text: "✅ **Pipeline complete!** Your document has been processed through OCR → Parser → Coding → Predictor → Validator. Ask me anything about the claim." },
                ]);
              }
            }
            return newClaims;
          });
        }
      })
      .catch(() => {});
  };

  useEffect(() => {
    refreshClaims();
    fetch(`${CHAT_API}/providers`, { headers: authHeaders() }).then((r) => r.json()).then((d) => {
      if (d?.current) setLlmProvider(d.current);
    }).catch(() => {});
    // Load patient names + searchable metadata for ALL claims (not just
    // completed ones) so the queue search works across the full list.
    fetch(`${API}/claims`, { headers: authHeaders() }).then((r) => r.json()).then((data) => {
      if (!data?.claims) return;
      data.claims.forEach((c: Claim) => {
        fetch(`${SUBMISSION_API}/claims/${c.id}/preview`, { headers: authHeaders() })
          .then((r) => r.json())
          .then((p: PreviewData) => {
            const s = p?.summary;
            if (!s) return;
            if (s.patient_name) {
              setClaimNames((prev) => ({ ...prev, [c.id]: s.patient_name }));
            }
            const blob = [s.patient_name, s.hospital, s.doctor, s.diagnosis]
              .filter(Boolean)
              .join(" ")
              .toLowerCase();
            if (blob) {
              setClaimSearchIndex((prev) => ({ ...prev, [c.id]: blob }));
            }
          })
          .catch(() => {});
      });
    }).catch(() => {});
  }, []);

  /* ── auto-refresh claim status every 5s while any claim is processing ── */
  const refreshClaimProgress = () => {
    const activeClaims = claims.filter((c) => PIPELINE_ACTIVE_STATUSES.has(c.status));
    activeClaims.forEach((claim) => {
      setPollingClaims((prev) => new Set(prev).add(claim.id));
      fetch(`${API}/claims/${claim.id}/progress?t=${Date.now()}`, { cache: "no-store" })
        .then((r) => r.json())
        .then((data) => {
          if (data.is_complete) {
            setPollingClaims((prev) => {
              const newSet = new Set(prev);
              newSet.delete(claim.id);
              return newSet;
            });
          }
          if (data && typeof data.percentage === "number") {
            setClaimProgress((prev) => {
              const newProgress = {
                status: data.status || claim.status,
                step: data.step || claim.status,
                percentage: data.percentage,
              };
              const prevProgress = prev[claim.id];
              if (!prevProgress || newProgress.step !== prevProgress.step) {
                const now = Date.now();
                const lastTime = lastStepChangeTime[claim.id] || 0;
                if (now - lastTime < 200) {
                  // Don't update step yet, only percentage
                  return {
                    ...prev,
                    [claim.id]: {
                      ...prevProgress,
                      percentage: newProgress.percentage,
                    },
                  };
                } else {
                  // Update step and time
                  setLastStepChangeTime((prevTimes) => ({ ...prevTimes, [claim.id]: now }));
                  return {
                    ...prev,
                    [claim.id]: newProgress,
                  };
                }
              } else {
                // Same step, update percentage
                return {
                  ...prev,
                  [claim.id]: {
                    ...prevProgress,
                    percentage: newProgress.percentage,
                  },
                };
              }
            });
            if (data.percentage === 100) {
              setTimeout(() => refreshClaims(), 500);
            }
          }
        })
        .catch(() => {});
    });
  };

  useEffect(() => {
    if (pollingClaims.size === 0) return;

    const id = setInterval(refreshClaimProgress, 200);
    return () => clearInterval(id);
  }, [pollingClaims]);

  /* ── poll claim status updates at 2s intervals ── */
  useEffect(() => {
    const activeClaims = claims.filter((c) =>
      PIPELINE_ACTIVE_STATUSES.has(c.status)
    );
    if (activeClaims.length === 0) return;

    const id = setInterval(refreshClaims, 2000);
    return () => clearInterval(id);
  }, [claims]);

  /* ── Fetch TPA messages for requested claims ── */
  useEffect(() => {
    const requested = claims.filter(c => c.status === "DOCUMENTS_REQUESTED" || c.status === "MODIFICATION_REQUESTED");
    if (requested.length === 0) return;
    requested.forEach(c => {
      if (tpaMessages[c.id]) return; // already fetched
      fetch(`${SUBMISSION_API}/claims/${c.id}/audit`, { headers: authHeaders() })
        .then(r => r.json())
        .then(data => {
          if (!data?.audit_trail) return;
          // Find the latest TPA action entry
          const tpaEntry = [...data.audit_trail].reverse().find((e: any) =>
            e.action?.startsWith("CLAIM_") && e.metadata?.reason
          );
          if (tpaEntry?.metadata?.reason) {
            setTpaMessages(prev => ({ ...prev, [c.id]: tpaEntry.metadata.reason }));
          }
        })
        .catch(() => {});
    });
  }, [claims]);

  /* ── B2B Enterprise: Global keyboard shortcuts (Cmd+K, ?, Esc) ── */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      const inField = target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable;
      // Cmd/Ctrl + K → command palette
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setCmdOpen((v) => !v);
        return;
      }
      // ? → shortcuts modal (only when not typing)
      if (!inField && e.key === "?") {
        e.preventDefault();
        setShortcutsOpen((v) => !v);
        return;
      }
      // Esc → close any open modal
      if (e.key === "Escape") {
        if (cmdOpen) setCmdOpen(false);
        if (notifOpen) setNotifOpen(false);
        if (userMenuOpen) setUserMenuOpen(false);
        if (shortcutsOpen) setShortcutsOpen(false);
      }
      // Cmd/Ctrl + / → toggle density
      if ((e.metaKey || e.ctrlKey) && e.key === "/") {
        e.preventDefault();
        setDensity((d) => (d === "comfortable" ? "compact" : "comfortable"));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cmdOpen, notifOpen, userMenuOpen, shortcutsOpen]);

  /* ── Close dropdowns on outside click ── */
  useEffect(() => {
    if (!notifOpen && !userMenuOpen) return;
    const onClick = (e: MouseEvent) => {
      const t = e.target as HTMLElement;
      if (!t.closest(".notif-wrap") && notifOpen) setNotifOpen(false);
      if (!t.closest(".user-menu-wrap") && userMenuOpen) setUserMenuOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [notifOpen, userMenuOpen]);

  /* ── helper: file type icon ── */
  const fileIcon = (name: string) => {
    const ext = name.split(".").pop()?.toLowerCase() || "";
    if (["pdf"].includes(ext)) return "📄";
    if (["jpg", "jpeg", "png", "tiff", "tif", "bmp", "webp"].includes(ext)) return "🖼️";
    if (["doc", "docx"].includes(ext)) return "📝";
    if (["xls", "xlsx", "csv"].includes(ext)) return "📊";
    if (["json", "xml", "html"].includes(ext)) return "📋";
    if (["txt"].includes(ext)) return "📃";
    return "📎";
  };

  /* ── upload handler (XHR for progress, multi-file) ── */
  /* appendToActive=false → sidebar upload → always new claim */
  /* appendToActive=true  → chat attach/camera/screenshot → add to active claim */
  const upload = (files: File[], appendToActive = false) => {
    if (!files.length) return;
    setUploadError(null);
    setUploading(true);
    setUploadProgress(0);
    setUploadFiles(files);

    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));

    const isAppend = appendToActive && !!activeClaim;
    const url = isAppend
      ? `${API}/claims/${activeClaim}/documents`
      : `${API}/claims`;

    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) {
        setUploadProgress(Math.round((e.loaded / e.total) * 100));
      }
    };

    xhr.onload = () => {
      setUploading(false);
      setUploadFiles([]);
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const claim: any = JSON.parse(xhr.responseText);
          // Update or insert the claim in the list
          setClaims((prev) => {
            const exists = prev.find((c) => c.id === claim.id);
            if (exists) return prev.map((c) => (c.id === claim.id ? claim : c));
            return [claim, ...prev];
          });
          setActiveClaim(claim.id);

          // Kick off an aggressive refresh schedule so the UI picks up
          // the rapid status transitions (UPLOADED → OCR → PARSE → CODED → COMPLETED)
          // without waiting for the next polling tick.
          [400, 1200, 2500, 4500, 7000, 10000, 14000].forEach((delay) => {
            setTimeout(refreshClaims, delay);
          });

          if (claim.already_exists) {
            setMessages([
              {
                role: "bot",
                text: `⚠️ A report has already been generated for this file. <a href='${claim.report_url}' target='_blank' rel='noopener noreferrer'>View Report</a>`,
              },
            ]);
          } else {
            const count = claim.documents?.length || files.length;
            const newNames = files.map((f) => f.name).join(", ");
            if (isAppend) {
              setMessages((prev) => [
                ...prev,
                { role: "bot", text: `📎 **${files.length} supporting document${files.length > 1 ? "s" : ""} added** to this claim (${newNames}). Total: ${count} documents. Re-processing through pipeline...` },
              ]);
            } else {
              const fname = claim.documents?.[0]?.file_name || files[0].name;
              const label = count > 1 ? `${count} documents (${fname}, ...)` : `"${fname}"`;
              setMessages([
                { role: "bot", text: `Claim with ${label} uploaded. Processing through AI pipeline (OCR > Parse > Code > Predict > Validate)...` },
              ]);
            }
          }
        } catch {
          setUploadError("Invalid response from server.");
        }
      } else {
        try {
          const err = JSON.parse(xhr.responseText);
          setUploadError(err?.detail || `Upload failed (${xhr.status})`);
        } catch {
          setUploadError(`Upload failed (${xhr.status})`);
        }
      }
    };

    xhr.onerror = () => {
      setUploading(false);
      setUploadFiles([]);
      setUploadError("Network error — is the server running?");
    };

    xhr.send(fd);
  };

  /* ── drag handlers ── */
  const onDragOver = (e: DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  };
  const onDragLeave = () => setDragOver(false);
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const files = e.dataTransfer.files;
    if (files?.length) upload(Array.from(files));
  };

  /* ── delete single document ── */
  const deleteDoc = async (claimId: string, docId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      const resp = await fetch(`${API}/claims/${claimId}/documents/${docId}`, { method: "DELETE", headers: authHeaders() });
      if (resp.ok) {
        const updated: Claim = await resp.json();
        setClaims((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
      }
    } catch { /* ignore */ }
  };

  /* ── delete handler ── */
  const deleteClaim = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      const resp = await fetch(`${API}/claims/${id}`, { method: "DELETE", headers: authHeaders() });
      if (!resp.ok && resp.status !== 204) return;
      setClaims((prev) => prev.filter((c) => c.id !== id));
      if (activeClaim === id) {
        setActiveClaim(null);
        setMessages([]);
      }
    } catch { /* ignore */ }
  };

  /* ── code feedback handler ── */
  const sendCodeFeedback = async (code: string, action: string) => {
    if (!activeClaim) return;
    try {
      await fetch(`${SUBMISSION_API}/claims/${activeClaim}/code-feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ code, action }),
      });
    } catch { /* ignore */ }
  };

  /* ── audit / history loader ── */
  const loadAudit = async (claimId: string) => {
    setAuditLoading(true);
    try {
      const resp = await fetch(`${SUBMISSION_API}/claims/${claimId}/audit`, { headers: authHeaders() });
      if (resp.ok) {
        const data = await resp.json();
        setAuditTrail(Array.isArray(data?.audit_trail) ? data.audit_trail : []);
      } else {
        setAuditTrail([]);
      }
    } catch {
      setAuditTrail([]);
    }
    setAuditLoading(false);
  };

  /* ── preview handler ── */
  const loadPreview = async (claimId: string) => {
    setPreviewLoading(true);
    try {
      const resp = await fetch(`${SUBMISSION_API}/claims/${claimId}/preview`, { headers: authHeaders() });
      if (resp.ok) {
        const data: PreviewData = await resp.json();
        setPreview(data);
        setShowPreview(true);
        setEditedFields({
          patient_name: data.summary?.patient_name || "",
          age: data.summary?.age || "",
          gender: data.summary?.gender || "",
          hospital: data.summary?.hospital || "",
          doctor: data.summary?.doctor || "",
          admission_date: data.summary?.admission_date || "",
          discharge_date: data.summary?.discharge_date || "",
          diagnosis: data.summary?.diagnosis || "",
          total_amount: data.summary?.total_amount || "",
        });
        setFieldsSaved(false);
        if (data.summary?.patient_name) {
          setClaimNames((prev) => ({ ...prev, [claimId]: data.summary.patient_name }));
        }
        // Keep the queue search index in sync when previews are opened directly
        const s = data.summary;
        const blob = s
          ? [s.patient_name, s.hospital, s.doctor, s.diagnosis].filter(Boolean).join(" ").toLowerCase()
          : "";
        if (blob) {
          setClaimSearchIndex((prev) => ({ ...prev, [claimId]: blob }));
        }
      }
    } catch { /* ignore */ }
    setPreviewLoading(false);
  };

  const saveEditedFields = async () => {
    if (!preview?.claim_id) return;
    setFieldsSaving(true);
    try {
      /* Map UI field names to DB field names */
      const dbFields: Record<string, string> = {};
      const fieldMap: Record<string, string> = {
        patient_name: "patient_name",
        age: "age",
        gender: "gender",
        hospital: "hospital_name",
        doctor: "doctor_name",
        admission_date: "admission_date",
        discharge_date: "discharge_date",
        diagnosis: "diagnosis",
        total_amount: "total_amount",
      };
      for (const [uiKey, dbKey] of Object.entries(fieldMap)) {
        if (editedFields[uiKey] !== undefined) dbFields[dbKey] = editedFields[uiKey];
      }
      const resp = await fetch(`${SUBMISSION_API}/claims/${preview.claim_id}/fields`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ fields: dbFields }),
      });
      if (resp.ok) {
        setFieldsSaved(true);
        /* Update preview summary in-place so UI reflects changes immediately */
        setPreview((prev) => prev ? {
          ...prev,
          summary: { ...prev.summary, ...editedFields },
        } : prev);
        /* Auto-clear saved indicator after 3s */
        setTimeout(() => setFieldsSaved(false), 3000);
      }
    } catch { /* ignore */ }
    setFieldsSaving(false);
  };





  /* ── chat handler ── */
  const sendMessage = async (e: FormEvent) => {
    e.preventDefault();
    const text = input.trim();
    if (!text) return;
    setInput("");
    setChatOpen(true);
    setChatUnread(0);
    setMessages((prev) => [...prev, { role: "user", text }]);
    setTyping(true);

    const sessionId = activeClaim || "general";
    const language = lang;

    /* ── Try streaming first, fallback to regular endpoint ── */
    try {
      const resp = await fetch(`${CHAT_API}/${sessionId}/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ message: text, claim_id: activeClaim, language }),
      });

      if (resp.ok && resp.body) {
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let accumulated = "";
        let botIdx: number | null = null;
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (!line.startsWith("data: ") || line === "data: [DONE]") continue;
            try {
              const payload = JSON.parse(line.slice(6));
              if (payload.suggestions || payload.field_actions) {
                setMessages((prev) => {
                  const copy = [...prev];
                  if (copy.length > 0 && copy[copy.length - 1].role === "bot") {
                    copy[copy.length - 1] = {
                      ...copy[copy.length - 1],
                      suggestions: payload.suggestions || copy[copy.length - 1].suggestions,
                      fieldActions: payload.field_actions || copy[copy.length - 1].fieldActions,
                    };
                  }
                  return copy;
                });
                continue;
              }
              const chunk = payload.content || "";
              if (!chunk) continue;
              accumulated += chunk;
              if (botIdx === null) {
                setMessages((prev) => {
                  botIdx = prev.length;
                  return [...prev, { role: "bot", text: accumulated }];
                });
              } else {
                const snap = accumulated;
                setMessages((prev) => {
                  const copy = [...prev];
                  if (botIdx !== null && copy[botIdx]) copy[botIdx] = { ...copy[botIdx], text: snap };
                  return copy;
                });
              }
            } catch { /* skip malformed */ }
          }
        }
        if (!accumulated) throw new Error("empty stream");
        setTyping(false);
        return;
      }
      /* Non-streaming fallback */
      throw new Error("stream not ok");
    } catch {
      /* ── Fallback: regular endpoint ── */
      try {
        const resp2 = await fetch(`${CHAT_API}/${sessionId}/message`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeaders() },
          body: JSON.stringify({ message: text, claim_id: activeClaim, language }),
        });
        const data = await resp2.json();
        setMessages((prev) => [
          ...prev.filter((m) => !(m.role === "bot" && m.text === "")),
          {
            role: "bot",
            text: data.message || data.detail || "No response.",
            suggestions: data.suggestions || [],
            fieldActions: data.field_actions || [],
          },
        ]);
      } catch {
        setMessages((prev) => [
          ...prev,
          { role: "bot", text: "Could not reach the chat service." },
        ]);
      }
    } finally {
      setTyping(false);
    }
  };

  /* helper: send a suggestion as if the user typed it */
  const sendSuggestion = (text: string) => {
    setChatOpen(true);
    setChatUnread(0);
    setInput(text);
    setTimeout(() => {
      const form = document.querySelector(".chat-input-bar") as HTMLFormElement;
      form?.requestSubmit();
    }, 50);
  };

  /* helper: open the floating chat dock and pre-fill an input prompt
     (does NOT auto-submit — gives the user a chance to edit) */
  const openChatAbout = (prompt: string) => {
    setChatOpen(true);
    setChatUnread(0);
    setInput(prompt);
    setTimeout(() => {
      const inp = document.querySelector(".chat-input-bar input[type='text'], .chat-input-bar input:not([type])") as HTMLInputElement | null;
      inp?.focus();
    }, 80);
  };

  /* helper: apply field actions (add/modify/delete) to claim via API */
  const applyFieldActions = async (actions: FieldAction[], msgIdx: number) => {
    if (!activeClaim || actions.length === 0) return;
    try {
      const resp = await fetch(`${CHAT_API}/fields/apply`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ claim_id: activeClaim, actions }),
      });
      if (resp.ok) {
        // Remove the field actions from the message (mark as applied)
        setMessages((prev) => {
          const copy = [...prev];
          copy[msgIdx] = { ...copy[msgIdx], fieldActions: [], text: copy[msgIdx].text + "\n\n✅ **Field changes applied successfully!**" };
          return copy;
        });
        // Refresh claim data
        if (activeClaim) {
          loadPreview(activeClaim);
        }
      } else {
        const err = await resp.json().catch(() => ({ detail: "Failed" }));
        setMessages((prev) => {
          const copy = [...prev];
          copy[msgIdx] = { ...copy[msgIdx], text: copy[msgIdx].text + `\n\n❌ **Failed to apply:** ${err.detail || "Unknown error"}` };
          return copy;
        });
      }
    } catch {
      setMessages((prev) => {
        const copy = [...prev];
        copy[msgIdx] = { ...copy[msgIdx], text: copy[msgIdx].text + "\n\n❌ **Could not reach the service.**" };
        return copy;
      });
    }
  };

  /* helper: dismiss field actions */
  const dismissFieldActions = (msgIdx: number) => {
    setMessages((prev) => {
      const copy = [...prev];
      copy[msgIdx] = { ...copy[msgIdx], fieldActions: [] };
      return copy;
    });
  };

  /* ── Autocomplete suggestions (Google-like) ── */
  const getAutoSuggestions = (text: string): string[] => {
    const t = text.toLowerCase().trim();
    if (!t || t.length < 2) return [];

    // Fuzzy match: checks if input is close to target (allows typos)
    const fuzzyMatch = (input: string, target: string): number => {
      const a = input.toLowerCase();
      const b = target.toLowerCase();
      if (b.startsWith(a)) return 3;  // exact prefix = best
      if (b.includes(a)) return 2;    // substring match = good

      // Check each word in target
      const words = b.split(/\s+/);
      for (const w of words) {
        if (w.startsWith(a)) return 2.5;
        // Levenshtein-like: allow 1-2 char typos per word
        if (a.length >= 3 && w.length >= 3) {
          let matches = 0;
          const shorter = a.length < w.length ? a : w;
          const longer = a.length < w.length ? w : a;
          for (let i = 0; i < shorter.length; i++) {
            if (longer.includes(shorter[i])) matches++;
          }
          const ratio = matches / longer.length;
          if (ratio >= 0.65) return 1;  // fuzzy hit
        }
      }

      // Check if input chars appear in order in target (subsequence)
      let j = 0;
      for (let i = 0; i < b.length && j < a.length; i++) {
        if (b[i] === a[j]) j++;
      }
      if (j >= a.length * 0.75) return 0.5; // partial subsequence

      return 0;
    };

    // Build dynamic field names from current claim data
    const fieldNames: string[] = [];
    const fieldEntries: Array<[string, string]> = [];
    if (preview?.parsed_fields) {
      for (const [k, v] of Object.entries(preview.parsed_fields)) {
        const label = k.replace(/_/g, " ");
        if (!fieldNames.includes(label)) {
          fieldNames.push(label);
          if (v) fieldEntries.push([label, v]);
        }
      }
    }

    // ── CRUD operation suggestions ──
    const crudTemplates = [
      ...fieldNames.map((f) => `Add ${f}`),
      "Add patient name", "Add diagnosis", "Add hospital name", "Add doctor name",
      "Add policy id", "Add admission date", "Add discharge date", "Add claim amount",
      ...fieldEntries.map(([f]) => `Change ${f} to `),
      ...fieldEntries.map(([f]) => `Update ${f}`),
      "Change patient name to ", "Change diagnosis to ", "Change hospital to ",
      "Update doctor name to ", "Correct the admission date to ",
      ...fieldNames.map((f) => `Remove ${f}`),
      "Remove policy id", "Delete the provider name",
      ...fieldEntries.map(([f]) => `${f} should be `),
      ...fieldEntries.map(([f]) => `${f} is missing, it should be `),
    ];

    // ── General query suggestions ──
    const generalTemplates = [
      "Show me the claim summary", "What is the patient name?", "What is the diagnosis?",
      "Show billing details", "What is the rejection risk?", "Show all ICD codes",
      "Show CPT codes", "Are there any validation issues?", "What fields are missing?",
      "Show the OCR extracted text", "Explain the risk factors", "How can I reduce rejection risk?",
      "Show patient information", "What is the total claim amount?", "Show hospital details",
      "List all parsed fields", "What is the admission date?", "What is the discharge date?",
      "Show insurance details", "Who is the treating doctor?", "How does the claim pipeline work?",
      "What file types can I upload?", "Generate a full claim report",
      "Why was this claim rejected?", "Explain the rejection reasons", "What went wrong with this claim?",
      "Why did this claim get denied?", "What caused the rejection?",
    ];

    const all = [...new Set([...crudTemplates, ...generalTemplates])];

    // Score and sort by relevance (fuzzy + exact)
    const scored: Array<[string, number]> = [];
    for (const s of all) {
      if (s.toLowerCase() === t) continue;
      const score = fuzzyMatch(t, s);
      if (score > 0) scored.push([s, score]);
    }
    scored.sort((a, b) => b[1] - a[1]);

    return scored.slice(0, 8).map(([s]) => s);
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setInput(val);
    const sug = getAutoSuggestions(val);
    setAutoSuggestions(sug);
    setShowAutoSuggest(sug.length > 0);
    setSelectedSuggestIdx(-1);
  };

  const handleInputKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!showAutoSuggest || autoSuggestions.length === 0) return;

    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedSuggestIdx((prev) => Math.min(prev + 1, autoSuggestions.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedSuggestIdx((prev) => Math.max(prev - 1, -1));
    } else if (e.key === "Enter" && selectedSuggestIdx >= 0) {
      e.preventDefault();
      setInput(autoSuggestions[selectedSuggestIdx]);
      setShowAutoSuggest(false);
      setSelectedSuggestIdx(-1);
    } else if (e.key === "Tab" && selectedSuggestIdx >= 0) {
      e.preventDefault();
      setInput(autoSuggestions[selectedSuggestIdx]);
      setShowAutoSuggest(false);
      setSelectedSuggestIdx(-1);
    } else if (e.key === "Escape") {
      setShowAutoSuggest(false);
    }
  };

  const selectAutoSuggestion = (s: string) => {
    setInput(s);
    setShowAutoSuggest(false);
    setSelectedSuggestIdx(-1);
    // Focus the input
    const inp = document.querySelector(".input-wrapper input") as HTMLInputElement;
    inp?.focus();
  };

  /* ── risk color ── */
  const riskColor = (score: number | null) => {
    if (score === null) return "#94a3b8";
    if (score <= 0.3) return "#22c55e";
    if (score <= 0.6) return "#eab308";
    return "#ef4444";
  };

  const toggleSection = (key: string) =>
    setCollapsedSections((prev) => ({ ...prev, [key]: !prev[key] }));

  const verdictLabel = (score: number | null) => {
    if (score === null) return { text: "PENDING", cls: "verdict-pending" };
    if (score <= 0.3) return { text: "LIKELY APPROVED", cls: "verdict-approved" };
    if (score <= 0.6) return { text: "NEEDS REVIEW", cls: "verdict-review" };
    return { text: "HIGH RISK", cls: "verdict-rejected" };
  };

  const confClass = (c: number) =>
    c >= 0.8 ? "conf-high" : c >= 0.5 ? "conf-mid" : "conf-low";

  /* ── B2B: SLA / Turnaround time helper (24h SLA target) ── */
  const claimSla = (createdAt: string, status: string) => {
    const ageMs = Date.now() - new Date(createdAt).getTime();
    const ageHours = ageMs / (1000 * 60 * 60);
    const isResolved = ["SUBMITTED", "APPROVED", "REJECTED"].includes(status);
    let label: string;
    if (ageHours < 1) label = `${Math.round(ageHours * 60)}m`;
    else if (ageHours < 24) label = `${Math.round(ageHours)}h`;
    else label = `${Math.round(ageHours / 24)}d`;
    let cls = "sla-good";
    if (!isResolved) {
      if (ageHours > 48) cls = "sla-breach";
      else if (ageHours > 24) cls = "sla-warn";
    } else {
      cls = "sla-done";
    }
    return { label, cls, ageHours, isResolved };
  };

  /* ── B2B: Filtered claims for queue ── */
  const filteredClaims = claims.filter((c) => {
    if (statusFilter !== "ALL") {
      if (statusFilter === "PROCESSING" && !PIPELINE_ACTIVE_STATUSES.has(c.status)) return false;
      if (statusFilter === "READY" && !["COMPLETED", "VALIDATED", "CODED"].includes(c.status)) return false;
      if (statusFilter === "SUBMITTED" && c.status !== "SUBMITTED") return false;
      if (statusFilter === "FAILED" && !c.status.includes("FAILED") && c.status !== "REJECTED") return false;
      if (statusFilter === "ACTION" && c.status !== "DOCUMENTS_REQUESTED" && c.status !== "MODIFICATION_REQUESTED") return false;
    }
    if (claimSearch.trim()) {
      const q = claimSearch.toLowerCase();
      const matchesId = c.id.toLowerCase().includes(q);
      const matchesPatient = (c.patient_id || "").toLowerCase().includes(q);
      const matchesPolicy = (c.policy_id || "").toLowerCase().includes(q);
      const matchesFile = c.documents?.some(d => d.file_name.toLowerCase().includes(q));
      const matchesName = (claimNames[c.id] || "").toLowerCase().includes(q);
      // Searches patient_name + hospital + doctor + diagnosis from preview metadata
      const matchesMeta = (claimSearchIndex[c.id] || "").includes(q);
      if (!matchesId && !matchesPatient && !matchesPolicy && !matchesFile && !matchesName && !matchesMeta) return false;
    }
    return true;
  });

  /* ── B2B: Stats for operations dashboard ── */
  const statsProcessing = claims.filter(c => PIPELINE_ACTIVE_STATUSES.has(c.status)).length;
  const statsReady = claims.filter(c => ["COMPLETED", "VALIDATED", "CODED"].includes(c.status)).length;
  const statsSubmitted = claims.filter(c => c.status === "SUBMITTED").length;
  const statsFailed = claims.filter(c => c.status.includes("FAILED") || c.status === "REJECTED").length;
  const statsApproved = claims.filter(c => c.status === "APPROVED").length;
  const statsAction = claims.filter(c => c.status === "DOCUMENTS_REQUESTED" || c.status === "MODIFICATION_REQUESTED").length;
  const approvalRate = (statsSubmitted + statsApproved) > 0
    ? Math.round((statsApproved / (statsSubmitted + statsApproved)) * 100)
    : null;

  /* ── B2B: Avg TAT (turnaround) for processed claims ── */
  const processedClaims = claims.filter(c => ["SUBMITTED", "APPROVED", "REJECTED", "COMPLETED", "VALIDATED", "CODED"].includes(c.status));
  const avgTatHours = processedClaims.length > 0
    ? processedClaims.reduce((sum, c) => sum + (Date.now() - new Date(c.created_at).getTime()) / (1000 * 60 * 60), 0) / processedClaims.length
    : null;
  const avgTatLabel = avgTatHours === null
    ? "—"
    : avgTatHours < 1 ? `${Math.round(avgTatHours * 60)}m`
    : avgTatHours < 24 ? `${avgTatHours.toFixed(1)}h`
    : `${(avgTatHours / 24).toFixed(1)}d`;

  /* ── B2B: SLA breach count (>24h, not resolved) ── */
  const slaBreaches = claims.filter(c => {
    const isResolved = ["SUBMITTED", "APPROVED", "REJECTED"].includes(c.status);
    if (isResolved) return false;
    const ageHours = (Date.now() - new Date(c.created_at).getTime()) / (1000 * 60 * 60);
    return ageHours > 24;
  }).length;

  /* ── B2B: Total billed value across all claims (INR) ── */
  // Note: requires preview data per claim — we approximate from active preview only for now

  /* ── B2B Enterprise: Notifications feed (derived from claims) ── */
  type Notif = { id: string; type: "breach" | "action" | "info" | "success"; title: string; body: string; time: string; claimId?: string };
  const notifications: Notif[] = [
    ...claims
      .filter((c) => {
        const isResolved = ["SUBMITTED", "APPROVED", "REJECTED"].includes(c.status);
        if (isResolved) return false;
        const ageH = (Date.now() - new Date(c.created_at).getTime()) / 3.6e6;
        return ageH > 24;
      })
      .slice(0, 4)
      .map((c) => ({
        id: `breach-${c.id}`,
        type: "breach" as const,
        title: "SLA Breach",
        body: `Claim #${shortClaimId(c.id)} pending > 24h`,
        time: new Date(c.created_at).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }),
        claimId: c.id,
      })),
    ...claims
      .filter((c) => c.status === "DOCUMENTS_REQUESTED" || c.status === "MODIFICATION_REQUESTED")
      .slice(0, 3)
      .map((c) => ({
        id: `action-${c.id}`,
        type: "action" as const,
        title: c.status === "DOCUMENTS_REQUESTED" ? "Documents Requested" : "Modification Requested",
        body: tpaMessages[c.id] || `TPA needs additional input on #${shortClaimId(c.id)}`,
        time: "Now",
        claimId: c.id,
      })),
    ...claims
      .filter((c) => c.status === "APPROVED")
      .slice(0, 2)
      .map((c) => ({
        id: `approved-${c.id}`,
        type: "success" as const,
        title: "Claim Approved",
        body: `#${shortClaimId(c.id)} approved by TPA`,
        time: new Date(c.created_at).toLocaleDateString("en-IN", { day: "2-digit", month: "short" }),
        claimId: c.id,
      })),
  ];
  const notifBreachCount = notifications.filter((n) => n.type === "breach" || n.type === "action").length;

  /* ── B2B Enterprise: Command palette items ── */
  const cmdItems = [
    { id: "new-claim", group: "Actions", label: "New Claim", hint: "N", icon: "➕", action: () => { setActiveClaim(null); setMessages([]); setCmdOpen(false); } },
    { id: "tpa", group: "Navigate", label: "TPA Portal", hint: "G T", icon: "🏢", action: () => { window.open("/tpa", "_self"); } },
    { id: "analytics", group: "Navigate", label: "Analytics Dashboard", hint: "G A", icon: "📊", action: () => { window.open("/tpa/analytics", "_self"); } },
    { id: "filter-action", group: "Filter", label: "Show Action Required", icon: "⚠️", action: () => { setStatusFilter("ACTION"); setCmdOpen(false); } },
    { id: "filter-ready", group: "Filter", label: "Show Ready for Review", icon: "✅", action: () => { setStatusFilter("READY"); setCmdOpen(false); } },
    { id: "filter-processing", group: "Filter", label: "Show In Pipeline", icon: "⚙️", action: () => { setStatusFilter("PROCESSING"); setCmdOpen(false); } },
    { id: "filter-all", group: "Filter", label: "Show All Claims", icon: "📋", action: () => { setStatusFilter("ALL"); setCmdOpen(false); } },
    { id: "density", group: "Preferences", label: `Density: ${density === "comfortable" ? "Comfortable → Compact" : "Compact → Comfortable"}`, hint: "⌘ /", icon: "🔀", action: () => { setDensity((d) => d === "comfortable" ? "compact" : "comfortable"); setCmdOpen(false); } },
    { id: "shortcuts", group: "Help", label: "Keyboard Shortcuts", hint: "?", icon: "⌨️", action: () => { setCmdOpen(false); setShortcutsOpen(true); } },
  ];
  const cmdFiltered = cmdQuery.trim()
    ? cmdItems.filter((i) => i.label.toLowerCase().includes(cmdQuery.toLowerCase()))
    : cmdItems;
  // Also surface matching claims from query
  const cmdClaimMatches = cmdQuery.trim()
    ? claims.filter((c) =>
        c.id.toLowerCase().includes(cmdQuery.toLowerCase()) ||
        (claimNames[c.id] || "").toLowerCase().includes(cmdQuery.toLowerCase()) ||
        (c.patient_id || "").toLowerCase().includes(cmdQuery.toLowerCase()) ||
        (c.policy_id || "").toLowerCase().includes(cmdQuery.toLowerCase())
      ).slice(0, 5)
    : [];

  /* ── render ── */
  /* Block on auth: show splash during init, login screen when unauthenticated */
  if (authLoading) {
    return (
      <div className="auth-splash" role="status" aria-live="polite">
        <div className="auth-splash-spinner" aria-hidden />
        <span className="auth-splash-text">Loading ClaimGPT…</span>
      </div>
    );
  }
  if (!isAuthenticated) {
    return <SsoLoginScreen />;
  }

  return (
    <div className="app-shell">
      {/* User-menu backdrop scrim — rendered at root so it escapes
          the nav's `backdrop-filter` stacking context. */}
      {userMenuOpen && (
        <div className="user-menu-scrim" onClick={() => setUserMenuOpen(false)} aria-hidden />
      )}
      {/* ── Top Navigation Bar ── */}
      <nav className="top-nav">
        <div className="top-nav-left">
          <div className="top-nav-brand">
            <span className="brand-icon">
              <svg width="28" height="28" viewBox="0 0 30 30" fill="none"><rect width="30" height="30" rx="7" fill="url(#brandbg)"/><path d="M15 7v16M7 15h16" stroke="#fff" strokeWidth="2.6" strokeLinecap="round"/><defs><linearGradient id="brandbg" x1="0" y1="0" x2="30" y2="30"><stop stopColor="#0f4c81"/><stop offset="1" stopColor="#0d9488"/></linearGradient></defs></svg>
            </span>
            <span className="brand-name">ClaimGPT</span>
          </div>
          <div className="top-nav-links">
            <button className="nav-link active">{t("nav.claims")}</button>
            <button className="nav-link" onClick={() => window.open("/tpa", "_self")}>{t("nav.tpaPortal")}</button>
            <button className="nav-link" onClick={() => window.open("/tpa/analytics", "_self")}>{t("nav.analytics")}</button>
            {hasRole("admin") && (
              <button className="nav-link nav-link-admin" onClick={() => window.open("/admin/users", "_self")} title={t("profile.adminConsole")}>
                {t("nav.admin")}
              </button>
            )}
          </div>
        </div>
        <div className="top-nav-right">
          {/* Search / command palette */}
          <button className="cmd-trigger" onClick={() => setCmdOpen(true)} title="Search & quick actions (⌘K)">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
            <span className="cmd-trigger-text">{t("nav.search")}</span>
            <kbd className="cmd-kbd">⌘K</kbd>
          </button>

          {/* Language */}
          <LanguageSwitcher />

          {/* Notifications */}
          <div className="notif-wrap">
            <button
              className="icon-btn notif-btn"
              onClick={() => { setNotifOpen((v) => !v); setUserMenuOpen(false); }}
              title="Notifications"
              aria-label="Notifications"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>
              {notifBreachCount > 0 && <span className="notif-dot">{notifBreachCount > 9 ? "9+" : notifBreachCount}</span>}
            </button>
            {notifOpen && (
              <div className="dropdown-panel notif-panel">
                <div className="dropdown-head">
                  <span className="dropdown-title">{t("notif.title")}</span>
                  <span className="dropdown-sub">{notifications.length} {t("notif.updates")}</span>
                </div>
                <div className="dropdown-body">
                  {notifications.length === 0 ? (
                    <div className="dropdown-empty">
                      <span className="dropdown-empty-icon">🎉</span>
                      <span>{t("notif.empty")}</span>
                    </div>
                  ) : notifications.map((n) => (
                    <button
                      key={n.id}
                      className={`notif-item notif-${n.type}`}
                      onClick={() => {
                        if (n.claimId) {
                          setActiveClaim(n.claimId);
                          setMessages([]);
                        }
                        setNotifOpen(false);
                      }}
                    >
                      <span className="notif-icon">{n.type === "breach" ? "🚨" : n.type === "action" ? "⚠️" : n.type === "success" ? "✅" : "ℹ️"}</span>
                      <div className="notif-content">
                        <div className="notif-title-row">
                          <span className="notif-title">{n.title}</span>
                          <span className="notif-time">{n.time}</span>
                        </div>
                        <span className="notif-body">{n.body}</span>
                      </div>
                    </button>
                  ))}
                </div>
                <div className="dropdown-foot">
                  <button className="dropdown-link" onClick={() => { setStatusFilter("ACTION"); setNotifOpen(false); }}>{t("notif.viewAll")}</button>
                </div>
              </div>
            )}
          </div>

          {/* User profile card */}
          <div className="user-menu-wrap">
            <span
              className="user-menu-trigger"
              onClick={() => { setUserMenuOpen((v) => !v); setNotifOpen(false); }}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setUserMenuOpen((v) => !v); setNotifOpen(false); } }}
              role="button"
              tabIndex={0}
              title={t("nav.account")}
            >
              <UserAvatarDisplay size={32} />
            </span>
            {userMenuOpen && (() => {
              /* Derive presentation data from the authenticated user. */
              const ROLE_ORDER = ["admin", "approver", "checker", "reviewer", "submitter", "viewer"];
              const knownRoles = (user?.roles || []).filter((r) => ROLE_ORDER.includes(r))
                .sort((a, b) => ROLE_ORDER.indexOf(a) - ROLE_ORDER.indexOf(b));
              const primary = knownRoles[0] || "viewer";
              const ROLE_LABEL: Record<string, string> = {
                admin: "Administrator", approver: "Approver", checker: "Checker",
                reviewer: "Reviewer", submitter: "Submitter", viewer: "Viewer",
              };
              const ROLE_DESC: Record<string, string> = {
                admin: "Full access · manage users, integrations, overrides",
                approver: "Authorises settlements (final sign-off)",
                checker: "Validates reviewer decisions before payout",
                reviewer: "Approve / reject / send back claims",
                submitter: "Upload and submit claims",
                viewer: "Read-only dashboard access",
              };
              const displayName = user?.name || user?.preferred_username || user?.email?.split("@")[0] || "Reviewer";
              const handle = user?.preferred_username || user?.email || "";
              const orgDomain = user?.email?.split("@")[1] || "claimgpt.in";

              /* Quick stats sourced from the loaded claim list. */
              const myCount = claims.length;
              const approvedCt = claims.filter((c) => ["APPROVED", "COMPLETED", "SUBMITTED"].includes(c.status)).length;
              const approvalRate = myCount ? Math.round((approvedCt / myCount) * 100) : 0;
              const breachCt = claims.filter((c) => {
                const ageH = (Date.now() - new Date(c.created_at).getTime()) / 3_600_000;
                return ageH > 24 && !["APPROVED", "COMPLETED", "REJECTED", "SETTLED"].includes(c.status);
              }).length;

              return (
                <div className="dropdown-panel user-menu-panel user-profile-card" role="dialog" aria-label="Profile card">
                  {/* Header: avatar + name + role chips */}
                  <div className="user-profile-head">
                    <div className="user-profile-cover" />
                    <UserAvatarDisplay size={64} />
                    <div className="user-profile-identity">
                      <span className="user-profile-name">{displayName}</span>
                      <span className="user-profile-handle">{handle}</span>
                      <div className="user-profile-rolechips">
                        {knownRoles.length === 0 && (
                          <span className="user-profile-rolechip user-profile-rolechip-viewer">Viewer</span>
                        )}
                        {knownRoles.map((r) => (
                          <span key={r} className={`user-profile-rolechip user-profile-rolechip-${r}`} title={ROLE_DESC[r]}>
                            {ROLE_LABEL[r]}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>

                  {/* Org meta */}
                  <div className="user-profile-meta">
                    <div className="user-profile-meta-item">
                      <span className="user-profile-meta-label">{t("profile.organisation")}</span>
                      <span className="user-profile-meta-value">{orgDomain}</span>
                    </div>
                    <div className="user-profile-meta-item">
                      <span className="user-profile-meta-label">{t("profile.hub")}</span>
                      <span className="user-profile-meta-value">Mumbai · IN</span>
                    </div>
                    <div className="user-profile-meta-item">
                      <span className="user-profile-meta-label">{t("profile.primaryRole")}</span>
                      <span className="user-profile-meta-value">{ROLE_LABEL[primary]}</span>
                    </div>
                  </div>

                  {/* Live workload stats */}
                  <div className="user-profile-stats">
                    <div className="user-profile-stat">
                      <span className="user-profile-stat-value">{myCount}</span>
                      <span className="user-profile-stat-label">{t("profile.inView")}</span>
                    </div>
                    <div className="user-profile-stat">
                      <span className="user-profile-stat-value user-profile-stat-good">{approvalRate}%</span>
                      <span className="user-profile-stat-label">{t("profile.approved")}</span>
                    </div>
                    <div className="user-profile-stat">
                      <span className={`user-profile-stat-value ${breachCt > 0 ? "user-profile-stat-bad" : "user-profile-stat-good"}`}>{breachCt}</span>
                      <span className="user-profile-stat-label">{t("profile.slaBreaches")}</span>
                    </div>
                  </div>

                  {/* Quick actions */}
                  <div className="user-profile-actions">
                    <button className="user-profile-action" onClick={() => setUserMenuOpen(false)}>
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
                      {t("profile.myProfile")}
                    </button>
                    <button className="user-profile-action" onClick={() => { setDensity(d => d === "comfortable" ? "compact" : "comfortable"); setUserMenuOpen(false); }}>
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
                      {t("profile.density")} · <strong>{density === "comfortable" ? t("profile.comfortable") : t("profile.compact")}</strong>
                    </button>
                    <button className="user-profile-action" onClick={() => { setShortcutsOpen(true); setUserMenuOpen(false); }}>
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M6 8h.01M10 8h.01M14 8h.01M18 8h.01M8 12h.01M12 12h.01M16 12h.01M7 16h10"/></svg>
                      {t("profile.shortcuts")}
                      <kbd className="user-menu-kbd">?</kbd>
                    </button>
                    <button className="user-profile-action" onClick={() => setUserMenuOpen(false)}>
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
                      {t("profile.preferences")}
                    </button>
                  </div>

                  {/* Admin shortcuts (gated) */}
                  {hasRole("admin") && (
                    <div className="user-profile-admin">
                      <div className="user-profile-section-label">{t("profile.adminConsole")}</div>
                      <a className="user-profile-action user-profile-action-admin" href="/admin/users">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
                        {t("profile.usersAndRoles")}
                      </a>
                      <a className="user-profile-action user-profile-action-admin" href="/admin/integrations">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
                        {t("profile.integrations")}
                      </a>
                    </div>
                  )}

                  {/* Sign out */}
                  <div className="user-profile-foot">
                    <button className="user-profile-signout" onClick={() => logout?.()}>
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
                      {t("profile.signOut")}
                    </button>
                  </div>
                </div>
              );
            })()}
          </div>
        </div>
      </nav>

      {/* ── B2B: Command Palette (⌘K) ── */}
      {cmdOpen && (
        <div className="cmd-overlay" onClick={() => setCmdOpen(false)}>
          <div className="cmd-modal" onClick={(e) => e.stopPropagation()}>
            <div className="cmd-input-row">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
              <input
                className="cmd-input"
                placeholder="Search claims, run actions, jump to pages…"
                value={cmdQuery}
                onChange={(e) => setCmdQuery(e.target.value)}
                autoFocus
              />
              <kbd className="cmd-kbd">esc</kbd>
            </div>
            <div className="cmd-results">
              {cmdClaimMatches.length > 0 && (
                <div className="cmd-group">
                  <div className="cmd-group-label">Claims</div>
                  {cmdClaimMatches.map((c) => (
                    <button
                      key={c.id}
                      className="cmd-item"
                      onClick={() => { setActiveClaim(c.id); setMessages([]); setCmdOpen(false); setCmdQuery(""); }}
                    >
                      <span className="cmd-item-icon">📋</span>
                      <div className="cmd-item-body">
                        <span className="cmd-item-label">{claimNames[c.id] || `Claim ${shortClaimId(c.id)}`}</span>
                        <span className="cmd-item-sub">#{shortClaimId(c.id)} · {c.status}{c.patient_id ? ` · ${c.patient_id}` : ""}</span>
                      </div>
                    </button>
                  ))}
                </div>
              )}
              {(["Actions", "Navigate", "Filter", "Preferences", "Help"] as const).map((group) => {
                const items = cmdFiltered.filter((i) => i.group === group);
                if (items.length === 0) return null;
                return (
                  <div key={group} className="cmd-group">
                    <div className="cmd-group-label">{group}</div>
                    {items.map((i) => (
                      <button key={i.id} className="cmd-item" onClick={i.action}>
                        <span className="cmd-item-icon">{i.icon}</span>
                        <div className="cmd-item-body">
                          <span className="cmd-item-label">{i.label}</span>
                        </div>
                        {i.hint && <kbd className="cmd-item-hint">{i.hint}</kbd>}
                      </button>
                    ))}
                  </div>
                );
              })}
              {cmdFiltered.length === 0 && cmdClaimMatches.length === 0 && (
                <div className="cmd-empty">No results for &ldquo;{cmdQuery}&rdquo;</div>
              )}
            </div>
            <div className="cmd-foot">
              <span><kbd>↑</kbd><kbd>↓</kbd> Navigate</span>
              <span><kbd>↵</kbd> Select</span>
              <span><kbd>esc</kbd> Close</span>
              <span className="cmd-foot-spacer" />
              <span className="cmd-foot-brand">ClaimGPT Command</span>
            </div>
          </div>
        </div>
      )}

      {/* ── B2B: Keyboard Shortcuts Modal ── */}
      {shortcutsOpen && (
        <div className="modal-overlay" onClick={() => setShortcutsOpen(false)}>
          <div className="shortcut-modal" onClick={(e) => e.stopPropagation()}>
            <div className="shortcut-head">
              <h3>Keyboard Shortcuts</h3>
              <button className="icon-btn" onClick={() => setShortcutsOpen(false)} aria-label="Close">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </button>
            </div>
            <div className="shortcut-body">
              {[
                { group: "General", items: [
                  { keys: ["⌘", "K"], label: "Open command palette" },
                  { keys: ["?"], label: "Show this help" },
                  { keys: ["esc"], label: "Close any modal" },
                  { keys: ["⌘", "/"], label: "Toggle density (compact / comfortable)" },
                ]},
                { group: "Claims Queue", items: [
                  { keys: ["⌘", "K"], label: "Search across claims, codes, patients" },
                  { keys: ["A"], label: "Show all claims" },
                  { keys: ["P"], label: "Filter to in-pipeline" },
                  { keys: ["R"], label: "Filter to ready for review" },
                ]},
                { group: "Review", items: [
                  { keys: ["⌘", "↵"], label: "Submit / send chat message" },
                  { keys: ["⌘", "U"], label: "Upload document" },
                ]},
              ].map((sec) => (
                <div key={sec.group} className="shortcut-group">
                  <h4>{sec.group}</h4>
                  <ul>
                    {sec.items.map((it) => (
                      <li key={it.label}>
                        <span>{it.label}</span>
                        <span className="shortcut-keys">
                          {it.keys.map((k, idx) => <kbd key={idx}>{k}</kbd>)}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ── Content Row (Sidebar + Main) ── */}
      <div className={`app-content density-${density}`}>

      {/* ── Preview Modal ── */}
      {showPreview && preview && (
        <div className="modal-overlay" onClick={() => setShowPreview(false)}>
          <div className="modal-content brain-modal" onClick={(e) => e.stopPropagation()}>
            {/* Brain Header */}
            <div className="brain-header">
              <div className="brain-header-bar" />
              <div className="brain-header-content">
                <div className="brain-title-row">
                  <div className="brain-title-left">
                    <h2 className="brain-title">
                      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2a10 10 0 0 1 10 10c0 5.523-4.477 10-10 10S2 17.523 2 12 6.477 2 12 2Z"/><path d="M12 6v6l4 2"/></svg>
                      ClaimGPT Brain Report
                    </h2>
                    <p className="brain-subtitle">Comprehensive AI Analysis &middot; Generated {new Date().toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}</p>
                  </div>
                  <div className="brain-meta">
                    <span className="brain-claim-id">#{preview.claim_id.slice(0, 8)}</span>
                    <span className={`brain-status ${(preview.status || "").toLowerCase()}`}>{preview.status}</span>
                    <span className={`brain-verdict ${verdictLabel(preview.summary.risk_score).cls}`}>
                      {verdictLabel(preview.summary.risk_score).text}
                    </span>
                  </div>
                </div>
                <button className="modal-close" onClick={() => setShowPreview(false)}>×</button>
              </div>
            </div>

            <div className="modal-body brain-body">

              {/* KPI Strip */}
              <div className="brain-kpi-strip">
                <div className="brain-kpi kpi-risk">
                  <span className="brain-kpi-icon">⚡</span>
                  <span className="brain-kpi-value" style={{ color: riskColor(preview.summary.risk_score) }}>
                    {preview.summary.risk_score !== null ? `${(preview.summary.risk_score * 100).toFixed(0)}%` : "N/A"}
                  </span>
                  <span className="brain-kpi-label">Risk Score</span>
                </div>
                <div className="brain-kpi kpi-codes">
                  <span className="brain-kpi-icon">🏥</span>
                  <span className="brain-kpi-value">{preview.summary.icd_count + preview.summary.cpt_count}</span>
                  <span className="brain-kpi-label">Medical Codes</span>
                </div>
                <div className="brain-kpi kpi-rules">
                  <span className="brain-kpi-icon">✓</span>
                  <span className="brain-kpi-value">{preview.summary.validation_passed}/{preview.summary.validation_total}</span>
                  <span className="brain-kpi-label">Rules Passed</span>
                </div>
                <div className="brain-kpi kpi-cost">
                  <span className="brain-kpi-icon">₹</span>
                  <span className="brain-kpi-value brain-kpi-cost-val">
                    {preview.billed_total ? `Rs. ${preview.billed_total.toLocaleString("en-IN")}` : preview.cost_summary ? `Rs. ${preview.cost_summary.grand_total.toLocaleString("en-IN")}` : "N/A"}
                  </span>
                  <span className="brain-kpi-label">{preview.billed_total ? "Billed Total" : "Est. Total Cost"}</span>
                </div>
                <div className="brain-kpi kpi-fields">
                  <span className="brain-kpi-icon">📋</span>
                  <span className="brain-kpi-value">{Object.keys(preview.parsed_fields).length}</span>
                  <span className="brain-kpi-label">Fields Extracted</span>
                </div>
              </div>

              {/* ─── Section: Patient & Claim Details ─── */}
              <div className="brain-section">
                <h3 className="brain-section-toggle" onClick={() => toggleSection("patient")}>
                  <span>📋 Patient & Claim Details {fieldsSaved && <span className="fields-saved-badge">✅ Saved</span>}</span>
                  <span className={`section-chevron ${collapsedSections["patient"] ? "collapsed" : ""}`}>▾</span>
                </h3>
                {!collapsedSections["patient"] && (
                  <>
                    <div className="preview-grid">
                      <div className="preview-field">
                        <span className="label">Patient</span>
                        <input className="field-input" value={editedFields.patient_name || ""} onChange={(e) => setEditedFields(f => ({...f, patient_name: e.target.value}))} />
                      </div>
                      <div className="preview-field">
                        <span className="label">Age / Gender</span>
                        <div className="field-row-split">
                          <input className="field-input field-input-sm" value={editedFields.age || ""} onChange={(e) => setEditedFields(f => ({...f, age: e.target.value}))} placeholder="Age" />
                          <input className="field-input field-input-sm" value={editedFields.gender || ""} onChange={(e) => setEditedFields(f => ({...f, gender: e.target.value}))} placeholder="Gender" />
                        </div>
                      </div>
                      <div className="preview-field">
                        <span className="label">Hospital</span>
                        <input className="field-input" value={editedFields.hospital || ""} onChange={(e) => setEditedFields(f => ({...f, hospital: e.target.value}))} />
                      </div>
                      <div className="preview-field">
                        <span className="label">Doctor</span>
                        <input className="field-input" value={editedFields.doctor || ""} onChange={(e) => setEditedFields(f => ({...f, doctor: e.target.value}))} />
                      </div>
                      <div className="preview-field">
                        <span className="label">Admission</span>
                        <input className="field-input" value={editedFields.admission_date || ""} onChange={(e) => setEditedFields(f => ({...f, admission_date: e.target.value}))} />
                      </div>
                      <div className="preview-field">
                        <span className="label">Discharge</span>
                        <input className="field-input" value={editedFields.discharge_date || ""} onChange={(e) => setEditedFields(f => ({...f, discharge_date: e.target.value}))} />
                      </div>
                      <div className="preview-field preview-field-wide">
                        <span className="label">Diagnosis</span>
                        <input className="field-input" value={editedFields.diagnosis || ""} onChange={(e) => setEditedFields(f => ({...f, diagnosis: e.target.value}))} />
                      </div>
                      <div className="preview-field">
                        <span className="label">Billed Amount</span>
                        <div className="field-amount-wrap">
                          <span className="field-rs">Rs.</span>
                          <input className="field-input" value={editedFields.total_amount || ""} onChange={(e) => setEditedFields(f => ({...f, total_amount: e.target.value}))} />
                        </div>
                      </div>
                    </div>
                    <div className="field-save-bar">
                      <button className="btn-primary field-save-btn" disabled={fieldsSaving} onClick={saveEditedFields}>
                        {fieldsSaving ? "⏳ Saving..." : "💾 Save Changes"}
                      </button>
                      {fieldsSaved && <span className="field-save-msg">Changes saved — PDF will reflect updates</span>}
                    </div>
                  </>
                )}
              </div>

              {/* ─── Section: AI Brain Insights ─── */}
              {preview.brain_insights && preview.brain_insights.length > 0 && (
                <div className="brain-section brain-insights-section">
                  <h3 className="brain-section-toggle" onClick={() => toggleSection("insights")}>
                    <span>🧠 AI Brain Insights <span className="count-badge">{preview.brain_insights.length}</span></span>
                    <span className={`section-chevron ${collapsedSections["insights"] ? "collapsed" : ""}`}>▾</span>
                  </h3>
                  {!collapsedSections["insights"] && (
                    <div className="brain-insights-list">
                      {preview.brain_insights.map((insight, i) => {
                        const tag = insight.match(/^\[([A-Z]+)\]/)?.[1] || "INFO";
                        const text = insight.replace(/^\[[A-Z]+\]\s*/, "");
                        const tagClass = tag === "ALERT" ? "brain-tag-alert" : tag === "RISK" ? "brain-tag-risk" : tag === "CODING" ? "brain-tag-coding" : tag === "COST" ? "brain-tag-cost" : tag === "VALIDATION" ? "brain-tag-validation" : "brain-tag-info";
                        return (
                          <div key={i} className="brain-insight-row">
                            <span className={`brain-tag ${tagClass}`}>{tag}</span>
                            <span className="brain-insight-text">{text}</span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}

              {/* ─── Section: Hospital Expense Breakdown ─── */}
              {preview.expenses && preview.expenses.length > 0 && (
                <div className="brain-section">
                  <h3 className="brain-section-toggle" onClick={() => toggleSection("expenses")}>
                    <span>🏥 Hospital Expense Breakdown <span className="count-badge">{preview.expenses.length} items</span></span>
                    <span className={`section-chevron ${collapsedSections["expenses"] ? "collapsed" : ""}`}>▾</span>
                  </h3>
                  {!collapsedSections["expenses"] && (
                    <>
                      <table className="code-table expense-table">
                        <thead><tr><th>#</th><th>Expense Category</th><th style={{ textAlign: "right" }}>Amount (INR)</th></tr></thead>
                        <tbody>
                          {preview.expenses.map((e, i) => (
                            <tr key={i}>
                              <td style={{ color: "var(--text-muted)", fontSize: 11 }}>{i + 1}</td>
                              <td>{e.category}</td>
                              <td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>Rs. {e.amount.toLocaleString("en-IN")}</td>
                            </tr>
                          ))}
                          <tr className="expense-total-row">
                            <td></td>
                            <td style={{ fontWeight: 700 }}>Itemised Total</td>
                            <td style={{ textAlign: "right", fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>Rs. {(preview.expense_total || 0).toLocaleString("en-IN")}</td>
                          </tr>
                          {preview.billed_total != null && preview.billed_total > 0 && (
                            <tr className="expense-billed-row">
                              <td></td>
                              <td style={{ fontWeight: 700, color: "var(--accent)" }}>Billed Total (from document)</td>
                              <td style={{ textAlign: "right", fontWeight: 700, color: "var(--accent)", fontVariantNumeric: "tabular-nums" }}>Rs. {preview.billed_total.toLocaleString("en-IN")}</td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                      {preview.expense_total != null && preview.billed_total != null && preview.billed_total > 0 && Math.abs(preview.billed_total - preview.expense_total) > 100 && (
                        <div className="expense-mismatch-alert">
                          ⚠️ Itemised total (Rs. {preview.expense_total.toLocaleString("en-IN")}) differs from billed total (Rs. {preview.billed_total.toLocaleString("en-IN")}) by Rs. {Math.abs(preview.billed_total - preview.expense_total).toLocaleString("en-IN")}
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}

              {/* ─── Section: Cross-Document Reimbursement Intelligence ─── */}
              {preview.reimbursement_brain && (preview.reimbursement_brain.documents_analyzed?.length > 0 || preview.reimbursement_brain.insights?.length > 0) && (
                <div className="brain-section reimburse-brain-section">
                  <h3 className="brain-section-toggle" onClick={() => toggleSection("reimburse")}>
                    <span>
                      🔗 Cross-Document Reimbursement Intelligence
                      {preview.reimbursement_brain.completeness_pct != null && (
                        <span className={`reimburse-score-badge ${preview.reimbursement_brain.completeness_pct >= 80 ? "reimburse-score-good" : preview.reimbursement_brain.completeness_pct >= 50 ? "reimburse-score-ok" : "reimburse-score-low"}`}>
                          {preview.reimbursement_brain.completeness_pct}% Ready
                        </span>
                      )}
                    </span>
                    <span className={`section-chevron ${collapsedSections["reimburse"] ? "collapsed" : ""}`}>▾</span>
                  </h3>
                  {!collapsedSections["reimburse"] && (
                    <>
                      {/* Completeness bar */}
                      {preview.reimbursement_brain.completeness_pct != null && (
                        <div className="reimburse-completeness">
                          <div className="reimburse-completeness-track">
                            <div
                              className="reimburse-completeness-fill"
                              style={{
                                width: `${preview.reimbursement_brain.completeness_pct}%`,
                                backgroundColor: preview.reimbursement_brain.completeness_pct >= 80 ? "#22c55e" : preview.reimbursement_brain.completeness_pct >= 50 ? "#eab308" : "#ef4444",
                              }}
                            />
                          </div>
                          <span className="reimburse-completeness-label">Reimbursement Readiness</span>
                        </div>
                      )}

                      {/* Documents analyzed */}
                      {preview.reimbursement_brain.documents_analyzed.length > 0 && (
                        <div className="reimburse-docs-grid">
                          <div className="reimburse-docs-title">📁 Documents Analyzed ({preview.reimbursement_brain.documents_analyzed.length})</div>
                          {preview.reimbursement_brain.documents_analyzed.map((da, i) => (
                            <div key={i} className="reimburse-doc-card">
                              <span className="reimburse-doc-type-badge">{da.doc_type}</span>
                              <span className="reimburse-doc-name">{da.file_name}</span>
                              <span className="reimburse-doc-fields">{Object.keys(da.fields_found).length} fields extracted</span>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Cross-references */}
                      {preview.reimbursement_brain.cross_references.length > 0 && (
                        <div className="reimburse-xref-section">
                          <div className="reimburse-xref-title">🔍 Cross-Document Verification</div>
                          {preview.reimbursement_brain.cross_references.map((xr, i) => (
                            <div key={i} className={`reimburse-xref-row reimburse-xref-${xr.status}`}>
                              <span className={`reimburse-xref-status ${xr.status === "match" ? "reimburse-xref-ok" : "reimburse-xref-warn"}`}>
                                {xr.status === "match" ? "✓" : "⚠"}
                              </span>
                              <span className="reimburse-xref-field">{xr.field}</span>
                              <div className="reimburse-xref-sources">
                                {xr.sources.map((src, si) => (
                                  <span key={si} className="reimburse-xref-source">
                                    <em>{src.doc_type}:</em> {src.value}
                                  </span>
                                ))}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Reimbursement checklist */}
                      {preview.reimbursement_brain.reimbursement_checklist.length > 0 && (
                        <div className="reimburse-checklist">
                          <div className="reimburse-checklist-title">✅ Reimbursement Checklist</div>
                          <div className="reimburse-checklist-grid">
                            {preview.reimbursement_brain.reimbursement_checklist.map((item, i) => (
                              <div key={i} className={`reimburse-check-item reimburse-check-${item.status}`}>
                                <span className="reimburse-check-icon">{item.status === "present" ? "✅" : "❌"}</span>
                                <span className="reimburse-check-name">{item.item}</span>
                                <span className="reimburse-check-reason">{item.reason}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Insights */}
                      {preview.reimbursement_brain.insights.length > 0 && (
                        <div className="reimburse-insights">
                          <div className="reimburse-insights-title">💡 Cross-Document Insights</div>
                          {preview.reimbursement_brain.insights.map((ins, i) => (
                            <div key={i} className={`reimburse-insight-row reimburse-insight-${ins.type}`}>
                              <span className={`reimburse-insight-icon`}>
                                {ins.type === "match" ? "✓" : ins.type === "mismatch" ? "⚠" : "ℹ"}
                              </span>
                              <span className="reimburse-insight-cat">{ins.category}</span>
                              <span className="reimburse-insight-text">{ins.text}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}

              {/* ─── Section: Medical Imaging ─── */}
              {preview.scan_analyses && preview.scan_analyses.length > 0 && (
                <div className="brain-section scan-analysis-section">
                  <h3 className="brain-section-toggle" onClick={() => toggleSection("scans")}>
                    <span>🩻 Medical Imaging Analysis <span className="count-badge">{preview.scan_analyses.length}</span></span>
                    <span className={`section-chevron ${collapsedSections["scans"] ? "collapsed" : ""}`}>▾</span>
                  </h3>
                  {!collapsedSections["scans"] && preview.scan_analyses.map((scan, si) => (
                    <div key={si} className={`scan-card${scan.is_abnormal ? " scan-abnormal" : ""}`}>
                      <div className="scan-card-header">
                        <span className="scan-type-badge">{scan.scan_type}</span>
                        <span className="scan-body-part">{scan.body_part}</span>
                        {scan.modality && <span className="scan-modality">{scan.modality}</span>}
                        <span className={`scan-status-badge ${scan.is_abnormal ? "scan-status-abnormal" : "scan-status-normal"}`}>
                          {scan.is_abnormal ? "⚠ Abnormal" : "✓ Normal"}
                        </span>
                      </div>
                      {scan.file_name && (
                        <div className="scan-file-name">📁 {scan.file_name}</div>
                      )}
                      {scan.findings.length > 0 && (
                        <div className="scan-findings">
                          <div className="scan-findings-title">Findings</div>
                          {scan.findings.map((f, fi) => (
                            <div key={fi} className={`scan-finding-item scan-sev-${f.severity}`}>
                              <span className="scan-finding-dot" />
                              <span className="scan-finding-text">{f.finding}</span>
                              <span className="scan-finding-conf">{(f.confidence * 100).toFixed(0)}%</span>
                            </div>
                          ))}
                        </div>
                      )}
                      {scan.impression && (
                        <div className="scan-impression">
                          <strong>Impression:</strong> {scan.impression}
                        </div>
                      )}
                      {scan.recommendation && (
                        <div className="scan-recommendation">
                          <strong>Recommendation:</strong> {scan.recommendation}
                        </div>
                      )}
                      <div className="scan-confidence-bar">
                        <span className="scan-conf-label">Analysis Confidence</span>
                        <div className="scan-conf-track">
                          <div className="scan-conf-fill" style={{ width: `${(scan.confidence * 100)}%` }} />
                        </div>
                        <span className="scan-conf-value">{(scan.confidence * 100).toFixed(0)}%</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* ─── Section: Risk Assessment ─── */}
              {preview.summary.risk_score !== null && (
                <div className="brain-section">
                  <h3 className="brain-section-toggle" onClick={() => toggleSection("risk")}>
                    <span>📊 AI Risk Assessment</span>
                    <span className={`section-chevron ${collapsedSections["risk"] ? "collapsed" : ""}`}>▾</span>
                  </h3>
                  {!collapsedSections["risk"] && (
                    <>
                      <div className="brain-risk-row">
                        <div className="brain-risk-meter">
                          <div className="brain-risk-bar" style={{ width: `${Math.min((preview.summary.risk_score || 0) * 100, 100)}%`, backgroundColor: riskColor(preview.summary.risk_score) }} />
                        </div>
                        <span className="brain-risk-score" style={{ color: riskColor(preview.summary.risk_score) }}>
                          {(preview.summary.risk_score * 100).toFixed(0)}%
                        </span>
                        <span className="brain-risk-label">
                          {preview.summary.risk_score <= 0.3 ? "LOW RISK" : preview.summary.risk_score <= 0.6 ? "MODERATE" : "HIGH RISK"}
                        </span>
                      </div>
                      {preview.predictions?.[0]?.top_reasons && (
                        <div className="brain-risk-factors">
                          {preview.predictions[0].top_reasons.map((r, i: number) => (
                            <div key={i} className="brain-risk-factor">
                              <span className="brain-rf-dot" style={{ backgroundColor: r.weight >= 0.12 ? "#ef4444" : r.weight >= 0.08 ? "#eab308" : "#94a3b8" }} />
                              <span>{r.reason}</span>
                              {r.weight > 0 && <span className="brain-rf-weight">{(r.weight * 100).toFixed(0)}%</span>}
                            </div>
                          ))}
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}

              {/* ─── Section: ICD-10 Codes ─── */}
              {preview.icd_codes.length > 0 && (
                <div className="brain-section">
                  <h3 className="brain-section-toggle" onClick={() => toggleSection("icd")}>
                    <span>🔬 ICD-10 Codes — Diagnosis <span className="count-badge">{preview.icd_codes.length}</span></span>
                    <span className={`section-chevron ${collapsedSections["icd"] ? "collapsed" : ""}`}>▾</span>
                  </h3>
                  {!collapsedSections["icd"] && (
                    <table className="code-table">
                      <thead><tr><th>#</th><th>Code</th><th>Description</th><th>Est. Cost</th><th>Confidence</th><th>Action</th></tr></thead>
                      <tbody>
                        {preview.icd_codes.map((c, i) => (
                          <tr key={i}>
                            <td style={{ color: "var(--text-muted)", fontSize: 11 }}>{i + 1}</td>
                            <td className="code-cell">{c.code}</td>
                            <td>{c.description}</td>
                            <td className="cost-cell">{c.estimated_cost != null ? `Rs. ${c.estimated_cost.toLocaleString("en-IN")}` : "—"}</td>
                            <td><span className={`conf-badge ${confClass(c.confidence)}`}>{c.confidence ? `${(c.confidence * 100).toFixed(0)}%` : "N/A"}</span></td>
                            <td className="action-cell">
                              <button className="fb-btn fb-accept" onClick={() => sendCodeFeedback(c.code, "accept")} title="Accept">&#10003;</button>
                              <button className="fb-btn fb-reject" onClick={() => sendCodeFeedback(c.code, "reject")} title="Reject">&#10007;</button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              )}

              {/* ─── Section: CPT Codes ─── */}
              {preview.cpt_codes.length > 0 && (
                <div className="brain-section">
                  <h3 className="brain-section-toggle" onClick={() => toggleSection("cpt")}>
                    <span>⚕️ CPT Codes — Procedures <span className="count-badge">{preview.cpt_codes.length}</span></span>
                    <span className={`section-chevron ${collapsedSections["cpt"] ? "collapsed" : ""}`}>▾</span>
                  </h3>
                  {!collapsedSections["cpt"] && (
                    <table className="code-table">
                      <thead><tr><th>#</th><th>Code</th><th>Description</th><th>Est. Cost</th><th>Confidence</th><th>Action</th></tr></thead>
                      <tbody>
                        {preview.cpt_codes.map((c, i) => (
                          <tr key={i}>
                            <td style={{ color: "var(--text-muted)", fontSize: 11 }}>{i + 1}</td>
                            <td className="code-cell">{c.code}</td>
                            <td>{c.description}</td>
                            <td className="cost-cell">{c.estimated_cost != null ? `Rs. ${c.estimated_cost.toLocaleString("en-IN")}` : "—"}</td>
                            <td><span className={`conf-badge ${confClass(c.confidence)}`}>{c.confidence ? `${(c.confidence * 100).toFixed(0)}%` : "N/A"}</span></td>
                            <td className="action-cell">
                              <button className="fb-btn fb-accept" onClick={() => sendCodeFeedback(c.code, "accept")} title="Accept">&#10003;</button>
                              <button className="fb-btn fb-reject" onClick={() => sendCodeFeedback(c.code, "reject")} title="Reject">&#10007;</button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              )}

              {/* ─── Section: Validation Rules ─── */}
              {preview.validations.length > 0 && (
                <div className="brain-section">
                  <h3 className="brain-section-toggle" onClick={() => toggleSection("validations")}>
                    <span>✅ Validation Rules <span className="count-badge">{preview.summary.validation_passed}/{preview.summary.validation_total} passed</span></span>
                    <span className={`section-chevron ${collapsedSections["validations"] ? "collapsed" : ""}`}>▾</span>
                  </h3>
                  {!collapsedSections["validations"] && (
                    <div className="validation-list">
                      {preview.validations.map((v, i) => (
                        <div key={i} className={`validation-item ${v.passed ? "val-pass" : "val-fail"}`}>
                          <span className="val-icon">{v.passed ? "\u2705" : "\u274c"}</span>
                          <span className="val-name">{v.rule_name}</span>
                          <span className="val-msg">{v.message}</span>
                          <span className={`val-sev val-sev-${v.severity.toLowerCase()}`}>{v.severity}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* ─── Sticky Action Footer ─── */}
              <div className="brain-actions-footer">
                <div className="brain-actions-left">
                  <span className="brain-footer-meta">
                    {preview.summary.icd_count + preview.summary.cpt_count} codes &middot; {preview.validations.length} rules &middot; {Object.keys(preview.parsed_fields).length} fields
                  </span>
                </div>
                <div className="brain-actions-right">
                  <button className="btn-secondary" onClick={() => setShowPreview(false)}>
                    Close
                  </button>
                  <button
                    className="btn-tpa brain-pdf-btn"
                    disabled={pdfLoading}
                    onClick={async () => {
                      const url = `${SUBMISSION_API}/claims/${preview.claim_id}/tpa-pdf`;
                      setPdfDownloadUrl(url);
                      setPdfLoading(true);
                      setPdfKind("tpa");
                      try {
                        const resp = await fetch(url, { headers: authHeaders() });
                        const blob = await resp.blob();
                        const blobUrl = URL.createObjectURL(blob);
                        setPdfPreviewUrl(blobUrl);
                      } catch { setPdfPreviewUrl(null); }
                      setPdfLoading(false);
                    }}
                    title="TPA Claim Report — comprehensive summary with brain insights, expense breakdown, ICD/CPT codes, and reimbursement readiness checklist."
                  >
                    {pdfLoading ? (
                      <span className="btn-irda-inner">
                        <span className="btn-irda-spinner" aria-hidden="true" />
                        <span className="btn-irda-text">
                          <span className="btn-irda-title">Generating…</span>
                          <span className="btn-irda-sub">Building TPA report</span>
                        </span>
                      </span>
                    ) : (
                      <span className="btn-irda-inner">
                        <svg className="btn-irda-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                          <polyline points="7 10 12 15 17 10" />
                          <line x1="12" y1="15" x2="12" y2="3" />
                        </svg>
                        <span className="btn-irda-text">
                          <span className="btn-irda-title">Preview &amp; Download</span>
                          <span className="btn-irda-sub">TPA Claim Report · PDF</span>
                        </span>
                        <span className="btn-irda-badge">Brain</span>
                      </span>
                    )}
                  </button>
                  <button
                    className="btn-irda brain-pdf-btn"
                    disabled={irdaLoading}
                    onClick={async () => {
                      const url = `${SUBMISSION_API}/claims/${preview.claim_id}/irda-pdf`;
                      setPdfDownloadUrl(url);
                      setIrdaLoading(true);
                      setPdfKind("irda");
                      try {
                        const resp = await fetch(url, { headers: authHeaders() });
                        const blob = await resp.blob();
                        const blobUrl = URL.createObjectURL(blob);
                        setPdfPreviewUrl(blobUrl);
                      } catch { setPdfPreviewUrl(null); }
                      setIrdaLoading(false);
                    }}
                    title="IRDAI Standard Reimbursement Claim Form (Part A + Part B) — opens with editable text fields, radio buttons & checkboxes you can fill in any PDF reader, then save / print / sign."
                  >
                    {irdaLoading ? (
                      <span className="btn-irda-inner">
                        <span className="btn-irda-spinner" aria-hidden="true" />
                        <span className="btn-irda-text">
                          <span className="btn-irda-title">Generating…</span>
                          <span className="btn-irda-sub">Building IRDA form</span>
                        </span>
                      </span>
                    ) : (
                      <span className="btn-irda-inner">
                        <svg className="btn-irda-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                          <polyline points="14 2 14 8 20 8" />
                          <line x1="9" y1="13" x2="15" y2="13" />
                          <line x1="9" y1="17" x2="13" y2="17" />
                        </svg>
                        <span className="btn-irda-text">
                          <span className="btn-irda-title">IRDA Claim Form</span>
                          <span className="btn-irda-sub">Part A + B · Editable</span>
                        </span>
                        <span className="btn-irda-badge">70 fields</span>
                      </span>
                    )}
                  </button>
                  <a
                    className="btn-irda btn-irda-ghost brain-pdf-btn"
                    href={`${SUBMISSION_API}/claims/${preview.claim_id}/irda-pdf?blank=1`}
                    target="_blank"
                    rel="noopener noreferrer"
                    title="Download a blank IRDA form template (only patient & policy retained) — fill any field by clicking it in your PDF reader."
                  >
                    <span className="btn-irda-inner">
                      <svg className="btn-irda-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                        <rect x="4" y="3" width="16" height="18" rx="2" />
                        <line x1="8" y1="8" x2="16" y2="8" />
                        <line x1="8" y1="12" x2="16" y2="12" />
                        <line x1="8" y1="16" x2="12" y2="16" />
                      </svg>
                      <span className="btn-irda-text">
                        <span className="btn-irda-title">Blank IRDA Template</span>
                        <span className="btn-irda-sub">Print &amp; fill manually</span>
                      </span>
                    </span>
                  </a>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Rich PDF Generating Overlay ── */}
      {(pdfLoading || irdaLoading) && (() => {
        const isIrda = irdaLoading;
        const accent = isIrda ? "emerald" : "blue";
        const steps = isIrda
          ? [
              { label: "Collecting parsed claim fields", icon: "📋" },
              { label: "Composing IRDAI Part A + Part B", icon: "🗂️" },
              { label: "Embedding 70 editable AcroForm widgets", icon: "✏️" },
              { label: "Rendering with WeasyPrint", icon: "🎨" },
              { label: "Finalising fillable PDF", icon: "✅" },
            ]
          : [
              { label: "Aggregating claim data & validations", icon: "🔎" },
              { label: "Running reimbursement Brain analysis", icon: "🧠" },
              { label: "Building expense & code tables", icon: "📊" },
              { label: "Composing TPA report PDF", icon: "📄" },
              { label: "Optimising for delivery", icon: "📦" },
            ];
        return (
          <div className="pdf-gen-overlay" role="status" aria-live="polite" aria-busy="true">
            <div className={`pdf-gen-card pdf-gen-${accent}`}>
              <div className="pdf-gen-header">
                <div className="pdf-gen-orb">
                  <span className="pdf-gen-orb-ring" />
                  <span className="pdf-gen-orb-ring pdf-gen-orb-ring--2" />
                  <span className="pdf-gen-orb-core">{isIrda ? "📋" : "📄"}</span>
                </div>
                <div className="pdf-gen-titles">
                  <h3 className="pdf-gen-title">
                    {isIrda ? "Generating IRDA Claim Form" : "Generating TPA Report"}
                  </h3>
                  <p className="pdf-gen-sub">
                    {isIrda
                      ? "Building Part A + Part B with editable form widgets"
                      : "Aggregating claim data, brain insights, and codes"}
                  </p>
                </div>
              </div>

              <div className="pdf-gen-progress">
                <div className="pdf-gen-progress-bar">
                  <span className="pdf-gen-progress-fill" />
                </div>
              </div>

              <ul className="pdf-gen-steps">
                {steps.map((s, i) => (
                  <li
                    key={i}
                    className="pdf-gen-step"
                    style={{ animationDelay: `${i * 0.6}s` }}
                  >
                    <span className="pdf-gen-step-icon">{s.icon}</span>
                    <span className="pdf-gen-step-label">{s.label}</span>
                    <span className="pdf-gen-step-tick">✓</span>
                  </li>
                ))}
              </ul>

              <p className="pdf-gen-foot">
                Please keep this window open · usually finishes in&nbsp;1–3&nbsp;seconds
              </p>
            </div>
          </div>
        );
      })()}

      {/* ── PDF Preview Modal ── */}
      {pdfPreviewUrl && (
        <div className="modal-overlay pdf-preview-overlay" onClick={() => { URL.revokeObjectURL(pdfPreviewUrl); setPdfPreviewUrl(null); }}>
          <div className="pdf-preview-modal" onClick={(e) => e.stopPropagation()}>
            <div className="pdf-preview-header">
              <div className="pdf-preview-title">
                <span>{pdfKind === "irda" ? "📋" : "📄"}</span>
                <h3>{pdfKind === "irda" ? "IRDAI Standard Claim Form (Part A + B)" : "TPA Claim Report Preview"}</h3>
                {pdfKind === "irda" && (
                  <span
                    style={{
                      marginLeft: 10,
                      fontSize: "11px",
                      fontWeight: 600,
                      letterSpacing: "0.04em",
                      textTransform: "uppercase",
                      padding: "3px 8px",
                      borderRadius: 999,
                      background: "rgba(16,185,129,0.12)",
                      color: "#047857",
                      border: "1px solid rgba(16,185,129,0.35)",
                    }}
                    title="All text fields, radio buttons and checkboxes are editable in your PDF reader"
                  >
                    ✓ Editable fields
                  </span>
                )}
              </div>
              <div className="pdf-preview-actions">
                <a
                  className={`${pdfKind === "irda" ? "btn-irda" : "btn-tpa"} brain-pdf-btn`}
                  href={pdfPreviewUrl}
                  download={(() => {
                    const pf = preview?.parsed_fields || {};
                    const name = (pf.patient_name || pf.member_name || pf.insured_name || "").trim().replace(/\s+/g, "_");
                    const policy = (pf.policy_number || pf.policy_id || pf.policy_no || preview?.policy_id || "").trim().replace(/\s+/g, "_");
                    const prefix = pdfKind === "irda" ? "IRDA_ClaimForm_" : "";
                    if (name && policy) return `${prefix}${name}_${policy}.pdf`;
                    if (name) return `${prefix}${name}_Claim.pdf`;
                    if (policy) return `${prefix}Claim_${policy}.pdf`;
                    return `${prefix || "TPA_Claim_"}${preview?.claim_id?.slice(0, 8) || "report"}.pdf`;
                  })()}
                  title="Save the PDF to your device"
                >
                  <span className="btn-irda-inner">
                    <svg className="btn-irda-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                      <polyline points="7 10 12 15 17 10" />
                      <line x1="12" y1="15" x2="12" y2="3" />
                    </svg>
                    <span className="btn-irda-text">
                      <span className="btn-irda-title">Download PDF</span>
                      <span className="btn-irda-sub">{pdfKind === "irda" ? "IRDA · Editable" : "TPA · Brain Report"}</span>
                    </span>
                  </span>
                </a>
                <button
                  className="btn-tpa-send brain-pdf-btn"
                  onClick={async () => {
                    try {
                      const resp = await fetch(`${SUBMISSION_API}/tpa-list`, { headers: authHeaders() });
                      const data = await resp.json();
                      setTpaList(data.tpas || []);
                    } catch { setTpaList([]); }
                    setTpaSent(null);
                    setTpaSearch("");
                    setShowTpaModal(true);
                  }}
                  title="Forward this PDF to a registered TPA"
                >
                  <span className="btn-irda-inner">
                    <svg className="btn-irda-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <line x1="22" y1="2" x2="11" y2="13" />
                      <polygon points="22 2 15 22 11 13 2 9 22 2" />
                    </svg>
                    <span className="btn-irda-text">
                      <span className="btn-irda-title">Send to TPA</span>
                      <span className="btn-irda-sub">Submit electronically</span>
                    </span>
                  </span>
                </button>
                <button className="pdf-preview-close" onClick={() => { URL.revokeObjectURL(pdfPreviewUrl); setPdfPreviewUrl(null); }} aria-label="Close preview">×</button>
              </div>
            </div>
            <div className="pdf-preview-body">
              <iframe
                src={pdfPreviewUrl + "#toolbar=1&navpanes=0"}
                className="pdf-preview-iframe"
                title="TPA PDF Preview"
              />
            </div>
          </div>
        </div>
      )}

      {/* ── Send to TPA Modal ── */}
      {showTpaModal && (
        <div className="modal-overlay tpa-modal-overlay" onClick={() => setShowTpaModal(false)}>
          <div className="tpa-modal" onClick={(e) => e.stopPropagation()}>
            <div className="tpa-modal-header">
              <div className="tpa-modal-title">
                <span>📤</span>
                <h3>Send Claim to TPA</h3>
              </div>
              <button className="modal-close" onClick={() => setShowTpaModal(false)}>×</button>
            </div>

            {tpaSent ? (
              <div className="tpa-success">
                <div className="tpa-success-icon">✅</div>
                <h4>Claim Sent Successfully!</h4>
                <p>Your claim has been dispatched to <strong>{tpaSent.tpa_name}</strong></p>
                <div className="tpa-ref">Reference: <code>{tpaSent.reference}</code></div>
                <button className="btn-primary" onClick={() => { setShowTpaModal(false); setTpaSent(null); }}>
                  Done
                </button>
              </div>
            ) : (
              <>
                <div className="tpa-search">
                  <input
                    type="text"
                    placeholder="Search TPA / Insurance provider..."
                    value={tpaSearch}
                    onChange={(e) => setTpaSearch(e.target.value)}
                    autoFocus
                  />
                </div>
                <div className="tpa-list">
                  {tpaList
                    .filter(t => t.name.toLowerCase().includes(tpaSearch.toLowerCase()) || t.type.toLowerCase().includes(tpaSearch.toLowerCase()))
                    .map(tpa => (
                    <button
                      key={tpa.id}
                      className="tpa-card"
                      disabled={tpaSending}
                      onClick={async () => {
                        setTpaSending(true);
                        try {
                          const resp = await fetch(`${SUBMISSION_API}/claims/${preview?.claim_id}/send-to-tpa`, {
                            method: "POST",
                            headers: { "Content-Type": "application/json", ...authHeaders() },
                            body: JSON.stringify({ tpa_id: tpa.id }),
                          });
                          const data = await resp.json();
                          if (data.status === "success") {
                            setTpaSent({ tpa_name: data.tpa_name, reference: data.reference });
                            /* refresh claims list to show SUBMITTED status */
                            fetch(`${API}/claims`, { headers: authHeaders() }).then(r => r.json()).then(d => { const arr = Array.isArray(d) ? d : d.claims; if (arr) setClaims(arr); });
                          }
                        } catch {}
                        setTpaSending(false);
                      }}
                    >
                      <span className="tpa-logo">{tpa.logo}</span>
                      <div className="tpa-info">
                        <span className="tpa-name">{tpa.name}</span>
                        <span className="tpa-meta">
                          <span className={`tpa-type-badge tpa-type-${tpa.type.toLowerCase()}`}>{tpa.type}</span>
                          {tpa.phone && <span className="tpa-phone">📞 {tpa.phone}</span>}
                        </span>
                      </div>
                      <span className="tpa-arrow">→</span>
                    </button>
                  ))}
                  {tpaList.filter(t => t.name.toLowerCase().includes(tpaSearch.toLowerCase())).length === 0 && (
                    <div className="tpa-empty">No TPA found matching &ldquo;{tpaSearch}&rdquo;</div>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* ── Sidebar: Claims Queue ── */}
      <aside className="sidebar">
        <div className="sidebar-header">
          <div className="sidebar-title-row">
            <h1>{t("queue.title")}</h1>
            <span className="queue-count">{claims.length}</span>
          </div>
          <p>{t("queue.subtitle")}</p>
        </div>

        {/* Search bar */}
        <div className="queue-search">
          <svg className="queue-search-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
          <input
            className="queue-search-input"
            placeholder={t("queue.searchPlaceholder")}
            value={claimSearch}
            onChange={(e) => setClaimSearch(e.target.value)}
          />
          {claimSearch && (
            <button className="queue-search-clear" onClick={() => setClaimSearch("")}>×</button>
          )}
        </div>

        {/* Status filter tabs */}
        <div className="queue-filters">
          {[
            { key: "ALL", label: t("queue.filter.all"), count: claims.length },
            { key: "PROCESSING", label: t("queue.filter.processing"), count: statsProcessing },
            { key: "READY", label: t("queue.filter.ready"), count: statsReady },
            { key: "SUBMITTED", label: t("queue.filter.submitted"), count: statsSubmitted },
            { key: "ACTION", label: t("queue.filter.action"), count: statsAction },
            { key: "FAILED", label: t("queue.filter.failed"), count: statsFailed },
          ].filter(f => f.key === "ALL" || f.count > 0).map((f) => (
            <button
              key={f.key}
              className={`queue-filter-btn ${statusFilter === f.key ? "active" : ""}`}
              onClick={() => setStatusFilter(f.key)}
            >
              {f.label}
              {f.count > 0 && <span className="queue-filter-count">{f.count}</span>}
            </button>
          ))}
        </div>

        {/* Drop zone */}
        <div
          className={`drop-zone ${dragOver ? "drag-over" : ""}`}
          onClick={() => fileRef.current?.click()}
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onDrop={onDrop}
        >
          <div className="icon">
            <svg width="42" height="42" viewBox="0 0 42 42" fill="none" xmlns="http://www.w3.org/2000/svg">
              {/* Back doc */}
              <rect x="10" y="4" width="24" height="30" rx="3" fill="var(--accent-lighter)" stroke="var(--accent)" strokeWidth="1.5" opacity="0.5"/>
              {/* Middle doc */}
              <rect x="6" y="8" width="24" height="30" rx="3" fill="var(--glass-bg)" stroke="var(--accent)" strokeWidth="1.5" opacity="0.75"/>
              {/* Front doc */}
              <rect x="2" y="12" width="24" height="30" rx="3" fill="white" stroke="var(--accent)" strokeWidth="1.5"/>
              {/* Lines on front doc */}
              <line x1="7" y1="20" x2="21" y2="20" stroke="var(--accent)" strokeWidth="1.2" strokeLinecap="round" opacity="0.5"/>
              <line x1="7" y1="24" x2="18" y2="24" stroke="var(--accent)" strokeWidth="1.2" strokeLinecap="round" opacity="0.4"/>
              <line x1="7" y1="28" x2="15" y2="28" stroke="var(--accent)" strokeWidth="1.2" strokeLinecap="round" opacity="0.3"/>
              {/* Plus circle */}
              <circle cx="32" cy="32" r="9" fill="var(--accent)" opacity="0.9"/>
              <line x1="32" y1="27" x2="32" y2="37" stroke="white" strokeWidth="2" strokeLinecap="round"/>
              <line x1="27" y1="32" x2="37" y2="32" stroke="white" strokeWidth="2" strokeLinecap="round"/>
            </svg>
          </div>
          <p>
            <strong>{t("drop.title")}</strong> {t("drop.or")}
          </p>
          <p className="hint">{t("drop.hint")}</p>
          <input
            ref={fileRef}
            type="file"
            hidden
            multiple
            accept=".pdf,.jpeg,.jpg,.png,.tiff,.tif,.bmp,.webp,.docx,.doc,.xlsx,.xls,.csv,.txt,.json,.xml,.html"
            onChange={(e) => {
              const files = e.target.files;
              if (files?.length) upload(Array.from(files));
              e.target.value = "";
            }}
          />
        </div>

        {/* Upload feedback */}
        {uploading && (
          <div className="upload-card">
            <div className="upload-card-top">
              <span className="upload-card-name">{uploadFiles.length} file{uploadFiles.length > 1 ? "s" : ""}</span>
              <span className="upload-card-pct">{uploadProgress}%</span>
            </div>
            <div className="upload-file-list">
              {uploadFiles.map((f, i) => (
                <div key={i} className="upload-file-item">
                  <span className="upload-file-icon">{fileIcon(f.name)}</span>
                  <span className="upload-file-name">{f.name}</span>
                  <span className="upload-file-size">{(f.size / 1024).toFixed(0)} KB</span>
                </div>
              ))}
            </div>
            <div className="progress-track">
              <div className="progress-fill" style={{ width: `${uploadProgress}%` }} />
            </div>
          </div>
        )}
        {uploadError && <div className="upload-error">{uploadError}</div>}

        {/* Claims list */}
        <div className="claims-list">
          <div className="claims-list-header">
            <h3>
              {statusFilter === "ALL" ? t("header.allClaims") : statusFilter === "PROCESSING" ? t("header.inProcessing") : statusFilter === "READY" ? t("header.readyForReview") : statusFilter === "ACTION" ? t("header.actionRequired") : statusFilter}
            </h3>
            <span className="claims-list-count">{filteredClaims.length} of {claims.length}</span>
          </div>
          {filteredClaims.length === 0 && claims.length > 0 && (
            <p style={{ fontSize: 13, color: "#94a3b8", textAlign: "center", padding: "20px 0" }}>
              No claims match this filter.
            </p>
          )}
          {claims.length === 0 && (
            <p style={{ fontSize: 13, color: "#94a3b8", textAlign: "center", padding: "20px 0" }}>
              No claims in queue. Upload documents to begin processing.
            </p>
          )}
          {filteredClaims.map((c) => (
            <div
              key={c.id}
              className={`claim-card ${activeClaim === c.id ? "active" : ""}`}
              onClick={() => {
                /* Switching claims — reset stale right-panel state immediately */
                setActiveClaim(c.id);
                setPreview(null);
                setShowPreview(false);
                setEditedFields({});
                setFieldsSaved(false);
                setAuditTrail([]);
                setHistoryExpanded(false);
                setChatUnread(0);
                setMessages([
                  {
                    role: "bot",
                    text: `Claim **#${shortClaimId(c.id)}** loaded — ${c.documents?.length || 0} document(s). I can analyze codes, check compliance, estimate costs, or explain risk factors.`,
                  },
                ]);
                /* Try to load preview for any status that may have parsed data; the
                   endpoint guards itself with `if (resp.ok)` so unparsed claims
                   simply leave preview=null and we fall through to the
                   processing-status placeholder card below. */
                loadPreview(c.id).then(() => setShowPreview(false));
                /* Also pull the audit/history trail for the timeline card. */
                loadAudit(c.id);
              }}
            >
              <div className="claim-card-top-row">
                <div className="meta">
                  <span className="claim-id-tag">#{shortClaimId(c.id)}</span>
                  <span className="meta-time">
                    {new Date(c.created_at).toLocaleDateString("en-IN", { day: "2-digit", month: "short" })}{" "}
                    {new Date(c.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                  </span>
                </div>
                <div className="claim-card-actions">
                  {(() => { const sla = claimSla(c.created_at, c.status); return (
                    <span className={`sla-badge ${sla.cls}`} title={`Age: ${sla.label} · ${sla.isResolved ? "Resolved" : sla.ageHours > 48 ? "SLA breach (>48h)" : sla.ageHours > 24 ? "SLA warning (>24h)" : "Within SLA (<24h)"}`}>
                      {!sla.isResolved && sla.ageHours > 24 && "⚠ "}{sla.label}
                    </span>
                  ); })()}
                  <button
                    className="delete-btn"
                    title="Delete claim"
                    onClick={(e) => deleteClaim(c.id, e)}
                  >
                    X
                  </button>
                </div>
              </div>
              {(c.patient_id || c.policy_id) && (
                <div className="claim-person">
                  {c.patient_id && <span title="Patient / Insured">👤 {c.patient_id}</span>}
                  {c.policy_id && <span title="Policy ID">🆔 {c.policy_id}</span>}
                </div>
              )}
              <div className="claim-card-header">
                <div className="name">
                  {fileIcon(c.documents?.[0]?.file_name || "")}{" "}
                  {claimNames[c.id]
                    ? `${claimNames[c.id]}'s - ${c.documents?.length || 0} document${(c.documents?.length || 0) !== 1 ? "s" : ""}`
                    : c.documents?.length === 1
                      ? c.documents[0].file_name
                      : `${c.documents?.length || 0} documents`
                  }
                </div>
              </div>
              {c.documents?.length > 0 && (
                <div className="claim-doc-list">
                  {c.documents.map((d, i) => (
                    <span key={d.id} className="claim-doc-tag">
                      {fileIcon(d.file_name)} <span className="doc-name">{d.file_name}</span>
                      {c.documents.length > 1 && (
                        <button
                          className="doc-delete-btn"
                          title={`Remove ${d.file_name}`}
                          onClick={(e) => deleteDoc(c.id, d.id, e)}
                        >
                          ×
                        </button>
                      )}
                    </span>
                  ))}
                </div>
              )}
              <span
                className={`status ${STATUS_CLASS[c.status] || "status-processing"}`}
              >
                {c.status === "PROCESSING" && <span className="spinner-sm" />}
                {c.status === "DOCUMENTS_REQUESTED" ? "📋 Docs Requested" : c.status === "MODIFICATION_REQUESTED" ? "✏️ Modification Needed" : c.status === "APPROVED" ? "✅ Approved" : c.status === "REJECTED" ? "❌ Rejected" : c.status.charAt(0) + c.status.slice(1).toLowerCase()}
              </span>
              {(c.status === "DOCUMENTS_REQUESTED" || c.status === "MODIFICATION_REQUESTED") && (
                <div className="claim-tpa-banner">
                  <div className="claim-tpa-banner-icon">{c.status === "DOCUMENTS_REQUESTED" ? "📎" : "✏️"}</div>
                  <div className="claim-tpa-banner-text">
                    <strong>{c.status === "DOCUMENTS_REQUESTED" ? "TPA requested more documents" : "TPA requested modifications"}</strong>
                    {tpaMessages[c.id] ? (
                      <span className="claim-tpa-message">&ldquo;{tpaMessages[c.id]}&rdquo;</span>
                    ) : (
                      <span>{c.status === "DOCUMENTS_REQUESTED" ? "Upload additional documents to proceed" : "Edit and resubmit your claim"}</span>
                    )}
                  </div>
                </div>
              )}
              {c.status === "DOCUMENTS_REQUESTED" && (
                <div className="claim-actions claim-actions-request">
                  <label className="upload-more-btn">
                    <input type="file" multiple hidden onChange={(e) => { if (e.target.files?.length) { setActiveClaim(c.id); upload(Array.from(e.target.files), true); } }} />
                    📎 Upload Documents
                  </label>
                  <button className="preview-btn" onClick={(e) => { e.stopPropagation(); loadPreview(c.id); }}>👁 Preview</button>
                </div>
              )}
              {c.status === "MODIFICATION_REQUESTED" && (
                <div className="claim-actions claim-actions-request">
                  <button className="preview-btn preview-btn-edit" onClick={(e) => { e.stopPropagation(); loadPreview(c.id); }}>✏️ Edit & Preview</button>
                  <label className="upload-more-btn">
                    <input type="file" multiple hidden onChange={(e) => { if (e.target.files?.length) { setActiveClaim(c.id); upload(Array.from(e.target.files), true); } }} />
                    📎 Add Docs
                  </label>
                </div>
              )}
              {PIPELINE_ACTIVE_STATUSES.has(c.status) && (
                <div className="claim-progress-card">
                  <div className="progress-track">
                    <div
                      className="progress-fill"
                      style={{ width: `${(claimProgress[c.id]?.percentage || 0)}%` }}
                    />
                  </div>
                  <div className="progress-meta">
                    {(claimProgress[c.id]?.step || c.status)} · {(claimProgress[c.id]?.percentage || 0)}%
                  </div>
                </div>
              )}
              {["COMPLETED", "VALIDATED", "CODED", "SUBMITTED"].includes(c.status) && (
                <div className="claim-actions">
                  <button
                    className="preview-btn"
                    onClick={(e) => {
                      e.stopPropagation();
                      loadPreview(c.id);
                    }}
                   >
                    {previewLoading ? "Loading..." : "Preview"}
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      </aside>

      {/* ── Main Panel (Chat + Data) ── */}
      <section className="chat-panel">
        <div className="chat-header">
          <h2>{activeClaim ? `Claim #${shortClaimId(activeClaim)}` : t("workspace.title")}</h2>
          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
            {activeClaim && (
              <span className="badge">{claims.find(c => c.id === activeClaim)?.status?.replace(/_/g, " ") || "Active"}</span>
            )}
            {activeClaim && preview && (
              <span className={`cd-verdict ${verdictLabel(preview.summary.risk_score).cls}`}>
                {verdictLabel(preview.summary.risk_score).text}
              </span>
            )}
          </div>
        </div>

        {/* ── Inline Claim Dashboard ── */}
        {activeClaim && preview && !showPreview && (() => {
          const claim = claims.find(c => c.id === activeClaim);
          return (
            <div className="claim-dashboard">
              {/* Top-row patient info & diagnosis are now consolidated into
                  the Patient full-info card in the detail-grid below. */}

              <div className="cd-kpi-row">
                <div className="cd-kpi">
                  <span className="cd-kpi-val" style={{ color: riskColor(preview.summary.risk_score) }}>
                    {preview.summary.risk_score !== null ? `${(preview.summary.risk_score * 100).toFixed(0)}%` : "—"}
                  </span>
                  <span className="cd-kpi-label">Risk</span>
                </div>
                <div className="cd-kpi">
                  <span className="cd-kpi-val">{preview.summary.icd_count}</span>
                  <span className="cd-kpi-label">ICD</span>
                </div>
                <div className="cd-kpi">
                  <span className="cd-kpi-val">{preview.summary.cpt_count}</span>
                  <span className="cd-kpi-label">CPT</span>
                </div>
                <div className="cd-kpi">
                  <span className="cd-kpi-val">{preview.summary.validation_passed}/{preview.summary.validation_total}</span>
                  <span className="cd-kpi-label">Rules</span>
                </div>
                <div className="cd-kpi">
                  <span className="cd-kpi-val cd-kpi-cost">
                    {preview.billed_total ? `₹${preview.billed_total.toLocaleString("en-IN")}` : preview.cost_summary ? `₹${preview.cost_summary.grand_total.toLocaleString("en-IN")}` : "—"}
                  </span>
                  <span className="cd-kpi-label">Amount</span>
                </div>
                <div className="cd-kpi">
                  <span className="cd-kpi-val">{Object.keys(preview.parsed_fields).length}</span>
                  <span className="cd-kpi-label">Fields</span>
                </div>
              </div>

              {/* Diagnosis line removed — it's shown in the Patient full-info card */}

              <div className="cd-actions">
                <button className="cd-action-btn cd-btn-preview" onClick={() => setShowPreview(true)}>
                  🧠 Brain Report
                </button>
                <button
                  className="cd-action-btn cd-btn-tpa-pdf"
                  disabled={pdfLoading}
                  onClick={async () => {
                    setPdfKind("tpa");
                    setPdfLoading(true);
                    try {
                      const resp = await fetch(`${SUBMISSION_API}/claims/${preview.claim_id}/tpa-pdf`, { headers: authHeaders() });
                      const blob = await resp.blob();
                      setPdfPreviewUrl(URL.createObjectURL(blob));
                    } catch { /* ignore */ }
                    setPdfLoading(false);
                  }}
                >
                  📄 TPA PDF
                </button>
                <button
                  className="cd-action-btn cd-btn-irda"
                  disabled={irdaLoading}
                  onClick={async () => {
                    setPdfKind("irda");
                    setIrdaLoading(true);
                    try {
                      const resp = await fetch(`${SUBMISSION_API}/claims/${preview.claim_id}/irda-pdf`, { headers: authHeaders() });
                      const blob = await resp.blob();
                      setPdfPreviewUrl(URL.createObjectURL(blob));
                    } catch { /* ignore */ }
                    setIrdaLoading(false);
                  }}
                >
                  📋 IRDA Form
                </button>
                <button
                  className="cd-action-btn cd-btn-send"
                  onClick={async () => {
                    try {
                      const resp = await fetch(`${SUBMISSION_API}/tpa-list`, { headers: authHeaders() });
                      const data = await resp.json();
                      setTpaList(data.tpas || []);
                    } catch { setTpaList([]); }
                    setTpaSent(null);
                    setTpaSearch("");
                    setShowTpaModal(true);
                  }}
                >
                  🚀 Send to TPA
                </button>
              </div>
            </div>
          );
        })()}

        {/* ── Detail strip: structured info cards (only when preview is loaded) ── */}
        {activeClaim && preview && !showPreview && (() => {
          const topPrediction = preview.predictions?.[0];
          const topReason = topPrediction?.top_reasons?.[0];
          const failedValidations = (preview.validations || []).filter(v => !v.passed);
          const claim = claims.find(c => c.id === activeClaim);
          const billed = preview.billed_total || preview.cost_summary?.grand_total || 0;
          /* Inline SVG icons (Lucide-style, 16px, currentColor) */
          const Icon = {
            user: (<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>),
            building: (<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M3 21h18M5 21V7l8-4v18M19 21V11l-6-4"/><path d="M9 9h.01M9 12h.01M9 15h.01M9 18h.01"/></svg>),
            calendar: (<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>),
            stethoscope: (<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M4.8 2.3A.3.3 0 1 0 5 2H4a2 2 0 0 0-2 2v5a6 6 0 0 0 6 6v0a6 6 0 0 0 6-6V4a2 2 0 0 0-2-2h-1a.2.2 0 1 0 .2.3"/><path d="M8 15v1a6 6 0 0 0 6 6v0a6 6 0 0 0 6-6v-4"/><circle cx="20" cy="10" r="2"/></svg>),
            hash: (<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><line x1="4" y1="9" x2="20" y2="9"/><line x1="4" y1="15" x2="20" y2="15"/><line x1="10" y1="3" x2="8" y2="21"/><line x1="16" y1="3" x2="14" y2="21"/></svg>),
            cross: (<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M11 2h2a1 1 0 0 1 1 1v6h6a1 1 0 0 1 1 1v2a1 1 0 0 1-1 1h-6v6a1 1 0 0 1-1 1h-2a1 1 0 0 1-1-1v-6H4a1 1 0 0 1-1-1v-2a1 1 0 0 1 1-1h6V3a1 1 0 0 1 1-1z"/></svg>),
            alert: (<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>),
            check: (<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>),
            xcircle: (<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>),
            rupee: (<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M6 3h12M6 8h12M6 13l9 8M6 13h3a4 4 0 0 0 0-8"/></svg>),
            paperclip: (<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>),
          };

          return (
            <div className="cd-detail-grid">
              {/* Top row: Patient card + Clinical Coding side-by-side */}
              <div className="cd-top-row">
              {/* Patient — full information card */}
              <div
                className="cd-info-card cd-info-card-wide cd-patient-full-card cd-info-clickable"
                role="button"
                tabIndex={0}
                onClick={() => openChatAbout(`Tell me about the patient on claim #${shortClaimId(activeClaim)}.`)}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openChatAbout(`Tell me about the patient on claim #${shortClaimId(activeClaim)}.`); } }}
              >
                <div className="cd-info-card-head">
                  <span className="cd-info-icon">{Icon.user}</span>
                  <span className="cd-info-title">Patient</span>
                  {claim?.patient_id && <span className="cd-info-badge">ID #{claim.patient_id}</span>}
                </div>
                <div className="cd-info-body cd-patient-full-body">
                  {/* Hero row: name + age/gender chip */}
                  <div className="cd-patient-hero">
                    <div className="cd-patient-hero-avatar" aria-hidden>
                      {(preview.summary.patient_name || "?").trim().charAt(0).toUpperCase()}
                    </div>
                    <div className="cd-patient-hero-text">
                      <div className="cd-patient-hero-name">
                        {preview.summary.patient_name || <span className="cd-info-empty">Not provided</span>}
                      </div>
                      <div className="cd-patient-hero-meta">
                        {preview.summary.age && <span className="cd-patient-chip cd-patient-chip-age">{preview.summary.age} yrs</span>}
                        {preview.summary.gender && <span className="cd-patient-chip cd-patient-chip-gender">{preview.summary.gender}</span>}
                        {(() => {
                          if (!preview.summary.admission_date || !preview.summary.discharge_date) return null;
                          const a = new Date(preview.summary.admission_date);
                          const d = new Date(preview.summary.discharge_date);
                          if (isNaN(a.getTime()) || isNaN(d.getTime())) return null;
                          const days = Math.max(0, Math.round((d.getTime() - a.getTime()) / 86400000));
                          return <span className="cd-patient-chip cd-patient-chip-stay">{days} day stay</span>;
                        })()}
                      </div>
                    </div>
                  </div>

                  {/* KV grid: detailed fields in two columns */}
                  <div className="cd-patient-kv-grid">
                    {claim?.policy_id && (
                      <div className="cd-patient-kv">
                        <span className="cd-patient-kv-label">Policy</span>
                        <span className="cd-patient-kv-value">{claim.policy_id}</span>
                      </div>
                    )}
                    {claim?.patient_id && (
                      <div className="cd-patient-kv">
                        <span className="cd-patient-kv-label">Patient ID</span>
                        <span className="cd-patient-kv-value">{claim.patient_id}</span>
                      </div>
                    )}
                    {preview.summary.admission_date && (
                      <div className="cd-patient-kv">
                        <span className="cd-patient-kv-label">Admit</span>
                        <span className="cd-patient-kv-value">{preview.summary.admission_date}</span>
                      </div>
                    )}
                    {preview.summary.discharge_date && (
                      <div className="cd-patient-kv">
                        <span className="cd-patient-kv-label">Discharge</span>
                        <span className="cd-patient-kv-value">{preview.summary.discharge_date}</span>
                      </div>
                    )}
                    {preview.summary.hospital && (
                      <div className="cd-patient-kv cd-patient-kv-span2">
                        <span className="cd-patient-kv-label">Hospital</span>
                        <span className="cd-patient-kv-value cd-info-clip">{preview.summary.hospital}</span>
                      </div>
                    )}
                    {preview.summary.doctor && (
                      <div className="cd-patient-kv cd-patient-kv-span2">
                        <span className="cd-patient-kv-label">Treating Doctor</span>
                        <span className="cd-patient-kv-value cd-info-clip">Dr. {preview.summary.doctor}</span>
                      </div>
                    )}
                    {preview.summary.diagnosis && (
                      <div className="cd-patient-kv cd-patient-kv-span2">
                        <span className="cd-patient-kv-label">Primary Diagnosis</span>
                        <span className="cd-patient-kv-value cd-info-clip">{preview.summary.diagnosis}</span>
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* Hospital + Stay are now folded into the Patient card above */}

              {/* Diagnosis is folded into the Patient card above */}

              {/* SECTION GROUP: Clinical Coding (sits beside Patient in top row) */}
              <div className="cd-section-group">
              <div className="cd-section-label">
                <span className="cd-section-label-text">Clinical Coding</span>
                <span className="cd-section-label-line" aria-hidden />
              </div>
              <div className="cd-section-cards">

              {/* ICD-10 codes */}
              {preview.icd_codes?.length > 0 && (
                <div
                  className="cd-info-card cd-info-clickable"
                  role="button"
                  tabIndex={0}
                  onClick={() => openChatAbout(`Are all ${preview.icd_codes.length} ICD-10 codes correct? Flag any that look wrong.`)}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openChatAbout(`Are all ${preview.icd_codes.length} ICD-10 codes correct? Flag any that look wrong.`); } }}
                >
                  <div className="cd-info-card-head">
                    <span className="cd-info-icon">{Icon.hash}</span>
                    <span className="cd-info-title">ICD-10</span>
                    <span className="cd-info-badge">{preview.icd_codes.length}</span>
                  </div>
                  <div className="cd-info-body">
                    {preview.icd_codes.slice(0, 3).map((c, i) => (
                      <div key={i} className="cd-info-code-row">
                        <code className="cd-code-pill">{c.code}</code>
                        <span className="cd-info-muted cd-info-clip">{c.description}</span>
                      </div>
                    ))}
                    {preview.icd_codes.length > 3 && (
                      <button type="button" className="cd-info-more" onClick={() => setShowPreview(true)}>
                        View all {preview.icd_codes.length} codes →
                      </button>
                    )}
                  </div>
                </div>
              )}

              {/* CPT codes */}
              {preview.cpt_codes?.length > 0 && (
                <div
                  className="cd-info-card cd-info-clickable"
                  role="button"
                  tabIndex={0}
                  onClick={() => openChatAbout(`Review the ${preview.cpt_codes.length} CPT procedures — are they appropriate for the diagnosis?`)}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openChatAbout(`Review the ${preview.cpt_codes.length} CPT procedures — are they appropriate for the diagnosis?`); } }}
                >
                  <div className="cd-info-card-head">
                    <span className="cd-info-icon">{Icon.cross}</span>
                    <span className="cd-info-title">CPT Procedures</span>
                    <span className="cd-info-badge">{preview.cpt_codes.length}</span>
                  </div>
                  <div className="cd-info-body">
                    {preview.cpt_codes.slice(0, 3).map((c, i) => (
                      <div key={i} className="cd-info-code-row">
                        <code className="cd-code-pill">{c.code}</code>
                        <span className="cd-info-muted cd-info-clip">{c.description}</span>
                      </div>
                    ))}
                    {preview.cpt_codes.length > 3 && (
                      <button type="button" className="cd-info-more" onClick={() => setShowPreview(true)}>
                        View all {preview.cpt_codes.length} codes →
                      </button>
                    )}
                  </div>
                </div>
              )}

              </div>
              </div>
              </div>{/* /.cd-top-row */}

              {/* ── Risk & Compliance — full-width row ── */}
              <div className="cd-section-group cd-section-group-wide">
              <div className="cd-section-label">
                <span className="cd-section-label-text">Risk &amp; Compliance</span>
                <span className="cd-section-label-line" aria-hidden />
              </div>
              <div className="cd-section-cards cd-section-cards-2col">

              {/* Risk driver */}
              {topReason && (
                <div
                  className="cd-info-card cd-info-card-amber cd-info-clickable"
                  role="button"
                  tabIndex={0}
                  onClick={() => openChatAbout(`Explain the top risk driver "${topReason.reason}" and how I can mitigate it before submission.`)}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openChatAbout(`Explain the top risk driver "${topReason.reason}" and how I can mitigate it before submission.`); } }}
                >
                  <div className="cd-info-card-head">
                    <span className="cd-info-icon">{Icon.alert}</span>
                    <span className="cd-info-title">Top Risk Driver</span>
                    <span className="cd-info-badge cd-info-badge-amber">
                      {(topReason.weight * 100).toFixed(0)}%
                    </span>
                  </div>
                  <div className="cd-info-body">
                    <div className="cd-info-line cd-info-strong cd-info-clip">{topReason.reason}</div>
                    {topPrediction?.model_name && (
                      <div className="cd-info-line cd-info-muted">Model: {topPrediction.model_name}</div>
                    )}
                  </div>
                </div>
              )}

              {/* Validations */}
              {(preview.validations?.length || 0) > 0 && (
                <div
                  className={`cd-info-card cd-info-clickable ${failedValidations.length > 0 ? "cd-info-card-rose" : "cd-info-card-emerald"}`}
                  role="button"
                  tabIndex={0}
                  onClick={() => openChatAbout(failedValidations.length > 0
                    ? `Walk me through the ${failedValidations.length} failed validation rule${failedValidations.length > 1 ? "s" : ""} and how to fix them.`
                    : `All validation rules passed — give me a brief summary of what was checked.`)}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openChatAbout(failedValidations.length > 0 ? `Walk me through the ${failedValidations.length} failed validation rule${failedValidations.length > 1 ? "s" : ""} and how to fix them.` : `All validation rules passed — give me a brief summary of what was checked.`); } }}
                >
                  <div className="cd-info-card-head">
                    <span className="cd-info-icon">{failedValidations.length > 0 ? Icon.xcircle : Icon.check}</span>
                    <span className="cd-info-title">Validation Rules</span>
                    <span className={`cd-info-badge ${failedValidations.length > 0 ? "cd-info-badge-rose" : "cd-info-badge-emerald"}`}>
                      {preview.summary.validation_passed}/{preview.summary.validation_total}
                    </span>
                  </div>
                  <div className="cd-info-body">
                    {failedValidations.length === 0 ? (
                      <div className="cd-info-line cd-info-muted">All checks passed.</div>
                    ) : (
                      failedValidations.slice(0, 1).map((v, i) => (
                        <div key={i}>
                          <div className="cd-info-line cd-info-strong cd-info-clip">{v.rule_name}</div>
                          <div className="cd-info-line cd-info-muted cd-info-clip">{v.message}</div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              )}

              </div>
              </div>

              {/* ── Financial & Documents — full-width row below ── */}
              <div className="cd-section-group cd-section-group-wide">
              <div className="cd-section-label">
                <span className="cd-section-label-text">Financial &amp; Documents</span>
                <span className="cd-section-label-line" aria-hidden />
              </div>
              <div className="cd-section-cards cd-section-cards-2col">

              {/* Billing */}
              {billed > 0 && (
                <div
                  className="cd-info-card cd-info-clickable"
                  role="button"
                  tabIndex={0}
                  onClick={() => openChatAbout(`Break down the billed amount of ₹${billed.toLocaleString("en-IN")} and check for any over-billing.`)}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openChatAbout(`Break down the billed amount of ₹${billed.toLocaleString("en-IN")} and check for any over-billing.`); } }}
                >
                  <div className="cd-info-card-head">
                    <span className="cd-info-icon">{Icon.rupee}</span>
                    <span className="cd-info-title">Billed Amount</span>
                  </div>
                  <div className="cd-info-body">
                    <div className="cd-info-amount">₹{billed.toLocaleString("en-IN")}</div>
                    {preview.cost_summary && (
                      <div className="cd-info-line cd-info-muted">
                        ICD ₹{preview.cost_summary.icd_total.toLocaleString("en-IN")} · CPT ₹{preview.cost_summary.cpt_total.toLocaleString("en-IN")}
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Documents */}
              {(claim?.documents?.length || 0) > 0 && (
                <div
                  className="cd-info-card cd-info-clickable"
                  role="button"
                  tabIndex={0}
                  onClick={() => openChatAbout(`What information was extracted from the ${claim?.documents.length} attached document${(claim?.documents.length || 0) > 1 ? "s" : ""}?`)}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openChatAbout(`What information was extracted from the ${claim?.documents.length} attached document${(claim?.documents.length || 0) > 1 ? "s" : ""}?`); } }}
                >
                  <div className="cd-info-card-head">
                    <span className="cd-info-icon">{Icon.paperclip}</span>
                    <span className="cd-info-title">Documents</span>
                    <span className="cd-info-badge">{claim?.documents.length}</span>
                  </div>
                  <div className="cd-info-body">
                    {claim?.documents.slice(0, 4).map((d) => (
                      <div key={d.id} className="cd-info-doc-row" title={d.file_name}>
                        <span className="cd-info-doc-icon">{fileIcon(d.file_name)}</span>
                        <span className="cd-info-doc-name cd-info-clip">{d.file_name}</span>
                      </div>
                    ))}
                    {(claim?.documents.length || 0) > 4 && (
                      <div className="cd-info-more">+{(claim?.documents.length || 0) - 4} more</div>
                    )}
                  </div>
                </div>
              )}

              </div>
              </div>
            </div>
          );
        })()}

        {/* ── Activity / Audit timeline (collapsible, grouped by date) ── */}
        {activeClaim && (auditTrail.length > 0 || auditLoading) && (() => {
          /* Group entries by date label (latest first) */
          const ACTION_META: Record<string, { label: string; tone: "info" | "success" | "warn" | "danger" | "default" }> = {
            CLAIM_CREATED: { label: "Claim created", tone: "info" },
            DOCUMENT_UPLOADED: { label: "Document uploaded", tone: "info" },
            OCR_COMPLETED: { label: "OCR processed", tone: "info" },
            PARSING_COMPLETED: { label: "Fields extracted", tone: "info" },
            CODING_COMPLETED: { label: "Codes assigned", tone: "info" },
            VALIDATION_PASSED: { label: "Validation passed", tone: "success" },
            VALIDATION_FAILED: { label: "Validation failed", tone: "danger" },
            FIELDS_EDITED: { label: "Fields edited", tone: "warn" },
            SUBMITTED_TO_TPA: { label: "Submitted to TPA", tone: "success" },
            TPA_APPROVED: { label: "Approved by TPA", tone: "success" },
            TPA_REJECTED: { label: "Rejected by TPA", tone: "danger" },
            DOCUMENTS_REQUESTED: { label: "Additional documents requested", tone: "warn" },
            MODIFICATION_REQUESTED: { label: "Modifications requested", tone: "warn" },
          };
          const sorted = auditTrail.slice().reverse();
          const groups: { dateLabel: string; entries: AuditEntry[] }[] = [];
          for (const e of sorted) {
            const ts = e.created_at ? new Date(e.created_at) : null;
            const today = new Date();
            const yesterday = new Date(); yesterday.setDate(today.getDate() - 1);
            let label = "Earlier";
            if (ts) {
              if (ts.toDateString() === today.toDateString()) label = "Today";
              else if (ts.toDateString() === yesterday.toDateString()) label = "Yesterday";
              else label = ts.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
            }
            const last = groups[groups.length - 1];
            if (last && last.dateLabel === label) last.entries.push(e);
            else groups.push({ dateLabel: label, entries: [e] });
          }

          return (
            <div className="cd-history">
              <button
                type="button"
                className="cd-history-toggle"
                onClick={() => setHistoryExpanded((v) => !v)}
                aria-expanded={historyExpanded}
              >
                <span className="cd-history-icon" aria-hidden>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="10"/>
                    <polyline points="12 6 12 12 16 14"/>
                  </svg>
                </span>
                <span className="cd-history-label">Activity</span>
                {auditTrail.length > 0 && (
                  <span className="cd-history-count">{auditTrail.length}</span>
                )}
                {auditLoading && <span className="cd-history-loading">Loading…</span>}
                <span className={`cd-history-chev ${historyExpanded ? "open" : ""}`} aria-hidden>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="6 9 12 15 18 9"/>
                  </svg>
                </span>
              </button>
              {historyExpanded && (
                <div className="cd-history-panel">
                  {auditTrail.length === 0 && !auditLoading && (
                    <div className="cd-history-empty">No activity recorded yet.</div>
                  )}
                  {groups.map((g) => (
                    <div key={g.dateLabel} className="cd-history-group">
                      <div className="cd-history-date">{g.dateLabel}</div>
                      <ol className="cd-history-list">
                        {g.entries.map((e) => {
                          const ts = e.created_at ? new Date(e.created_at) : null;
                          const meta = e.metadata && typeof e.metadata === "object" ? e.metadata : null;
                          const note = meta && typeof (meta as any).note === "string" ? (meta as any).note as string : null;
                          const m = ACTION_META[e.action] || { label: e.action.replace(/_/g, " ").toLowerCase(), tone: "default" as const };
                          return (
                            <li key={e.id} className={`cd-history-item cd-history-tone-${m.tone}`}>
                              <span className="cd-history-marker" aria-hidden />
                              <div className="cd-history-body">
                                <div className="cd-history-row">
                                  <span className="cd-history-action">{m.label}</span>
                                  {ts && (
                                    <span className="cd-history-time" title={ts.toLocaleString("en-IN")}>
                                      {ts.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}
                                    </span>
                                  )}
                                </div>
                                {e.actor && <div className="cd-history-actor">{e.actor}</div>}
                                {note && <div className="cd-history-note">{note}</div>}
                              </div>
                            </li>
                          );
                        })}
                      </ol>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })()}

        {/* ── Placeholder card while a claim is selected but preview isn't ready ── */}
        {activeClaim && !preview && !showPreview && (() => {
          const claim = claims.find(c => c.id === activeClaim);
          if (!claim) return null;
          const isProcessing = PIPELINE_ACTIVE_STATUSES.has(claim.status);
          const isFailed = claim.status.endsWith("_FAILED");
          const prog = claimProgress[claim.id];
          return (
            <div className="claim-dashboard claim-dashboard-stub">
              <div className="cd-top-row">
                <div className="cd-patient-info">
                  <span className="cd-patient-icon">{isFailed ? "⚠️" : isProcessing ? "⏳" : "📄"}</span>
                  <div className="cd-patient-details">
                    <span className="cd-patient-name">
                      {claimNames[claim.id] || `Claim #${shortClaimId(claim.id)}`}
                    </span>
                    <span className="cd-patient-meta">
                      {claim.documents?.length || 0} document{(claim.documents?.length || 0) !== 1 ? "s" : ""}
                      {claim.policy_id && ` · Policy ${claim.policy_id}`}
                    </span>
                  </div>
                </div>
                <div className="cd-status-row">
                  <span className={`cd-status ${STATUS_CLASS[claim.status] || "status-processing"}`}>
                    {claim.status.replace(/_/g, " ")}
                  </span>
                </div>
              </div>

              {isProcessing && (
                <div className="cd-progress-block">
                  <div className="cd-progress-track">
                    <div
                      className="cd-progress-fill"
                      style={{ width: `${prog?.percentage || 0}%` }}
                    />
                  </div>
                  <div className="cd-progress-meta">
                    {previewLoading
                      ? "Loading preview…"
                      : `${prog?.step || claim.status} · ${prog?.percentage || 0}%`}
                  </div>
                </div>
              )}

              {isFailed && (
                <div className="cd-diagnosis">
                  <span className="cd-diag-label">Status:</span>
                  <span className="cd-diag-text">
                    Pipeline stage failed. Re-upload the document or contact support.
                  </span>
                </div>
              )}

              {!isProcessing && !isFailed && previewLoading && (
                <div className="cd-progress-meta" style={{ padding: "8px 0" }}>Loading preview…</div>
              )}

              <div className="cd-actions">
                <button
                  className="cd-action-btn cd-btn-preview"
                  disabled={previewLoading}
                  onClick={() => loadPreview(claim.id).then(() => setShowPreview(false))}
                >
                  🔄 {previewLoading ? "Loading…" : "Refresh Preview"}
                </button>
                <label className="cd-action-btn cd-btn-tpa-pdf" style={{ cursor: "pointer" }}>
                  <input
                    type="file"
                    multiple
                    hidden
                    onChange={(e) => {
                      if (e.target.files?.length) upload(Array.from(e.target.files), true);
                    }}
                  />
                  📎 Add Documents
                </label>
              </div>
            </div>
          );
        })()}

        {/* ── Floating Chat Dock (corner) ── */}
        <div className={`floating-chat-dock ${chatOpen ? "open" : "closed"}`} role="dialog" aria-label="Claim assistant chat" aria-hidden={!chatOpen}>
          <div className="fcd-header">
            <div className="fcd-title">
              <span className="fcd-avatar" aria-hidden>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 2a8 8 0 0 0-8 8c0 1.6.5 3 1.3 4.2L4 20l5.8-1.3c.8.4 2 .6 3.2.6a8 8 0 0 0 0-16h-1z"/>
                  <circle cx="9" cy="10" r="1" fill="currentColor"/>
                  <circle cx="13" cy="10" r="1" fill="currentColor"/>
                  <circle cx="17" cy="10" r="1" fill="currentColor"/>
                </svg>
                <span className="fcd-status-dot" />
              </span>
              <div className="fcd-title-text">
                <span className="fcd-title-main">Claim Assistant</span>
                <span className="fcd-title-sub">
                  {activeClaim
                    ? <>Discussing <code>#{shortClaimId(activeClaim)}</code></>
                    : "Online · Ready to help"}
                </span>
              </div>
            </div>
            <div className="fcd-actions">
              <button
                type="button"
                className="fcd-action-btn"
                onClick={() => { setChatOpen(false); }}
                aria-label="Minimize chat"
                title="Minimize"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><line x1="5" y1="12" x2="19" y2="12"/></svg>
              </button>
              <button
                type="button"
                className="fcd-action-btn"
                onClick={() => { setChatOpen(false); setMessages([]); }}
                aria-label="Close chat and clear conversation"
                title="Close"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/></svg>
              </button>
            </div>
          </div>

          <div className="tab-content fcd-body">
            <>
              <div className="messages">
                {messages.length === 0 ? (
                  <div className="empty-state chatgpt-welcome">
                    {!activeClaim ? (
                      <>
                        {/* ── B2B Operations Dashboard ── */}
                        <div className="ops-dashboard">
                          <div className="ops-header">
                            <div className="ops-header-row">
                              <div>
                                <h2 className="ops-title">Operations Command Center</h2>
                                <p className="ops-subtitle">Real-time claims processing overview · Indian health insurance</p>
                              </div>
                              <div className="ops-header-meta">
                                <span className="ops-meta-pill">
                                  <span className="ops-live-dot" /> Live
                                </span>
                                <span className="ops-meta-pill ops-meta-time">
                                  {new Date().toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })} IST
                                </span>
                              </div>
                            </div>
                          </div>

                          {/* Pipeline KPIs */}
                          <div className="ops-kpi-grid">
                            <div className="ops-kpi ops-kpi-total">
                              <div className="ops-kpi-icon">
                                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2"/><rect x="9" y="3" width="6" height="4" rx="1"/></svg>
                              </div>
                              <span className="ops-kpi-val">{claims.length}</span>
                              <span className="ops-kpi-label">Total Claims</span>
                            </div>
                            <div className="ops-kpi ops-kpi-proc">
                              <div className="ops-kpi-icon">
                                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>
                              </div>
                              <span className="ops-kpi-val">{statsProcessing}</span>
                              <span className="ops-kpi-label">In Pipeline</span>
                            </div>
                            <div className="ops-kpi ops-kpi-ready">
                              <div className="ops-kpi-icon">
                                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
                              </div>
                              <span className="ops-kpi-val">{statsReady}</span>
                              <span className="ops-kpi-label">Ready for Review</span>
                            </div>
                            <div className="ops-kpi ops-kpi-submitted">
                              <div className="ops-kpi-icon">
                                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4 20-7z"/></svg>
                              </div>
                              <span className="ops-kpi-val">{statsSubmitted}</span>
                              <span className="ops-kpi-label">Submitted to TPA</span>
                            </div>
                            {statsAction > 0 && (
                              <div className="ops-kpi ops-kpi-action">
                                <div className="ops-kpi-icon">
                                  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                                </div>
                                <span className="ops-kpi-val">{statsAction}</span>
                                <span className="ops-kpi-label">Action Required</span>
                              </div>
                            )}
                            {approvalRate !== null && (
                              <div className="ops-kpi ops-kpi-rate">
                                <div className="ops-kpi-icon">
                                  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 20V10"/><path d="M18 20V4"/><path d="M6 20v-4"/></svg>
                                </div>
                                <span className="ops-kpi-val">{approvalRate}%</span>
                                <span className="ops-kpi-label">Approval Rate</span>
                              </div>
                            )}
                          </div>

                          {/* Operational metrics row (Indian context) */}
                          {claims.length > 0 && (
                            <div className="ops-metrics-row">
                              <div className="ops-metric ops-metric-tat">
                                <div className="ops-metric-head">
                                  <span className="ops-metric-label">Avg Turnaround Time</span>
                                  <span className="ops-metric-trend">vs IRDAI 30-day target</span>
                                </div>
                                <div className="ops-metric-val-row">
                                  <span className="ops-metric-val">{avgTatLabel}</span>
                                  <span className="ops-metric-target">Target: ≤24h</span>
                                </div>
                              </div>
                              <div className={`ops-metric ${slaBreaches > 0 ? "ops-metric-breach" : "ops-metric-ok"}`}>
                                <div className="ops-metric-head">
                                  <span className="ops-metric-label">SLA Breaches</span>
                                  <span className="ops-metric-trend">Claims &gt; 24h unresolved</span>
                                </div>
                                <div className="ops-metric-val-row">
                                  <span className="ops-metric-val">{slaBreaches}</span>
                                  <span className="ops-metric-target">{slaBreaches === 0 ? "All within SLA" : "Action needed"}</span>
                                </div>
                              </div>
                              <div className="ops-metric ops-metric-network">
                                <div className="ops-metric-head">
                                  <span className="ops-metric-label">TPA Network</span>
                                  <span className="ops-metric-trend">Connected partners</span>
                                </div>
                                <div className="ops-metric-val-row">
                                  <span className="ops-metric-val">12</span>
                                  <span className="ops-metric-target">Star · ICICI · HDFC +9</span>
                                </div>
                              </div>
                              <div className="ops-metric ops-metric-compliance">
                                <div className="ops-metric-head">
                                  <span className="ops-metric-label">Compliance Score</span>
                                  <span className="ops-metric-trend">IRDAI · DPDP · ISO 27001</span>
                                </div>
                                <div className="ops-metric-val-row">
                                  <span className="ops-metric-val">A+</span>
                                  <span className="ops-metric-target">Last audit: clean</span>
                                </div>
                              </div>
                            </div>
                          )}

                          {/* Pipeline Funnel */}
                          {claims.length > 0 && (
                            <div className="ops-funnel">
                              <h3 className="ops-funnel-title">Processing Pipeline</h3>
                              <div className="ops-funnel-bars">
                                {[
                                  { label: "Intake", count: claims.length, color: "#64748b" },
                                  { label: "OCR & Parsing", count: statsProcessing, color: "#0ea5e9" },
                                  { label: "Coded & Validated", count: statsReady, color: "#8b5cf6" },
                                  { label: "Submitted", count: statsSubmitted, color: "#16a34a" },
                                  { label: "Approved", count: statsApproved, color: "#059669" },
                                ].map((stage) => (
                                  <div key={stage.label} className="funnel-stage">
                                    <div className="funnel-label-row">
                                      <span className="funnel-label">{stage.label}</span>
                                      <span className="funnel-count">{stage.count}</span>
                                    </div>
                                    <div className="funnel-bar-track">
                                      <div
                                        className="funnel-bar-fill"
                                        style={{
                                          width: claims.length > 0 ? `${Math.max((stage.count / claims.length) * 100, stage.count > 0 ? 4 : 0)}%` : "0%",
                                          backgroundColor: stage.color,
                                        }}
                                      />
                                    </div>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>

                        {/* Quick actions */}
                        <div className="ops-quick-actions">
                          <p className="ops-qa-label">Quick Actions</p>
                          <div className="starter-grid-home">
                            {[
                              { icon: "📤", title: "Upload claim", desc: "Submit new claim documents for processing" },
                              { icon: "🔍", title: "Query codes", desc: "Search ICD-10 / CPT codes with AI" },
                              { icon: "📊", title: "Risk analysis", desc: "How does the ML rejection model work?" },
                              { icon: "📋", title: "Compliance check", desc: "Review validation rules and IRDA guidelines" },
                            ].map((card) => (
                              <button
                                key={card.title}
                                className="starter-card-home"
                                onClick={() => sendSuggestion(card.desc)}
                              >
                                <span className="sc-icon">{card.icon}</span>
                                <span className="sc-title">{card.title}</span>
                                <span className="sc-desc">{card.desc}</span>
                              </button>
                            ))}
                          </div>
                        </div>
                      </>
                    ) : (
                      <>
                        <div className="welcome-logo">
                          <span className="logo-glow">CG</span>
                        </div>
                        <h2 className="welcome-title">Claim loaded — ask me anything</h2>
                        <p className="welcome-sub">I can analyze codes, check compliance, estimate costs, or explain risk factors for this claim.</p>
                        <div className="starter-grid-home">
                          {[
                            { icon: "🔍", title: "Summarize claim", desc: "Give me a full summary of this claim" },
                            { icon: "🏥", title: "Verify codes", desc: "Are the ICD-10 and CPT codes correct?" },
                            { icon: "⚠️", title: "Risk factors", desc: "What are the top rejection risk factors?" },
                            { icon: "📋", title: "Compliance", desc: "Does this claim pass all validation rules?" },
                          ].map((card) => (
                            <button
                              key={card.title}
                              className="starter-card-home"
                              onClick={() => sendSuggestion(card.desc)}
                            >
                              <span className="sc-icon">{card.icon}</span>
                              <span className="sc-title">{card.title}</span>
                              <span className="sc-desc">{card.desc}</span>
                            </button>
                          ))}
                        </div>
                      </>
                    )}
                  </div>
                ) : (
                  <>
                    {messages.map((m, i) => (
                      <div key={i} className={`msg-row ${m.role}`}>
                        <div className="msg-avatar">
                          {m.role === "user" ? (
                            <span className="avatar-user">You</span>
                          ) : (
                            <span className="avatar-bot">CG</span>
                          )}
                        </div>
                        <div className="msg-body">
                          <div className={`msg-content ${m.role}`}>
                            <span dangerouslySetInnerHTML={{ __html: renderMarkdown(m.text) }} />
                          </div>
                          {m.role === "bot" && (
                            <div className="msg-actions">
                              <button
                                className="msg-action-btn"
                                title="Copy"
                                onClick={() => { navigator.clipboard.writeText(m.text); }}
                              >
                                📋
                              </button>
                            </div>
                          )}
                          {m.role === "bot" && m.fieldActions && m.fieldActions.length > 0 && (
                            <div className="field-action-card">
                              <div className="fac-header">
                                <span className="fac-icon">✏️</span>
                                <span className="fac-title">Suggested Field Changes</span>
                              </div>
                              <div className="fac-list">
                                {m.fieldActions.map((fa, j) => (
                                  <div key={j} className={`fac-item fac-${fa.action}`}>
                                    <span className="fac-badge">{fa.action.toUpperCase()}</span>
                                    <span className="fac-field">{fa.field_name.replace(/_/g, " ")}</span>
                                    {fa.action === "delete" && fa.old_value && (
                                      <span className="fac-value fac-old">❌ {fa.old_value}</span>
                                    )}
                                    {fa.action === "modify" && (
                                      <>
                                        <span className="fac-value fac-old">{fa.old_value || "(empty)"}</span>
                                        <span className="fac-arrow">→</span>
                                        <span className="fac-value fac-new">{fa.new_value}</span>
                                      </>
                                    )}
                                    {fa.action === "add" && (
                                      <span className="fac-value fac-new">+ {fa.new_value}</span>
                                    )}
                                  </div>
                                ))}
                              </div>
                              <div className="fac-buttons">
                                <button className="fac-btn fac-btn-apply" onClick={() => applyFieldActions(m.fieldActions!, i)}>
                                  ✅ Apply Changes
                                </button>
                                <button className="fac-btn fac-btn-dismiss" onClick={() => dismissFieldActions(i)}>
                                  ✖ Dismiss
                                </button>
                              </div>
                            </div>
                          )}
                          {m.role === "bot" && m.suggestions && m.suggestions.length > 0 && i === messages.length - 1 && (
                            <div className="suggestion-row">
                              {m.suggestions.map((s) => (
                                <button key={s} className="suggestion-chip" onClick={() => sendSuggestion(s)}>
                                  {s}
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                  </>
                )}
                {typing && (
                  <div className="msg-row bot">
                    <div className="msg-avatar"><span className="avatar-bot">CG</span></div>
                    <div className="msg-body">
                      <div className="msg-content bot typing-indicator">
                        <span className="dot"></span><span className="dot"></span><span className="dot"></span>
                      </div>
                    </div>
                  </div>
                )}
                <div ref={msgEnd} />
              </div>

              <form className="chat-input-bar" onSubmit={(e) => { setShowAutoSuggest(false); sendMessage(e); }}>
                <div className="input-wrapper">
                  {showAutoSuggest && autoSuggestions.length > 0 && (
                    <div className="autosuggest-dropdown">
                      {autoSuggestions.map((s, idx) => (
                        <button
                          key={s}
                          type="button"
                          className={`autosuggest-item${idx === selectedSuggestIdx ? " active" : ""}`}
                          onMouseDown={(e) => { e.preventDefault(); selectAutoSuggestion(s); }}
                        >
                          <span className="as-icon">
                            {s.toLowerCase().startsWith("add") ? "➕" :
                             s.toLowerCase().startsWith("change") || s.toLowerCase().startsWith("update") || s.toLowerCase().startsWith("correct") ? "✏️" :
                             s.toLowerCase().startsWith("remove") || s.toLowerCase().startsWith("delete") ? "🗑️" :
                             s.toLowerCase().startsWith("show") || s.toLowerCase().startsWith("what") || s.toLowerCase().startsWith("list") ? "🔍" :
                             "💬"}
                          </span>
                          <span className="as-text">{s}</span>
                        </button>
                      ))}
                    </div>
                  )}
                  <div className="input-actions-left">
                    <div className="plus-menu-wrap">
                      <button type="button" className={`plus-toggle-btn${plusMenuOpen ? " open" : ""}`} title="Attach" onClick={() => setPlusMenuOpen((v) => !v)}>
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
                          <line x1="12" y1="5" x2="12" y2="19" />
                          <line x1="5" y1="12" x2="19" y2="12" />
                        </svg>
                      </button>
                      {plusMenuOpen && (
                        <div className="plus-menu" onMouseLeave={() => setPlusMenuOpen(false)}>
                          <button type="button" className="plus-menu-item" onClick={() => { setPlusMenuOpen(false); chatFileRef.current?.click(); }}>
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
                            <span>Attach File</span>
                          </button>
                          <button type="button" className="plus-menu-item" onClick={() => { setPlusMenuOpen(false); openCamera(); }}>
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
                            <span>Camera</span>
                          </button>
                          <button type="button" className="plus-menu-item" onClick={() => { setPlusMenuOpen(false); captureScreenshot(); }}>
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/><circle cx="12" cy="10" r="2" fill="currentColor" stroke="none"/></svg>
                            <span>Screenshot</span>
                          </button>
                        </div>
                      )}
                    </div>
                    <input
                      ref={chatFileRef}
                      type="file"
                      hidden
                      multiple
                      accept=".pdf,.jpeg,.jpg,.png,.tiff,.tif,.bmp,.webp,.docx,.doc,.xlsx,.xls,.csv,.txt,.json,.xml,.html"
                      onChange={(e) => {
                        const files = e.target.files;
                        if (files?.length) upload(Array.from(files), true);
                        e.target.value = "";
                      }}
                    />
                  </div>
                  <input
                    value={input}
                    onChange={handleInputChange}
                    onKeyDown={handleInputKeyDown}
                    onBlur={() => setTimeout(() => setShowAutoSuggest(false), 200)}
                    onFocus={() => { const sug = getAutoSuggestions(input); if (sug.length > 0) { setAutoSuggestions(sug); setShowAutoSuggest(true); } }}
                    placeholder={typing ? t("chat.processing") : activeClaim ? t("chat.placeholderActive") : t("chat.placeholderIdle")}
                    disabled={typing}
                    autoComplete="off"
                  />
                  <button type="submit" disabled={!input.trim() || typing} className="send-btn">
                    <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M1 8.5L1 1.5L15 8L1 14.5L1 8.5ZM1 8.5L8 8.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
                  </button>
                </div>
                <p className="input-hint">{t("chat.hint")}</p>
              </form>

              {/* Camera modal */}
              {cameraOpen && (
                <div className="camera-overlay" onClick={closeCamera}>
                  <div className="camera-modal" onClick={(e) => e.stopPropagation()}>
                    <div className="camera-header">
                      <span>📷 Capture Document</span>
                      <button className="camera-close" onClick={closeCamera}>✕</button>
                    </div>
                    <div className="camera-viewfinder">
                      {cameraError ? (
                        <div className="camera-error">
                          <span>⚠️</span>
                          <p>{cameraError}</p>
                          <p className="camera-error-hint">Please allow camera access in your browser settings</p>
                        </div>
                      ) : (
                        <>
                          <video ref={videoRef} autoPlay playsInline muted className="camera-video" />
                          {!cameraReady && <div className="camera-loading">Initializing camera...</div>}
                          <div className="camera-guide">
                            <div className="guide-corner tl" /><div className="guide-corner tr" />
                            <div className="guide-corner bl" /><div className="guide-corner br" />
                            <span className="guide-text">Align document within frame</span>
                          </div>
                        </>
                      )}
                    </div>
                    <div className="camera-controls">
                      <button className="camera-cancel" onClick={closeCamera}>Cancel</button>
                      <button className="camera-capture" onClick={capturePhoto} disabled={!cameraReady}>
                        <span className="shutter" />
                      </button>
                      <div style={{ width: 64 }} />
                    </div>
                    <canvas ref={canvasRef} hidden />
                  </div>
                </div>
              )}
            </>
        </div>
        </div>
        {/* ── End Floating Chat Dock ── */}

        {/* ── Chat launcher FAB (visible when dock is closed) ── */}
        <button
          type="button"
          className={`chat-fab ${chatOpen ? "hidden" : ""} ${chatUnread > 0 ? "has-unread" : ""}`}
          onClick={() => { setChatOpen(true); setChatUnread(0); }}
          aria-label={chatUnread > 0 ? `Open chat — ${chatUnread} new message${chatUnread > 1 ? "s" : ""}` : "Open chat"}
          title="Chat with Claim Assistant"
        >
          <svg className="chat-fab-icon" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
          </svg>
          {chatUnread > 0 && (
            <span className="chat-fab-badge" aria-hidden>{chatUnread > 9 ? "9+" : chatUnread}</span>
          )}
          <span className="chat-fab-pulse" aria-hidden />
        </button>
      </section>

      </div>{/* end app-content */}

      {/* Footer — professional, single line */}
      <footer className="wct-footer">
        <div className="wct-footer-left">
          <span className="footer-status">
            <span className="footer-status-dot" />
            <span>All systems operational</span>
          </span>
          <span className="footer-sep" />
          <span className="footer-region" title="Data Residency: Mumbai (ap-south-1)">IN · Mumbai</span>
          <span className="footer-sep" />
          <span className="footer-compliance">IRDAI · ISO 27001 · DPDP · HIPAA-aligned</span>
        </div>
        <div className="wct-footer-right">
          <span>© 2026 <strong>WaferWire Cloud Technologies</strong></span>
          <span className="footer-sep" />
          <span className="footer-version">ClaimGPT v2.0</span>
        </div>
      </footer>
    </div>
  );
}

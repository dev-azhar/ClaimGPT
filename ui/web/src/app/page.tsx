"use client";

import { useState, useRef, useEffect, DragEvent, FormEvent } from "react";

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
};

const PIPELINE_ACTIVE_STATUSES = new Set([
  "UPLOADED",
  "PROCESSING",
  "OCR_PROCESSING",
  "OCR_DONE",
  "PARSING",
  "PARSED",
  "CODED",
  "PREDICTED",
  "VALIDATED",
]);

const PIPELINE_READY_STATUSES = new Set([
  "COMPLETED",
  "VALIDATED",
  "SUBMITTED",
]);

const API = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000/ingress";
const CHAT_API = process.env.NEXT_PUBLIC_CHAT_BASE || "http://localhost:8000/chat";
const SUBMISSION_API = process.env.NEXT_PUBLIC_SUBMISSION_BASE || "http://localhost:8000/submission";

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
  const [collapsedSections, setCollapsedSections] = useState<Record<string, boolean>>({});
  const [editedFields, setEditedFields] = useState<Record<string, string>>({});
  const [fieldsSaving, setFieldsSaving] = useState(false);
  const [fieldsSaved, setFieldsSaved] = useState(false);

  const [claimNames, setClaimNames] = useState<Record<string, string>>({});
  const [cameraOpen, setCameraOpen] = useState(false);
  const [showTpaModal, setShowTpaModal] = useState(false);
  const [tpaList, setTpaList] = useState<{id: string; name: string; logo: string; type: string; email: string; phone: string; website: string}[]>([]);
  const [tpaSending, setTpaSending] = useState(false);
  const [tpaSent, setTpaSent] = useState<{tpa_name: string; reference: string} | null>(null);
  const [tpaSearch, setTpaSearch] = useState("");
  const [plusMenuOpen, setPlusMenuOpen] = useState(false);
  const [cameraReady, setCameraReady] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
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

  /* ── load claims on mount ── */
  const refreshClaims = () => {
    fetch(`${API}/claims`)
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
    fetch(`${CHAT_API}/providers`).then((r) => r.json()).then((d) => {
      if (d?.current) setLlmProvider(d.current);
    }).catch(() => {});
    // Load patient names for completed claims
    fetch(`${API}/claims`).then((r) => r.json()).then((data) => {
      if (!data?.claims) return;
      const completed = data.claims.filter((c: Claim) =>
        ["COMPLETED", "VALIDATED", "CODED", "SUBMITTED"].includes(c.status)
      );
      completed.forEach((c: Claim) => {
        fetch(`${SUBMISSION_API}/claims/${c.id}/preview`, { cache: "no-store" })
          .then((r) => r.json())
          .then((p: PreviewData) => {
            if (p?.summary?.patient_name) {
              setClaimNames((prev) => ({ ...prev, [c.id]: p.summary.patient_name }));
            }
          })
          .catch(() => {});
      });
    }).catch(() => {});
  }, []);

  /* ── auto-refresh claim status every 5s while any claim is processing ── */
  useEffect(() => {
    const hasProcessing = claims.some((c) =>
      PIPELINE_ACTIVE_STATUSES.has(c.status)
    );
    if (!hasProcessing) return;
    const interval = setInterval(refreshClaims, 5000);
    return () => clearInterval(interval);
  }, [claims]);

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
          const claim: Claim = JSON.parse(xhr.responseText);
          // Update or insert the claim in the list
          setClaims((prev) => {
            const exists = prev.find((c) => c.id === claim.id);
            if (exists) return prev.map((c) => (c.id === claim.id ? claim : c));
            return [claim, ...prev];
          });
          setActiveClaim(claim.id);

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
      const resp = await fetch(`${API}/claims/${claimId}/documents/${docId}`, { method: "DELETE" });
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
      const resp = await fetch(`${API}/claims/${id}`, { method: "DELETE" });
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
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code, action }),
      });
    } catch { /* ignore */ }
  };

  /* ── preview handler ── */
  const loadPreview = async (claimId: string) => {
    setPreviewLoading(true);
    try {
      const resp = await fetch(`${SUBMISSION_API}/claims/${claimId}/preview`, { cache: "no-store" });
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
        headers: { "Content-Type": "application/json" },
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
    setMessages((prev) => [...prev, { role: "user", text }]);
    setTyping(true);

    const sessionId = activeClaim || "general";

    /* ── Try streaming first, fallback to regular endpoint ── */
    try {
      const resp = await fetch(`${CHAT_API}/${sessionId}/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, claim_id: activeClaim }),
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
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: text, claim_id: activeClaim }),
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
    setInput(text);
    setTimeout(() => {
      const form = document.querySelector(".chat-input-bar") as HTMLFormElement;
      form?.requestSubmit();
    }, 50);
  };

  /* helper: apply field actions (add/modify/delete) to claim via API */
  const applyFieldActions = async (actions: FieldAction[], msgIdx: number) => {
    if (!activeClaim || actions.length === 0) return;
    try {
      const resp = await fetch(`${CHAT_API}/fields/apply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
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

  /* ── render ── */
  return (
    <div className="app-shell">
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
                    className="btn-primary brain-pdf-btn"
                    disabled={pdfLoading}
                    onClick={async () => {
                      const url = `${SUBMISSION_API}/claims/${preview.claim_id}/tpa-pdf`;
                      setPdfDownloadUrl(url);
                      setPdfLoading(true);
                      try {
                        const resp = await fetch(url);
                        const blob = await resp.blob();
                        const blobUrl = URL.createObjectURL(blob);
                        setPdfPreviewUrl(blobUrl);
                      } catch { setPdfPreviewUrl(null); }
                      setPdfLoading(false);
                    }}
                  >
                    {pdfLoading ? "⏳ Generating..." : "📄 Preview & Download PDF"}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── PDF Preview Modal ── */}
      {pdfPreviewUrl && (
        <div className="modal-overlay pdf-preview-overlay" onClick={() => { URL.revokeObjectURL(pdfPreviewUrl); setPdfPreviewUrl(null); }}>
          <div className="pdf-preview-modal" onClick={(e) => e.stopPropagation()}>
            <div className="pdf-preview-header">
              <div className="pdf-preview-title">
                <span>📄</span>
                <h3>TPA Claim Report Preview</h3>
              </div>
              <div className="pdf-preview-actions">
                <a
                  className="btn-primary pdf-download-btn"
                  href={pdfPreviewUrl}
                  download={(() => {
                    const pf = preview?.parsed_fields || {};
                    const name = (pf.patient_name || pf.member_name || pf.insured_name || "").trim().replace(/\s+/g, "_");
                    const policy = (pf.policy_number || pf.policy_id || pf.policy_no || preview?.policy_id || "").trim().replace(/\s+/g, "_");
                    if (name && policy) return `${name}_${policy}.pdf`;
                    if (name) return `${name}_Claim.pdf`;
                    if (policy) return `Claim_${policy}.pdf`;
                    return `TPA_Claim_${preview?.claim_id?.slice(0, 8) || "report"}.pdf`;
                  })()}
                >
                  ⬇ Download PDF
                </a>
                <button
                  className="btn-primary tpa-send-btn"
                  onClick={async () => {
                    try {
                      const resp = await fetch(`${SUBMISSION_API}/tpa-list`);
                      const data = await resp.json();
                      setTpaList(data.tpas || []);
                    } catch { setTpaList([]); }
                    setTpaSent(null);
                    setTpaSearch("");
                    setShowTpaModal(true);
                  }}
                >
                  📤 Send to TPA
                </button>
                <button className="modal-close" onClick={() => { URL.revokeObjectURL(pdfPreviewUrl); setPdfPreviewUrl(null); }}>×</button>
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
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ tpa_id: tpa.id }),
                          });
                          const data = await resp.json();
                          if (data.status === "success") {
                            setTpaSent({ tpa_name: data.tpa_name, reference: data.reference });
                            /* refresh claims list to show SUBMITTED status */
                            fetch(`${API}/claims`).then(r => r.json()).then(d => { if (Array.isArray(d)) setClaims(d); });
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

      {/* ── Sidebar ── */}
      <aside className="sidebar">
        <div className="sidebar-header">
          <h1>ClaimGPT</h1>
          <p>AI-Powered Claims Brain</p>
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
            <strong>Drop claim documents</strong> or click to browse
          </p>
          <p className="hint">Multiple files supported · PDF, Images, Word, Excel, CSV, Text - up to 50 MB each</p>
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
          <h3>Recent Claims</h3>
          {claims.length === 0 && (
            <p style={{ fontSize: 13, color: "#94a3b8" }}>
              No claims yet. Upload a document to begin.
            </p>
          )}
          {claims.map((c) => (
            <div
              key={c.id}
              className={`claim-card ${activeClaim === c.id ? "active" : ""}`}
              onClick={() => {
                setActiveClaim(c.id);
                const fname = c.documents?.[0]?.file_name || "Untitled";
                setMessages([
                  {
                    role: "bot",
                    text: `Viewing claim "${fname}". Ask me anything about it.`,
                  },
                ]);
              }}
            >
              <div className="claim-card-top-row">
                <div className="meta">
                  {new Date(c.created_at).toLocaleDateString()}{" "}
                  {new Date(c.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                </div>
                <button
                  className="delete-btn"
                  title="Delete claim"
                  onClick={(e) => deleteClaim(c.id, e)}
                >
                  X
                </button>
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
                {c.status.charAt(0) + c.status.slice(1).toLowerCase()}
              </span>
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
          <h2>ClaimGPT Assistant</h2>
          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
            {llmProvider && (
              <span className="badge provider-badge" title={`LLM: ${llmProvider}`}>
                🏠 Ollama
              </span>
            )}
            {activeClaim && <span className="badge">Claim Active</span>}
          </div>
        </div>

        <div className="tab-content">
            <>
              <div className="messages">
                {messages.length === 0 ? (
                  <div className="empty-state chatgpt-welcome">
                    <div className="welcome-logo">
                      <span className="logo-glow">CG</span>
                    </div>
                    <h2 className="welcome-title">How can I help you today?</h2>
                    <p className="welcome-sub">I&apos;m ClaimGPT — your AI claims assistant powered by Llama 3.2</p>
                    <div className="starter-grid-home">
                      {[
                        { icon: "🔍", title: "Analyze a claim", desc: "Upload a document and I'll extract everything" },
                        { icon: "🏥", title: "Medical codes", desc: "Explain ICD-10 and CPT coding" },
                        { icon: "💰", title: "Billing help", desc: "Understand charges, coverage, deductibles" },
                        { icon: "📊", title: "Rejection risk", desc: "How is the ML risk score calculated?" },
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
                    placeholder={typing ? "ClaimGPT is thinking..." : "Message ClaimGPT..."}
                    disabled={typing}
                    autoComplete="off"
                  />
                  <button type="submit" disabled={!input.trim() || typing} className="send-btn">
                    <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M1 8.5L1 1.5L15 8L1 14.5L1 8.5ZM1 8.5L8 8.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
                  </button>
                </div>
                <p className="input-hint">ClaimGPT can make mistakes. Verify important medical codes.</p>
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
      </section>

      {/* Footer */}
      <footer className="wct-footer">
        Developed by <strong>WaferWire Cloud Technologies</strong>
      </footer>
    </div>
  );
}

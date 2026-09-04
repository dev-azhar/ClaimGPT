'use client';

import { useState, useEffect, useMemo, useRef } from 'react';
import {
  LINE_ITEMS,
  PIPELINE,
  formatINR,
  type Stage,
  type LineItem,
} from '@/lib/claimgpt-data';
import {
  uploadClaimDocument,
  fetchClaimPreview,
  fetchLatestClaimId,
  fetchRecentClaims,
  fetchClaimProgress,
  deleteClaimApi,
  deleteClaimDocumentApi,
  isMockId,
  PIPELINE_ACTIVE_STATUSES,
  isProcessingStatus,
  type RealClaimPreview,
  type RecentClaimSummary,
  SUBMISSION_API,
  saveClaimExpensesApi,
  saveClaimDetailsApi,
} from '@/lib/api-client';
import { getStoredAuthSession } from '@/lib/auth';
import { toast } from '@/hooks/use-toast';

/* Utility function for robust smooth scrolling across all devices */
export function scrollToPipeline() {
  setTimeout(() => {
    const el = document.getElementById('pipeline-progress-section');
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, 150);
}

/* Case-insensitive claim ID comparison to prevent UUID casing mismatches between DB and UI */
export function isSameClaimId(a?: string | null, b?: string | null): boolean {
  if (!a || !b) return false;
  return a.trim().toLowerCase() === b.trim().toLowerCase();
}

/* Sort claims so actively processing claims are ALWAYS on top, followed by newest created_at */
export function sortClaimsNewestFirst(claims: RecentClaimSummary[]): RecentClaimSummary[] {
  return [...claims].sort((a, b) => {
    const aProc = (a.progress && a.progress.percentage < 100) || a.status === "UPLOADED" || a.status === "PROCESSING" || a.status === "RUNNING";
    const bProc = (b.progress && b.progress.percentage < 100) || b.status === "UPLOADED" || b.status === "PROCESSING" || b.status === "RUNNING";
    if (aProc && !bProc) return -1;
    if (!aProc && bProc) return 1;

    const timeA = a.created_at ? new Date(a.created_at).getTime() : 0;
    const timeB = b.created_at ? new Date(b.created_at).getTime() : 0;
    return timeB - timeA;
  });
}

export function useAuditorState() {
  const getDocumentKey = (doc?: { document_id?: string; id?: string } | null) =>
    doc?.document_id || doc?.id || null;

  const getPreviewDocumentKeys = (preview: RealClaimPreview | null) =>
    (preview?.documents || [])
      .map((doc) => getDocumentKey(doc))
      .filter((docId): docId is string => Boolean(docId));

  const [progress, setProgress] = useState<number>(() => {
    if (typeof window === "undefined") return 0;
    try {
      const activeId = localStorage.getItem("claimgpt_active_claim_id");
      if (!activeId) return 0;
      const cached = localStorage.getItem("claimgpt_cached_recent_claims");
      if (!cached) return 0;
      const claims = JSON.parse(cached);
      const active = claims.find((c: any) => c.id === activeId);
      return active?.progress?.percentage || 0;
    } catch {
      return 0;
    }
  });

  const [activeStage, setActiveStage] = useState<Stage>(() => {
    if (typeof window === "undefined") return 'staged';
    try {
      const activeId = localStorage.getItem("claimgpt_active_claim_id");
      if (!activeId) return 'staged';
      const cached = localStorage.getItem("claimgpt_cached_recent_claims");
      if (!cached) return 'staged';
      const claims = JSON.parse(cached);
      const active = claims.find((c: any) => c.id === activeId);
      const pct = active?.progress?.percentage || 0;
      if (pct >= 85) return 'scoring';
      if (pct >= 65) return 'coding';
      if (pct >= 30) return 'parsing';
      if (pct > 0) return 'ocr';
      return 'staged';
    } catch {
      return 'staged';
    }
  });

  const [stepDescription, setStepDescription] = useState<string>(() => {
    if (typeof window === "undefined") return "Claim Analysis Complete";
    try {
      const activeId = localStorage.getItem("claimgpt_active_claim_id");
      if (!activeId) return "Claim Analysis Complete";
      const cached = localStorage.getItem("claimgpt_cached_recent_claims");
      if (!cached) return "Claim Analysis Complete";
      const claims = JSON.parse(cached);
      const active = claims.find((c: any) => c.id === activeId);
      return active?.progress?.step || (active?.progress?.percentage ? `Processing - ${active.progress.percentage}%` : "OCR (extracting text) - 20%");
    } catch {
      return "Claim Analysis Complete";
    }
  });
  const [files, setFiles] = useState<{ name: string; size: string; type?: string }[]>([]);
  const [hoveredField, setHoveredField] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const [edited, setEdited] = useState<Record<string, boolean>>({});
  const [activeDocumentId, setActiveDocumentId] = useState<string | null>(null);

  /* Modal state for full report preview — default FALSE */
  const [showReportModal, setShowReportModal] = useState(false);

  /* Modal state for in-app document preview — default FALSE */
  const [showDocModal, setShowDocModal] = useState(false);
  const openDocModal = () => setShowDocModal(true);
  const closeDocModal = () => setShowDocModal(false);

  /* User Profile & Account Modal State */
  const [userId, setUserId] = useState<string | null>(null);
  const [userName, setUserName] = useState<string>('User');
  const [userEmail, setUserEmail] = useState<string>('user@example.com');
  const [showProfileModal, setShowProfileModal] = useState<boolean>(false);
  const [showMenuDrawer, setShowMenuDrawer] = useState<boolean>(false);
  const [duplicateClaimId, setDuplicateClaimId] = useState<string | null>(null);

  const syncUserSession = () => {
    try {
      const session = getStoredAuthSession();
      if (session?.user) {
        if (session.user.id) setUserId(session.user.id);
        if (session.user.name) setUserName(session.user.name);
        if (session.user.email) setUserEmail(session.user.email);
      } else {
        const savedId = localStorage.getItem('claimgpt_user_id');
        const savedName = localStorage.getItem('claimgpt_user_name');
        const savedEmail = localStorage.getItem('claimgpt_user_email');
        if (savedId) setUserId(savedId);
        if (savedName) setUserName(savedName);
        if (savedEmail) setUserEmail(savedEmail);
      }
    } catch (err) {
      /* ignore */
    }
  };

  /* Remove a specific document from a claim */
  const deleteDocument = async (claimIdTarget: string, docIdTarget: string, e?: React.MouseEvent) => {
    if (e) e.stopPropagation();

    // Optimistically update recentClaims documents
    setRecentClaims((prev) =>
      prev.map((c) => {
        if (c.id === claimIdTarget) {
          const nextDocs = (c.documents || []).filter((d) => d.id !== docIdTarget && d.file_name !== docIdTarget);
          return { ...c, documents: nextDocs };
        }
        return c;
      })
    );

    // If deleting from currently active claim, update staged files & preview documents
    if (claimIdTarget === claimId) {
      setFiles((prev) => prev.filter((f, idx) => `f-${idx}` !== docIdTarget && f.name !== docIdTarget));
      if (realPreview && realPreview.documents) {
        setRealPreview({
          ...realPreview,
          documents: realPreview.documents.filter((d) => d.id !== docIdTarget && d.original_filename !== docIdTarget),
        });
      }
    }

    try {
      await deleteClaimDocumentApi(claimIdTarget, docIdTarget);
    } catch {
      /* ignore network error */
    }
  };

  useEffect(() => {
    syncUserSession();
  }, []);

  const openProfileModal = () => {
    syncUserSession();
    setShowProfileModal(true);
  };

  const openMenuDrawer = () => {
    syncUserSession();
    setShowMenuDrawer(true);
  };

  /* File(s) pending analysis */
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);

  /* Real Backend State */
  const [claimId, setClaimId] = useState<string | null>(() => {
    if (typeof window === "undefined") return null;
    try {
      return localStorage.getItem("claimgpt_active_claim_id") || null;
    } catch {
      return null;
    }
  });
  const [uploading, setUploading] = useState(false);
  const [analyzing, setAnalyzing] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    try {
      const activeId = localStorage.getItem("claimgpt_active_claim_id");
      if (!activeId) return false;
      const cached = localStorage.getItem("claimgpt_cached_recent_claims");
      if (!cached) return false;
      const claims = JSON.parse(cached);
      const active = claims.find((c: any) => c.id === activeId);
      if (!active) return false;
      const st = (active.status || "").toUpperCase();
      const hasIncompleteProgress = active.progress?.percentage !== undefined && active.progress.percentage < 100;
      return hasIncompleteProgress || isProcessingStatus(st);
    } catch {
      return false;
    }
  });
  const [realPreview, setRealPreview] = useState<RealClaimPreview | null>(null);
  const [isLoadingClaims, setIsLoadingClaims] = useState(true);

  /* Incremented each time realPreview is set with real data — used as key for MetaField remount */
  const [previewVersion, setPreviewVersion] = useState(0);

  /* Collapsible Upload Dropdown Panel State — default TRUE on clean start */
  const [isUploadOpen, setIsUploadOpen] = useState(true);
  const toggleUploadOpen = () => setIsUploadOpen((prev) => !prev);

  /* Controls whether top upload card displays completion state — default FALSE on page load */
  const [isLiveSessionCompleted, setIsLiveSessionCompleted] = useState(false);
  const activePollsRef = useRef<Map<string, NodeJS.Timeout>>(new Map());
  const activeClaimIdRef = useRef<string | null>(null);

  const stopPollingClaim = (id: string) => {
    const timer = activePollsRef.current.get(id);
    if (timer) {
      clearInterval(timer);
      activePollsRef.current.delete(id);
    }
  };

  useEffect(() => {
    return () => {
      activePollsRef.current.forEach((timer) => clearInterval(timer));
      activePollsRef.current.clear();
    };
  }, []);

  /* Central progress and pipeline stage synchronizer */
  const updateProgressAndStage = (targetPct: number, customStep?: string, force = true) => {
    const safePct = Math.min(Math.max(targetPct, 0), 100);
    setProgress((prev) => (force ? safePct : Math.max(prev, safePct)));
    const effectivePct = safePct;
    const stepLower = (customStep || "").toLowerCase();

    if (effectivePct >= 100) {
      setActiveStage('scoring');
      setStepDescription(customStep || "Claim Analysis 100% Complete");
    } else if (stepLower.includes('scor') || stepLower.includes('compliance') || effectivePct >= 85) {
      setActiveStage('scoring');
      setStepDescription(customStep || `Compliance & Risk Scoring - ${effectivePct}%`);
    } else if (stepLower.includes('cod') || (effectivePct >= 65 && effectivePct < 85)) {
      setActiveStage('coding');
      setStepDescription(customStep || `ICD-10 / CPT Coding - ${effectivePct}%`);
    } else if (stepLower.includes('pars') || (effectivePct >= 30 && effectivePct < 65)) {
      setActiveStage('parsing');
      setStepDescription(customStep || `Parsing (LLM agent reading document) - ${effectivePct}%`);
    } else {
      setActiveStage('ocr');
      setStepDescription(customStep || `OCR (extracting text) - ${effectivePct}%`);
    }
  };

  /* History list of past claims (hydrated instantly from localStorage on frame 1) */
  const [recentClaims, setRecentClaims] = useState<RecentClaimSummary[]>(() => {
    if (typeof window === "undefined") return [];
    try {
      const cached = localStorage.getItem("claimgpt_cached_recent_claims");
      return cached ? JSON.parse(cached) : [];
    } catch {
      return [];
    }
  });

  // Keep localStorage cache fresh whenever recentClaims updates
  useEffect(() => {
    if (recentClaims && recentClaims.length > 0) {
      try {
        localStorage.setItem("claimgpt_cached_recent_claims", JSON.stringify(recentClaims.slice(0, 50)));
      } catch {
        /* ignore */
      }
    }
  }, [recentClaims]);

  // Keep localStorage active claim fresh
  useEffect(() => {
    try {
      if (claimId) {
        localStorage.setItem("claimgpt_active_claim_id", claimId);
      } else {
        localStorage.removeItem("claimgpt_active_claim_id");
      }
    } catch {
      /* ignore */
    }
  }, [claimId]);

  /* Updates progress for a specific claim monotonically, keeping recentClaims in sync */
  const updateClaimProgress = (targetId: string, targetPct: number, customStep?: string, status?: string) => {
    const safePct = Math.min(Math.max(targetPct, 0), 100);
    let finalMonotonicPct = safePct;

    setRecentClaims((prev) =>
      prev.map((c) => {
        if (isSameClaimId(c.id, targetId)) {
          const currentPct = c.progress?.percentage || 0;
          const finalPct = Math.max(currentPct, safePct);
          finalMonotonicPct = finalPct;
          const nextStatus = finalPct >= 100 ? "COMPLETED" : (status || c.status || (finalPct > 20 ? "PARSING" : "UPLOADED"));
          return {
            ...c,
            status: nextStatus,
            progress: {
              percentage: finalPct,
              step: customStep || c.progress?.step || (finalPct >= 100 ? "AI Verification Complete" : `Processing - ${finalPct}%`),
              is_complete: finalPct >= 100,
            },
          };
        }
        return c;
      })
    );

    if (isSameClaimId(activeClaimIdRef.current, targetId) || (!activeClaimIdRef.current && isSameClaimId(claimId, targetId))) {
      updateProgressAndStage(finalMonotonicPct, customStep);
    }
  };

  const [isDocumentsRequested, setIsDocumentsRequested] = useState(false);
  const [missingGroups, setMissingGroups] = useState<string[]>([]);

  const checkStatus = (preview: RealClaimPreview | null) => {
    if (!preview) {
      setIsDocumentsRequested(false);
      setMissingGroups([]);
      return;
    }

    if ((preview.status || "").toUpperCase() === "DOCUMENTS_REQUESTED") {
      setIsDocumentsRequested(true);
      const docs = preview.documents || [];
      const kyc_types = ["aadhaar_card", "pan_card", "identity_proof"];
      const clinical_types = ["discharge_summary", "lab_report"];
      const financial_types = ["hospital_bill", "pharmacy_bill"];

      const hasKyc = docs.some(d => kyc_types.includes((d.doc_type || "").toLowerCase()));
      const hasClinical = docs.some(d => clinical_types.includes((d.doc_type || "").toLowerCase()));
      const hasFinancial = docs.some(d => financial_types.includes((d.doc_type || "").toLowerCase()));

      const missing = [];
      if (!hasClinical && !hasFinancial) missing.push("Hospital Documents (Discharge Summary / Hospital Bill)");
      if (!hasKyc) missing.push("Identity / KYC Proof (Aadhaar / PAN / Passport)");
      setMissingGroups(missing);
    } else {
      setIsDocumentsRequested(false);
      setMissingGroups([]);
    }
  };

  useEffect(() => {
    checkStatus(realPreview);
  }, [realPreview]);

  useEffect(() => {
    const documentKeys = getPreviewDocumentKeys(realPreview);

    if (documentKeys.length === 0) {
      setActiveDocumentId(null);
      return;
    }

    setActiveDocumentId((current) => (current && documentKeys.includes(current) ? current : documentKeys[0]));
  }, [realPreview?.claim_id, realPreview?.documents]);

  /* Helper to fetch list of past claims from backend */
  const reloadRecentClaims = async () => {
    try {
      const session = getStoredAuthSession();
      const patientId = session?.user?.id || userId || session?.user?.email || (session?.user?.name !== 'User' ? session?.user?.name : undefined);
      const claims = await fetchRecentClaims(patientId);
      if (claims && claims.length > 0) {
        setRecentClaims((prev) => {
          const merged = claims.map((newClaim) => {
            const existing = prev.find((p) => isSameClaimId(p.id, newClaim.id));
            if (existing && existing.progress) {
              const existingPct = existing.progress.percentage || 0;
              const newPct = newClaim.progress?.percentage || 0;
              if (existingPct >= newPct) {
                return {
                  ...newClaim,
                  status: existingPct >= 100 ? "COMPLETED" : (newClaim.status || existing.status),
                  progress: existing.progress,
                };
              }
            } else if (existing) {
              return {
                ...newClaim,
                status: existing.status || newClaim.status,
                progress: existing.progress,
              };
            }
            return newClaim;
          });

          // Preserve any locally created in-flight claims not yet returned by backend
          for (const existing of prev) {
            if (!merged.some((m) => isSameClaimId(m.id, existing.id))) {
              merged.push(existing);
            }
          }

          return sortClaimsNewestFirst(merged);
        });
      }
    } catch (err) {
      console.warn("Failed to load recent claims list:", err);
    }
  };

  /* Periodic background sync to keep claim statuses and names fresh without overlapping */
  useEffect(() => {
    let active = true;
    let isFetching = false;

    const runSync = async () => {
      if (isFetching || !active) return;
      isFetching = true;
      try {
        await reloadRecentClaims();
      } finally {
        isFetching = false;
      }
    };

    const interval = setInterval(runSync, 8000);
    return () => {
      active = false;
      clearInterval(interval);
    };
  }, []);

  /* On mount: load latest claim data for auditor workspace & recent claims list */
  useEffect(() => {
    async function loadInitial() {
      try {
        const session = getStoredAuthSession();
        let patientId: string | undefined = session?.user?.id || session?.user?.email;
        if (!patientId) {
          if (session?.user?.name && session.user.name !== 'User') {
            patientId = session.user.name;
          } else {
            const savedName = localStorage.getItem('claimgpt_user_name');
            if (savedName && savedName !== 'User') patientId = savedName;
          }
        }

        const claims = await fetchRecentClaims(patientId);
        if (claims && claims.length > 0) {
          setRecentClaims((prev) => {
            const merged = claims.map((newClaim) => {
              const existing = prev.find((p) => isSameClaimId(p.id, newClaim.id));
              if (existing && existing.progress) {
                const existingPct = existing.progress.percentage || 0;
                const newPct = newClaim.progress?.percentage || 0;
                if (existingPct >= newPct) {
                  return {
                    ...newClaim,
                    status: existingPct >= 100 ? "COMPLETED" : (newClaim.status || existing.status),
                    progress: existing.progress,
                  };
                }
              } else if (existing) {
                return {
                  ...newClaim,
                  status: existing.status || newClaim.status,
                  progress: existing.progress,
                };
              }
              return newClaim;
            });
            for (const existing of prev) {
              if (!merged.some((m) => isSameClaimId(m.id, existing.id))) {
                merged.push(existing);
              }
            }
            return sortClaimsNewestFirst(merged);
          });
        }

        // Determine target active claim: prefer saved in-flight claim, else latest
        const savedActiveId = localStorage.getItem("claimgpt_active_claim_id");
        const effectiveList = (claims && claims.length > 0) ? claims : recentClaims;
        const targetId = (savedActiveId && effectiveList.some((c) => isSameClaimId(c.id, savedActiveId)))
          ? savedActiveId
          : (effectiveList.length > 0 ? effectiveList[0].id : null);

        if (targetId) {
          activeClaimIdRef.current = targetId;
          setClaimId(targetId);
          setIsUploadOpen(false); // Collapse upload panel when existing claim is loaded

          const targetMeta = effectiveList.find((c) => isSameClaimId(c.id, targetId));
          const rawStatus = (targetMeta?.status || "").toUpperCase();
          const isCompletedStatus = rawStatus === "COMPLETED" || rawStatus === "VALIDATED";
          const hasIncompleteProgress = targetMeta?.progress?.percentage !== undefined && targetMeta.progress.percentage < 100;
          const isKnownActive = hasIncompleteProgress || (!isCompletedStatus && isProcessingStatus(rawStatus));

          const statusInfo = await fetchClaimProgress(targetId);
          if (statusInfo?.not_found || statusInfo?.status === "NOT_FOUND") {
            setClaimId(null);
            setRealPreview(null);
            setFiles([]);
            setProgress(0);
            setActiveStage('staged');
            setIsUploadOpen(true);
            return;
          }

          const isComplete = Boolean(
            statusInfo?.is_complete ||
            (statusInfo?.percentage ?? 0) >= 100 ||
            statusInfo?.status === "COMPLETED" ||
            statusInfo?.status === "VALIDATED"
          );

          if (!isComplete || isKnownActive) {
            setAnalyzing(true);
            setIsLiveSessionCompleted(false);
            const livePct = Math.max(statusInfo?.percentage || 20, targetMeta?.progress?.percentage || 20);
            updateProgressAndStage(livePct, statusInfo?.step ? `${statusInfo.step} - ${livePct}%` : undefined, true);
            if (!activePollsRef.current.has(targetId)) {
              runProgressSequence(targetId);
            }
          } else {
            const prevData = await fetchClaimPreview(targetId);
            if (prevData) {
              setRealPreview(prevData);
              setPreviewVersion((v) => v + 1);
            }
            const statusUpper = (prevData?.status || statusInfo?.status || "").toUpperCase();
            if (statusUpper === "DOCUMENTS_REQUESTED" || statusUpper === "MANUAL_REVIEW_REQUIRED") {
              setAnalyzing(false);
              setIsLiveSessionCompleted(false);
              setIsDocumentsRequested(statusUpper === "DOCUMENTS_REQUESTED");
              updateProgressAndStage(100, statusUpper === "DOCUMENTS_REQUESTED" ? "Documents Requested" : "Manual Review Required", true);
            } else {
              setAnalyzing(false);
              setIsLiveSessionCompleted(true);
              setIsDocumentsRequested(false);
              const finalPct = targetMeta?.progress?.percentage !== undefined ? targetMeta.progress.percentage : 100;
              updateProgressAndStage(finalPct, "Claim Analysis 100% Complete", true);
            }
          }
        } else {
          setClaimId(null);
          setRealPreview(null);
          setFiles([]);
          setProgress(0);
          setActiveStage('staged');
          setIsUploadOpen(true);
        }
      } catch (err) {
        console.warn("Could not load initial claim data on mount:", err);
      } finally {
        setIsLoadingClaims(false);
      }
    }
    loadInitial();
  }, [userName]);

  /* Remove a claim from local UI state and delete it from Docker backend */
  const deleteClaim = async (idToDelete: string, e?: React.MouseEvent) => {
    if (e) e.stopPropagation();

    const remaining = recentClaims.filter((c) => !isSameClaimId(c.id, idToDelete));
    setRecentClaims(remaining);

    // If deleting the currently active claim or all claims are deleted
    if (isSameClaimId(idToDelete, claimId) || remaining.length === 0) {
      if (remaining.length > 0) {
        // Automatically switch to the next available claim
        selectClaim(remaining[0].id);
      } else {
        // All claims deleted — reset workspace to clean empty state!
        setClaimId(null);
        setRealPreview(null);
        setFiles([]);
        setProgress(0);
        setActiveStage('staged');
        setIsLiveSessionCompleted(false);
        setActiveDocumentId(null);
        setHoveredField(null);
        setIsUploadOpen(true);
      }
    }

    try {
      await deleteClaimApi(idToDelete);
      let patientId: string | undefined = undefined;
      const session = getStoredAuthSession();
      if (session?.user?.name) {
        patientId = session.user.name;
      } else {
        const savedName = localStorage.getItem('claimgpt_user_name');
        if (savedName) patientId = savedName;
      }
      const remainingClaims = await fetchRecentClaims(patientId);
      setRecentClaims(remainingClaims);
    } catch (err) {
      console.warn("Backend deletion error:", err);
    }
  };

  /* Select any previous claim from history list */
  const selectClaim = async (targetId: string) => {
    if (!targetId) return;

    const targetClaimMeta = recentClaims.find((c) => isSameClaimId(c.id, targetId));
    const rawStatus = (targetClaimMeta?.status || "").toUpperCase();
    const isCompletedStatus = rawStatus === "COMPLETED" || rawStatus === "VALIDATED";
    const hasIncompleteProgress = targetClaimMeta?.progress?.percentage !== undefined && targetClaimMeta.progress.percentage < 100;
    const isKnownActive = hasIncompleteProgress || (!isCompletedStatus && isProcessingStatus(rawStatus));

    activeClaimIdRef.current = targetId;
    setClaimId(targetId);
    setIsUploadOpen(false); // Auto-collapse upload dropdown when selecting old claims
    setEdited({}); // Reset edit badges from previous claim

    // Determine target claim's EXACT progress (DO NOT inherit from previous claim!)
    const initialPct = targetClaimMeta?.progress?.percentage !== undefined
      ? targetClaimMeta.progress.percentage
      : (isCompletedStatus ? 100 : (rawStatus === "UPLOADED" ? 20 : 55));
    const initialStep = targetClaimMeta?.progress?.step || (initialPct >= 100 ? "Claim Analysis 100% Complete" : (rawStatus === "UPLOADED" ? "OCR (extracting text) - 20%" : `Processing - ${initialPct}%`));

    // Synchronously set analyzing state and progress so there is 0ms glitch or flicker
    if (isKnownActive || activePollsRef.current.has(targetId)) {
      setAnalyzing(true);
      setIsLiveSessionCompleted(false);
      updateProgressAndStage(initialPct, initialStep, true);
      if (!activePollsRef.current.has(targetId)) {
        runProgressSequence(targetId);
      }
    } else {
      setAnalyzing(false);
      setIsLiveSessionCompleted(initialPct >= 100);
      setIsDocumentsRequested(false);
      updateProgressAndStage(initialPct, initialStep, true);
    }

    try {
      const statusInfo = await fetchClaimProgress(targetId);
      if (statusInfo?.not_found || statusInfo?.status === "NOT_FOUND") {
        setAnalyzing(false);
        setIsLiveSessionCompleted(false);
        setClaimId(null);
        setRealPreview(null);
        reloadRecentClaims();
        return;
      }

      const isComplete = Boolean(
        statusInfo?.is_complete ||
        (statusInfo?.percentage ?? 0) >= 100 ||
        statusInfo?.status === "COMPLETED" ||
        statusInfo?.status === "VALIDATED"
      );

      if (!isComplete) {
        setAnalyzing(true);
        setIsLiveSessionCompleted(false);
        const livePct = Math.max(statusInfo?.percentage || 20, targetClaimMeta?.progress?.percentage || 20);
        updateProgressAndStage(livePct, statusInfo?.step ? `${statusInfo.step} - ${livePct}%` : undefined, true);
        if (!activePollsRef.current.has(targetId)) {
          runProgressSequence(targetId);
        }
      } else {
        const prevData = await fetchClaimPreview(targetId);
        if (prevData) {
          setRealPreview(prevData);
          setPreviewVersion((v) => v + 1);
        }
        setRecentClaims((prev) =>
          prev.map((c) => (isSameClaimId(c.id, targetId) ? { ...c, status: "COMPLETED", progress: { percentage: 100, step: "AI Verification Complete", is_complete: true } } : c))
        );
        const statusUpper = (prevData?.status || statusInfo?.status || "").toUpperCase();
        if (statusUpper === "DOCUMENTS_REQUESTED" || statusUpper === "MANUAL_REVIEW_REQUIRED") {
          setAnalyzing(false);
          setIsLiveSessionCompleted(false);
          setIsDocumentsRequested(statusUpper === "DOCUMENTS_REQUESTED");
          updateProgressAndStage(100, statusUpper === "DOCUMENTS_REQUESTED" ? "Documents Requested" : "Manual Review Required", true);
        } else {
          setAnalyzing(false);
          setIsLiveSessionCompleted(false);
          setIsDocumentsRequested(false);
          updateProgressAndStage(100, "Claim Analysis 100% Complete", true);
        }
      }
    } catch (err) {
      console.warn("Failed to select claim preview:", err);
    }
  };

  /* Auto-scroll smoothly to Pipeline Progress Card whenever analysis starts */
  useEffect(() => {
    if (analyzing) {
      scrollToPipeline();
    }
  }, [analyzing]);

  /* Dynamically extracted metadata fields from backend preview */
  const extractedPatient = realPreview?.summary?.patient_name && realPreview.summary.patient_name !== "N/A"
    ? realPreview.summary.patient_name
    : realPreview?.parsed_fields?.patient_name || realPreview?.parsed_fields?.member_name || realPreview?.parsed_fields?.insured_name;

  const extractedHospital = realPreview?.summary?.hospital && realPreview.summary.hospital !== "N/A"
    ? realPreview.summary.hospital
    : realPreview?.parsed_fields?.hospital_name || realPreview?.parsed_fields?.hospital;

  const extractedAdmission = realPreview?.summary?.admission_date && realPreview.summary.admission_date !== "N/A"
    ? realPreview.summary.admission_date
    : realPreview?.parsed_fields?.admission_date || realPreview?.parsed_fields?.service_date;

  const extractedDischarge = realPreview?.summary?.discharge_date && realPreview.summary.discharge_date !== "N/A"
    ? realPreview.summary.discharge_date
    : realPreview?.parsed_fields?.discharge_date;

  const extractedDiagnosis = realPreview?.summary?.diagnosis && realPreview.summary.diagnosis !== "N/A"
    ? realPreview.summary.diagnosis
    : realPreview?.parsed_fields?.diagnosis || realPreview?.parsed_fields?.primary_diagnosis;

  const hasClaim = Boolean(claimId || realPreview);
  const patientName = extractedPatient || (analyzing ? "Processing..." : (hasClaim ? "Patient Record" : ""));
  const hospitalName = extractedHospital || (analyzing ? "Processing..." : (hasClaim ? "City Care Hospital" : ""));
  const admissionDate = extractedAdmission || (analyzing ? "Processing..." : (hasClaim ? "10/06/2026" : ""));
  const dischargeDate = extractedDischarge || (analyzing ? "Processing..." : (hasClaim ? "14/06/2026" : ""));
  const diagnosis = extractedDiagnosis || (analyzing ? "Processing..." : (hasClaim ? "Hospital Reimbursement Audit" : ""));

  /* Select file(s) without immediately analyzing — appends new files to pending list */
  /* Select file(s) without immediately analyzing — appends new files to pending list */
  const handleSelectFile = (input: any) => {
    let incoming: File[] = [];

    if (input && typeof input === "object" && "target" in input && input.target && (input.target as HTMLInputElement).files) {
      incoming = Array.from((input.target as HTMLInputElement).files || []);
    } else if (input && typeof input === "object" && "dataTransfer" in input && input.dataTransfer && input.dataTransfer.files) {
      incoming = Array.from(input.dataTransfer.files);
    } else if (Array.isArray(input)) {
      incoming = input;
    } else if (input instanceof File) {
      incoming = [input];
    } else if (input && typeof input === "object" && "length" in input) {
      incoming = Array.from(input as ArrayLike<File>);
    }

    if (incoming.length === 0) return;

    setIsUploadOpen(true); // Keep upload panel open when user selects files
    setPendingFiles((prev) => [...prev, ...incoming]);
    setFiles((prev) => [
      ...prev,
      ...incoming.map((f) => ({
        name: f.name,
        size: f.size > 1024 * 1024 ? `${(f.size / (1024 * 1024)).toFixed(1)} MB` : `${(f.size / 1024).toFixed(0)} KB`,
        type: f.type || (f.name.endsWith('.pdf') ? 'application/pdf' : 'image/png'),
        rawFile: f,
      })),
    ]);

    if (input && typeof input === "object" && "target" in input && input.target) {
      (input.target as HTMLInputElement).value = '';
    }
  };

  /* Remove individual attached file */
  const removeFile = (index: number) => {
    setPendingFiles((prev) => prev.filter((_, i) => i !== index));
    setFiles((prev) => prev.filter((_, i) => i !== index));
  };

  /* Reset upload state for new claim */
  const resetState = () => {
    setPendingFiles([]);
    setFiles([]);
    setClaimId(null);
    setRealPreview(null);
    setProgress(0);
    setActiveStage('staged');
    setStepDescription("Claim Attached");
    setAnalyzing(false);
    setUploading(false);
    setIsLiveSessionCompleted(false);
    setIsDocumentsRequested(false);
    setMissingGroups([]);
    setIsUploadOpen(true);
    setActiveDocumentId(null);
    activeClaimIdRef.current = null;
  };

  /* Direct upload & instant analysis */
  const handleUploadFile = async (fileInput: File | File[], appendToActive = false) => {
    handleSelectFile(fileInput);
    const filesToUpload = Array.isArray(fileInput) ? fileInput : [fileInput];
    await startClaimAnalysis(filesToUpload, appendToActive);
  };

  /* Progress animation + background data sync that keeps polling until real data arrives */
  const runProgressSequence = (targetClaimId: string | null) => {
    if (!targetClaimId) return;

    // Do not spawn duplicate pollers for the same claim
    if (activePollsRef.current.has(targetClaimId)) {
      return;
    }

    let dataArrived = false;

    const finishProgress = async () => {
      if (dataArrived) return;
      dataArrived = true;
      stopPollingClaim(targetClaimId);

      // Persist 100% in recentClaims for this claim
      updateClaimProgress(targetClaimId, 100, "Claim Analysis 100% Complete", "COMPLETED");

      // If user is currently looking at this claim, update main view
      if (isSameClaimId(activeClaimIdRef.current, targetClaimId)) {
        updateProgressAndStage(100, "Claim Analysis 100% Complete");
        setAnalyzing(false);
        setIsLiveSessionCompleted(true);

        const finalData = await fetchClaimPreview(targetClaimId);
        if (finalData) {
          setRealPreview(finalData);
          setPreviewVersion((v) => v + 1);
        }
      }
      reloadRecentClaims();
    };

    // Clean polling every 800ms directly syncing with Docker backend
    const pollStartTime = Date.now();
    const pollInterval = setInterval(async () => {
      if (dataArrived) {
        stopPollingClaim(targetClaimId);
        return;
      }

      if (Date.now() - pollStartTime > 180000) {
        await finishProgress();
        return;
      }

      const statusInfo = await fetchClaimProgress(targetClaimId);
      if (statusInfo) {
        if (statusInfo.not_found || statusInfo.status === "NOT_FOUND") {
          stopPollingClaim(targetClaimId);
          if (isSameClaimId(activeClaimIdRef.current, targetClaimId)) {
            setAnalyzing(false);
          }
          reloadRecentClaims();
          return;
        }

        if (statusInfo.is_complete || statusInfo.percentage >= 100 || statusInfo.status === "COMPLETED" || statusInfo.status === "VALIDATED") {
          if (isSameClaimId(activeClaimIdRef.current, targetClaimId)) {
            try {
              const finalData = await fetchClaimPreview(targetClaimId);
              if (finalData) {
                setRealPreview(finalData);
                setPreviewVersion((v) => v + 1);
                setClaimId(targetClaimId);
              }
            } catch {
              /* ignore preview fetch error */
            }
          }
          await finishProgress();
          return;
        }

        if (statusInfo.status === "DOCUMENTS_REQUESTED" || statusInfo.status === "MANUAL_REVIEW_REQUIRED") {
          stopPollingClaim(targetClaimId);
          updateClaimProgress(targetClaimId, 100, "Manual Review Required", statusInfo.status);
          if (isSameClaimId(activeClaimIdRef.current, targetClaimId)) {
            try {
              const finalData = await fetchClaimPreview(targetClaimId);
              if (finalData) {
                setRealPreview(finalData);
                setPreviewVersion((v) => v + 1);
                setClaimId(targetClaimId);
              }
            } catch {
              /* ignore preview fetch error */
            }
            setAnalyzing(false);
            setIsLiveSessionCompleted(false);
            setProgress(100);
            setActiveStage('scoring');
            setStepDescription("Manual Review Required");
          }
          dataArrived = true;
          return;
        }

        if (statusInfo.percentage > 0 && statusInfo.percentage < 100) {
          let stepLabel: string | undefined = undefined;
          if (statusInfo.step) {
            const stepUpper = statusInfo.step.toUpperCase();
            if (stepUpper.includes("OCR")) {
              stepLabel = `OCR (extracting text) - ${statusInfo.percentage}%`;
            } else if (stepUpper.includes("PARS") || stepUpper.includes("LLM") || stepUpper.includes("LAYOUT") || stepUpper.includes("TABLE")) {
              stepLabel = `Parsing (LLM agent reading document) - ${statusInfo.percentage}%`;
            } else if (stepUpper.includes("COD") || stepUpper.includes("ICD") || stepUpper.includes("CPT")) {
              stepLabel = `ICD-10 / CPT Coding - ${statusInfo.percentage}%`;
            } else if (stepUpper.includes("SCOR") || stepUpper.includes("COMPLIANCE") || stepUpper.includes("RISK")) {
              stepLabel = `Compliance & Risk Scoring - ${statusInfo.percentage}%`;
            } else {
              stepLabel = `${statusInfo.step} - ${statusInfo.percentage}%`;
            }
          }
          updateClaimProgress(targetClaimId, statusInfo.percentage, stepLabel, statusInfo.status);
        }
      }
    }, 800);

    activePollsRef.current.set(targetClaimId, pollInterval);
  };

  /* Begin Claim Analysis action button */
  const startClaimAnalysis = async (overrideFiles?: File | File[], appendToActive = false) => {
    let targetFiles: File[] = [];
    if (overrideFiles) {
      targetFiles = Array.isArray(overrideFiles) ? overrideFiles : [overrideFiles];
    } else {
      targetFiles = pendingFiles.length > 0 ? pendingFiles : files.map((f: any) => f.rawFile).filter(Boolean);
    }

    if (targetFiles.length === 0 && files.length === 0) return;

    // Clear all previous polling loops so only ONE active poller drives the UI
    activePollsRef.current.forEach((intervalId) => clearInterval(intervalId));
    activePollsRef.current.clear();

    if (!appendToActive) {
      setRealPreview(null);
      setClaimId(null);
      setIsDocumentsRequested(false);
      setMissingGroups([]);
    }

    setAnalyzing(true);
    setUploading(true);
    setShowReportModal(false);
    setIsLiveSessionCompleted(false);
    setIsUploadOpen(true); // Keep open during analysis to show circular progress
    setActiveStage('ocr');
    setProgress(20);
    setStepDescription("OCR (extracting text) · 20%");

    scrollToPipeline();

    let activeClaimId: string | null = null;
    try {
      const session = getStoredAuthSession();
      const userIdentifier = session?.user?.id || userId || session?.user?.email || userName;
      const res = await uploadClaimDocument(
        targetFiles.length > 0 ? targetFiles : files.map((f: any) => f.rawFile || new File([], f.name)),
        userIdentifier,
        (appendToActive && claimId) ? claimId : undefined
      );
      if (res.claim_id) {
        if (res.status === "COMPLETED" || res.task_id === null) {
          setDuplicateClaimId(res.claim_id);
          setAnalyzing(false);
          setUploading(false);
          setProgress(0);
          setActiveStage('staged');
          toast({
            title: "Duplicate Document Detected",
            description: "This exact set of documents has already been processed in a previous claim.",
          });
          return;
        }

        const normalizedClaimId = res.claim_id.toLowerCase();
        activeClaimId = normalizedClaimId;
        activeClaimIdRef.current = normalizedClaimId;
        setClaimId(normalizedClaimId);

        // Optimistically add the new processing claim to recentClaims at the top
        setRecentClaims((prev) => {
          const filtered = prev.filter((c) => !isSameClaimId(c.id, normalizedClaimId));
          const newEntry: RecentClaimSummary = {
            id: normalizedClaimId,
            patient_name: "Processing...",
            status: "UPLOADED",
            created_at: new Date().toISOString(),
            total_amount: "",
            documents: targetFiles.map((f, i) => ({ id: `doc-${i}`, file_name: f.name })),
            progress: {
              percentage: 20,
              step: "OCR (extracting text) - 20%",
            },
          };
          return sortClaimsNewestFirst([newEntry, ...filtered]);
        });

        // Try immediate prefetch for this claim ID
        const initialPreview = await fetchClaimPreview(res.claim_id);
        if (initialPreview) {
          setRealPreview(initialPreview);
          setPreviewVersion((v) => v + 1);
        }
      }
    } catch (err) {
      console.warn("Backend API upload error:", err);
    } finally {
      setUploading(false);
    }

    runProgressSequence(activeClaimId);
  };





  /* Manually open report modal and fetch selected or latest claim preview directly from backend */
  const openReportModal = async () => {
    try {
      const idToQuery = claimId || (await fetchLatestClaimId());
      if (idToQuery) {
        const prevData = await fetchClaimPreview(idToQuery);
        if (prevData) {
          setRealPreview(prevData);
          setPreviewVersion((v) => v + 1);
          setClaimId(idToQuery);
        }
      }
    } catch (err) {
      console.warn("Failed to load report modal preview:", err);
    }
    setShowReportModal(true);
  };

  /* Computed items & total */
  const lineItems: LineItem[] = realPreview?.expenses?.length
    ? realPreview.expenses.map((exp, idx) => ({
      id: `exp-${idx}`,
      category: exp.category || "Expense",
      description: exp.description || exp.category,
      amount: exp.amount || 0,
      box: { x: 8, y: 30 + idx * 10, w: 84, h: 7 },
    }))
    : (analyzing || (progress < 100 && !realPreview?.expenses?.length) ? [] : LINE_ITEMS);

  const total = lineItems.reduce((sum, i) => sum + i.amount, 0);
  const stageIndex = PIPELINE.findIndex((s) => s.key === activeStage);

  const markEdited = (key: string) =>
    setEdited((e) => (e[key] ? e : { ...e, [key]: true }));

  /* Resolve enrolled TPA / Insurer from registration, profile, or preview */
  const enrolledTpa = useMemo(() => {
    try {
      const email = userEmail || "";
      const name = userName || "";
      const session = getStoredAuthSession();
      const sessionEmail = session?.user?.email || "";
      const sessionName = session?.user?.name || "";

      const stored =
        (sessionEmail && localStorage.getItem(`claimgpt_user_insurer_${sessionEmail}`)) ||
        (sessionName && localStorage.getItem(`claimgpt_user_insurer_${sessionName}`)) ||
        (email && localStorage.getItem(`claimgpt_user_insurer_${email}`)) ||
        (name && localStorage.getItem(`claimgpt_user_insurer_${name}`)) ||
        localStorage.getItem("claimgpt_user_insurer") ||
        (sessionEmail && localStorage.getItem(`claimgpt_user_org_${sessionEmail}`)) ||
        (sessionName && localStorage.getItem(`claimgpt_user_org_${sessionName}`)) ||
        (email && localStorage.getItem(`claimgpt_user_org_${email}`)) ||
        (name && localStorage.getItem(`claimgpt_user_org_${name}`)) ||
        localStorage.getItem("claimgpt_user_org") ||
        (realPreview?.summary as any)?.insurer ||
        (realPreview?.parsed_fields as any)?.insurer ||
        (realPreview?.parsed_fields as any)?.insurance_company ||
        (realPreview?.parsed_fields as any)?.tpa_name ||
        "Star Health";
      return stored;
    } catch {
      return "Star Health";
    }
  }, [userEmail, userName, realPreview]);

  const tpaParam = enrolledTpa ? `&tpa_name=${encodeURIComponent(enrolledTpa)}` : "";

  /* PDF Report URLs */
  const tpaPdfUrl = claimId ? `${SUBMISSION_API}/claims/${claimId}/tpa-pdf?${tpaParam.slice(1)}` : null;
  const irdaPdfUrl = claimId ? `${SUBMISSION_API}/claims/${claimId}/irda-pdf` : null;
  const tpaPdfViewUrl = claimId ? `${SUBMISSION_API}/claims/${claimId}/tpa-pdf?view=true${tpaParam}` : null;
  const irdaPdfViewUrl = claimId ? `${SUBMISSION_API}/claims/${claimId}/irda-pdf?view=true` : null;

  /* Detect Patient Name Mismatch warning from backend preview */
  const nameMismatchWarning = useMemo(() => {
    return null; // Disabled as requested to support family/third-party uploads
  }, [realPreview]);

  const saveExpenses = async (expensesList: Array<{ category: string; amount: number }>) => {
    setRealPreview((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        expenses: expensesList.map((e) => ({
          category: e.category,
          amount: e.amount,
        })),
        billed_total: expensesList.reduce((sum, e) => sum + e.amount, 0),
      };
    });
    if (!claimId) return;
    const success = await saveClaimExpensesApi(claimId, expensesList);
    if (success) {
      const prevData = await fetchClaimPreview(claimId);
      if (prevData) {
        setRealPreview(prevData);
      }
      toast({
        title: "Success",
        description: "Expenses saved successfully.",
      });
    } else {
      toast({
        title: "Success",
        description: "Expenses updated locally.",
      });
    }
  };

  const saveDetails = async (details: Record<string, string>) => {
    if (!claimId) return;
    const success = await saveClaimDetailsApi(claimId, details);
    if (success) {
      const prevData = await fetchClaimPreview(claimId);
      if (prevData) {
        setRealPreview(prevData);
      }
      toast({
        title: "Success",
        description: "Details saved successfully.",
      });
    } else {
      toast({
        title: "Error",
        description: "Failed to save details.",
        variant: "destructive",
      });
    }
  };

  return {
    progress,
    setProgress,
    resetState,
    activeStage,
    setActiveStage,
    files,
    setFiles,
    pendingFiles,
    removeFile,
    hoveredField,
    setHoveredField,
    zoom,
    setZoom,
    edited,
    markEdited,
    activeDocumentId,
    setActiveDocumentId,
    total,
    stageIndex,
    lineItems,
    /* Real Backend Extensions */
    claimId,
    uploading,
    analyzing,
    isUploadOpen,
    setIsUploadOpen,
    toggleUploadOpen,
    isLiveSessionCompleted,
    stepDescription,
    handleSelectFile,
    handleUploadFile,
    startClaimAnalysis,
    realPreview,
    nameMismatchWarning,
    showReportModal,
    setShowReportModal,
    openReportModal,
    closeReportModal: () => setShowReportModal(false),
    showDocModal,
    setShowDocModal,
    openDocModal,
    closeDocModal,
    patientName,
    hospitalName,
    admissionDate,
    dischargeDate,
    diagnosis,
    tpaPdfUrl,
    irdaPdfUrl,
    tpaPdfViewUrl,
    irdaPdfViewUrl,
    recentClaims,
    isLoadingClaims,
    selectClaim,
    deleteClaim,
    deleteDocument,
    reloadRecentClaims,
    isDocumentsRequested,
    missingGroups,
    previewVersion,
    userId,
    userName,
    setUserName,
    userEmail,
    setUserEmail,
    showProfileModal,
    setShowProfileModal,
    openProfileModal: () => setShowProfileModal(true),
    closeProfileModal: () => setShowProfileModal(false),
    showMenuDrawer,
    setShowMenuDrawer,
    openMenuDrawer: () => setShowMenuDrawer(true),
    closeMenuDrawer: () => setShowMenuDrawer(false),
    duplicateClaimId,
    setDuplicateClaimId,
    saveExpenses,
    saveDetails,
  };
}

export type AuditorState = ReturnType<typeof useAuditorState>;

export { LINE_ITEMS, PIPELINE, formatINR };

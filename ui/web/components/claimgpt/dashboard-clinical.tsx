'use client';

import { useState, useEffect, useMemo } from 'react';
import fullLogo from './ClaimsGuru Black PNG.png';

import {
  AlertTriangle,
  Bell,
  Camera,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock,
  FileText,
  Folder,
  Image as ImageIcon,
  Plus,
  Search,
  ShieldCheck,
  Sparkles,
  Trash2,
  Upload,
  X,
  Menu,
  Loader2,
} from 'lucide-react';
import { LanguageSwitcher } from '@/components/claimgpt/language-switcher';
import { DuplicateClaimModal } from '@/components/claimgpt/duplicate-modal';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { DocumentViewer } from '@/components/claimgpt/document-viewer';
import { ClaimReportModal } from '@/components/claimgpt/claim-report-modal';
import { DocumentPreviewModal } from '@/components/claimgpt/document-preview-modal';
import { UserProfileModal } from '@/components/claimgpt/user-profile-modal';
import { NotificationBell } from '@/components/claimgpt/notification-bell';
import { UserAvatar } from '@/components/claimgpt/user-avatar';
import {
  LINE_ITEMS,
  PIPELINE,
  formatINR,
  useAuditorState,
  isSameClaimId,
  sortClaimsNewestFirst,
} from '@/components/claimgpt/use-auditor-state';
import { PIPELINE_ACTIVE_STATUSES, isProcessingStatus } from '@/lib/api-client';
import {
  CountUp,
  MagneticButton,
  SpotlightCard,
  StaggerContainer,
  StaggerItem,
} from '@/components/claimgpt/effects';
import { cn } from '@/lib/utils';
import { formatClaimTime, formatClaimAge } from '@/lib/claimgpt-data';

function getStageBadgeLabel(progress: number, step?: string): string {
  const stepUpper = (step || "").toUpperCase();
  if (progress >= 100) return "Ready";
  if (stepUpper.includes("OCR") || progress <= 20) return "OCR";
  if (stepUpper.includes("PARS") || stepUpper.includes("LLM") || progress <= 70) return "Parsing";
  if (stepUpper.includes("COD") || stepUpper.includes("ICD") || stepUpper.includes("CPT") || progress <= 85) return "Coding";
  if (stepUpper.includes("SCOR") || stepUpper.includes("COMPLIANCE") || stepUpper.includes("RISK")) return "Scoring";
  return progress <= 20 ? "OCR" : "Processing";
}

export function DashboardClinical() {
  const s = useAuditorState();
  const [claimToDelete, setClaimToDelete] = useState<{ id: string; name: string } | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [isSearchFocused, setIsSearchFocused] = useState(false);

  // Merge currently active processing claim into the list if not already present
  const allClaims = useMemo(() => {
    let list = [...s.recentClaims];
    if (s.claimId && !list.some((c) => isSameClaimId(c.id, s.claimId))) {
      list.unshift({
        id: s.claimId,
        patient_name: s.patientName || (s.analyzing ? "Processing..." : "Active Claim"),
        status: s.analyzing ? (s.activeStage === "ocr" ? "UPLOADED" : "PARSING") : "COMPLETED",
        created_at: new Date().toISOString(),
        total_amount: "",
        documents: s.files.map((f, i) => ({ id: `doc-${i}`, file_name: f.name })),
        progress: {
          percentage: s.progress,
          step: s.stepDescription,
          is_complete: s.progress >= 100,
        },
      } as any);
    }
    return sortClaimsNewestFirst(list);
  }, [s.recentClaims, s.claimId, s.patientName, s.analyzing, s.activeStage, s.progress, s.stepDescription, s.files]);

  const filteredClaims = allClaims.filter((claim) => {
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase().trim();
    const rawId = (claim.id || "").toLowerCase();
    const shortId = rawId.replace(/-/g, "");
    const patientName = (claim.patient_name || "").toLowerCase();
    const hospitalName = (claim.hospital_name || "").toLowerCase();
    const diagnosis = (claim.diagnosis || "").toLowerCase();
    const policyId = (claim.policy_id || "").toLowerCase();
    const patientId = (claim.patient_id || "").toLowerCase();
    const docNames = (claim.documents || []).map((d: any) => (d.file_name || d.display_title || "").toLowerCase()).join(" ");

    return (
      rawId.includes(q) ||
      shortId.includes(q) ||
      patientName.includes(q) ||
      hospitalName.includes(q) ||
      diagnosis.includes(q) ||
      policyId.includes(q) ||
      patientId.includes(q) ||
      docNames.includes(q)
    );
  });

  const processingInList = s.recentClaims.filter((c) => {
    const st = (c.status || "").toUpperCase();
    return st === "PENDING" || st === "PROCESSING" || st === "IN_PROGRESS" || st === "QUEUED" || (st !== "COMPLETED" && st !== "VALIDATED" && st !== "FINISHED" && st !== "REJECTED");
  });

  const isCurrentClaimProcessing = (s.progress > 0 && s.progress < 100) || s.uploading || s.analyzing;
  const currentInList = processingInList.some((c) => c.id === s.claimId);

  const activeQueueCount = processingInList.length + (isCurrentClaimProcessing && !currentInList ? 1 : 0);

  const hasActiveClaim = Boolean(
    s.claimId ||
    s.realPreview ||
    s.recentClaims.length > 0 ||
    s.analyzing ||
    s.isLiveSessionCompleted
  );

  const isUploadOpenEffective = s.isUploadOpen;

  return (
    <div className="relative flex flex-col min-h-screen overflow-x-hidden bg-slate-100/80 text-foreground">
      {/* Header */}
      <header className="sticky top-0 z-40 border-b border-border bg-white/90 backdrop-blur-md">
        <div className="flex h-16 items-center justify-between gap-2 px-3 sm:px-6">
          <div className="flex items-center gap-2 sm:gap-2.5 min-w-0">
            <img src={fullLogo.src} className="h-7 sm:h-8 w-auto flex-none" alt="ClaimsGuru Logo" />
            <span className="rounded bg-teal-50 px-2 py-0.5 text-[9px] sm:text-[10px] font-semibold text-teal-700 whitespace-nowrap flex-none">
              <span className="hidden sm:inline">Self-Service Portal</span>
              <span className="sm:hidden">Clinical</span>
            </span>
          </div>
          <div className="relative ml-4 hidden flex-1 max-w-md md:block">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onFocus={() => setIsSearchFocused(true)}
              onBlur={() => {
                setTimeout(() => setIsSearchFocused(false), 200);
              }}
              placeholder="Search claims, hospital bills, ICD-10 codes…"
              className="h-10 border-slate-200 bg-slate-50 pl-10 pr-9 text-sm focus-visible:bg-white focus-visible:ring-2 focus-visible:ring-teal-500 rounded-xl transition-all"
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery('')}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 p-0.5 rounded-full hover:bg-slate-200 transition-colors"
                title="Clear search"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}

            {/* Quick Match Results Dropdown when focused & typing */}
            {isSearchFocused && searchQuery.trim() && (
              <div 
                className="absolute left-0 right-0 top-full mt-1.5 z-50 rounded-xl border border-slate-200 bg-white shadow-xl overflow-hidden p-1.5 space-y-1 animate-in fade-in zoom-in-95 duration-100 max-h-80 overflow-y-auto"
                onMouseDown={(e) => e.preventDefault()}
              >
                <div className="px-2.5 py-1 text-[11px] font-semibold text-slate-400 uppercase tracking-wider flex items-center justify-between">
                  <span>Matching Claims ({filteredClaims.length})</span>
                  {filteredClaims.length > 0 && <span className="text-[10px] text-teal-600 font-normal">Click to audit</span>}
                </div>
                {filteredClaims.length === 0 ? (
                  <div className="p-4 text-center text-xs text-slate-500">
                    No claims found for &ldquo;<span className="font-semibold text-slate-700">{searchQuery}</span>&rdquo;
                  </div>
                ) : (
                  filteredClaims.map((c) => {
                    const cShortId = (c.id || "").replace(/-/g, "").slice(-8).toUpperCase();
                    const isSelected = c.id === s.claimId;
                    return (
                      <div
                        key={c.id}
                        role="button"
                        tabIndex={0}
                        onClick={() => {
                          s.selectClaim(c.id);
                          setIsSearchFocused(false);
                        }}
                        className={cn(
                          "flex items-center justify-between gap-3 px-3 py-2 rounded-lg text-xs cursor-pointer transition-colors",
                          isSelected ? "bg-teal-50 text-teal-900 border border-teal-200" : "hover:bg-slate-100 text-slate-800"
                        )}
                      >
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-1.5 font-semibold truncate">
                            <span>{c.patient_name || `Claim #${cShortId}`}</span>
                            <span className="text-[10px] font-mono text-slate-400">#{cShortId}</span>
                          </div>
                          <div className="text-[11px] text-slate-500 truncate">
                            {c.documents?.[0]?.file_name || c.hospital_name || c.diagnosis || "Medical Claim Document"}
                          </div>
                        </div>
                        <div className="flex-none flex items-center gap-1.5">
                          <span className="text-[10px] text-slate-400 whitespace-nowrap">{formatClaimTime(c.created_at)}</span>
                          <span className={cn(
                            "px-1.5 py-0.5 rounded text-[9px] font-bold uppercase",
                            c.status === "COMPLETED" ? "bg-emerald-100 text-emerald-800" : "bg-blue-100 text-blue-800"
                          )}>
                            {c.status || "COMPLETED"}
                          </span>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            )}
          </div>
          <div className="ml-auto flex items-center gap-2 sm:gap-3">
            <span className="hidden items-center gap-1.5 rounded-full border border-teal-200 bg-teal-50 px-3 py-1.5 text-xs font-semibold text-teal-700 sm:inline-flex">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-teal-500 opacity-60" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-teal-600" />
              </span>
              Processing Queue: <CountUp end={activeQueueCount} />
            </span>
            <LanguageSwitcher variant="light" />
            <NotificationBell variant="clinical" />
            <button
              type="button"
              onClick={s.openProfileModal}
              title={`${s.userName} (${s.userEmail})`}
              className="cursor-pointer hover:scale-105 transition-transform rounded-full focus:outline-none focus:ring-2 focus:ring-teal-500"
              aria-label="User Profile"
            >
              <UserAvatar name={s.userName} size="md" />
            </button>
          </div>
        </div>
      </header>

      <main className="relative z-10 flex-1 px-4 py-6 sm:px-6 lg:px-8">
        <StaggerContainer className="mx-auto max-w-7xl space-y-6 pb-24">
          <StaggerItem index={0}>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h1 className="font-display text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">Patient Claim Reimbursement Portal</h1>
                <p className="mt-1 text-sm text-slate-600">Upload hospital bills, discharge summaries &amp; diagnostic reports for AI-powered verification &amp; settlement.</p>
              </div>
            </div>
          </StaggerItem>

          {/* Responsive Desktop & Mobile Grid */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-4 lg:items-start">

            {/* Desktop Left Sidebar: Processed Claims History */}
            <StaggerItem index={1} className="hidden lg:block lg:col-span-1">
              <div id="processed-claims-section" className="rounded-xl border border-border bg-white p-4 shadow-elevation-sm">
                <div className="mb-3 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent/10 text-accent">
                      <Clock className="h-4 w-4" />
                    </div>
                    <div>
                      <h3 className="text-xs font-bold text-foreground uppercase tracking-wider">Processed Claims</h3>
                      <p className="text-[10px] text-muted-foreground">Select claim to audit</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5">
                    {searchQuery.trim() && (
                      <button
                        type="button"
                        onClick={() => setSearchQuery('')}
                        className="text-[10px] text-teal-600 hover:text-teal-800 font-semibold cursor-pointer underline mr-0.5"
                      >
                        Clear
                      </button>
                    )}
                    <span className="rounded-full bg-accent/10 px-2.5 py-0.5 text-[11px] font-semibold text-accent">
                      {searchQuery.trim() ? `${filteredClaims.length}/${allClaims.length}` : allClaims.length}
                    </span>
                  </div>
                </div>

                <div className="flex flex-col gap-2 overflow-y-auto max-h-[720px] pr-1 scrollbar-thin">
                  {filteredClaims.length === 0 ? (
                    searchQuery.trim() && s.recentClaims.length > 0 ? (
                      <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border bg-slate-50/80 p-5 text-center my-1">
                        <p className="text-xs font-bold text-slate-700">No Matching Claims</p>
                        <p className="text-[10px] text-slate-500 mt-1 max-w-[150px] leading-tight">
                          No claims match &ldquo;{searchQuery}&rdquo;.
                        </p>
                        <button
                          type="button"
                          onClick={() => setSearchQuery('')}
                          className="mt-2 text-[11px] font-semibold text-teal-600 hover:text-teal-700 underline cursor-pointer"
                        >
                          Clear Filter
                        </button>
                      </div>
                    ) : s.claimId ? (
                      <button
                        type="button"
                        onClick={() => s.selectClaim(s.claimId || "")}
                        className="w-full rounded-xl border border-accent bg-accent/10 p-3 text-left shadow-sm"
                      >
                        <div className="flex items-center justify-between gap-1">
                          <p className="text-xs font-bold truncate text-foreground">{s.patientName || "Active Patient"}</p>
                          <span className="flex h-2 w-2 rounded-full bg-emerald-500 flex-none" />
                        </div>
                        <p className="text-[10px] text-muted-foreground mt-1 truncate">
                          ID: {s.claimId.slice(0, 8)}...
                        </p>
                      </button>
                    ) : s.isLoadingClaims ? (
                      <div className="space-y-2 p-1">
                        {[1, 2, 3].map((n) => (
                          <div key={n} className="rounded-2xl border border-slate-100 bg-white/70 p-3.5 space-y-2 animate-pulse">
                            <div className="flex items-center justify-between">
                              <div className="h-4 w-24 bg-slate-200 rounded" />
                              <div className="h-4 w-12 bg-slate-100 rounded-full" />
                            </div>
                            <div className="h-3 w-32 bg-slate-100 rounded" />
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border bg-slate-50/80 p-5 text-center my-1">
                        <div className="flex h-9 w-9 items-center justify-center rounded-full bg-slate-200 text-slate-500 mb-2">
                          <FileText className="h-4 w-4" />
                        </div>
                        <p className="text-xs font-bold text-slate-700">No Claims Found</p>
                        <p className="text-[10px] text-slate-500 mt-1 max-w-[150px] leading-tight">
                          Upload your claim documents to start AI verification.
                        </p>
                      </div>
                    )
                  ) : (
                    filteredClaims.map((claim) => {
                      const isSelected = String(claim.id || "").toLowerCase() === String(s.claimId || "").toLowerCase();
                      const claimName = claim.patient_name && claim.patient_name !== "N/A" ? claim.patient_name : `Claim #${claim.id.slice(0, 6)}`;
                      const docs = (claim.documents && claim.documents.length > 0)
                        ? claim.documents
                        : (isSelected && s.analyzing && s.files.length > 0 ? s.files.map((f, i) => ({ id: `f-${i}`, file_name: f.name })) : []);
                      const isCompletedStatus = (claim.status || "").toUpperCase() === "COMPLETED" || (claim.status || "").toUpperCase() === "VALIDATED";
                      const isClaimActiveStatus = isProcessingStatus(claim.status) || PIPELINE_ACTIVE_STATUSES.has((claim.status || "").toUpperCase());
                      const hasIncompleteProgress = claim.progress?.percentage !== undefined && claim.progress.percentage < 100;
                      const isClaimProcessing = hasIncompleteProgress || (!isCompletedStatus && isClaimActiveStatus) || (isSelected && s.analyzing);
                      const isClaimSelected = isSelected;
                      const currentProgress = (isClaimSelected && s.analyzing)
                        ? s.progress
                        : (claim.progress?.percentage !== undefined ? claim.progress.percentage : (isCompletedStatus ? 100 : (claim.status === "UPLOADED" ? 20 : (isClaimActiveStatus ? 55 : 20))));
                      const currentStep = (isClaimSelected && s.analyzing && s.stepDescription)
                        ? s.stepDescription
                        : (claim.progress?.step || (claim.status === "UPLOADED" ? "OCR (extracting text) - 20%" : (isCompletedStatus ? "AI Verification Complete" : `Processing - ${currentProgress}%`)));
                      const shortId = (claim.id || "").replace(/-/g, "").slice(-8).toUpperCase();

                      return (
                        <div
                          key={claim.id}
                          onClick={() => s.selectClaim(claim.id)}
                          className={cn(
                            "w-full rounded-2xl border p-3.5 text-left transition-all tap-highlight-none space-y-2 cursor-pointer",
                            isSelected
                              ? "border-blue-400 bg-white shadow-md ring-1 ring-blue-300"
                              : "border-slate-200 bg-white/80 hover:bg-white shadow-2xs"
                          )}
                        >
                          {/* Top Row: Short ID, Date, SLA, Delete X */}
                          <div className="flex items-center justify-between gap-1 text-[10px]">
                            <div className="flex items-center gap-1.5 min-w-0">
                              <span className="rounded bg-blue-50 text-blue-700 font-mono font-bold px-1.5 py-0.5 text-[9px] border border-blue-200">
                                #{shortId || "CLM001"}
                              </span>
                              <span className="text-[10px] text-slate-400 whitespace-nowrap">
                                {formatClaimTime(claim.created_at)}
                              </span>
                            </div>
                            <div className="flex items-center gap-1 flex-none">
                              <span className="rounded-full bg-emerald-100 text-emerald-800 px-1.5 py-0.2 text-[9px] font-bold">
                                {formatClaimAge(claim.created_at)}
                              </span>
                              <span
                                role="button"
                                tabIndex={0}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setClaimToDelete({ id: claim.id, name: claimName });
                                }}
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter' || e.key === ' ') {
                                    e.stopPropagation();
                                    setClaimToDelete({ id: claim.id, name: claimName });
                                  }
                                }}
                                className="p-1 rounded-md text-slate-400 hover:text-rose-600 hover:bg-rose-50 transition-colors cursor-pointer"
                                title="Delete claim"
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </span>
                            </div>
                          </div>

                          {/* Person / Policy Info */}
                          <div className="flex items-center gap-2 text-[10px] text-slate-500 font-medium">
                            <span className="truncate">👤 {claim.patient_name || "mattanivas"}</span>
                            <span className="truncate">🆔 {claim.id.slice(0, 10)}</span>
                          </div>

                          {/* Group Name Header */}
                          <div className="flex items-center gap-1.5 text-xs font-bold text-slate-800 pt-0.5">
                            <FileText className="h-3.5 w-3.5 text-slate-400 flex-none" />
                            <span className="truncate">{claimName}&apos;s - {docs.length} document{docs.length !== 1 ? "s" : ""}</span>
                          </div>

                          {/* Document Rows */}
                          {docs.length > 0 && (
                            <div className="space-y-1">
                              {docs.map((d: any) => (
                                <div
                                  key={d.id || d.file_name}
                                  className="flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50/70 px-2.5 py-1 text-[11px] font-medium text-slate-700"
                                >
                                  <div className="flex items-center gap-1.5 min-w-0">
                                    {d.file_name.endsWith('.pdf') ? (
                                      <FileText className="h-3 w-3 text-red-500 flex-none" />
                                    ) : (
                                      <ImageIcon className="h-3 w-3 text-teal-600 flex-none" />
                                    )}
                                    <span className="truncate max-w-[130px]">{d.file_name}</span>
                                  </div>
                                  <button
                                    type="button"
                                    title={`Remove ${d.file_name}`}
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      s.deleteDocument(claim.id, d.id || d.file_name, e);
                                    }}
                                    className="text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded p-0.5 text-xs flex-none ml-1 cursor-pointer transition-colors"
                                  >
                                    ✕
                                  </button>
                                </div>
                              ))}
                            </div>
                          )}

                          {/* Live Processing Bar & Stage Tag */}
                          {isClaimProcessing ? (
                            <div className="space-y-1.5 pt-1">
                              <div>
                                <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 border border-amber-300 text-amber-800 font-bold px-2 py-0.5 text-[9px]">
                                  <span className="h-1.5 w-1.5 rounded-full bg-amber-500 animate-ping" />
                                  {getStageBadgeLabel(currentProgress, currentStep)}
                                </span>
                              </div>
                              <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-200">
                                <div
                                  className="h-full bg-blue-500 rounded-full transition-all duration-300"
                                  style={{ width: `${Math.max(currentProgress, 10)}%` }}
                                />
                              </div>
                              <p className="text-[11px] text-slate-600 font-normal truncate">
                                {currentStep}
                              </p>
                            </div>
                          ) : (
                            <div className="flex items-center justify-between text-[10px] text-muted-foreground pt-0.5">
                              <span className="truncate font-mono">ID: {claim.id.slice(0, 8)}...</span>
                              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 text-emerald-700 font-semibold px-2 py-0.5 text-[9px] border border-emerald-200">
                                ✓ Completed
                              </span>
                            </div>
                          )}
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            </StaggerItem>

            {/* Right Main Content Area */}
            <div className="space-y-6 lg:col-span-3">

              {/* Upload Dropdown Panel (Always open & prominent when no claims are present) */}
              <StaggerItem index={2}>
                <SpotlightCard className="bg-white p-3.5 sm:p-4 shadow-elevation-sm">
                  {/* Ultra-compact 1-line flex row for both mobile & desktop */}
                  <div
                    onClick={() => {
                      if (!isUploadOpenEffective) {
                        s.resetState();
                      } else {
                        s.toggleUploadOpen();
                      }
                    }}
                    className="flex cursor-pointer select-none items-center justify-between gap-2 p-1"
                  >
                    <div className="flex items-center gap-2.5 min-w-0 flex-1">
                      <div className="flex h-9 w-9 flex-none items-center justify-center rounded-xl bg-teal-50 text-teal-600 border border-teal-200">
                        <Upload className="h-4.5 w-4.5" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <h2 className="text-xs sm:text-sm font-bold text-foreground truncate">Upload Claim Documents</h2>
                        <p className="text-[10px] sm:text-xs text-muted-foreground truncate">
                          {isUploadOpenEffective ? "Click to collapse panel" : "Expand to upload & analyze new claim documents"}
                        </p>
                      </div>
                    </div>

                    <Button
                      type="button"
                      size="sm"
                      onClick={(e) => {
                        e.stopPropagation();
                        if (!isUploadOpenEffective) {
                          s.resetState();
                        } else {
                          s.toggleUploadOpen();
                        }
                      }}
                      className="teal-gradient text-[11px] sm:text-xs font-semibold text-white shadow-sm h-8 px-3 rounded-lg flex-none cursor-pointer"
                    >
                      {isUploadOpenEffective ? (
                        <>
                          <ChevronUp className="mr-1 h-3.5 w-3.5" /> Collapse
                        </>
                      ) : (
                        <>
                          <Plus className="mr-1 h-3.5 w-3.5" /> Upload New Claim
                        </>
                      )}
                    </Button>
                  </div>

                  {/* Dropdown Body */}
                  {isUploadOpenEffective && (
                    <div className="mt-3 pt-3 border-t border-border animate-fade-in">
                      {s.analyzing ? (
                        <div className="flex flex-col items-center justify-center p-6 bg-accent/5 rounded-xl border border-accent/30 text-center min-h-[180px] space-y-4 animate-fade-in">
                          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-accent/20 text-accent animate-spin">
                            <Sparkles className="h-6 w-6" />
                          </div>
                          <div>
                            <p className="text-base font-bold text-foreground">AI Medical Engine Analyzing...</p>
                            <p className="text-xs font-semibold text-accent mt-1">{s.stepDescription || "OCR (extracting text) · 20%"}</p>
                          </div>
                        </div>
                      ) : s.isLiveSessionCompleted ? (
                        <div className="flex flex-col items-center justify-center p-6 bg-emerald-500/10 rounded-xl border border-emerald-500/30 text-center min-h-[180px] space-y-4 animate-fade-in">
                          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 shadow-lg">
                            <CheckCircle2 className="h-6 w-6" />
                          </div>
                          <div>
                            <h3 className="text-base font-bold text-foreground">Claim Analysis 100% Complete!</h3>
                            <p className="text-xs text-muted-foreground mt-1">
                              Extracted report for <span className="font-semibold text-foreground">{s.files[0]?.name || "claim_document.pdf"}</span> is generated.
                            </p>
                          </div>
                          <div className="pt-2 w-full max-w-sm space-y-2">
                            <Button onClick={s.openReportModal} className="teal-gradient w-full h-11 text-sm font-semibold text-white shadow-lg cursor-pointer">
                              <FileText className="mr-2 h-4 w-4" /> View AI Post-Processing Audit Report
                            </Button>
                            <button
                              type="button"
                              onClick={() => s.resetState()}
                              className="inline-flex items-center justify-center gap-1.5 text-xs text-muted-foreground hover:text-foreground underline pt-1 cursor-pointer"
                            >
                              <Plus className="h-3.5 w-3.5" /> Upload Another Claim Document
                            </button>
                          </div>
                        </div>
                      ) : (
                        <label
                          htmlFor="c-upload"
                          onDragOver={(e) => e.preventDefault()}
                          onDrop={(e) => {
                            e.preventDefault();
                            s.handleSelectFile(e);
                          }}
                          className="group flex min-h-[170px] cursor-pointer flex-col items-center justify-center gap-2.5 rounded-xl border-2 border-dashed border-teal-300/80 bg-teal-50/30 text-center transition-all hover:border-teal-500 hover:bg-teal-50/60 tap-highlight-none p-4"
                        >
                          <div className="flex h-13 w-13 items-center justify-center rounded-2xl bg-teal-600 text-white shadow-md transition-transform group-hover:scale-110">
                            <Upload className="h-6 w-6" />
                          </div>
                          <div>
                            <p className="text-sm font-bold text-foreground">Drag &amp; drop hospital bills or discharge summaries</p>
                            <p className="text-xs text-muted-foreground mt-0.5">Supports PDF, JPG, PNG up to 25 MB — Instant AI verification</p>
                          </div>
                          <span className="inline-flex items-center gap-1 rounded-full bg-white border border-teal-200 px-3 py-1 text-[11px] font-bold text-teal-700 shadow-xs">
                            <Plus className="h-3 w-3" /> Browse Files on Computer
                          </span>
                          <input
                            id="c-upload"
                            type="file"
                            multiple
                            accept=".pdf,.jpg,.jpeg,.png"
                            className="hidden"
                            onChange={s.handleSelectFile}
                          />
                        </label>
                      )}

                      {/* Staged files preview */}
                      {s.files.length > 0 && !s.analyzing && !s.isLiveSessionCompleted && (
                        <div className="mt-4 space-y-3">
                          <div className="flex items-center justify-between text-xs text-muted-foreground">
                            <span className="font-semibold text-foreground">Attached Files ({s.files.length})</span>
                            <button
                              type="button"
                              onClick={() => document.getElementById('c-upload')?.click()}
                              className="text-[11px] font-bold text-teal-600 hover:text-teal-700 inline-flex items-center gap-1 underline"
                            >
                              <Plus className="h-3.5 w-3.5" /> Add More Documents
                            </button>
                          </div>
                          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                            {s.files.map((f, i) => (
                              <div key={i} className="flex items-center justify-between rounded-xl border border-border bg-slate-50 p-3 text-xs shadow-sm">
                                <div className="flex items-center gap-2.5 min-w-0">
                                  {f.type?.startsWith("image/") || f.name.match(/\.(jpg|jpeg|png|webp)$/i) ? (
                                    <ImageIcon className="h-4 w-4 text-teal-600 flex-none" />
                                  ) : (
                                    <Folder className="h-4 w-4 text-teal-600 flex-none" />
                                  )}
                                  <div className="min-w-0">
                                    <p className="font-semibold truncate text-foreground">{f.name}</p>
                                    <p className="text-[10px] text-muted-foreground font-mono mt-0.5">{f.size}</p>
                                  </div>
                                </div>
                                <button type="button" onClick={() => s.removeFile(i)} className="text-slate-400 hover:text-rose-600 p-1">
                                  <Trash2 className="h-4 w-4" />
                                </button>
                              </div>
                            ))}
                          </div>
                          <Button onClick={() => s.startClaimAnalysis()} disabled={s.analyzing} className="teal-gradient w-full h-11 text-xs sm:text-sm font-bold text-white shadow-md rounded-xl cursor-pointer">
                            <Sparkles className={cn("mr-2 h-4 w-4", s.analyzing && "animate-spin")} />
                            {s.analyzing ? "Analyzing Claim Document..." : `Begin Claim Analysis (${s.files.length} ${s.files.length === 1 ? 'Doc' : 'Docs'})`}
                          </Button>
                        </div>
                      )}
                    </div>
                  )}
                </SpotlightCard>
              </StaggerItem>

              {/* Mobile Only: Processed Claims History Selector */}
              {hasActiveClaim && (
                <StaggerItem index={3} className="block lg:hidden">
                  <div id="processed-claims-mobile-section" className="rounded-xl border border-border bg-white p-4 shadow-elevation-sm">
                    <div className="mb-2.5 flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <div className="flex h-6 w-6 items-center justify-center rounded-md bg-accent/10 text-accent">
                          <Clock className="h-3.5 w-3.5" />
                        </div>
                        <h3 className="text-xs font-bold text-foreground uppercase tracking-wider">Processed Claims History</h3>
                      </div>
                      <div className="flex items-center gap-1.5">
                        {searchQuery.trim() && (
                          <button
                            type="button"
                            onClick={() => setSearchQuery('')}
                            className="text-[10px] text-teal-600 hover:text-teal-800 font-semibold cursor-pointer underline mr-0.5"
                          >
                            Clear
                          </button>
                        )}
                        <span className="rounded-full bg-accent/10 px-2.5 py-0.5 text-[11px] font-semibold text-accent">
                          {searchQuery.trim() ? `${filteredClaims.length}/${s.recentClaims.length}` : (s.recentClaims.length || 1)} Claims
                        </span>
                      </div>
                    </div>

                    <div className="flex gap-2.5 overflow-x-auto pb-1 scrollbar-thin snap-x">
                      {filteredClaims.length === 0 ? (
                        searchQuery.trim() && s.recentClaims.length > 0 ? (
                          <div className="flex items-center gap-2 py-2 px-3 rounded-lg border border-dashed text-xs text-slate-500">
                            <span>No claims match &ldquo;{searchQuery}&rdquo;</span>
                            <button type="button" onClick={() => setSearchQuery('')} className="text-teal-600 font-semibold underline cursor-pointer">Clear</button>
                          </div>
                        ) : s.claimId ? (
                          <button
                            type="button"
                            onClick={() => s.selectClaim(s.claimId || "")}
                            className="flex-none snap-start rounded-lg border border-accent bg-accent/10 px-3.5 py-2 text-left shadow-sm min-w-[150px]"
                          >
                            <div className="flex items-center justify-between gap-1">
                              <p className="text-xs font-bold truncate text-foreground">{s.patientName || "Patient Record"}</p>
                              <span className="flex h-2 w-2 rounded-full bg-emerald-500 flex-none" />
                            </div>
                            <p className="text-[10px] text-muted-foreground mt-0.5 truncate">
                              ID: {s.claimId.slice(0, 8)}...
                            </p>
                          </button>
                        ) : s.isLoadingClaims ? (
                          <div className="flex gap-2">
                            {[1, 2].map((n) => (
                              <div key={n} className="flex-none rounded-2xl border border-slate-100 bg-white/70 p-3 min-w-[200px] space-y-2 animate-pulse">
                                <div className="h-4 w-24 bg-slate-200 rounded" />
                                <div className="h-3 w-32 bg-slate-100 rounded" />
                              </div>
                            ))}
                          </div>
                        ) : (
                          <p className="text-xs text-muted-foreground italic py-1 px-1">No uploaded claims present</p>
                        )
                      ) : (
                      filteredClaims.map((claim) => {
                        const isSelected = String(claim.id || "").toLowerCase() === String(s.claimId || "").toLowerCase();
                        const claimName = claim.patient_name && claim.patient_name !== "N/A" ? claim.patient_name : `Claim #${claim.id.slice(0, 6)}`;
                        const docs = (claim.documents && claim.documents.length > 0)
                          ? claim.documents
                          : (isSelected && s.analyzing && s.files.length > 0 ? s.files.map((f, i) => ({ id: `f-${i}`, file_name: f.name })) : []);
                        const isCompletedStatus = (claim.status || "").toUpperCase() === "COMPLETED" || (claim.status || "").toUpperCase() === "VALIDATED";
                        const isClaimActiveStatus = isProcessingStatus(claim.status) || PIPELINE_ACTIVE_STATUSES.has((claim.status || "").toUpperCase());
                        const hasIncompleteProgress = claim.progress?.percentage !== undefined && claim.progress.percentage < 100;
                        const isClaimProcessing = hasIncompleteProgress || (!isCompletedStatus && isClaimActiveStatus) || (isSelected && s.analyzing);
                        const isClaimSelected = isSelected;
                        const currentProgress = (isClaimSelected && s.analyzing)
                          ? s.progress
                          : (claim.progress?.percentage !== undefined ? claim.progress.percentage : (isCompletedStatus ? 100 : (claim.status === "UPLOADED" ? 20 : (isClaimActiveStatus ? 55 : 20))));
                        const currentStep = (isClaimSelected && s.analyzing && s.stepDescription)
                          ? s.stepDescription
                          : (claim.progress?.step || (claim.status === "UPLOADED" ? "OCR (extracting text) - 20%" : (isCompletedStatus ? "AI Verification Complete" : `Processing - ${currentProgress}%`)));
                        const shortId = (claim.id || "").replace(/-/g, "").slice(-8).toUpperCase();

                        return (
                          <div
                            key={claim.id}
                            onClick={() => s.selectClaim(claim.id)}
                            className={cn(
                              "flex-none snap-start rounded-2xl border p-3 text-left transition-all tap-highlight-none min-w-[220px] max-w-[260px] space-y-2 cursor-pointer",
                              isSelected
                                ? "border-blue-400 bg-white shadow-md ring-1 ring-blue-300"
                                : "border-slate-200 bg-white/80 hover:bg-white shadow-2xs"
                            )}
                          >
                            <div className="flex items-center justify-between gap-1 text-[10px]">
                              <div className="flex items-center gap-1.5 min-w-0">
                                <span className="rounded bg-blue-50 text-blue-700 font-mono font-bold px-1.5 py-0.5 text-[9px] border border-blue-200">
                                  #{shortId || "CLM001"}
                                </span>
                              </div>
                              <div className="flex items-center gap-1 flex-none">
                                {isClaimProcessing ? (
                                  <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 text-amber-800 font-bold px-1.5 py-0.5 text-[9px] border border-amber-300">
                                    <span className="h-1.5 w-1.5 rounded-full bg-amber-500 animate-ping" />
                                    {getStageBadgeLabel(currentProgress, currentStep)}
                                  </span>
                                ) : (
                                  <span className="rounded-full bg-emerald-100 text-emerald-800 px-1.5 py-0.5 text-[9px] font-bold">
                                    ✓ Ready
                                  </span>
                                )}
                                <span
                                  role="button"
                                  tabIndex={0}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setClaimToDelete({ id: claim.id, name: claimName });
                                  }}
                                  onKeyDown={(e) => {
                                    if (e.key === 'Enter' || e.key === ' ') {
                                      e.stopPropagation();
                                      setClaimToDelete({ id: claim.id, name: claimName });
                                    }
                                  }}
                                  className="p-1 rounded-md text-slate-400 hover:text-rose-600 hover:bg-rose-50 transition-colors cursor-pointer"
                                  title="Delete claim"
                                >
                                  <Trash2 className="h-3.5 w-3.5" />
                                </span>
                              </div>
                            </div>

                            <div className="min-w-0">
                              <p className="text-xs font-bold truncate text-slate-900">
                                {claimName}
                              </p>
                              {docs.length > 0 && (
                                <p className="text-[10px] text-slate-500 truncate mt-0.5">
                                  {docs[0].file_name} {docs.length > 1 ? `+${docs.length - 1} more` : ''}
                                </p>
                              )}
                            </div>

                            {/* Progress bar if actively processing */}
                            {isClaimProcessing ? (
                              <div className="space-y-1 pt-1 border-t border-amber-200/60">
                                <div className="flex items-center justify-between text-[10px] font-semibold text-amber-900">
                                  <span className="truncate pr-1">{currentStep}</span>
                                  <span className="font-mono font-bold">{currentProgress}%</span>
                                </div>
                                <div className="h-1.5 w-full rounded-full bg-amber-100 overflow-hidden border border-amber-200/50">
                                  <div
                                    className="h-full bg-gradient-to-r from-amber-400 to-amber-500 rounded-full transition-all duration-300"
                                    style={{ width: `${Math.max(currentProgress, 10)}%` }}
                                  />
                                </div>
                              </div>
                            ) : null}
                          </div>
                        );
                      })
                      )}
                    </div>
                  </div>
                </StaggerItem>
              )}

              {/* WHEN NO CLAIM IS UPLOADED / SELECTED: Display High-Converting Onboarding Guide */}
              {!hasActiveClaim ? (
                <StaggerItem index={3}>
                  <SpotlightCard className="bg-white p-6 sm:p-8 shadow-elevation-sm rounded-2xl border border-slate-200">
                    <div className="text-center max-w-2xl mx-auto space-y-2.5 mb-8">
                      <div className="inline-flex items-center gap-2 rounded-full bg-teal-50 border border-teal-200 px-3 py-1 text-xs font-bold text-teal-800">
                        <Sparkles className="h-3.5 w-3.5 text-teal-600" />
                        AI-Powered Medical Claim Verification &amp; Audit Engine
                      </div>
                      <h2 className="text-xl sm:text-2xl font-extrabold text-foreground tracking-tight">
                        Audit &amp; Settle Claims in 3 Automated Steps
                      </h2>
                      <p className="text-xs sm:text-sm text-muted-foreground leading-relaxed">
                        Upload your hospital final bills, discharge summaries, or diagnostic reports above to activate real-time OCR extraction, IRDAI compliance scoring, and 1-click TPA settlement reports.
                      </p>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                      <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-5 space-y-3 hover:bg-slate-50 hover:border-teal-300 transition-all shadow-xs">
                        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-teal-600 text-white font-bold text-sm shadow-md">
                          1
                        </div>
                        <h3 className="text-sm font-bold text-foreground">Upload Claim Documents</h3>
                        <p className="text-xs text-muted-foreground leading-relaxed">
                          Drop multi-page hospital bills, discharge summaries, pharmacy invoices, or diagnostic lab tests.
                        </p>
                      </div>

                      <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-5 space-y-3 hover:bg-slate-50 hover:border-teal-300 transition-all shadow-xs">
                        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-cyan-600 text-white font-bold text-sm shadow-md">
                          2
                        </div>
                        <h3 className="text-sm font-bold text-foreground">Neural OCR &amp; Table Parsing</h3>
                        <p className="text-xs text-muted-foreground leading-relaxed">
                          ClaimsGuru automatically extracts patient demographics, admission/discharge dates, itemized medical lines, and ICD/CPT codes.
                        </p>
                      </div>

                      <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-5 space-y-3 hover:bg-slate-50 hover:border-teal-300 transition-all shadow-xs">
                        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-600 text-white font-bold text-sm shadow-md">
                          3
                        </div>
                        <h3 className="text-sm font-bold text-foreground">IRDAI Audit &amp; Settlement</h3>
                        <p className="text-xs text-muted-foreground leading-relaxed">
                          Inspect compliance scores, discrepancy validations, and instantly view on-screen TPA and IRDAI claim settlement reports.
                        </p>
                      </div>
                    </div>

                    <div className="mt-8 pt-6 border-t border-border flex flex-col sm:flex-row items-center justify-between gap-4 text-xs text-muted-foreground">
                      <div className="flex items-center gap-2">
                        <ShieldCheck className="h-4.5 w-4.5 text-emerald-600 flex-none" />
                        <span className="font-semibold text-slate-700">256-Bit Encrypted · IRDAI Rule Compliant · HIPAA Ready</span>
                      </div>
                      <button
                        type="button"
                        onClick={() => document.getElementById('c-upload')?.click()}
                        className="teal-gradient inline-flex items-center gap-1.5 rounded-xl px-4 py-2.5 text-xs font-bold text-white shadow-md hover:opacity-90 active:scale-95 transition-all cursor-pointer"
                      >
                        <Upload className="h-3.5 w-3.5" /> Select Files to Get Started
                      </button>
                    </div>
                  </SpotlightCard>
                </StaggerItem>
              ) : (
                <>
                  {/* Processing Pipeline Progress Bar Card (Only visible when claim is active/uploaded) */}
                  <StaggerItem index={4} id="pipeline-progress-section">
                    <SpotlightCard className="bg-white p-4 shadow-elevation-sm sm:p-5">
                      {/* Top Bar: Claim Info on Left, Status + View Report Button on Right (Always 1 row on mobile) */}
                      <div className="flex items-center justify-between gap-2">
                        <div className="min-w-0 flex-1">
                          <h2 className="text-xs sm:text-sm font-bold text-foreground truncate">Processing Pipeline</h2>
                          <p className="text-[10px] sm:text-[11px] text-muted-foreground truncate font-mono mt-0.5">
                            ID: {s.claimId ? `${s.claimId.slice(0, 8)}...` : (s.analyzing ? "Generating..." : "Ready for Upload")}
                          </p>
                        </div>

                        <div className="flex items-center gap-1.5 flex-none">
                          {s.isDocumentsRequested ? (
                            <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/10 px-2 py-0.5 text-[10px] sm:text-[11px] font-bold text-amber-700 border border-amber-500/30 animate-pulse">
                              <AlertTriangle className="h-3 w-3 text-amber-600" />
                              REQUIRED
                            </span>
                          ) : s.nameMismatchWarning ? (
                            <span className="inline-flex items-center gap-1 rounded-full bg-red-500/10 px-2 py-0.5 text-[10px] sm:text-[11px] font-bold text-red-700 border border-red-500/30 animate-pulse">
                              <AlertTriangle className="h-3 w-3 text-red-600" />
                              MISMATCH
                            </span>
                          ) : (s.progress >= 100 && s.claimId) ? (
                            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] sm:text-[11px] font-bold text-emerald-700 border border-emerald-500/30">
                              <CheckCircle2 className="h-3 w-3 text-emerald-600" />
                              100% COMPLETE
                            </span>
                          ) : (!s.claimId || (s.progress === 0 && !s.analyzing)) ? (
                            <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-[10px] sm:text-[11px] font-semibold text-slate-500 border border-slate-200">
                              <Clock className="h-3 w-3 text-slate-400" />
                              0%
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 rounded-full bg-cyan-500/10 px-2 py-0.5 text-[10px] sm:text-[11px] font-bold text-cyan-700 border border-cyan-500/30 animate-pulse">
                              <Loader2 className="h-3 w-3 text-cyan-600 animate-spin" />
                              {s.progress}%
                            </span>
                          )}

                          {s.progress >= 100 && s.claimId && !s.analyzing && !s.isDocumentsRequested && !s.nameMismatchWarning ? (
                            <Button
                              onClick={s.openReportModal}
                              size="sm"
                              className="teal-gradient text-[11px] sm:text-xs font-semibold text-white shadow-md animate-scale-in h-7 sm:h-8 px-2 sm:px-3 rounded-lg cursor-pointer flex items-center gap-1"
                            >
                              <FileText className="h-3 w-3 sm:h-3.5 sm:w-3.5" />
                              <span>View Report</span>
                            </Button>
                          ) : null}
                        </div>
                      </div>

                      {/* Glowing Progress Bar (0% to 100%) */}
                      <div className="relative mt-3 mb-3">
                        <div className="h-2 w-full rounded-full bg-slate-100 overflow-hidden border border-border">
                          <div
                            className={cn(
                              "h-full rounded-full transition-all duration-500",
                              (!s.claimId || (s.progress === 0 && !s.analyzing))
                                ? "bg-slate-200"
                                : s.isDocumentsRequested
                                ? "bg-gradient-to-r from-amber-500 to-orange-500 shadow-[0_0_10px_rgba(245,158,11,0.4)]"
                                : "bg-gradient-to-r from-teal-500 via-emerald-500 to-teal-600 shadow-[0_0_10px_rgba(16,185,129,0.4)]"
                            )}
                            style={{ width: `${(!s.claimId || (s.progress === 0 && !s.analyzing)) ? 0 : Math.max(s.progress, 5)}%` }}
                          />
                        </div>
                        <div className="mt-1.5 flex items-center justify-between gap-2">
                          <div className="flex items-center gap-1.5 min-w-0">
                            {s.analyzing && s.progress < 100 && !s.isDocumentsRequested && (
                              <span className="h-1.5 w-1.5 rounded-full bg-teal-500 animate-ping flex-none" />
                            )}
                            <span className="text-[11px] font-semibold text-slate-700 truncate">
                              {s.claimId && s.progress >= 100
                                ? "AI Verification Complete"
                                : (s.claimId && (s.analyzing || s.progress > 0))
                                ? (s.stepDescription || "Analyzing documents...")
                                : "Ready for Document Upload"}
                            </span>
                          </div>
                          <span className="font-mono font-extrabold text-[11px] text-teal-700 bg-teal-50 border border-teal-200 px-2 py-0.2 rounded-full flex-none">
                            {s.claimId ? s.progress : 0}%
                          </span>
                        </div>
                      </div>

                      {/* 5-Stage Stepper Tracker */}
                      {/* Mobile: Connected Stepper Track */}
                      <div className="sm:hidden pt-3 border-t border-border/50">
                        <div className="relative flex items-center justify-between px-1">
                          {/* Connecting Background Track */}
                          <div className="absolute left-4 right-4 top-3.5 h-0.5 bg-slate-200 -z-0" />
                          <div
                            className="absolute left-4 top-3.5 h-0.5 bg-gradient-to-r from-teal-500 to-emerald-500 transition-all duration-500 -z-0"
                            style={{
                              width: s.progress >= 100
                                ? 'calc(100% - 32px)'
                                : s.progress === 0 && !s.analyzing
                                ? '0%'
                                : `${Math.min(100, Math.max(0, (s.stageIndex / 4) * 100))}%`,
                            }}
                          />

                          {PIPELINE.map((stage, i) => {
                            const isIdle = s.progress === 0 && !s.analyzing;
                            const done = !isIdle && (i < s.stageIndex || s.progress >= 100);
                            const current = s.analyzing && i === s.stageIndex && s.progress < 100;
                            const shortLabels = ['Attached', 'OCR Text', 'Parsing', 'Coding', 'Settled'];

                            return (
                              <button
                                key={stage.key}
                                type="button"
                                onClick={() => s.setActiveStage(stage.key)}
                                className="relative z-10 flex flex-col items-center gap-1 tap-highlight-none group cursor-pointer focus:outline-none"
                              >
                                <div
                                  className={cn(
                                    "flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold transition-all shadow-xs",
                                    done && "bg-emerald-600 text-white shadow-emerald-500/20",
                                    current && "bg-teal-600 text-white ring-2 ring-teal-500/40 ring-offset-2 scale-110",
                                    !done && !current && "bg-white border-2 border-slate-200 text-slate-400"
                                  )}
                                >
                                  {done ? <Check className="h-3.5 w-3.5" /> : i + 1}
                                </div>
                                <span
                                  className={cn(
                                    "text-[9px] font-semibold text-center leading-tight tracking-tight",
                                    current && "font-bold text-teal-700",
                                    done && "text-slate-700",
                                    !done && !current && "text-slate-400"
                                  )}
                                >
                                  {shortLabels[i] || stage.label}
                                </span>
                              </button>
                            );
                          })}
                        </div>
                      </div>

                      {/* Desktop: 5 Stage Cards */}
                      <div className="hidden sm:grid grid-cols-5 gap-2 pt-3 border-t border-border/50">
                        {PIPELINE.map((stage, i) => {
                          const isIdle = s.progress === 0 && !s.analyzing;
                          const done = !isIdle && (i < s.stageIndex || s.progress >= 100);
                          const current = s.analyzing && i === s.stageIndex && s.progress < 100;
                          return (
                            <button
                              key={stage.key}
                              type="button"
                              onClick={() => s.setActiveStage(stage.key)}
                              className={cn(
                                "flex items-center justify-center gap-2 p-2 rounded-xl border text-center transition-all tap-highlight-none min-h-[44px] cursor-pointer",
                                done && "border-emerald-500/30 bg-emerald-500/10 shadow-xs",
                                current && "border-teal-500 bg-teal-500/10 ring-2 ring-teal-500/30 animate-pulse shadow-sm",
                                !done && !current && "border-border bg-slate-50 hover:bg-slate-100"
                              )}
                            >
                              <span className={cn(
                                "flex h-5 w-5 flex-none items-center justify-center rounded-full text-[10px] font-bold",
                                done && "bg-emerald-600 text-white",
                                current && "bg-teal-600 text-white animate-bounce",
                                !done && !current && "bg-slate-200 text-slate-500"
                              )}>
                                {done ? <Check className="h-3 w-3" /> : i + 1}
                              </span>
                              <span className={cn(
                                "text-xs font-semibold truncate",
                                done && "text-emerald-900 font-bold",
                                current && "text-teal-900 font-bold",
                                !done && !current && "text-slate-500"
                              )}>
                                {stage.label}
                              </span>
                            </button>
                          );
                        })}
                      </div>

                      {s.isDocumentsRequested && (
                        <div className="mt-4 p-4 rounded-xl border border-amber-200 bg-amber-50/50 text-amber-900 animate-fade-in text-left">
                          <div className="flex items-start gap-2.5">
                            <AlertTriangle className="h-5 w-5 text-amber-600 flex-shrink-0 mt-0.5" />
                            <div className="space-y-1 w-full">
                              <h4 className="text-xs font-bold uppercase tracking-wider text-amber-800">Mandatory Document Missing</h4>
                              <p className="text-xs text-amber-700">
                                We detected incomplete information in your claim upload. Please upload the following items to resume analysis:
                              </p>
                              <ul className="list-disc list-inside pl-1.5 text-xs font-medium space-y-0.5 mt-1 text-amber-900">
                                {s.missingGroups.map((grp: string) => (
                                  <li key={grp}>{grp}</li>
                                ))}
                              </ul>
                              <div className="mt-3 flex items-center gap-3">
                                <label className="teal-gradient inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-bold text-white shadow-sm cursor-pointer hover:opacity-90">
                                  <input
                                    type="file"
                                    multiple
                                    hidden
                                    onChange={(e) => {
                                      if (e.target.files?.length) {
                                        s.handleUploadFile(Array.from(e.target.files), true);
                                      }
                                    }}
                                  />
                                  <Upload className="h-3.5 w-3.5" /> Upload Missing Documents
                                </label>
                              </div>
                            </div>
                          </div>
                        </div>
                      )}

                      {s.nameMismatchWarning && (
                        <div className="mt-4 p-4 rounded-xl border border-red-200 bg-red-50/50 text-red-900 animate-fade-in text-left">
                          <div className="flex items-start gap-2.5">
                            <AlertTriangle className="h-5 w-5 text-red-600 flex-shrink-0 mt-0.5" />
                            <div className="space-y-1 w-full font-sans">
                              <h4 className="text-xs font-bold uppercase tracking-wider text-red-800">Patient Name Mismatch Detected</h4>
                              <p className="text-xs text-red-700 leading-relaxed">
                                {s.nameMismatchWarning}
                              </p>
                              <div className="mt-3 flex items-center gap-3">
                                <label className="bg-gradient-to-r from-red-500 to-red-600 hover:from-red-400 hover:to-red-500 inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-bold text-white shadow-sm cursor-pointer hover:opacity-90">
                                  <input
                                    type="file"
                                    multiple
                                    hidden
                                    onChange={(e) => {
                                      if (e.target.files?.length) {
                                        s.handleUploadFile(Array.from(e.target.files), true);
                                      }
                                    }}
                                  />
                                  <Upload className="h-3.5 w-3.5" /> Upload Correct ID Proof
                                </label>
                              </div>
                            </div>
                          </div>
                        </div>
                      )}
                    </SpotlightCard>
                  </StaggerItem>

                  {/* Auditor Workspace (Sits right below Pipeline!) */}
                  <StaggerItem index={5}>
                    <SpotlightCard className="bg-white shadow-elevation-sm">
                      <div className="border-b border-border px-5 py-4 flex items-center justify-between">
                        <div>
                          <h2 className="text-sm font-semibold text-foreground">Claims Auditor &amp; Preview</h2>
                          <p className="text-xs text-muted-foreground">Hover a table row to highlight its source on the document.</p>
                        </div>
                        {s.progress >= 100 && !s.analyzing && !s.isDocumentsRequested && (
                          <Button onClick={s.openReportModal} size="sm" className="teal-gradient text-xs font-semibold text-white cursor-pointer">
                            <FileText className="mr-1.5 h-3.5 w-3.5" /> Full Audit Report
                          </Button>
                        )}
                      </div>
                      <div className="grid grid-cols-1 lg:grid-cols-2 lg:h-[560px] min-h-[500px]">
                        <DocumentViewer
                          claimId={s.claimId}
                          fileObj={s.files.length > 0 ? s.files[s.files.length - 1] : null}
                          zoom={s.zoom}
                          setZoom={s.setZoom}
                          hoveredField={s.hoveredField}
                          filename={s.realPreview?.documents?.[0]?.display_title || s.realPreview?.documents?.[0]?.original_filename || (s.files.length > 0 ? s.files[s.files.length - 1]?.name : undefined)}
                          documents={s.realPreview?.documents}
                          activeDocumentId={s.activeDocumentId}
                          onSelectDocument={s.setActiveDocumentId}
                          onOpenDocModal={s.openDocModal}
                          className="border-b border-border lg:border-b-0 lg:border-r h-full overflow-hidden"
                        />
                        <div className="flex flex-col h-full overflow-hidden">
                          <div className="border-b border-border bg-slate-50/60 px-5 py-3 flex items-center justify-between flex-none">
                            <h3 className="text-sm font-semibold text-foreground">Extracted Claim Data</h3>
                            {s.nameMismatchWarning && (
                              <span className="inline-flex items-center gap-1 rounded-full bg-red-100 border border-red-300 px-2.5 py-0.5 text-[10px] font-bold text-red-800 animate-pulse">
                                <AlertTriangle className="h-3 w-3 text-red-600" />
                                Name Mismatch
                              </span>
                            )}
                          </div>
                          {s.nameMismatchWarning && (
                            <div className="mx-5 mt-3 flex items-start gap-2.5 rounded-xl border border-red-200 bg-red-50 p-3 text-xs text-red-900 shadow-sm animate-fade-in font-sans flex-none">
                              <AlertTriangle className="h-4 w-4 text-red-600 flex-none mt-0.5" />
                              <div>
                                <h4 className="font-bold text-red-900">Patient Name Mismatch Detected</h4>
                                <p className="mt-0.5 text-red-700 leading-relaxed">{s.nameMismatchWarning}</p>
                              </div>
                            </div>
                          )}
                          <div key={`${s.claimId || 'default-clinical'}-${s.previewVersion}`} className="grid grid-cols-1 gap-3.5 p-4 sm:grid-cols-2 flex-none">
                            <MetaField id="c-patient-name" label="Patient Name" defaultValue={s.patientName} edited={!!s.edited['patient-name']} onEdit={() => s.markEdited('patient-name')} />
                            <MetaField id="c-hospital" label="Hospital" defaultValue={s.hospitalName} edited={!!s.edited['hospital']} onEdit={() => s.markEdited('hospital')} />
                            <MetaField id="c-admission" label="Admission Date" defaultValue={s.admissionDate} edited={!!s.edited['admission']} onEdit={() => s.markEdited('admission')} />
                            <MetaField id="c-discharge" label="Discharge Date" defaultValue={s.dischargeDate} edited={!!s.edited['discharge']} onEdit={() => s.markEdited('discharge')} />
                            <MetaField id="c-diagnosis" label="Diagnosis" defaultValue={s.diagnosis} edited={!!s.edited['diagnosis']} onEdit={() => s.markEdited('diagnosis')} className="sm:col-span-2" />
                          </div>
                          <div className="border-t border-border px-5 py-3 flex-1 flex flex-col min-h-0 overflow-hidden">
                            <div className="mb-2 flex items-center justify-between">
                              <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Categorized Expenses</h3>
                              {(s.analyzing || (s.progress < 100 && !s.realPreview?.expenses?.length)) && (
                                <span className="inline-flex items-center gap-1 text-[11px] font-medium text-teal-600">
                                  <Loader2 className="h-3 w-3 animate-spin" /> Processing...
                                </span>
                              )}
                            </div>
                            <div className="overflow-hidden rounded-lg border border-border flex-1 flex flex-col min-h-0">
                              <div className="overflow-y-auto scrollbar-thin flex-1 h-full">
                                <table className="w-full text-sm">
                                  <thead className="bg-slate-100 text-xs uppercase tracking-wide text-muted-foreground sticky top-0 z-10 shadow-2xs">
                                    <tr>
                                      <th className="px-3 py-2 text-left font-semibold bg-slate-100">Category</th>
                                      <th className="hidden px-3 py-2 text-left font-semibold sm:table-cell bg-slate-100">Description</th>
                                      <th className="px-3 py-2 text-right font-semibold bg-slate-100">Amount</th>
                                    </tr>
                                  </thead>
                                  <tbody className="divide-y divide-border">
                                    {s.analyzing || (s.progress < 100 && !s.realPreview?.expenses?.length) ? (
                                      <>
                                        {[1, 2, 3].map((rowIdx) => (
                                          <tr key={`proc-exp-row-${rowIdx}`} className="bg-slate-50/50">
                                            <td className="px-3 py-2.5 font-medium text-muted-foreground">
                                              <div className="flex items-center gap-1.5">
                                                <Loader2 className="h-3 w-3 animate-spin text-teal-600 shrink-0" />
                                                <span className="text-xs italic text-muted-foreground">Processing...</span>
                                              </div>
                                            </td>
                                            <td className="hidden px-3 py-2.5 text-muted-foreground sm:table-cell text-xs italic">
                                              Processing...
                                            </td>
                                            <td className="px-3 py-2.5 text-right font-medium text-muted-foreground text-xs italic">
                                              Processing...
                                            </td>
                                          </tr>
                                        ))}
                                      </>
                                    ) : (
                                      s.lineItems.map((item) => (
                                        <tr key={item.id} onMouseEnter={() => s.setHoveredField(item.id)} onMouseLeave={() => s.setHoveredField(null)} className={cn('cursor-pointer transition-colors', s.hoveredField === item.id ? 'bg-accent/5' : 'hover:bg-slate-50')}>
                                          <td className="px-3 py-2 font-medium text-foreground">{item.category}</td>
                                          <td className="hidden px-3 py-2 text-muted-foreground sm:table-cell">{item.description}</td>
                                          <td className="px-3 py-2 text-right font-medium text-foreground">{formatINR(item.amount)}</td>
                                        </tr>
                                      ))
                                    )}
                                  </tbody>
                                  <tfoot className="sticky bottom-0 z-10 shadow-2xs bg-slate-50 border-t-2 border-border">
                                    <tr className="border-t-2 border-border bg-slate-50">
                                      <td className="px-3 py-2.5 font-bold text-foreground bg-slate-50">Total</td>
                                      <td className="hidden px-3 py-2.5 sm:table-cell bg-slate-50" />
                                      <td className="px-3 py-2.5 text-right font-bold text-teal-700 bg-slate-50">
                                        {s.analyzing || (s.progress < 100 && !s.realPreview?.expenses?.length) ? (
                                          <span className="text-xs italic text-muted-foreground font-normal">Processing...</span>
                                        ) : (
                                          formatINR(s.total)
                                        )}
                                      </td>
                                    </tr>
                                  </tfoot>
                                </table>
                              </div>
                            </div>
                          </div>
                        </div>
                      </div>
                    </SpotlightCard>
                  </StaggerItem>
                </>
              )}
            </div>
          </div>
        </StaggerContainer>
      </main>
      {/* Post-Processing Audit Report Modal */}
      <ClaimReportModal s={s} />
      <DocumentPreviewModal
        isOpen={s.showDocModal}
        onClose={s.closeDocModal}
        claimId={s.claimId}
        fileObj={s.files.length > 0 ? s.files[s.files.length - 1] : null}
        patientName={s.patientName}
        documents={s.realPreview?.documents}
        initialDocId={s.activeDocumentId}
      />

      {/* User Profile & Account Submissions Modal */}
      <UserProfileModal isOpen={s.showProfileModal} onClose={s.closeProfileModal} s={s} userName={s.userName} userEmail={s.userEmail} variant="clinical" />


      {/* Delete Claim Confirmation Modal */}
      {claimToDelete && (
        <div className="fixed inset-0 z-[130] flex items-center justify-center p-4 bg-slate-950/60 backdrop-blur-xs animate-fade-in font-sans">
          <div className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-5 shadow-2xl animate-scale-up">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 flex-none items-center justify-center rounded-xl bg-rose-100 text-rose-600">
                <Trash2 className="h-5 w-5" />
              </div>
              <div>
                <h3 className="text-base font-bold text-slate-900">Delete Claim?</h3>
                <p className="text-xs text-slate-500 mt-0.5">Are you sure you want to remove <span className="font-semibold text-slate-700">{claimToDelete.name}</span>?</p>
              </div>
            </div>

            <div className="mt-5 flex items-center justify-end gap-2.5">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setClaimToDelete(null)}
                className="rounded-xl border-slate-200 text-slate-700 hover:bg-slate-100 font-semibold"
              >
                Cancel
              </Button>
              <Button
                type="button"
                variant="destructive"
                size="sm"
                onClick={() => {
                  s.deleteClaim(claimToDelete.id);
                  setClaimToDelete(null);
                }}
                className="rounded-xl bg-rose-600 hover:bg-rose-700 text-white font-bold shadow-sm"
              >
                Confirm Delete
              </Button>
            </div>
          </div>
        </div>
      )}

      {s.duplicateClaimId && (
        <DuplicateClaimModal
          isOpen={!!s.duplicateClaimId}
          onClose={() => {
            s.setDuplicateClaimId(null);
            s.resetState();
          }}
          onConfirm={() => {
            const targetId = s.duplicateClaimId;
            s.setDuplicateClaimId(null);
            if (targetId) {
              s.selectClaim(targetId);
            }
          }}
        />
      )}

      {/* Footer */}
      <footer className="mt-auto border-t border-slate-200 bg-white px-6 py-4 flex flex-col sm:flex-row items-center justify-between gap-4 text-xs text-muted-foreground">
        <div className="flex flex-wrap items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
          <span>All systems operational</span>
          <span className="opacity-40">·</span>
          <span>IRDAI - ISO 27001 - HIPAA aligned</span>
        </div>
        <div className="flex items-center gap-2">
          <span>© 2026 WaferWire Cloud Technologies</span>
          <span className="opacity-40">·</span>
          <span>ClaimsGuru v1.0</span>
        </div>
      </footer>
    </div>
  );
}

function MetaField({
  id,
  label,
  defaultValue,
  edited,
  onEdit,
  className,
}: {
  id: string;
  label: string;
  defaultValue: string;
  edited: boolean;
  onEdit: () => void;
  className?: string;
}) {
  const [val, setVal] = useState(defaultValue);

  useEffect(() => {
    setVal(defaultValue);
  }, [defaultValue]);

  return (
    <div className={cn('space-y-1.5', className)}>
      <div className="flex items-center gap-2">
        <Label htmlFor={id} className="text-xs font-medium text-muted-foreground">{label}</Label>
        {edited && (
          <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 animate-scale-in">
            <Clock className="h-2.5 w-2.5" />Edited
          </span>
        )}
      </div>
      <Input
        id={id}
        value={val}
        onChange={(e) => {
          setVal(e.target.value);
          onEdit();
        }}
        className="h-10 border-slate-200"
      />
    </div>
  );
}

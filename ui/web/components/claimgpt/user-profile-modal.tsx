'use client';

import { useState, useEffect } from 'react';
import {
  User,
  ShieldCheck,
  FileText,
  X,
  Mail,
  CreditCard,
  Users,
  CheckCircle2,
  ChevronRight,
  Copy,
  Check,
  Calendar,
  Phone,
  Building2,
  IndianRupee,
  LogOut,
  LogIn,
  Loader2,
} from 'lucide-react';
import { useRouter } from 'next/navigation';
import { isSameClaimId, type AuditorState } from '@/components/claimgpt/use-auditor-state';
import { getStoredAuthSession, clearAuthSession } from '@/lib/auth';
import { UserAvatar } from '@/components/claimgpt/user-avatar';
import { formatDob } from '@/lib/claimgpt-data';

interface UserProfileModalProps {
  isOpen: boolean;
  onClose: () => void;
  s: AuditorState;
  userName: string;
  userEmail: string;
  variant?: 'neon' | 'clinical' | 'executive';
}

export function UserProfileModal({
  isOpen,
  onClose,
  s,
  userName,
  userEmail,
  variant = 'neon',
}: UserProfileModalProps) {
  const router = useRouter();
  const [copied, setCopied] = useState(false);
  const [userMeta, setUserMeta] = useState({
    dob: '01 Jan 2000',
    gender: 'Male',
    insurer: 'Star Health',
    policyNo: 'P-0007401',
    sumInsured: '₹5,000,000',
  });

  const handleLogout = () => {
    try {
      clearAuthSession();
      localStorage.removeItem('claimgpt_user_name');
      localStorage.removeItem('claimgpt_user_email');
    } catch {
      /* ignore */
    }
    onClose();
    router.push('/login');
  };

  const handleSwitchAccount = () => {
    onClose();
    router.push('/login');
  };

  useEffect(() => {
    try {
      const session = getStoredAuthSession();
      const currentEmail = userEmail || session?.user?.email || '';
      const rawDob =
        localStorage.getItem(`claimgpt_user_dob_${currentEmail}`) ||
        localStorage.getItem('claimgpt_user_dob');
      const insurer =
        localStorage.getItem(`claimgpt_user_insurer_${currentEmail}`) ||
        localStorage.getItem('claimgpt_user_insurer');
      const policy =
        localStorage.getItem(`claimgpt_user_policy_${currentEmail}`) ||
        localStorage.getItem('claimgpt_user_policy');
      const sum =
        localStorage.getItem(`claimgpt_user_sum_${currentEmail}`) ||
        localStorage.getItem('claimgpt_user_sum');
      const gender =
        localStorage.getItem(`claimgpt_user_gender_${currentEmail}`) ||
        localStorage.getItem('claimgpt_user_gender');

      setUserMeta({
        dob: formatDob(rawDob || '01012000'),
        gender: gender || 'Male',
        insurer: insurer || (session?.role === 'tpa' ? 'TPA Adjuster Org' : 'Star Health'),
        policyNo: policy || (session?.role === 'tpa' ? 'TPA-90021' : 'P-0007401'),
        sumInsured: sum
          ? (sum.startsWith('₹') ? sum : `₹${Number(sum).toLocaleString('en-IN')}`)
          : '₹5,000,000',
      });
    } catch {
      /* ignore localStorage error */
    }
  }, [isOpen, userEmail]);

  if (!isOpen) return null;

  // Generate 2-letter initials (e.g. Kareem Rossi -> KR, Swagath -> SW, Nivas -> NV)
  const nameParts = userName.trim().split(' ');
  const initials = nameParts.length >= 2
    ? (nameParts[0][0] + nameParts[1][0]).toUpperCase()
    : userName.slice(0, 2).toUpperCase();

  const handleCopyPolicy = () => {
    try {
      navigator.clipboard.writeText(userMeta.policyNo);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* fallback */
    }
  };

  // Compute family member / patient claim list under this account
  const accountClaims = s.recentClaims.length > 0
    ? s.recentClaims
    : [
        {
          id: s.claimId || 'CLM-18091900',
          patient_name: s.patientName || userName || 'Self',
          status: 'COMPLETED',
          created_at: 'Today',
          total_amount: s.total ? `₹${s.total.toLocaleString('en-IN')}` : '',
        },
      ];

  /* Theme-specific styles matching Design 1 (neon), Design 2 (clinical), and Design 3 (executive) */
  const themeStyles = {
    neon: {
      cardBg: 'bg-[#090e1a]/95 border-cyan-500/30 text-slate-100 shadow-[0_0_50px_rgba(6,182,212,0.15)]',
      headerBg: 'bg-cyan-950/40 border-b border-cyan-500/20',
      headerPill: 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40',
      initialsBox: 'bg-gradient-to-tr from-cyan-500 to-purple-600 text-white border border-cyan-400/40 shadow-lg shadow-cyan-500/20',
      policyPill: 'bg-cyan-950/50 hover:bg-cyan-900/60 border border-cyan-500/30 text-cyan-100',
      tagBadge: 'bg-cyan-400 text-slate-950 font-bold',
      gridBlock: 'bg-cyan-950/30 border border-cyan-500/20',
      labelColor: 'text-cyan-400/80',
      valueColor: 'text-white',
      accentValue: 'text-cyan-300',
      sumValue: 'text-emerald-400',
      divider: 'border-cyan-500/20',
      closeBtn: 'text-cyan-300 hover:bg-cyan-500/20 hover:text-white',
      mobileBtn: 'bg-cyan-600 hover:bg-cyan-500 text-white',
      switchAccountBtn: 'border-cyan-500/30 bg-cyan-950/40 hover:bg-cyan-900/50 text-cyan-200',
    },
    clinical: {
      cardBg: 'bg-white/95 border-slate-200 text-slate-900 shadow-2xl',
      headerBg: 'bg-slate-50 border-b border-slate-200',
      headerPill: 'bg-teal-50 text-teal-700 border border-teal-200',
      initialsBox: 'bg-teal-600 text-white font-bold shadow-sm',
      policyPill: 'bg-slate-100 hover:bg-slate-200 border border-slate-200 text-slate-800',
      tagBadge: 'bg-teal-600 text-white font-bold',
      gridBlock: 'bg-slate-50 border border-slate-200',
      labelColor: 'text-teal-700',
      valueColor: 'text-slate-900',
      accentValue: 'text-teal-800',
      sumValue: 'text-teal-700',
      divider: 'border-slate-200',
      closeBtn: 'text-slate-500 hover:bg-slate-100 hover:text-slate-900',
      mobileBtn: 'bg-teal-600 hover:bg-teal-700 text-white',
      switchAccountBtn: 'border-slate-200 bg-white hover:bg-slate-100 text-slate-700',
    },
    executive: {
      cardBg: 'bg-[#060b18]/95 border-amber-500/30 text-amber-50 shadow-[0_0_50px_rgba(245,158,11,0.15)]',
      headerBg: 'bg-amber-950/40 border-b border-amber-500/20',
      headerPill: 'bg-amber-500/20 text-amber-300 border border-amber-500/30',
      initialsBox: 'bg-gradient-to-tr from-amber-500 to-amber-600 text-slate-950 border border-amber-400/40 font-bold shadow-lg shadow-amber-500/20',
      policyPill: 'bg-amber-950/50 hover:bg-amber-900/60 border border-amber-500/30 text-amber-100',
      tagBadge: 'bg-amber-400 text-slate-950 font-bold',
      gridBlock: 'bg-amber-950/30 border border-amber-500/20',
      labelColor: 'text-amber-400/80',
      valueColor: 'text-white',
      accentValue: 'text-amber-300',
      sumValue: 'text-amber-400',
      divider: 'border-amber-500/20',
      closeBtn: 'text-amber-300 hover:bg-amber-500/20 hover:text-white',
      mobileBtn: 'bg-amber-600 hover:bg-amber-500 text-slate-950 font-bold',
      switchAccountBtn: 'border-amber-500/30 bg-amber-950/40 hover:bg-amber-900/50 text-amber-200',
    },
  }[variant];

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-3 sm:p-0 sm:block overflow-hidden font-sans">
      {/* Click outside backdrop */}
      <div 
        className="absolute inset-0 bg-slate-950/60 backdrop-blur-sm transition-opacity animate-fade-in"
        onClick={onClose} 
      />

      {/* Profile Card */}
      <div className={`relative w-full max-w-[360px] sm:max-w-none sm:absolute sm:top-16 sm:right-6 z-[101] sm:w-[380px] max-h-[82vh] sm:max-h-[85vh] flex flex-col rounded-3xl border backdrop-blur-2xl overflow-hidden animate-scale-in sm:animate-slide-down ${themeStyles.cardBg}`}>
        
        {/* Top Header Pill Bar */}
        <div className={`flex items-center justify-between px-4 pt-3.5 pb-2 ${themeStyles.headerBg}`}>
          <div className={`flex items-center gap-1.5 rounded-full px-3 py-0.5 text-xs font-semibold backdrop-blur-md ${themeStyles.headerPill}`}>
            <User className="h-3.5 w-3.5" />
            <span>Patient Profile</span>
          </div>

          <button
            type="button"
            onClick={onClose}
            className={`flex h-7 w-7 items-center justify-center rounded-full transition-colors ${themeStyles.closeBtn}`}
            title="Close profile"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Scrollable Content Body */}
        <div className="px-4 py-3 space-y-3 overflow-y-auto flex-1 scrollbar-thin">
          
          {/* Main User Banner */}
          <div className="flex items-start gap-3.5 pt-0.5">
            {/* Colorful Illustrated Avatar */}
            <UserAvatar name={userName} gender={userMeta.gender} size="xl" className="shadow-md" />

            <div className="min-w-0 flex-1 space-y-1.5">
              <h2 className={`text-base sm:text-lg font-bold tracking-tight truncate ${themeStyles.valueColor}`}>{userName}</h2>
              
              {/* Badges Row */}
              <div className="flex items-center gap-1.5 flex-wrap text-[10px] sm:text-[11px]">
                {/* Policy ID with copy */}
                <button
                  type="button"
                  onClick={handleCopyPolicy}
                  className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 font-medium transition-colors ${themeStyles.policyPill}`}
                  title="Copy Policy Number"
                >
                  <span>{userMeta.policyNo}</span>
                  {copied ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3 opacity-80" />}
                </button>

                {/* Status tag */}
                <span className={`rounded-full px-2.5 py-0.5 text-[9px] sm:text-[10px] font-bold uppercase ${themeStyles.tagBadge}`}>
                  Active Policy
                </span>
              </div>
            </div>
          </div>

          {/* 2-Column Grid of Registration Fields ONLY */}
          <div className="grid grid-cols-2 gap-2 text-xs">
            {/* EMAIL ADDRESS / CONTACT */}
            <div className={`col-span-2 rounded-2xl p-2.5 space-y-0.5 backdrop-blur-md ${themeStyles.gridBlock}`}>
              <span className={`text-[9px] font-bold uppercase tracking-wider flex items-center gap-1 ${themeStyles.labelColor}`}>
                <Mail className="h-3 w-3" /> EMAIL ADDRESS / CONTACT
              </span>
              <p className={`font-bold truncate text-xs ${themeStyles.valueColor}`}>{userEmail}</p>
            </div>

            {/* DATE OF BIRTH */}
            <div className={`rounded-2xl p-2.5 space-y-0.5 backdrop-blur-md ${themeStyles.gridBlock}`}>
              <span className={`text-[9px] font-bold uppercase tracking-wider flex items-center gap-1 ${themeStyles.labelColor}`}>
                <Calendar className="h-3 w-3" /> DATE OF BIRTH
              </span>
              <p className={`font-bold truncate text-xs ${themeStyles.valueColor}`}>{userMeta.dob}</p>
            </div>

            {/* GENDER */}
            <div className={`rounded-2xl p-2.5 space-y-0.5 backdrop-blur-md ${themeStyles.gridBlock}`}>
              <span className={`text-[9px] font-bold uppercase tracking-wider flex items-center gap-1 ${themeStyles.labelColor}`}>
                <User className="h-3 w-3" /> GENDER
              </span>
              <p className={`font-bold truncate text-xs ${themeStyles.accentValue}`}>{userMeta.gender}</p>
            </div>

            {/* INSURER PROVIDER */}
            <div className={`rounded-2xl p-2.5 space-y-0.5 backdrop-blur-md ${themeStyles.gridBlock}`}>
              <span className={`text-[9px] font-bold uppercase tracking-wider flex items-center gap-1 ${themeStyles.labelColor}`}>
                <Building2 className="h-3 w-3" /> INSURER
              </span>
              <p className={`font-bold truncate text-xs ${themeStyles.valueColor}`}>{userMeta.insurer}</p>
            </div>

            {/* POLICY NUMBER */}
            <div className={`rounded-2xl p-2.5 space-y-0.5 backdrop-blur-md ${themeStyles.gridBlock}`}>
              <span className={`text-[9px] font-bold uppercase tracking-wider flex items-center gap-1 ${themeStyles.labelColor}`}>
                <CreditCard className="h-3 w-3" /> POLICY NO.
              </span>
              <p className={`font-bold truncate text-xs ${themeStyles.valueColor}`}>{userMeta.policyNo}</p>
            </div>

            {/* SUM INSURED (INR) */}
            <div className={`col-span-2 rounded-2xl p-2.5 space-y-0.5 backdrop-blur-md ${themeStyles.gridBlock}`}>
              <span className={`text-[9px] font-bold uppercase tracking-wider flex items-center gap-1 ${themeStyles.labelColor}`}>
                <IndianRupee className="h-3 w-3" /> SUM INSURED (INR)
              </span>
              <p className={`font-bold text-xs sm:text-sm truncate ${themeStyles.sumValue}`}>{userMeta.sumInsured}</p>
            </div>
          </div>

          {/* Family & Account Member Claims Submissions */}
          <div className={`space-y-2 pt-2 border-t ${themeStyles.divider}`}>
            <div className="flex items-center justify-between gap-2 text-xs">
              <span className={`font-bold uppercase tracking-wider text-[10px] min-w-0 flex-1 leading-snug ${themeStyles.labelColor}`}>
                Submissions under {userName}&apos;s Account
              </span>
              <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[10px] font-bold whitespace-nowrap shrink-0 shadow-xs ${themeStyles.headerPill}`}>
                <span>{accountClaims.length}</span>
                <span className="font-medium text-[9px] opacity-80">{accountClaims.length === 1 ? 'Claim' : 'Claims'}</span>
              </span>
            </div>

            <div className="space-y-1.5 max-h-[220px] overflow-y-auto pr-1 scrollbar-thin">
              {accountClaims.map((claim, idx) => {
                const isSelected = isSameClaimId(claim.id, s.claimId);
                const shortId = (claim.id || '').replace(/-/g, '').slice(0, 8).toUpperCase();
                const isComplete = claim.status === 'COMPLETED' || claim.status === 'VALIDATED' || (claim.progress?.percentage ?? 0) >= 100;
                const isFailed = claim.status === 'FAILED' || claim.status === 'OCR_REJECTED';
                const isFamily = claim.patient_name && userName && claim.patient_name.toLowerCase() !== userName.toLowerCase();

                return (
                  <div
                    key={claim.id || idx}
                    onClick={() => {
                      if (claim.id) s.selectClaim(claim.id);
                      onClose();
                    }}
                    className={`flex items-center justify-between rounded-xl p-2 transition-all cursor-pointer group text-xs border ${
                      isSelected
                        ? 'border-teal-500/60 bg-teal-50/80 dark:bg-teal-950/40 ring-1 ring-teal-500/30'
                        : themeStyles.gridBlock
                    }`}
                  >
                    <div className="min-w-0 pr-2">
                      <div className="flex items-center gap-1.5">
                        <p className={`text-[11px] font-bold truncate ${themeStyles.valueColor}`}>
                          Patient: {claim.patient_name || userName || 'Self'}
                        </p>
                        {isFamily && (
                          <span className="rounded bg-purple-500/20 text-purple-600 dark:text-purple-300 border border-purple-400/30 px-1 py-0.2 text-[8px] font-bold uppercase">
                            Family
                          </span>
                        )}
                        {isSelected && (
                          <span className="rounded bg-teal-500/20 text-teal-700 dark:text-teal-300 border border-teal-500/30 px-1 py-0.2 text-[8px] font-bold uppercase">
                            Active
                          </span>
                        )}
                      </div>
                      <p className={`text-[9px] truncate mt-0.5 ${themeStyles.labelColor}`}>
                        ID: {shortId || 'CLM'}... {claim.total_amount ? `• ${claim.total_amount}` : ''}
                      </p>
                    </div>

                    {isComplete ? (
                      <span className="text-[9px] font-bold text-emerald-600 dark:text-emerald-400 flex items-center gap-0.5 flex-none">
                        <CheckCircle2 className="h-3 w-3" /> Done
                      </span>
                    ) : isFailed ? (
                      <span className="text-[9px] font-bold text-rose-500 flex items-center gap-0.5 flex-none">
                        <X className="h-3 w-3" /> Failed
                      </span>
                    ) : (
                      <span className="text-[9px] font-bold text-amber-600 dark:text-amber-400 flex items-center gap-0.5 flex-none">
                        <Loader2 className="h-3 w-3 animate-spin" /> {claim.progress?.percentage ? `${claim.progress.percentage}%` : 'Processing'}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

        </div>

        {/* Modal Bottom Actions: Switch Account & Sign Out (Visible on all screen sizes) */}
        <div className={`p-3 border-t flex items-center gap-2 ${themeStyles.headerBg}`}>
          <button
            type="button"
            onClick={handleSwitchAccount}
            className={`flex-1 rounded-xl py-2 px-3 text-xs font-semibold border transition-all cursor-pointer flex items-center justify-center gap-1.5 shadow-2xs active:scale-95 ${themeStyles.switchAccountBtn}`}
          >
            <LogIn className="h-3.5 w-3.5" />
            <span>Switch Account</span>
          </button>

          <button
            type="button"
            onClick={handleLogout}
            className="flex-1 rounded-xl py-2 px-3 text-xs font-semibold bg-rose-500/10 hover:bg-rose-500/20 text-rose-600 dark:text-rose-400 border border-rose-500/30 transition-all cursor-pointer flex items-center justify-center gap-1.5 shadow-2xs active:scale-95"
          >
            <LogOut className="h-3.5 w-3.5" />
            <span>Sign Out</span>
          </button>
        </div>

      </div>
    </div>
  );
}

"use client";

import { useEffect, useRef, useState } from "react";
import { useI18n } from "@/lib/i18n";

/**
 * Compact globe-icon dropdown that lists all 14 supported languages with
 * their native script. Selection persists via the i18n provider.
 */
export default function LanguageSwitcher() {
  const { lang, meta, setLang, languages, t } = useI18n();
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  /* Outside click + Esc to close. */
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="lang-wrap" ref={wrapRef}>
      <button
        className="icon-btn lang-btn"
        onClick={() => setOpen((v) => !v)}
        title={t("nav.language")}
        aria-label={t("nav.language")}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10"/>
          <line x1="2" y1="12" x2="22" y2="12"/>
          <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
        </svg>
        <span className="lang-btn-code">{meta.code.toUpperCase()}</span>
      </button>
      {open && (
        <div className="dropdown-panel lang-panel" role="listbox" aria-label={t("nav.language")}>
          <div className="dropdown-head">
            <span className="dropdown-title">{t("nav.language")}</span>
            <span className="dropdown-sub">14 supported</span>
          </div>
          <div className="lang-list">
            {languages.map((l) => {
              const active = l.code === lang;
              return (
                <button
                  key={l.code}
                  role="option"
                  aria-selected={active}
                  className={`lang-item${active ? " lang-item-active" : ""}`}
                  onClick={() => { setLang(l.code); setOpen(false); }}
                  dir={l.rtl ? "rtl" : "ltr"}
                >
                  <span className="lang-item-native">{l.native}</span>
                  <span className="lang-item-english">{l.english}</span>
                  {active && (
                    <svg className="lang-item-check" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="20 6 9 17 4 12"/>
                    </svg>
                  )}
                </button>
              );
            })}
          </div>
          <div className="dropdown-foot">
            <span className="lang-foot-note">UI translates incrementally — content stays in source language.</span>
          </div>
        </div>
      )}
    </div>
  );
}

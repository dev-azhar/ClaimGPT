"use client";

import { useState, useRef, useEffect, createContext, useContext, useCallback } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import ProfileAvatar from "@/components/ProfileAvatar";

interface SearchCtx {
  search: string;
  setSearch: (v: string) => void;
  suggestions: string[];
  setSuggestions: (v: string[]) => void;
}
const SearchContext = createContext<SearchCtx>({ search: "", setSearch: () => {}, suggestions: [], setSuggestions: () => {} });
export function useTpaSearch() { return useContext(SearchContext); }

const NAV_ITEMS = [
  { href: "/tpa", label: "Dashboard" },
];

function HeaderSearch({ search, setSearch, suggestions }: { search: string; setSearch: (v: string) => void; suggestions: string[] }) {
  const [focused, setFocused] = useState(false);
  const [selected, setSelected] = useState(-1);
  const wrapRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const filtered = search.trim().length > 0
    ? suggestions.filter(s => s.toLowerCase().includes(search.toLowerCase())).slice(0, 8)
    : [];

  const showDropdown = focused && filtered.length > 0;

  const pick = useCallback((val: string) => {
    setSearch(val);
    setFocused(false);
    setSelected(-1);
    inputRef.current?.blur();
  }, [setSearch]);

  function handleKeyDown(e: React.KeyboardEvent) {
    if (!showDropdown) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setSelected(s => Math.min(s + 1, filtered.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setSelected(s => Math.max(s - 1, -1)); }
    else if (e.key === "Enter" && selected >= 0) { e.preventDefault(); pick(filtered[selected]); }
    else if (e.key === "Escape") { setFocused(false); setSelected(-1); }
  }

  useEffect(() => {
    function outside(e: MouseEvent) { if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) { setFocused(false); setSelected(-1); } }
    document.addEventListener("mousedown", outside);
    return () => document.removeEventListener("mousedown", outside);
  }, []);

  // Ghost / predictive text
  const ghost = search.trim() && filtered.length > 0 && filtered[0].toLowerCase().startsWith(search.toLowerCase())
    ? search + filtered[0].slice(search.length)
    : "";

  function handleTab(e: React.KeyboardEvent) {
    if (e.key === "Tab" && ghost) { e.preventDefault(); setSearch(ghost); }
  }

  return (
    <div className="tpa-hsearch" ref={wrapRef}>
      <div className={`tpa-hsearch-box ${focused ? "tpa-hsearch-focused" : ""}`}>
        <svg className="tpa-hsearch-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        <div className="tpa-hsearch-input-wrap">
          {ghost && <span className="tpa-hsearch-ghost">{ghost}</span>}
          <input
            ref={inputRef}
            className="tpa-hsearch-input"
            placeholder="Search patients, policies, hospitals..."
            value={search}
            onChange={(e) => { setSearch(e.target.value); setSelected(-1); }}
            onFocus={() => setFocused(true)}
            onKeyDown={(e) => { handleKeyDown(e); handleTab(e); }}
            autoComplete="off"
            spellCheck={false}
          />
        </div>
        {search && (
          <button className="tpa-hsearch-clear" onClick={() => { setSearch(""); inputRef.current?.focus(); }}>
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        )}
        <kbd className="tpa-hsearch-kbd">/</kbd>
      </div>
      {showDropdown && (
        <div className="tpa-hsearch-dropdown">
          {filtered.map((s, i) => {
            const idx = s.toLowerCase().indexOf(search.toLowerCase());
            return (
              <button
                key={s + i}
                className={`tpa-hsearch-option ${i === selected ? "tpa-hsearch-option-active" : ""}`}
                onMouseDown={() => pick(s)}
                onMouseEnter={() => setSelected(i)}
              >
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="tpa-hsearch-option-icon">
                  <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
                </svg>
                <span>
                  {idx >= 0 ? (<>{s.slice(0, idx)}<mark className="tpa-hsearch-match">{s.slice(idx, idx + search.length)}</mark>{s.slice(idx + search.length)}</>) : s}
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function TpaLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [search, setSearch] = useState("");
  const [suggestions, setSuggestions] = useState<string[]>([]);

  return (
    <SearchContext.Provider value={{ search, setSearch, suggestions, setSuggestions }}>
    <div className="tpa-shell tpa-shell-full">
      {/* Top bar — full width */}
      <header className="tpa-topbar">
        <div className="tpa-topbar-left">
          <Link href="/tpa" className="tpa-logo">
            <span className="tpa-logo-icon">⚕</span>
            <span>ClaimGPT <span className="tpa-logo-tag">TPA</span></span>
          </Link>
          <HeaderSearch search={search} setSearch={setSearch} suggestions={suggestions} />
        </div>
        <div className="tpa-topbar-right">
          <Link href="/" className="tpa-topnav-item tpa-topnav-back">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M19 12H5"/><polyline points="12 19 5 12 12 5"/></svg>
            Portal
          </Link>
          <ProfileAvatar />
        </div>
      </header>

      {/* Full-width content */}
      <div className="tpa-content">{children}</div>
    </div>
    </SearchContext.Provider>
  );
}

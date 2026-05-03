"use client";

import { useState, useRef, useEffect } from "react";
import { useAuth } from "@/lib/auth";

function getInitials(user: { name?: string; preferred_username?: string; email?: string; given_name?: string; family_name?: string }): string {
  if (user.given_name && user.family_name) {
    return (user.given_name[0] + user.family_name[0]).toUpperCase();
  }
  if (user.name) {
    const parts = user.name.split(" ");
    return parts.length >= 2
      ? (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
      : parts[0].slice(0, 2).toUpperCase();
  }
  if (user.preferred_username) return user.preferred_username.slice(0, 2).toUpperCase();
  if (user.email) return user.email.slice(0, 2).toUpperCase();
  return "U";
}

const AVATAR_COLORS = ["#0369a1", "#7c3aed", "#c026d3", "#0891b2", "#059669", "#d97706"];

function getAvatarColor(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
  return AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length];
}

function roleBadgeClass(role: string): string {
  switch (role) {
    case "admin": return "profile-role-admin";
    case "approver": return "profile-role-approver";
    case "checker": return "profile-role-checker";
    case "reviewer": return "profile-role-reviewer";
    case "submitter": return "profile-role-submitter";
    default: return "profile-role-viewer";
  }
}

const KNOWN_ROLES = ["admin", "approver", "checker", "reviewer", "submitter", "viewer"];
const ROLE_RANK: Record<string, number> = { admin: 0, approver: 1, checker: 2, reviewer: 3, submitter: 4, viewer: 5 };

export default function ProfileAvatar() {
  const { user, loading, login, logout, isAuthenticated } = useAuth();
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  if (loading) {
    return <div className="profile-avatar-skeleton" />;
  }

  if (!isAuthenticated) {
    return (
      <button className="profile-login-btn" onClick={login}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M15 3h4a2 2 0 012 2v14a2 2 0 01-2 2h-4" />
          <polyline points="10 17 15 12 10 7" />
          <line x1="15" y1="12" x2="3" y2="12" />
        </svg>
        Sign In
      </button>
    );
  }

  const initials = getInitials(user!);
  const color = getAvatarColor(user!.preferred_username || user!.email || "user");
  const displayName = user!.name || user!.preferred_username || user!.email || "User";
  const primaryRole =
    user!.roles
      .filter((r) => KNOWN_ROLES.includes(r))
      .sort((a, b) => (ROLE_RANK[a] ?? 99) - (ROLE_RANK[b] ?? 99))[0] || "viewer";

  return (
    <div className="profile-wrapper" ref={menuRef}>
      <button
        className="profile-avatar-btn"
        onClick={() => setOpen(!open)}
        title={displayName}
        style={{ backgroundColor: color }}
      >
        {initials}
      </button>

      {open && (
        <div className="profile-dropdown">
          <div className="profile-dropdown-header">
            <div className="profile-dropdown-avatar" style={{ backgroundColor: color }}>
              {initials}
            </div>
            <div className="profile-dropdown-info">
              <span className="profile-dropdown-name">{displayName}</span>
              {user!.email && <span className="profile-dropdown-email">{user!.email}</span>}
            </div>
          </div>

          <div className="profile-dropdown-roles">
            {user!.roles
              .filter((r) => KNOWN_ROLES.includes(r))
              .sort((a, b) => (ROLE_RANK[a] ?? 99) - (ROLE_RANK[b] ?? 99))
              .map((role) => (
                <span key={role} className={`profile-role-badge ${roleBadgeClass(role)}`}>
                  {role}
                </span>
              ))}
          </div>

          <div className="profile-dropdown-divider" />

          <button className="profile-dropdown-item" onClick={logout}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4" />
              <polyline points="16 17 21 12 16 7" />
              <line x1="21" y1="12" x2="9" y2="12" />
            </svg>
            Sign Out
          </button>
        </div>
      )}
    </div>
  );
}

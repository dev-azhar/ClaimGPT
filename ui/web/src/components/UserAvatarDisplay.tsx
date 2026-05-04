"use client";

/**
 * <UserAvatarDisplay /> — purely visual avatar (initials in a coloured circle).
 *
 * Use this anywhere you need to *show* the current user without any
 * built-in click behaviour. <ProfileAvatar /> by contrast is a self-contained
 * button + dropdown; nesting it inside another menu trigger creates two
 * overlapping dropdowns.
 */

import { useAuth } from "@/lib/auth";

const AVATAR_COLORS = ["#0369a1", "#7c3aed", "#c026d3", "#0891b2", "#059669", "#d97706"];

function getInitials(u: { name?: string; preferred_username?: string; email?: string; given_name?: string; family_name?: string }): string {
  if (u.given_name && u.family_name) return (u.given_name[0] + u.family_name[0]).toUpperCase();
  if (u.name) {
    const parts = u.name.trim().split(/\s+/);
    return parts.length >= 2 ? (parts[0][0] + parts[parts.length - 1][0]).toUpperCase() : parts[0].slice(0, 2).toUpperCase();
  }
  if (u.preferred_username) return u.preferred_username.slice(0, 2).toUpperCase();
  if (u.email) return u.email.slice(0, 2).toUpperCase();
  return "U";
}
function getAvatarColor(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
  return AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length];
}

export default function UserAvatarDisplay({ size = 32 }: { size?: number }) {
  const { user } = useAuth();
  if (!user) {
    return (
      <span
        className="user-avatar-display user-avatar-display-anon"
        style={{ width: size, height: size, fontSize: Math.round(size * 0.4) }}
        aria-hidden
      >
        ?
      </span>
    );
  }
  const initials = getInitials(user);
  const color = getAvatarColor(user.preferred_username || user.email || "user");
  return (
    <span
      className="user-avatar-display"
      style={{
        width: size,
        height: size,
        fontSize: Math.round(size * 0.4),
        backgroundColor: color,
      }}
      aria-hidden
    >
      {initials}
    </span>
  );
}

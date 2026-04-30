"use client";

/**
 * <Can /> — declarative RBAC guard.
 *
 * Hides children unless the current user has the required role(s).
 * Admin role implicitly satisfies any check (see auth.tsx userHasRole).
 *
 * Examples:
 *   <Can role="admin"><AdminBadge /></Can>
 *   <Can anyOf={["checker", "approver"]}><AuthorizeButton /></Can>
 *   <Can role="approver" fallback={<PendingPill />}><AuthorizeButton /></Can>
 */

import { ReactNode } from "react";
import { useAuth, type Role } from "@/lib/auth";

interface CanProps {
  /** Single required role */
  role?: Role;
  /** User must have at least one of these roles */
  anyOf?: Role[];
  /** Render this when the user lacks the role (defaults to null) */
  fallback?: ReactNode;
  children: ReactNode;
}

export default function Can({ role, anyOf, fallback = null, children }: CanProps) {
  const { hasRole, hasAnyRole } = useAuth();

  let allowed = false;
  if (role) allowed = hasRole(role);
  else if (anyOf && anyOf.length) allowed = hasAnyRole(anyOf);

  return <>{allowed ? children : fallback}</>;
}

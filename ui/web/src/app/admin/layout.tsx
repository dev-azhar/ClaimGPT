"use client";

/* Admin section layout — gates all /admin/* routes to users with the `admin` role. */

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { useAuth, ROLES } from "@/lib/auth";

export default function AdminLayout({ children }: { children: ReactNode }) {
  const { hasRole, loading, isAuthenticated } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  // Redirect non-admins away
  useEffect(() => {
    if (loading) return;
    if (!isAuthenticated) {
      router.replace("/");
      return;
    }
    if (!hasRole(ROLES.ADMIN)) {
      router.replace("/tpa");
    }
  }, [loading, isAuthenticated, hasRole, router]);

  if (loading) return <div className="admin-loading">Loading admin console…</div>;
  if (!isAuthenticated || !hasRole(ROLES.ADMIN)) {
    return (
      <div className="admin-forbidden">
        <h2>Admin access required</h2>
        <p>This area is restricted to organisation administrators.</p>
        <Link href="/tpa" className="tpa-btn tpa-btn-primary">Return to dashboard</Link>
      </div>
    );
  }

  const navItems: { href: string; label: string }[] = [
    { href: "/admin/users",        label: "Users & Roles" },
    { href: "/admin/integrations", label: "Integrations" },
  ];

  return (
    <div className="admin-shell">
      <aside className="admin-sidebar">
        <div className="admin-sidebar-brand">
          <span className="admin-sidebar-mark">⚙︎</span>
          <div>
            <div className="admin-sidebar-title">Admin Console</div>
            <div className="admin-sidebar-sub">Organisation settings</div>
          </div>
        </div>
        <nav className="admin-sidebar-nav">
          {navItems.map((n) => (
            <Link
              key={n.href}
              href={n.href}
              className={`admin-sidebar-link ${pathname?.startsWith(n.href) ? "admin-sidebar-link-active" : ""}`}
            >
              {n.label}
            </Link>
          ))}
          <Link href="/tpa" className="admin-sidebar-link admin-sidebar-link-back">← Back to TPA portal</Link>
        </nav>
      </aside>
      <main className="admin-main">{children}</main>
    </div>
  );
}

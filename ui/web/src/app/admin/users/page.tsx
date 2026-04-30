"use client";

/**
 * Admin → Users & Roles
 *
 * Local-state stub for org user management. In production this should call
 * the Keycloak Admin API (or our backend's /admin/users proxy) for CRUD.
 * Roles are sourced from libs/auth ROLES constant so they stay in sync.
 */

import { FormEvent, useMemo, useState } from "react";
import { useAuth, ROLES, ALL_ROLES, type Role } from "@/lib/auth";

interface OrgUser {
  id: string;
  name: string;
  email: string;
  roles: Role[];
  status: "active" | "invited" | "disabled";
  invitedAt: string;
}

const SEED_USERS: OrgUser[] = [
  { id: "u-1", name: "Riya Mehra",      email: "riya@aaron-tpa.in",   roles: [ROLES.ADMIN, ROLES.APPROVER], status: "active",  invitedAt: "2024-09-01T08:00:00Z" },
  { id: "u-2", name: "Aravind Pillai",  email: "aravind@aaron-tpa.in", roles: [ROLES.APPROVER, ROLES.REVIEWER], status: "active",  invitedAt: "2024-09-02T08:00:00Z" },
  { id: "u-3", name: "Suresh Kumar",    email: "suresh@aaron-tpa.in",  roles: [ROLES.CHECKER, ROLES.REVIEWER], status: "active",  invitedAt: "2024-09-04T08:00:00Z" },
  { id: "u-4", name: "Neha Sharma",     email: "neha@aaron-tpa.in",    roles: [ROLES.REVIEWER],              status: "active",  invitedAt: "2024-09-06T08:00:00Z" },
  { id: "u-5", name: "Pratik Joshi",    email: "pratik@aaron-tpa.in",  roles: [ROLES.SUBMITTER],             status: "invited", invitedAt: "2024-10-12T08:00:00Z" },
];

const ROLE_LABEL: Record<Role, string> = {
  admin: "Admin",
  approver: "Approver",
  checker: "Checker",
  reviewer: "Reviewer",
  submitter: "Submitter",
  viewer: "Viewer",
};

const ROLE_DESC: Record<Role, string> = {
  admin: "Full access — manage users, integrations, and override decisions",
  approver: "Authorize settlements (final sign-off)",
  checker: "Validate a reviewer’s decision before settlement is requested",
  reviewer: "Approve / reject claims; request documents",
  submitter: "Upload claims and supporting documents",
  viewer: "Read-only dashboard access",
};

export default function AdminUsersPage() {
  const { user: me } = useAuth();
  const [users, setUsers] = useState<OrgUser[]>(SEED_USERS);
  const [search, setSearch] = useState("");
  const [filterRole, setFilterRole] = useState<"all" | Role>("all");

  // Invite form
  const [inviteOpen, setInviteOpen] = useState(false);
  const [inviteName, setInviteName] = useState("");
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRoles, setInviteRoles] = useState<Role[]>([ROLES.REVIEWER]);
  const [inviteError, setInviteError] = useState("");

  const filtered = useMemo(() => {
    return users.filter((u) => {
      if (filterRole !== "all" && !u.roles.includes(filterRole)) return false;
      if (!search.trim()) return true;
      const q = search.toLowerCase();
      return u.name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q);
    });
  }, [users, search, filterRole]);

  function toggleInviteRole(r: Role) {
    setInviteRoles((prev) => (prev.includes(r) ? prev.filter((x) => x !== r) : [...prev, r]));
  }

  function submitInvite(e: FormEvent) {
    e.preventDefault();
    setInviteError("");
    const email = inviteEmail.trim().toLowerCase();
    if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) { setInviteError("Enter a valid work email"); return; }
    if (users.some((u) => u.email.toLowerCase() === email)) { setInviteError("That user already exists"); return; }
    if (inviteRoles.length === 0) { setInviteError("Pick at least one role"); return; }

    const newUser: OrgUser = {
      id: `u-${Date.now()}`,
      name: inviteName.trim() || email.split("@")[0],
      email,
      roles: inviteRoles,
      status: "invited",
      invitedAt: new Date().toISOString(),
    };
    setUsers((prev) => [newUser, ...prev]);
    setInviteOpen(false);
    setInviteName(""); setInviteEmail(""); setInviteRoles([ROLES.REVIEWER]);
  }

  function toggleUserRole(uid: string, r: Role) {
    setUsers((prev) => prev.map((u) => {
      if (u.id !== uid) return u;
      return { ...u, roles: u.roles.includes(r) ? u.roles.filter((x) => x !== r) : [...u.roles, r] };
    }));
  }

  function setUserStatus(uid: string, status: OrgUser["status"]) {
    setUsers((prev) => prev.map((u) => (u.id === uid ? { ...u, status } : u)));
  }

  return (
    <div className="admin-page">
      <header className="admin-page-header">
        <div>
          <h1 className="admin-page-title">Users &amp; Roles</h1>
          <p className="admin-page-sub">
            Invite teammates and assign least-privilege roles. Maker-checker is enforced
            on settlement: a Reviewer requests, an Approver authorises.
          </p>
        </div>
        <button className="tpa-btn tpa-btn-primary" onClick={() => setInviteOpen(true)}>
          + Invite user
        </button>
      </header>

      <section className="admin-toolbar">
        <input
          className="admin-input"
          placeholder="Search name or email…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select
          className="admin-input"
          value={filterRole}
          onChange={(e) => setFilterRole(e.target.value as "all" | Role)}
        >
          <option value="all">All roles</option>
          {ALL_ROLES.map((r) => (
            <option key={r} value={r}>{ROLE_LABEL[r]}</option>
          ))}
        </select>
        <span className="admin-toolbar-count">{filtered.length} of {users.length}</span>
      </section>

      <section className="admin-card">
        <table className="admin-table">
          <thead>
            <tr>
              <th>User</th>
              <th>Roles</th>
              <th>Status</th>
              <th>Invited</th>
              <th aria-label="Actions"></th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((u) => (
              <tr key={u.id}>
                <td>
                  <div className="admin-user-cell">
                    <div className="admin-user-avatar">{u.name.split(" ").map((p) => p[0]).slice(0, 2).join("").toUpperCase()}</div>
                    <div>
                      <div className="admin-user-name">
                        {u.name}
                        {me?.email === u.email && <span className="admin-user-you">you</span>}
                      </div>
                      <div className="admin-user-email">{u.email}</div>
                    </div>
                  </div>
                </td>
                <td>
                  <div className="admin-role-chips">
                    {ALL_ROLES.map((r) => {
                      const active = u.roles.includes(r);
                      return (
                        <button
                          key={r}
                          type="button"
                          title={ROLE_DESC[r]}
                          onClick={() => toggleUserRole(u.id, r)}
                          className={`admin-role-chip ${active ? "admin-role-chip-active" : ""} admin-role-chip-${r}`}
                        >
                          {ROLE_LABEL[r]}
                        </button>
                      );
                    })}
                  </div>
                </td>
                <td>
                  <span className={`admin-status admin-status-${u.status}`}>{u.status}</span>
                </td>
                <td className="admin-muted">{new Date(u.invitedAt).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" })}</td>
                <td>
                  <div className="admin-row-actions">
                    {u.status === "active" && (
                      <button className="admin-link-btn" onClick={() => setUserStatus(u.id, "disabled")}>Disable</button>
                    )}
                    {u.status === "disabled" && (
                      <button className="admin-link-btn" onClick={() => setUserStatus(u.id, "active")}>Re-enable</button>
                    )}
                    {u.status === "invited" && (
                      <button className="admin-link-btn">Resend invite</button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr><td colSpan={5} className="admin-empty">No users match those filters</td></tr>
            )}
          </tbody>
        </table>
      </section>

      <section className="admin-role-legend">
        <h3>Role responsibilities</h3>
        <div className="admin-role-legend-grid">
          {ALL_ROLES.map((r) => (
            <div key={r} className="admin-role-legend-item">
              <span className={`admin-role-chip admin-role-chip-active admin-role-chip-${r}`}>{ROLE_LABEL[r]}</span>
              <p>{ROLE_DESC[r]}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Invite modal */}
      {inviteOpen && (
        <div className="tpa-modal-overlay" onClick={() => setInviteOpen(false)}>
          <div className="admin-modal" onClick={(e) => e.stopPropagation()}>
            <header className="admin-modal-header">
              <h2>Invite teammate</h2>
              <button className="admin-modal-close" onClick={() => setInviteOpen(false)} aria-label="Close">×</button>
            </header>
            <form onSubmit={submitInvite} className="admin-modal-body">
              <label className="admin-field">
                <span>Full name</span>
                <input
                  className="admin-input"
                  value={inviteName}
                  onChange={(e) => setInviteName(e.target.value)}
                  placeholder="e.g. Aravind Pillai"
                />
              </label>
              <label className="admin-field">
                <span>Work email *</span>
                <input
                  className="admin-input"
                  type="email"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  placeholder="aravind@yourtpa.in"
                  required
                  autoFocus
                />
              </label>
              <fieldset className="admin-field">
                <legend>Roles *</legend>
                <div className="admin-role-chips">
                  {ALL_ROLES.map((r) => (
                    <button
                      key={r}
                      type="button"
                      onClick={() => toggleInviteRole(r)}
                      title={ROLE_DESC[r]}
                      className={`admin-role-chip ${inviteRoles.includes(r) ? "admin-role-chip-active" : ""} admin-role-chip-${r}`}
                    >
                      {ROLE_LABEL[r]}
                    </button>
                  ))}
                </div>
              </fieldset>
              {inviteError && <div className="admin-error">{inviteError}</div>}
              <footer className="admin-modal-footer">
                <button type="button" className="tpa-btn tpa-btn-secondary" onClick={() => setInviteOpen(false)}>Cancel</button>
                <button type="submit" className="tpa-btn tpa-btn-primary">Send invite</button>
              </footer>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

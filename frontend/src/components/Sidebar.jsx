import React from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "@/lib/auth";
import { Lightning, ChartBar, ListChecks, Buildings, Calendar, SignOut, Gear } from "@phosphor-icons/react";

const items = [
  { to: "/", label: "Dashboard", icon: ChartBar, testid: "nav-dashboard" },
  { to: "/transactions", label: "Transactions", icon: ListChecks, testid: "nav-transactions" },
  { to: "/project-pnl", label: "Project P&L", icon: Buildings, testid: "nav-project-pnl" },
  { to: "/monthly", label: "Monthly", icon: Calendar, testid: "nav-monthly" },
  { to: "/settings", label: "Settings", icon: Gear, testid: "nav-settings" },
];

export default function Sidebar() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  return (
    <aside className="w-60 shrink-0 bg-white border-r border-neutral-200 flex flex-col h-screen sticky top-0">
      <div className="px-5 py-5 border-b border-neutral-200">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 bg-yellow-400 flex items-center justify-center">
            <Lightning weight="fill" size={20} className="text-neutral-900" />
          </div>
          <div>
            <div className="font-heading font-bold text-sm tracking-tight leading-tight">RUDAYA POWER</div>
            <div className="text-[10px] uppercase tracking-[0.2em] text-neutral-500">Finance Tracker</div>
          </div>
        </div>
      </div>
      <nav className="flex-1 py-4">
        {items.map((it) => (
          <NavLink
            key={it.to}
            to={it.to}
            end={it.to === "/"}
            data-testid={it.testid}
            className={({ isActive }) =>
              `flex items-center gap-3 px-5 py-2.5 text-sm border-l-2 transition-colors ${
                isActive
                  ? "border-yellow-400 bg-neutral-50 text-neutral-900 font-medium"
                  : "border-transparent text-neutral-600 hover:bg-neutral-50 hover:text-neutral-900"
              }`
            }
          >
            <it.icon size={18} />
            {it.label}
          </NavLink>
        ))}
      </nav>
      <div className="p-4 border-t border-neutral-200">
        <div className="text-xs text-neutral-500 mb-1 uppercase tracking-wider">Signed in</div>
        <div className="text-sm font-medium truncate" data-testid="sidebar-user-email">{user?.email}</div>
        <button
          data-testid="logout-button"
          onClick={async () => { await logout(); nav("/login"); }}
          className="mt-3 w-full text-sm flex items-center justify-center gap-2 py-2 border border-neutral-300 hover:bg-neutral-100 transition-colors"
        >
          <SignOut size={16} /> Sign out
        </button>
      </div>
    </aside>
  );
}

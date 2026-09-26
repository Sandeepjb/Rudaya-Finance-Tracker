import React from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "@/lib/auth";
import { ChartBar, ListChecks, Buildings, Calendar, SignOut, Gear, Target, ChartPieSlice, FileText, Wallet, Database, Bank } from "@phosphor-icons/react";

const items = [
  { to: "/", label: "Dashboard", icon: ChartBar, testid: "nav-dashboard" },
  { to: "/transactions", label: "Transactions", icon: ListChecks, testid: "nav-transactions" },
  { to: "/bank-transactions", label: "Bank Transactions", icon: Bank, testid: "nav-bank-transactions", adminOnly: true },
  { to: "/quotations", label: "Quotations", icon: FileText, testid: "nav-quotations" },
  { to: "/sales-forecast", label: "Sales Forecast", icon: Target, testid: "nav-sales-forecast" },
  { to: "/forecast", label: "Forecast vs Actual", icon: ChartPieSlice, testid: "nav-forecast" },
  { to: "/budget", label: "Expense Budget", icon: Wallet, testid: "nav-budget" },
  { to: "/project-pnl", label: "Project P&L", icon: Buildings, testid: "nav-project-pnl" },
  { to: "/monthly", label: "Monthly", icon: Calendar, testid: "nav-monthly" },
  { to: "/settings", label: "Settings", icon: Gear, testid: "nav-settings" },
];

const adminItems = [
  { to: "/admin/data-migration", label: "Data Migration", icon: Database, testid: "nav-data-migration" },
];

export default function Sidebar() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  return (
    <aside className="w-60 shrink-0 bg-white border-r border-neutral-200 flex flex-col h-screen sticky top-0">
      <div className="px-5 py-5 border-b border-neutral-200">
        <img
          src="/rudaya-logo.png"
          alt="Rudaya Powers Pvt. Ltd."
          className="h-11 w-auto object-contain"
          data-testid="sidebar-logo"
        />
        <div className="text-[10px] uppercase tracking-[0.2em] text-neutral-500 mt-2">Finance Tracker</div>
      </div>
      <nav className="flex-1 py-4 overflow-y-auto">
        {items.filter((it) => !it.adminOnly || user?.role === "admin").map((it) => (
          <NavLink
            key={it.to}
            to={it.to}
            end={it.to === "/"}
            data-testid={it.testid}
            className={({ isActive }) =>
              `flex items-center gap-3 px-5 py-2.5 text-sm border-l-2 transition-colors ${
                isActive
                  ? "border-red-600 bg-neutral-50 text-neutral-900 font-medium"
                  : "border-transparent text-neutral-600 hover:bg-neutral-50 hover:text-neutral-900"
              }`
            }
          >
            <it.icon size={18} />
            {it.label}
          </NavLink>
        ))}
        <div className="mt-6 px-5 text-[10px] uppercase tracking-[0.2em] text-neutral-400" data-testid="nav-admin-section">
          Administration
        </div>
        {adminItems.map((it) => (
          <NavLink
            key={it.to}
            to={it.to}
            data-testid={it.testid}
            className={({ isActive }) =>
              `flex items-center gap-3 px-5 py-2.5 text-sm border-l-2 transition-colors mt-1 ${
                isActive
                  ? "border-red-600 bg-neutral-50 text-neutral-900 font-medium"
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

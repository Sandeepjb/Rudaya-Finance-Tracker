import React from "react";
import { confidenceBand } from "@/lib/bankInbox";

export function ConfidenceBadge({ value, showBar = true }) {
  const band = confidenceBand(value);
  return (
    <div className="flex items-center gap-2" data-testid="confidence-badge">
      <span className={`inline-block text-[10px] uppercase tracking-wider px-2 py-0.5 border ${band.cls}`}>
        {value != null ? `${value}%` : "—"} · {band.label}
      </span>
      {showBar && (
        <div className="w-16 h-1.5 bg-neutral-200">
          <div className={`h-full ${band.bar}`} style={{ width: `${value || 0}%` }} />
        </div>
      )}
    </div>
  );
}

export function DirectionBadge({ direction }) {
  const debit = direction === "debit";
  return (
    <span data-testid="direction-badge" className={`inline-block text-[10px] uppercase tracking-wider px-2 py-0.5 border ${debit ? "border-neutral-800 text-neutral-800 bg-white" : "border-blue-600 text-blue-700 bg-blue-50"}`}>
      {direction}
    </span>
  );
}

export function StatusBadge({ status }) {
  const map = {
    pending: "border-amber-600 text-amber-700 bg-amber-50",
    approved: "border-emerald-600 text-emerald-700 bg-emerald-50",
    rejected: "border-neutral-500 text-neutral-600 bg-neutral-50",
    duplicate: "border-red-600 text-red-700 bg-red-50",
  };
  return (
    <span data-testid="status-badge" className={`inline-block text-[10px] uppercase tracking-wider px-2 py-0.5 border ${map[status] || ""}`}>{status}</span>
  );
}

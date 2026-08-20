import React from "react";
import { typeColor } from "@/lib/format";

const styles = {
  Revenue: "border-emerald-600 text-emerald-700 bg-emerald-50",
  Cost: "border-red-600 text-red-700 bg-red-50",
  Expense: "border-amber-600 text-amber-700 bg-amber-50",
};

export function TypeBadge({ type }) {
  const cls = styles[type] || "border-neutral-400 text-neutral-700 bg-neutral-50";
  return (
    <span className={`inline-block text-[10px] uppercase tracking-wider px-2 py-0.5 border ${cls}`}>
      {type}
    </span>
  );
}

export { typeColor };

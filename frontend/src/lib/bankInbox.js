export function confidenceBand(c) {
  if (c == null) return { label: "Unclassified", cls: "border-neutral-400 text-neutral-600 bg-neutral-50", bar: "bg-neutral-400" };
  if (c >= 90) return { label: "High confidence", cls: "border-emerald-600 text-emerald-700 bg-emerald-50", bar: "bg-emerald-600" };
  if (c >= 70) return { label: "Medium confidence", cls: "border-amber-600 text-amber-700 bg-amber-50", bar: "bg-amber-500" };
  return { label: "Needs Review", cls: "border-red-600 text-red-700 bg-red-50", bar: "bg-red-600" };
}

export const SOURCE_LABEL = {
  mapping_rule: "Learned mapping rule",
  historical: "Historical similarity",
  ai: "AI-assisted",
  none: "No suggestion",
};

export const fmtDate = (iso) => {
  if (!iso) return "";
  const d = new Date(iso.slice(0, 10) + "T00:00:00");
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
};

export const STATUS_TABS = [
  { key: "pending", label: "Pending" },
  { key: "approved", label: "Approved" },
  { key: "rejected", label: "Rejected" },
  { key: "duplicate", label: "Duplicates" },
  { key: "all", label: "All" },
];

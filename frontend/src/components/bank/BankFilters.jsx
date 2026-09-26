import React from "react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

const sel = "rounded-none border border-neutral-300 h-9 px-2 text-sm bg-white";

export default function BankFilters({ f, setF, meta, onReset }) {
  const set = (k) => (e) => setF((x) => ({ ...x, [k]: e.target.value }));
  return (
    <div className="bg-white border border-neutral-200 p-3 grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-2" data-testid="bank-filters">
      <Input data-testid="filter-search" placeholder="Search narration / ref" className="rounded-none" value={f.search} onChange={set("search")} />
      <Input data-testid="filter-bank" placeholder="Bank" className="rounded-none" value={f.bank} onChange={set("bank")} />
      <select data-testid="filter-direction" className={sel} value={f.direction} onChange={set("direction")}>
        <option value="">Debit / Credit</option><option value="debit">Debit</option><option value="credit">Credit</option>
      </select>
      <select data-testid="filter-type" className={sel} value={f.suggested_type} onChange={set("suggested_type")}>
        <option value="">Suggested type</option><option>Revenue</option><option>Cost</option><option>Expense</option>
      </select>
      <select data-testid="filter-account" className={sel} value={f.account} onChange={set("account")}>
        <option value="">Account</option>{(meta?.accounts || []).map((a) => <option key={a.name}>{a.name}</option>)}
      </select>
      <select data-testid="filter-project" className={`${sel} font-mono-tab`} value={f.project_id} onChange={set("project_id")}>
        <option value="">Project ID</option>{(meta?.project_ids || []).map((p) => <option key={p.code}>{p.code}</option>)}
      </select>
      <Input data-testid="filter-start" type="date" className="rounded-none" value={f.start_date} onChange={set("start_date")} />
      <Input data-testid="filter-end" type="date" className="rounded-none" value={f.end_date} onChange={set("end_date")} />
      <Input data-testid="filter-min-amount" type="number" placeholder="Min ₹" className="rounded-none font-mono-tab" value={f.min_amount} onChange={set("min_amount")} />
      <Input data-testid="filter-max-amount" type="number" placeholder="Max ₹" className="rounded-none font-mono-tab" value={f.max_amount} onChange={set("max_amount")} />
      <select data-testid="filter-confidence" className={sel} value={f.confidence} onChange={set("confidence")}>
        <option value="">Confidence</option><option value="high">High (90-100)</option><option value="medium">Medium (70-89)</option><option value="low">Needs review (&lt;70)</option>
      </select>
      <Button data-testid="filter-reset" variant="outline" className="rounded-none" onClick={onReset}>Reset</Button>
    </div>
  );
}

export const EMPTY_FILTERS = { search: "", bank: "", direction: "", suggested_type: "", account: "", project_id: "", start_date: "", end_date: "", min_amount: "", max_amount: "", confidence: "" };

export function filtersToParams(f) {
  const p = {};
  for (const k of ["search", "bank", "direction", "suggested_type", "account", "project_id", "start_date", "end_date", "min_amount", "max_amount"]) if (f[k]) p[k] = f[k];
  if (f.confidence === "high") p.min_confidence = 90;
  if (f.confidence === "medium") { p.min_confidence = 70; p.max_confidence = 89; }
  if (f.confidence === "low") p.max_confidence = 69;
  return p;
}

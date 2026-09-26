import React, { useState } from "react";
import { api, formatApiError, inr } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { Checks, X } from "@phosphor-icons/react";

export default function BulkApproveBar({ rows, selected, setSelected, onDone }) {
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState(null);
  const eligible = rows.filter((r) => r.status === "pending");
  const high = eligible.filter((r) => (r.suggestion?.confidence ?? 0) >= 90 && r.suggestion?.type);
  const total = eligible.filter((r) => selected.has(r.id)).reduce((s, r) => s + r.amount, 0);

  const approve = async () => {
    if (!selected.size) return;
    if (!window.confirm(`Approve & Post ${selected.size} bank transaction(s) totalling ${inr(total)}?`)) return;
    setBusy(true);
    try {
      const r = await api.post("/bank-transactions/bulk-approve", { ids: [...selected] });
      setReport(r.data);
      toast[r.data.failed ? "warning" : "success"](`${r.data.approved} approved, ${r.data.failed} skipped`);
      setSelected(new Set());
      onDone();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  return (
    <div className="space-y-2">
      <div className="bg-white border border-neutral-200 p-2 flex items-center gap-2 flex-wrap" data-testid="bulk-bar">
        <Button data-testid="bulk-select-high" size="sm" variant="outline" className="rounded-none" onClick={() => setSelected(new Set(high.map((r) => r.id)))} disabled={!high.length}>Select all ≥90% ({high.length})</Button>
        <Button data-testid="bulk-select-all" size="sm" variant="outline" className="rounded-none" onClick={() => setSelected(new Set(eligible.map((r) => r.id)))} disabled={!eligible.length}>Select all ({eligible.length})</Button>
        <Button data-testid="bulk-clear" size="sm" variant="ghost" className="rounded-none" onClick={() => setSelected(new Set())} disabled={!selected.size}><X size={14} className="mr-1" /> Clear</Button>
        <div className="ml-auto text-xs text-neutral-600" data-testid="bulk-summary">{selected.size} selected · {inr(total)}</div>
        <Button data-testid="bulk-approve-btn" size="sm" className="rounded-none bg-emerald-700 hover:bg-emerald-600" onClick={approve} disabled={busy || !selected.size}><Checks size={14} className="mr-1" /> {busy ? "Posting…" : `Approve & Post selected (${selected.size})`}</Button>
      </div>
      {report && (
        <div className="bg-white border border-neutral-200 p-3 text-xs" data-testid="bulk-report">
          <div className="flex justify-between mb-1"><span className="font-medium">Bulk result: {report.approved} approved, {report.failed} skipped</span><button data-testid="bulk-report-close" onClick={() => setReport(null)}><X size={12} /></button></div>
          <ul className="space-y-0.5 max-h-40 overflow-auto">
            {report.results.map((r) => <li key={r.id} className={r.ok ? "text-emerald-700" : "text-red-700"} data-testid="bulk-result-row">{r.ok ? `✓ ${r.narration} · ${inr(r.amount)} → finance ${r.finance_transaction_id}` : `✗ ${r.id}: ${r.error}`}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

import React from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { inr } from "@/lib/api";
import { fmtDate, SOURCE_LABEL } from "@/lib/bankInbox";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { TypeBadge } from "@/components/TypeBadge";

export default function ExplainDialog({ txn, open, onOpenChange }) {
  if (!txn) return null;
  const s = txn.suggestion || {};
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl rounded-none border-l-2 border-l-neutral-900" data-testid="explain-dialog">
        <DialogHeader>
          <div className="text-[11px] uppercase tracking-[0.25em] text-neutral-500">Why this suggestion?</div>
          <DialogTitle className="font-heading text-xl tracking-tight">{txn.narration}</DialogTitle>
          <DialogDescription>
            Source: <span className="font-medium text-neutral-800">{SOURCE_LABEL[s.source] || s.source}</span> · Pattern key: <span className="font-mono-tab">{s.merchant_key || "—"}</span>
          </DialogDescription>
        </DialogHeader>
        <div className="flex items-center gap-4 flex-wrap">
          {s.type && <TypeBadge type={s.type} />}
          <span className="text-sm">{s.account || "—"} · <span className="font-mono-tab">{s.project_id || "—"}</span></span>
          <ConfidenceBadge value={s.confidence} />
        </div>
        <ul className="mt-2 space-y-1.5 text-sm text-neutral-700 list-disc pl-5" data-testid="explain-reasons">
          {(s.reasons || []).map((r, i) => <li key={i}>{r}</li>)}
          {s.direction_note && <li className="text-neutral-500">{s.direction_note}</li>}
        </ul>
        <div className="mt-4">
          <div className="text-[10px] uppercase tracking-[0.2em] text-neutral-500 mb-2">Historical matches ({(txn.matches || []).length})</div>
          <div className="border border-neutral-200 max-h-64 overflow-auto">
            <table className="w-full text-xs" data-testid="historical-matches-table">
              <thead className="bg-neutral-50 text-neutral-500 uppercase tracking-wider text-[10px]">
                <tr><th className="text-left p-2">Date</th><th className="text-left p-2">Type</th><th className="text-left p-2">Account</th><th className="text-left p-2">Project</th><th className="text-right p-2">Amount</th><th className="text-left p-2">Notes</th><th className="text-right p-2">Similarity</th></tr>
              </thead>
              <tbody>
                {(txn.matches || []).map((m) => (
                  <tr key={m.id} className="border-t border-neutral-100">
                    <td className="p-2 font-mono-tab">{fmtDate(m.date)}</td>
                    <td className="p-2"><TypeBadge type={m.type} /></td>
                    <td className="p-2">{m.account}</td>
                    <td className="p-2 font-mono-tab">{m.project_id}</td>
                    <td className="p-2 text-right font-mono-tab">{inr(m.amount)}</td>
                    <td className="p-2 truncate max-w-[180px]" title={m.notes}>{m.notes}</td>
                    <td className="p-2 text-right font-mono-tab">{Math.round(m.similarity * 100)}%</td>
                  </tr>
                ))}
                {!(txn.matches || []).length && <tr><td colSpan={7} className="p-3 text-center text-neutral-500">No historical matches</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

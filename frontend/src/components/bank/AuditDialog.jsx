import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";

export default function AuditDialog({ txn, open, onOpenChange }) {
  const [rows, setRows] = useState([]);
  useEffect(() => {
    if (!open || !txn) return;
    api.get(`/bank-transactions/${txn.id}/audit`).then((r) => setRows(r.data)).catch(() => setRows([]));
  }, [open, txn]);
  if (!txn) return null;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl rounded-none" data-testid="audit-dialog">
        <DialogHeader>
          <div className="text-[11px] uppercase tracking-[0.25em] text-neutral-500">Audit history</div>
          <DialogTitle className="font-heading text-xl tracking-tight">{txn.narration}</DialogTitle>
          <DialogDescription>Every action recorded with actor, timestamp and before/after values.</DialogDescription>
        </DialogHeader>
        <div className="max-h-96 overflow-auto space-y-2">
          {rows.map((r) => (
            <div key={r.id} className="border border-neutral-200 p-2 text-xs" data-testid="audit-row">
              <div className="flex justify-between"><span className="uppercase tracking-wider font-medium">{r.action}</span><span className="font-mono-tab text-neutral-500">{new Date(r.timestamp).toLocaleString("en-IN")} · {r.actor}</span></div>
              {(r.previous || r.new) && (
                <div className="grid grid-cols-2 gap-2 mt-1 text-[11px] text-neutral-600">
                  <div><div className="text-neutral-400">Before</div><pre className="whitespace-pre-wrap break-all">{r.previous ? JSON.stringify(r.previous, null, 0) : "—"}</pre></div>
                  <div><div className="text-neutral-400">After</div><pre className="whitespace-pre-wrap break-all">{r.new ? JSON.stringify(r.new, null, 0) : "—"}</pre></div>
                </div>
              )}
            </div>
          ))}
          {!rows.length && <div className="text-sm text-neutral-500 p-4 text-center">No audit records.</div>}
        </div>
      </DialogContent>
    </Dialog>
  );
}

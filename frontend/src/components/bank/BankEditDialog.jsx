import React, { useEffect, useState } from "react";
import { api, formatApiError, inr } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { toast } from "sonner";
import { Check, X, PencilSimple } from "@phosphor-icons/react";

function Field({ label, children, modified }) {
  return (
    <div>
      <Label className="text-[10px] uppercase tracking-wider text-neutral-500 flex items-center gap-2">
        {label} {modified && <span className="text-[9px] px-1 border border-yellow-600 text-yellow-700 bg-yellow-50" data-testid="modified-tag">Modified</span>}
      </Label>
      <div className="mt-1">{children}</div>
    </div>
  );
}

const sel = "w-full rounded-none border border-neutral-300 h-9 px-2 text-sm bg-white";

export default function BankEditDialog({ txn, meta, open, onOpenChange, onSaved }) {
  const [form, setForm] = useState({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open || !txn) return;
    const s = txn.suggestion || {};
    setForm({
      type: s.type || "Expense", account: s.account || "", project_id: s.project_id || "",
      amount: txn.amount, date: txn.transaction_date, notes: s.notes || txn.narration,
      ...(txn.user_edits || {}),
    });
  }, [txn, open]);

  if (!txn) return null;
  const s = txn.suggestion || {};
  const base = { type: s.type, account: s.account, project_id: s.project_id, amount: txn.amount, date: txn.transaction_date, notes: s.notes || txn.narration };
  const mod = (k) => String(form[k] ?? "") !== String(base[k] ?? "");
  const setField = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const save = async () => {
    setSaving(true);
    try {
      const r = await api.put(`/bank-transactions/${txn.id}`, { ...form, amount: parseFloat(form.amount) });
      toast.success("Classification updated — review then Approve & Post");
      onSaved(r.data);
      onOpenChange(false);
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    } finally { setSaving(false); }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg rounded-none border-l-2 border-l-yellow-500" data-testid="bank-edit-dialog">
        <DialogHeader>
          <div className="text-[11px] uppercase tracking-[0.25em] text-neutral-500 flex items-center gap-1"><PencilSimple size={12} /> Edit before approval</div>
          <DialogTitle className="font-heading text-xl tracking-tight">{txn.bank_name} · {inr(txn.amount)} {txn.direction}</DialogTitle>
          <DialogDescription>{txn.narration}</DialogDescription>
        </DialogHeader>
        <div className="border border-neutral-200 bg-neutral-50 p-2 text-xs text-neutral-600" data-testid="original-suggestion">
          <span className="uppercase tracking-wider text-[10px] text-neutral-500">Suggested:</span> {s.type || "—"} · {s.account || "—"} · <span className="font-mono-tab">{s.project_id || "—"}</span> ({s.confidence ?? 0}%)
        </div>
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Date" modified={mod("date")}><Input data-testid="bank-edit-date" type="date" className="rounded-none" value={(form.date || "").slice(0, 10)} onChange={(e) => setField("date", e.target.value)} /></Field>
            <Field label="Type" modified={mod("type")}>
              <select data-testid="bank-edit-type" value={form.type || ""} onChange={(e) => setField("type", e.target.value)} className={sel}>
                <option value="Revenue">Revenue</option><option value="Cost">Cost</option><option value="Expense">Expense</option>
              </select>
            </Field>
          </div>
          <Field label="Amount (₹)" modified={mod("amount")}><Input data-testid="bank-edit-amount" type="number" step="0.01" className="rounded-none font-mono-tab" value={form.amount ?? ""} onChange={(e) => setField("amount", e.target.value)} /></Field>
          <Field label="Account" modified={mod("account")}>
            <select data-testid="bank-edit-account" value={form.account || ""} onChange={(e) => setField("account", e.target.value)} className={sel}>
              <option value="">— select —</option>
              {(meta?.accounts || []).map((a) => <option key={a.name} value={a.name}>{a.name}</option>)}
            </select>
          </Field>
          <Field label="Project ID" modified={mod("project_id")}>
            <select data-testid="bank-edit-project" value={form.project_id || ""} onChange={(e) => setField("project_id", e.target.value)} className={`${sel} font-mono-tab`}>
              <option value="">— select —</option>
              {(meta?.project_ids || []).map((p) => <option key={p.code} value={p.code}>{p.code}</option>)}
            </select>
          </Field>
          <Field label="Notes" modified={mod("notes")}><Input data-testid="bank-edit-notes" className="rounded-none" value={form.notes || ""} onChange={(e) => setField("notes", e.target.value)} /></Field>
          <div className="flex justify-end gap-2 pt-2">
            <Button data-testid="bank-edit-cancel" variant="outline" className="rounded-none" onClick={() => onOpenChange(false)}><X size={14} className="mr-1" /> Cancel</Button>
            <Button data-testid="bank-edit-save" onClick={save} disabled={saving} className="rounded-none bg-neutral-900 hover:bg-neutral-700"><Check size={14} className="mr-1" /> {saving ? "Saving…" : "Save changes"}</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

import React, { useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { toast } from "sonner";
import { Plus } from "@phosphor-icons/react";

const INIT = { bank_name: "ICICI Bank", bank_account: "", transaction_date: new Date().toISOString().slice(0, 10), transaction_time: "", direction: "debit", amount: "", narration: "", bank_reference: "", utr_reference: "" };

function F({ label, children }) {
  return <div><Label className="text-[10px] uppercase tracking-wider text-neutral-500">{label}</Label><div className="mt-1">{children}</div></div>;
}

export default function ManualBankTxnDialog({ open, onOpenChange, onCreated }) {
  const [form, setForm] = useState(INIT);
  const [saving, setSaving] = useState(false);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async () => {
    setSaving(true);
    try {
      const r = await api.post("/bank-transactions/manual", { ...form, amount: parseFloat(form.amount), source: "manual" });
      toast.success(r.data.status === "duplicate" ? "Ingested — flagged as DUPLICATE" : `Ingested — suggestion ${r.data.suggestion?.confidence ?? 0}% confidence`);
      setForm(INIT);
      onCreated(r.data);
      onOpenChange(false);
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setSaving(false); }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg rounded-none border-l-2 border-l-neutral-900" data-testid="manual-bank-dialog">
        <DialogHeader>
          <div className="text-[11px] uppercase tracking-[0.25em] text-neutral-500">Admin · Phase 1 testing</div>
          <DialogTitle className="font-heading text-xl tracking-tight">Manual Bank Transaction</DialogTitle>
          <DialogDescription>Runs through the same duplicate detection → historical matching → AI suggestion → approval pipeline as external ingestion.</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <F label="Bank"><Input data-testid="manual-bank" className="rounded-none" value={form.bank_name} onChange={set("bank_name")} /></F>
            <F label="Bank Account"><Input data-testid="manual-account" className="rounded-none font-mono-tab" value={form.bank_account} onChange={set("bank_account")} placeholder="Masked in UI" /></F>
            <F label="Date"><Input data-testid="manual-date" type="date" className="rounded-none" value={form.transaction_date} onChange={set("transaction_date")} /></F>
            <F label="Time"><Input data-testid="manual-time" type="time" className="rounded-none" value={form.transaction_time} onChange={set("transaction_time")} /></F>
            <F label="Direction">
              <select data-testid="manual-direction" className="w-full rounded-none border border-neutral-300 h-9 px-2 text-sm bg-white" value={form.direction} onChange={set("direction")}>
                <option value="debit">Debit</option><option value="credit">Credit</option>
              </select>
            </F>
            <F label="Amount (₹)"><Input data-testid="manual-amount" type="number" step="0.01" className="rounded-none font-mono-tab" value={form.amount} onChange={set("amount")} /></F>
          </div>
          <F label="Narration"><Input data-testid="manual-narration" className="rounded-none" value={form.narration} onChange={set("narration")} placeholder="e.g. MICROSOFT SUBSCRIPTION E080105RXG" /></F>
          <div className="grid grid-cols-2 gap-3">
            <F label="Bank Reference"><Input data-testid="manual-reference" className="rounded-none font-mono-tab" value={form.bank_reference} onChange={set("bank_reference")} /></F>
            <F label="UTR"><Input data-testid="manual-utr" className="rounded-none font-mono-tab" value={form.utr_reference} onChange={set("utr_reference")} /></F>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button data-testid="manual-cancel" variant="outline" className="rounded-none" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button data-testid="manual-submit" onClick={submit} disabled={saving || !form.amount || !form.narration} className="rounded-none bg-neutral-900 hover:bg-neutral-700"><Plus size={14} className="mr-1" /> {saving ? "Ingesting…" : "Ingest to Inbox"}</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

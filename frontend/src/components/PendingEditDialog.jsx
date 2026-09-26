import React, { useEffect, useState } from "react";
import { api, formatApiError, inr } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { toast } from "sonner";
import { Check, X, PencilSimple } from "@phosphor-icons/react";

const MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/**
 * Inline editor for a pending AI proposal. Supports transaction and sales_forecast fully,
 * and a light amount/notes edit for quotation single-line proposals.
 */
export default function PendingEditDialog({ pending, open, onOpenChange, onSaved }) {
  const [form, setForm] = useState({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open || !pending) return;
    setForm({ ...(pending.data || {}) });
  }, [pending, open]);

  if (!pending) return null;
  const kind = pending.kind;

  const setField = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const save = async () => {
    setSaving(true);
    try {
      const payload = { ...form };
      if (payload.amount != null) payload.amount = parseFloat(payload.amount);
      if (payload.year != null) payload.year = parseInt(payload.year);
      if (payload.month != null) payload.month = parseInt(payload.month);
      if (payload.expected_year != null) payload.expected_year = parseInt(payload.expected_year);
      if (payload.expected_month != null) payload.expected_month = parseInt(payload.expected_month);
      const r = await api.put(`/ai/pending/${pending.id}`, { data: payload });
      toast.success("Proposal updated");
      onSaved(r.data);
      onOpenChange(false);
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    } finally { setSaving(false); }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg rounded-none border-l-2 border-l-yellow-500" data-testid="pending-edit-dialog">
        <DialogHeader>
          <div className="text-[11px] uppercase tracking-[0.25em] text-neutral-500 flex items-center gap-1">
            <PencilSimple size={12} /> Edit before approval
          </div>
          <DialogTitle className="font-heading text-xl tracking-tight">
            {kind.replace("_", " ")} · {inr(form.amount || 0)}
          </DialogTitle>
          <DialogDescription>
            Adjust the AI's proposal before you approve it. Approve creates the real record; reject discards.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 mt-2">
          {kind === "transaction" && (
            <>
              <Field label="Date"><Input data-testid="edit-date" type="date" className="rounded-none" value={(form.date || "").slice(0, 10)} onChange={(e) => setField("date", e.target.value)} /></Field>
              <Field label="Type">
                <select data-testid="edit-type" value={form.type || "Revenue"} onChange={(e) => setField("type", e.target.value)} className="w-full rounded-none border border-neutral-300 h-9 px-2 text-sm">
                  <option value="Revenue">Revenue</option>
                  <option value="Cost">Cost</option>
                  <option value="Expense">Expense</option>
                </select>
              </Field>
              <Field label="Amount (₹)"><Input data-testid="edit-amount" type="number" step="0.01" className="rounded-none font-mono-tab" value={form.amount ?? ""} onChange={(e) => setField("amount", e.target.value)} /></Field>
              <Field label="Account"><Input data-testid="edit-account" className="rounded-none" value={form.account || ""} onChange={(e) => setField("account", e.target.value)} /></Field>
              <Field label="Project ID"><Input data-testid="edit-project" className="rounded-none font-mono-tab" value={form.project_id || ""} onChange={(e) => setField("project_id", e.target.value)} /></Field>
              <Field label="Notes"><Input data-testid="edit-notes" className="rounded-none" value={form.notes || ""} onChange={(e) => setField("notes", e.target.value)} /></Field>
            </>
          )}

          {kind === "sales_forecast" && (
            <>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Year"><Input data-testid="edit-year" type="number" className="rounded-none font-mono-tab" value={form.year ?? ""} onChange={(e) => setField("year", e.target.value)} /></Field>
                <Field label="Month">
                  <select data-testid="edit-month" value={form.month || 1} onChange={(e) => setField("month", e.target.value)} className="w-full rounded-none border border-neutral-300 h-9 px-2 text-sm">
                    {MONTHS.slice(1).map((m, i) => <option key={i + 1} value={i + 1}>{m}</option>)}
                  </select>
                </Field>
              </div>
              <Field label="Type">
                <select data-testid="edit-type" value={form.type || "Revenue"} onChange={(e) => setField("type", e.target.value)} className="w-full rounded-none border border-neutral-300 h-9 px-2 text-sm">
                  <option value="Revenue">Revenue</option>
                  <option value="Cost">Cost</option>
                  <option value="Expense">Expense</option>
                </select>
              </Field>
              <Field label="Amount (₹)"><Input data-testid="edit-amount" type="number" step="0.01" className="rounded-none font-mono-tab" value={form.amount ?? ""} onChange={(e) => setField("amount", e.target.value)} /></Field>
              <Field label="Project ID"><Input data-testid="edit-project" className="rounded-none font-mono-tab" value={form.project_id || ""} onChange={(e) => setField("project_id", e.target.value)} placeholder="Leave empty for unallocated" /></Field>
              <Field label="Notes"><Input data-testid="edit-notes" className="rounded-none" value={form.notes || ""} onChange={(e) => setField("notes", e.target.value)} /></Field>
            </>
          )}

          {kind === "quotation" && (
            <>
              <Field label="Quotation Number"><Input data-testid="edit-qnum" className="rounded-none font-mono-tab" value={form.quotation_number || ""} onChange={(e) => setField("quotation_number", e.target.value)} /></Field>
              <Field label="Client"><Input data-testid="edit-client" className="rounded-none" value={form.client_name || ""} onChange={(e) => setField("client_name", e.target.value)} /></Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Expected Year"><Input data-testid="edit-exp-year" type="number" className="rounded-none font-mono-tab" value={form.expected_year ?? ""} onChange={(e) => setField("expected_year", e.target.value)} /></Field>
                <Field label="Expected Month">
                  <select data-testid="edit-exp-month" value={form.expected_month || 1} onChange={(e) => setField("expected_month", e.target.value)} className="w-full rounded-none border border-neutral-300 h-9 px-2 text-sm">
                    {MONTHS.slice(1).map((m, i) => <option key={i + 1} value={i + 1}>{m}</option>)}
                  </select>
                </Field>
              </div>
              <Field label="Status">
                <select data-testid="edit-status" value={form.status || "draft"} onChange={(e) => setField("status", e.target.value)} className="w-full rounded-none border border-neutral-300 h-9 px-2 text-sm">
                  <option value="draft">draft</option><option value="sent">sent</option><option value="won">won</option><option value="lost">lost</option>
                </select>
              </Field>
              <div className="border border-neutral-200 p-2 text-[11px] text-neutral-600" data-testid="edit-lines-note">
                Line items ({(form.lines || []).length}) are preserved as-is. To edit them, reject and re-dictate the quotation.
              </div>
            </>
          )}

          <div className="flex justify-end gap-2 mt-4">
            <Button data-testid="edit-cancel" variant="outline" className="rounded-none" onClick={() => onOpenChange(false)}>
              <X size={14} className="mr-1" /> Cancel
            </Button>
            <Button data-testid="edit-save" onClick={save} disabled={saving} className="rounded-none bg-neutral-900 hover:bg-neutral-700">
              <Check size={14} className="mr-1" /> {saving ? "Saving…" : "Save changes"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function Field({ label, children }) {
  return (
    <div>
      <Label className="text-[10px] uppercase tracking-wider text-neutral-500">{label}</Label>
      <div className="mt-1">{children}</div>
    </div>
  );
}

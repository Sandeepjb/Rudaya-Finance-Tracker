import React, { useEffect, useState } from "react";
import { api, inr, formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";

const TYPES = ["Revenue", "Cost", "Expense"];

const emptyForm = () => ({
  date: new Date().toISOString().slice(0, 10),
  type: "Revenue",
  account: "",
  amount: "",
  project_id: "",
  notes: "",
});

function getSaveLabel(saving, editing) {
  if (saving) return "Saving…";
  if (editing) return "Update Entry";
  return "Create Entry";
}

export default function TransactionDrawer({ open, onOpenChange, editing, meta, onSaved }) {
  const [form, setForm] = useState(emptyForm());
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    if (editing) {
      setForm({
        date: editing.date?.slice(0, 10) || "",
        type: editing.type,
        account: editing.account,
        amount: editing.amount,
        project_id: editing.project_id,
        notes: editing.notes || "",
      });
    } else {
      setForm(emptyForm());
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editing, open]);

  const save = async () => {
    setSaving(true);
    try {
      const payload = { ...form, amount: parseFloat(form.amount), date: form.date + "T00:00:00" };
      if (editing) await api.put(`/transactions/${editing.id}`, payload);
      else await api.post("/transactions", payload);
      toast.success(editing ? "Updated" : "Created");
      onOpenChange(false);
      onSaved();
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    } finally {
      setSaving(false);
    }
  };

  const disabled = saving || !form.account || !form.amount || !form.project_id || !form.date;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full sm:max-w-md rounded-none border-l-2 border-l-neutral-900" data-testid="txn-drawer">
        <SheetHeader>
          <div className="text-[11px] uppercase tracking-[0.25em] text-neutral-500">{editing ? "Edit" : "New"} Entry</div>
          <SheetTitle className="font-heading text-2xl tracking-tight">Transaction</SheetTitle>
          <SheetDescription>Record a Revenue, Cost, or Expense against a project.</SheetDescription>
        </SheetHeader>
        <div className="mt-6 space-y-4">
          <div>
            <Label className="text-xs uppercase tracking-wider">Date</Label>
            <Input data-testid="txn-date" type="date" className="rounded-none mt-1" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} />
          </div>
          <div>
            <Label className="text-xs uppercase tracking-wider">Type</Label>
            <Select value={form.type} onValueChange={(v) => setForm({ ...form, type: v })}>
              <SelectTrigger data-testid="txn-type" className="rounded-none mt-1"><SelectValue /></SelectTrigger>
              <SelectContent>{TYPES.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-xs uppercase tracking-wider">Account</Label>
            <Select value={form.account} onValueChange={(v) => setForm({ ...form, account: v })}>
              <SelectTrigger data-testid="txn-account" className="rounded-none mt-1"><SelectValue placeholder="Select account" /></SelectTrigger>
              <SelectContent className="max-h-72">{meta.accounts.map((a) => <SelectItem key={a.name} value={a.name}>{a.name}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-xs uppercase tracking-wider">Amount ({inr(0).replace(/[\d.,]/g, "").trim() || "₹"})</Label>
            <Input data-testid="txn-amount" type="number" step="0.01" className="rounded-none mt-1 font-mono-tab" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
          </div>
          <div>
            <Label className="text-xs uppercase tracking-wider">Project ID</Label>
            <Select value={form.project_id} onValueChange={(v) => setForm({ ...form, project_id: v })}>
              <SelectTrigger data-testid="txn-project" className="rounded-none mt-1"><SelectValue placeholder="Select project" /></SelectTrigger>
              <SelectContent className="max-h-72">{meta.project_ids.map((p) => <SelectItem key={p.code} value={p.code}>{p.code}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-xs uppercase tracking-wider">Notes</Label>
            <Textarea data-testid="txn-notes" className="rounded-none mt-1" rows={3} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          </div>
          <Button data-testid="txn-save" onClick={save} disabled={disabled} className="w-full rounded-none bg-neutral-900 hover:bg-neutral-700 h-11">
            {getSaveLabel(saving, editing)}
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}

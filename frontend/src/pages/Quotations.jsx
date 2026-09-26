import React, { useCallback, useEffect, useMemo, useState } from "react";
import Layout from "@/components/Layout";
import { api, inr, formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import AttachmentsPanel from "@/components/AttachmentsPanel";
import { toast } from "sonner";
import { Plus, PencilSimple, Trash, FileText } from "@phosphor-icons/react";
import { TypeBadge } from "@/components/TypeBadge";

const currentYear = new Date().getFullYear();
const YEARS = [currentYear - 1, currentYear, currentYear + 1, currentYear + 2];
const TYPES = ["Revenue", "Cost", "Expense"];
const STATUSES = ["draft", "sent", "won", "lost"];
const MONTHS = [
  { v: 1, l: "Jan" }, { v: 2, l: "Feb" }, { v: 3, l: "Mar" }, { v: 4, l: "Apr" },
  { v: 5, l: "May" }, { v: 6, l: "Jun" }, { v: 7, l: "Jul" }, { v: 8, l: "Aug" },
  { v: 9, l: "Sep" }, { v: 10, l: "Oct" }, { v: 11, l: "Nov" }, { v: 12, l: "Dec" },
];
const ANY = "all";

const STATUS_STYLE = {
  draft: "bg-neutral-100 text-neutral-700 border-neutral-300",
  sent: "bg-blue-50 text-blue-700 border-blue-300",
  won: "bg-emerald-50 text-emerald-700 border-emerald-300",
  lost: "bg-red-50 text-red-700 border-red-300",
};

const lineId = () => `ln-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
const emptyLine = () => ({ _key: lineId(), type: "Revenue", description: "", amount: "", notes: "" });
const emptyForm = () => ({
  quotation_number: "",
  client_name: "",
  project_id: "",
  quote_date: new Date().toISOString().slice(0, 10),
  expected_year: currentYear,
  expected_month: new Date().getMonth() + 1,
  status: "draft",
  notes: "",
  lines: [emptyLine()],
});

function getSaveLabel(saving, editing) {
  if (saving) return "Saving…";
  if (editing) return "Update Quotation";
  return "Create Quotation";
}

function sumBy(lines, type) {
  return lines.reduce((a, l) => a + (l.type === type ? parseFloat(l.amount || 0) || 0 : 0), 0);
}

export default function Quotations() {
  const [items, setItems] = useState([]);
  const [meta, setMeta] = useState({ project_ids: [] });
  const [filterYear, setFilterYear] = useState(currentYear);
  const [filterStatus, setFilterStatus] = useState(ANY);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);

  const load = useCallback(async () => {
    const params = { year: filterYear };
    if (filterStatus !== ANY) params.status = filterStatus;
    const r = await api.get("/quotations", { params });
    setItems(r.data);
  }, [filterYear, filterStatus]);

  useEffect(() => {
    api.get("/meta").then((r) => setMeta(r.data));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { load(); }, [load]);

  const totals = useMemo(() => {
    const t = { Revenue: 0, Cost: 0, Expense: 0, count: items.length };
    items.forEach((q) => {
      TYPES.forEach((tp) => { t[tp] += q.totals?.[tp] || 0; });
    });
    return t;
  }, [items]);

  const remove = async (id) => {
    if (!window.confirm("Delete this quotation? All its line items will be removed from the forecast.")) return;
    try {
      await api.delete(`/quotations/${id}`);
      toast.success("Deleted");
      load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  return (
    <Layout
      title="Quotations"
      subtitle={`${totals.count} quotations · Rev ${inr(totals.Revenue)} · Cost ${inr(totals.Cost)} · Exp ${inr(totals.Expense)}`}
      actions={
        <Button data-testid="add-q-btn" className="rounded-none bg-neutral-900 hover:bg-neutral-700" onClick={() => { setEditing(null); setOpen(true); }}>
          <Plus size={16} className="mr-2" /> New Quotation
        </Button>
      }
    >
      <div className="rudaya-card p-4 mb-4">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 items-end">
          <div>
            <Label className="text-[11px] uppercase tracking-wider text-neutral-500">Expected Year</Label>
            <Select value={String(filterYear)} onValueChange={(v) => setFilterYear(parseInt(v))}>
              <SelectTrigger data-testid="q-filter-year" className="rounded-none mt-1"><SelectValue /></SelectTrigger>
              <SelectContent>{YEARS.map((y) => <SelectItem key={y} value={String(y)}>{y}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-[11px] uppercase tracking-wider text-neutral-500">Status</Label>
            <Select value={filterStatus} onValueChange={setFilterStatus}>
              <SelectTrigger data-testid="q-filter-status" className="rounded-none mt-1"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value={ANY}>All</SelectItem>
                {STATUSES.map((s) => <SelectItem key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
        </div>
        <p className="text-xs text-neutral-500 mt-3">
          Non-lost quotations feed the monthly Forecast vs Actual report by type.
        </p>
      </div>

      <div className="rudaya-card overflow-hidden">
        <table className="w-full" data-testid="quotations-table">
          <thead className="bg-neutral-50 border-b border-neutral-200">
            <tr className="text-left text-[11px] uppercase tracking-wider text-neutral-500">
              <th className="px-4 py-3">Q#</th>
              <th className="px-3 py-3">Client</th>
              <th className="px-3 py-3">Project</th>
              <th className="px-3 py-3">Expected</th>
              <th className="px-3 py-3">Status</th>
              <th className="px-3 py-3 text-right">Revenue</th>
              <th className="px-3 py-3 text-right">Cost</th>
              <th className="px-3 py-3 text-right">Expense</th>
              <th className="px-4 py-3 text-right">Net</th>
              <th className="px-3 py-3 w-24"></th>
            </tr>
          </thead>
          <tbody>
            {items.map((q) => (
              <tr key={q.id} className="border-b border-neutral-100 hover:bg-neutral-50 transition-colors">
                <td className="px-4 py-2 font-mono-tab text-xs">{q.quotation_number}</td>
                <td className="px-3 py-2 text-sm">{q.client_name}</td>
                <td className="px-3 py-2 font-mono-tab text-xs text-neutral-600">{q.project_id}</td>
                <td className="px-3 py-2 font-mono-tab text-xs">{MONTHS.find((m) => m.v === q.expected_month)?.l} {q.expected_year}</td>
                <td className="px-3 py-2"><span className={`inline-block text-[10px] uppercase tracking-wider px-2 py-0.5 border ${STATUS_STYLE[q.status] || STATUS_STYLE.draft}`}>{q.status}</span></td>
                <td className="px-3 py-2 text-right font-mono-tab text-sm text-emerald-700">{inr(q.totals?.Revenue || 0)}</td>
                <td className="px-3 py-2 text-right font-mono-tab text-sm text-red-700">{inr(q.totals?.Cost || 0)}</td>
                <td className="px-3 py-2 text-right font-mono-tab text-sm text-amber-700">{inr(q.totals?.Expense || 0)}</td>
                <td className={`px-4 py-2 text-right font-mono-tab text-sm font-semibold ${(q.totals?.net || 0) >= 0 ? "text-blue-700" : "text-red-700"}`}>{inr(q.totals?.net || 0)}</td>
                <td className="px-3 py-2 text-right">
                  <button data-testid={`edit-q-${q.id}`} onClick={() => { setEditing(q); setOpen(true); }} className="p-1.5 hover:bg-neutral-200 mr-1"><PencilSimple size={14} /></button>
                  <button data-testid={`delete-q-${q.id}`} onClick={() => remove(q.id)} className="p-1.5 hover:bg-red-100 text-red-600"><Trash size={14} /></button>
                </td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr><td colSpan="10" className="px-4 py-12 text-center text-neutral-500 text-sm">
                <FileText size={22} className="mx-auto text-neutral-300 mb-2" />
                No quotations yet. Click <b>New Quotation</b> to create your first breakup.
              </td></tr>
            )}
          </tbody>
        </table>
      </div>

      <QuotationDrawer
        open={open}
        onOpenChange={setOpen}
        editing={editing}
        meta={meta}
        onSaved={load}
        defaultYear={filterYear}
      />
    </Layout>
  );
}

function QuotationDrawer({ open, onOpenChange, editing, meta, onSaved, defaultYear }) {
  const [form, setForm] = useState(emptyForm());
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    if (editing) {
      setForm({
        quotation_number: editing.quotation_number || "",
        client_name: editing.client_name || "",
        project_id: editing.project_id || "",
        quote_date: editing.quote_date || new Date().toISOString().slice(0, 10),
        expected_year: editing.expected_year || currentYear,
        expected_month: editing.expected_month || new Date().getMonth() + 1,
        status: editing.status || "draft",
        notes: editing.notes || "",
        lines: (editing.lines && editing.lines.length) ? editing.lines.map((l) => ({ ...l, _key: l._key || lineId() })) : [emptyLine()],
      });
    } else {
      setForm({ ...emptyForm(), expected_year: defaultYear });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editing, open, defaultYear]);

  const updateLine = (idx, patch) => {
    setForm((f) => ({ ...f, lines: f.lines.map((l, i) => (i === idx ? { ...l, ...patch } : l)) }));
  };
  const addLine = () => setForm((f) => ({ ...f, lines: [...f.lines, emptyLine()] }));
  const removeLine = (idx) => setForm((f) => ({ ...f, lines: f.lines.filter((_, i) => i !== idx) }));

  const save = async () => {
    setSaving(true);
    try {
      const payload = {
        ...form,
        expected_year: parseInt(form.expected_year),
        expected_month: parseInt(form.expected_month),
        lines: form.lines
          .filter((l) => l.amount !== "" && !isNaN(parseFloat(l.amount)))
          .map((l) => ({
            type: l.type,
            description: l.description || "",
            amount: parseFloat(l.amount),
            notes: l.notes || "",
          })),      };
      if (editing) await api.put(`/quotations/${editing.id}`, payload);
      else await api.post("/quotations", payload);
      toast.success(editing ? "Quotation updated" : "Quotation created");
      onOpenChange(false);
      onSaved();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setSaving(false); }
  };

  const disabled = saving || !form.quotation_number || !form.quote_date || form.lines.length === 0;

  const totalsPreview = {
    Revenue: sumBy(form.lines, "Revenue"),
    Cost: sumBy(form.lines, "Cost"),
    Expense: sumBy(form.lines, "Expense"),
  };
  const netPreview = totalsPreview.Revenue - totalsPreview.Cost - totalsPreview.Expense;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full sm:max-w-2xl rounded-none border-l-2 border-l-neutral-900 overflow-y-auto rudaya-scroll" data-testid="q-drawer">
        <SheetHeader>
          <div className="text-[11px] uppercase tracking-[0.25em] text-neutral-500">{editing ? "Edit" : "New"} Quotation</div>
          <SheetTitle className="font-heading text-2xl tracking-tight">Quotation Breakup</SheetTitle>
          <SheetDescription>Header + line-item breakup classified as Revenue, Cost or Expense. Non-lost quotations feed the monthly forecast.</SheetDescription>
        </SheetHeader>

        <div className="mt-6 space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-xs uppercase tracking-wider">Quotation #</Label>
              <Input data-testid="q-number" className="rounded-none mt-1 font-mono-tab" value={form.quotation_number} onChange={(e) => setForm({ ...form, quotation_number: e.target.value })} placeholder="Q-2026-001" />
            </div>
            <div>
              <Label className="text-xs uppercase tracking-wider">Client</Label>
              <Input data-testid="q-client" className="rounded-none mt-1" value={form.client_name} onChange={(e) => setForm({ ...form, client_name: e.target.value })} />
            </div>
            <div>
              <Label className="text-xs uppercase tracking-wider">Project ID</Label>
              <Select value={form.project_id || "__none__"} onValueChange={(v) => setForm({ ...form, project_id: v === "__none__" ? "" : v })}>
                <SelectTrigger data-testid="q-project" className="rounded-none mt-1"><SelectValue placeholder="Optional" /></SelectTrigger>
                <SelectContent className="max-h-72">
                  <SelectItem value="__none__">— none —</SelectItem>
                  {meta.project_ids?.map((p) => <SelectItem key={p.code} value={p.code}>{p.code}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-xs uppercase tracking-wider">Quote Date</Label>
              <Input data-testid="q-date" type="date" className="rounded-none mt-1" value={form.quote_date} onChange={(e) => setForm({ ...form, quote_date: e.target.value })} />
            </div>
            <div>
              <Label className="text-xs uppercase tracking-wider">Expected Year</Label>
              <Select value={String(form.expected_year)} onValueChange={(v) => setForm({ ...form, expected_year: parseInt(v) })}>
                <SelectTrigger data-testid="q-exp-year" className="rounded-none mt-1"><SelectValue /></SelectTrigger>
                <SelectContent>{YEARS.map((y) => <SelectItem key={y} value={String(y)}>{y}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-xs uppercase tracking-wider">Expected Month</Label>
              <Select value={String(form.expected_month)} onValueChange={(v) => setForm({ ...form, expected_month: parseInt(v) })}>
                <SelectTrigger data-testid="q-exp-month" className="rounded-none mt-1"><SelectValue /></SelectTrigger>
                <SelectContent>{MONTHS.map((m) => <SelectItem key={m.v} value={String(m.v)}>{m.l}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div className="col-span-2">
              <Label className="text-xs uppercase tracking-wider">Status</Label>
              <Select value={form.status} onValueChange={(v) => setForm({ ...form, status: v })}>
                <SelectTrigger data-testid="q-status" className="rounded-none mt-1"><SelectValue /></SelectTrigger>
                <SelectContent>{STATUSES.map((s) => <SelectItem key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</SelectItem>)}</SelectContent>
              </Select>
            </div>
          </div>

          <div className="pt-3">
            <div className="flex items-center justify-between mb-2">
              <Label className="text-xs uppercase tracking-wider">Line-item Breakup</Label>
              <Button type="button" data-testid="q-add-line" onClick={addLine} variant="outline" className="rounded-none h-8 text-xs border-neutral-300"><Plus size={12} className="mr-1" /> Add Line</Button>
            </div>
            <div className="border border-neutral-200">
              <table className="w-full text-sm">
                <thead className="bg-neutral-50 border-b border-neutral-200 text-[10px] uppercase tracking-wider text-neutral-500">
                  <tr>
                    <th className="px-2 py-2 text-left w-28">Type</th>
                    <th className="px-2 py-2 text-left">Description</th>
                    <th className="px-2 py-2 text-right w-32">Amount ₹</th>
                    <th className="px-2 py-2 w-8"></th>
                  </tr>
                </thead>
                <tbody>
                  {form.lines.map((l, idx) => (
                    <tr key={l._key || `idx-${idx}`} className="border-b border-neutral-100" data-testid={`q-line-${idx}`}>
                      <td className="p-1.5">
                        <Select value={l.type} onValueChange={(v) => updateLine(idx, { type: v })}>
                          <SelectTrigger data-testid={`q-line-type-${idx}`} className="rounded-none h-8 text-xs"><SelectValue /></SelectTrigger>
                          <SelectContent>{TYPES.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}</SelectContent>
                        </Select>
                      </td>
                      <td className="p-1.5">
                        <Input data-testid={`q-line-desc-${idx}`} value={l.description} onChange={(e) => updateLine(idx, { description: e.target.value })} className="rounded-none h-8 text-xs" placeholder="e.g. Panel assembly" />
                      </td>
                      <td className="p-1.5">
                        <Input data-testid={`q-line-amt-${idx}`} type="number" step="0.01" value={l.amount} onChange={(e) => updateLine(idx, { amount: e.target.value })} className="rounded-none h-8 text-xs text-right font-mono-tab" placeholder="0" />
                      </td>
                      <td className="p-1.5 text-center">
                        <button type="button" data-testid={`q-line-remove-${idx}`} onClick={() => removeLine(idx)} className="p-1 text-red-600 hover:bg-red-50" disabled={form.lines.length === 1}><Trash size={12} /></button>
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot className="bg-neutral-50">
                  <tr>
                    <td colSpan="4" className="p-2">
                      <div className="grid grid-cols-4 gap-2 text-xs">
                        <div><span className="text-neutral-500 uppercase text-[10px] tracking-wider">Revenue</span><div className="font-mono-tab font-semibold text-emerald-700">{inr(totalsPreview.Revenue)}</div></div>
                        <div><span className="text-neutral-500 uppercase text-[10px] tracking-wider">Cost</span><div className="font-mono-tab font-semibold text-red-700">{inr(totalsPreview.Cost)}</div></div>
                        <div><span className="text-neutral-500 uppercase text-[10px] tracking-wider">Expense</span><div className="font-mono-tab font-semibold text-amber-700">{inr(totalsPreview.Expense)}</div></div>
                        <div><span className="text-neutral-500 uppercase text-[10px] tracking-wider">Net</span><div className={`font-mono-tab font-semibold ${netPreview >= 0 ? "text-blue-700" : "text-red-700"}`}>{inr(netPreview)}</div></div>
                      </div>
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </div>

          <div>
            <Label className="text-xs uppercase tracking-wider">Notes</Label>
            <Textarea data-testid="q-notes" className="rounded-none mt-1" rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          </div>

          <Button data-testid="q-save" onClick={save} disabled={disabled} className="w-full rounded-none bg-neutral-900 hover:bg-neutral-700 h-11">
            {getSaveLabel(saving, editing)}
          </Button>
          <div className="pt-2 border-t border-neutral-200">
            <AttachmentsPanel entityType="quotation" entityId={editing?.id} />
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}

export { TypeBadge };

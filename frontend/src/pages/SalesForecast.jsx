import React, { useCallback, useEffect, useMemo, useState } from "react";
import Layout from "@/components/Layout";
import { api, inr, formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import { Plus, PencilSimple, Trash, Target } from "@phosphor-icons/react";

const currentYear = new Date().getFullYear();
const YEARS = [currentYear - 1, currentYear, currentYear + 1, currentYear + 2];
const MONTHS = [
  { v: 1, l: "January" }, { v: 2, l: "February" }, { v: 3, l: "March" }, { v: 4, l: "April" },
  { v: 5, l: "May" }, { v: 6, l: "June" }, { v: 7, l: "July" }, { v: 8, l: "August" },
  { v: 9, l: "September" }, { v: 10, l: "October" }, { v: 11, l: "November" }, { v: 12, l: "December" },
];
const UNALLOCATED = "__unallocated__";
const ANY_PROJECT = "all";

const emptyForm = () => ({
  year: currentYear,
  month: new Date().getMonth() + 1,
  project_id: "",
  amount: "",
  notes: "",
});

function getSaveLabel(saving, editing) {
  if (saving) return "Saving…";
  if (editing) return "Update Entry";
  return "Create Entry";
}

export default function SalesForecast() {
  const [items, setItems] = useState([]);
  const [meta, setMeta] = useState({ project_ids: [] });
  const [filterYear, setFilterYear] = useState(currentYear);
  const [filterProject, setFilterProject] = useState(ANY_PROJECT);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);

  const load = useCallback(async () => {
    const params = { year: filterYear };
    if (filterProject && filterProject !== ANY_PROJECT) {
      params.project_id = filterProject === UNALLOCATED ? "" : filterProject;
    }
    const r = await api.get("/sales-forecast", { params });
    // If user selected "unallocated" filter, keep only empty project_id
    let rows = r.data;
    if (filterProject === UNALLOCATED) rows = rows.filter((x) => !x.project_id);
    setItems(rows);
  }, [filterYear, filterProject]);

  useEffect(() => {
    api.get("/meta").then((r) => setMeta(r.data));
    // api and setMeta are stable module/react identities; effect must run once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { load(); }, [load]);

  const totals = useMemo(() => {
    const monthly = {};
    let grand = 0;
    for (let m = 1; m <= 12; m++) monthly[m] = 0;
    items.forEach((i) => {
      monthly[i.month] = (monthly[i.month] || 0) + i.amount;
      grand += i.amount;
    });
    return { monthly, grand };
  }, [items]);

  const remove = async (id) => {
    if (!window.confirm("Delete this sales forecast entry?")) return;
    try {
      await api.delete(`/sales-forecast/${id}`);
      toast.success("Deleted");
      load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  return (
    <Layout
      title="Sales Forecast"
      subtitle={`${items.length} line item${items.length === 1 ? "" : "s"} · Total ${inr(totals.grand)}`}
      actions={
        <Button data-testid="add-sf-btn" className="rounded-none bg-neutral-900 hover:bg-neutral-700" onClick={() => { setEditing(null); setOpen(true); }}>
          <Plus size={16} className="mr-2" /> New Entry
        </Button>
      }
    >
      {/* Filters */}
      <div className="rudaya-card p-4 mb-4">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 items-end">
          <div>
            <Label className="text-[11px] uppercase tracking-wider text-neutral-500">Year</Label>
            <Select value={String(filterYear)} onValueChange={(v) => setFilterYear(parseInt(v))}>
              <SelectTrigger data-testid="sf-filter-year" className="rounded-none mt-1"><SelectValue /></SelectTrigger>
              <SelectContent>{YEARS.map((y) => <SelectItem key={y} value={String(y)}>{y}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-[11px] uppercase tracking-wider text-neutral-500">Project</Label>
            <Select value={filterProject} onValueChange={setFilterProject}>
              <SelectTrigger data-testid="sf-filter-project" className="rounded-none mt-1"><SelectValue placeholder="All projects" /></SelectTrigger>
              <SelectContent className="max-h-72">
                <SelectItem value={ANY_PROJECT}>All Projects</SelectItem>
                <SelectItem value={UNALLOCATED}>Unallocated</SelectItem>
                {meta.project_ids?.map((p) => <SelectItem key={p.code} value={p.code}>{p.code}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>

      {/* Monthly totals strip */}
      <div className="rudaya-card p-4 mb-4">
        <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500 mb-3">Monthly totals · {filterYear}</div>
        <div className="grid grid-cols-4 md:grid-cols-12 gap-2">
          {MONTHS.map((m) => (
            <div key={m.v} className="border border-neutral-200 p-2" data-testid={`sf-total-m-${m.v}`}>
              <div className="text-[10px] uppercase tracking-wider text-neutral-500">{m.l.slice(0, 3)}</div>
              <div className="font-mono-tab text-sm font-medium mt-1 text-neutral-900">{inr(totals.monthly[m.v])}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Line items table */}
      <div className="rudaya-card overflow-hidden">
        <table className="w-full" data-testid="sales-forecast-table">
          <thead className="bg-neutral-50 border-b border-neutral-200">
            <tr className="text-left text-[11px] uppercase tracking-wider text-neutral-500">
              <th className="px-4 py-3">Month</th>
              <th className="px-3 py-3">Project</th>
              <th className="px-3 py-3">Notes</th>
              <th className="px-4 py-3 text-right">Amount</th>
              <th className="px-3 py-3 w-24"></th>
            </tr>
          </thead>
          <tbody>
            {items.map((i) => (
              <tr key={i.id} className="border-b border-neutral-100 hover:bg-neutral-50 transition-colors">
                <td className="px-4 py-2 font-mono-tab text-sm whitespace-nowrap">
                  {MONTHS.find((mm) => mm.v === i.month)?.l.slice(0, 3)} {i.year}
                </td>
                <td className="px-3 py-2 text-sm">
                  {i.project_id ? <span className="font-mono-tab text-xs text-neutral-700">{i.project_id}</span> : <span className="text-xs uppercase tracking-wider text-neutral-400">Unallocated</span>}
                </td>
                <td className="px-3 py-2 text-sm text-neutral-700 max-w-[320px] truncate" title={i.notes}>{i.notes}</td>
                <td className="px-4 py-2 text-right font-mono-tab text-sm font-medium">{inr(i.amount)}</td>
                <td className="px-3 py-2 text-right">
                  <button data-testid={`edit-sf-${i.id}`} onClick={() => { setEditing(i); setOpen(true); }} className="p-1.5 hover:bg-neutral-200 mr-1"><PencilSimple size={14} /></button>
                  <button data-testid={`delete-sf-${i.id}`} onClick={() => remove(i.id)} className="p-1.5 hover:bg-red-100 text-red-600"><Trash size={14} /></button>
                </td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr><td colSpan="5" className="px-4 py-12 text-center text-neutral-500 text-sm">
                <Target size={22} className="mx-auto text-neutral-300 mb-2" />
                No sales forecast entries yet. Click <b>New Entry</b> to add one.
              </td></tr>
            )}
          </tbody>
          {items.length > 0 && (
            <tfoot className="bg-neutral-900 text-white">
              <tr>
                <td colSpan="3" className="px-4 py-3 uppercase text-[11px] tracking-widest">Total · {filterYear}</td>
                <td className="px-4 py-3 text-right font-mono-tab text-sm font-semibold">{inr(totals.grand)}</td>
                <td></td>
              </tr>
            </tfoot>
          )}
        </table>
      </div>

      <SalesForecastDrawer
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

function SalesForecastDrawer({ open, onOpenChange, editing, meta, onSaved, defaultYear }) {
  const [form, setForm] = useState(emptyForm());
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    if (editing) {
      setForm({
        year: editing.year,
        month: editing.month,
        project_id: editing.project_id || "",
        amount: editing.amount,
        notes: editing.notes || "",
      });
    } else {
      setForm({ ...emptyForm(), year: defaultYear });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editing, open, defaultYear]);

  const save = async () => {
    setSaving(true);
    try {
      const payload = {
        year: parseInt(form.year),
        month: parseInt(form.month),
        project_id: form.project_id === UNALLOCATED ? "" : form.project_id,
        amount: parseFloat(form.amount),
        notes: form.notes,
      };
      if (editing) await api.put(`/sales-forecast/${editing.id}`, payload);
      else await api.post("/sales-forecast", payload);
      toast.success(editing ? "Updated" : "Created");
      onOpenChange(false);
      onSaved();
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    } finally { setSaving(false); }
  };

  const disabled = saving || !form.amount || isNaN(parseFloat(form.amount)) || !form.year || !form.month;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full sm:max-w-md rounded-none border-l-2 border-l-neutral-900" data-testid="sf-drawer">
        <SheetHeader>
          <div className="text-[11px] uppercase tracking-[0.25em] text-neutral-500">{editing ? "Edit" : "New"} Sales Forecast</div>
          <SheetTitle className="font-heading text-2xl tracking-tight">Forecast Entry</SheetTitle>
          <SheetDescription>Add a month-wise sales forecast line item, optionally tagged to a project.</SheetDescription>
        </SheetHeader>
        <div className="mt-6 space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-xs uppercase tracking-wider">Year</Label>
              <Select value={String(form.year)} onValueChange={(v) => setForm({ ...form, year: parseInt(v) })}>
                <SelectTrigger data-testid="sf-year" className="rounded-none mt-1"><SelectValue /></SelectTrigger>
                <SelectContent>{YEARS.map((y) => <SelectItem key={y} value={String(y)}>{y}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-xs uppercase tracking-wider">Month</Label>
              <Select value={String(form.month)} onValueChange={(v) => setForm({ ...form, month: parseInt(v) })}>
                <SelectTrigger data-testid="sf-month" className="rounded-none mt-1"><SelectValue /></SelectTrigger>
                <SelectContent>{MONTHS.map((m) => <SelectItem key={m.v} value={String(m.v)}>{m.l}</SelectItem>)}</SelectContent>
              </Select>
            </div>
          </div>
          <div>
            <Label className="text-xs uppercase tracking-wider">Project ID (optional)</Label>
            <Select value={form.project_id || UNALLOCATED} onValueChange={(v) => setForm({ ...form, project_id: v === UNALLOCATED ? "" : v })}>
              <SelectTrigger data-testid="sf-project" className="rounded-none mt-1"><SelectValue placeholder="Unallocated" /></SelectTrigger>
              <SelectContent className="max-h-72">
                <SelectItem value={UNALLOCATED}>Unallocated</SelectItem>
                {meta.project_ids?.map((p) => <SelectItem key={p.code} value={p.code}>{p.code}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-xs uppercase tracking-wider">Amount (₹)</Label>
            <Input data-testid="sf-amount" type="number" step="0.01" className="rounded-none mt-1 font-mono-tab" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
          </div>
          <div>
            <Label className="text-xs uppercase tracking-wider">Notes</Label>
            <Textarea data-testid="sf-notes" className="rounded-none mt-1" rows={3} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          </div>
          <Button data-testid="sf-save" onClick={save} disabled={disabled} className="w-full rounded-none bg-neutral-900 hover:bg-neutral-700 h-11">
            {getSaveLabel(saving, editing)}
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}

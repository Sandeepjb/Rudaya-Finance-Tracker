import React, { useEffect, useMemo, useState } from "react";
import Layout from "@/components/Layout";
import { api, inr, formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import { Plus, MagnifyingGlass, PencilSimple, Trash, DownloadSimple } from "@phosphor-icons/react";
import { TypeBadge } from "@/pages/Dashboard";

const TYPES = ["Revenue", "Cost", "Expense"];

export default function Transactions() {
  const [items, setItems] = useState([]);
  const [meta, setMeta] = useState({ accounts: [], project_ids: [] });
  const [filters, setFilters] = useState({ type: "all", project_id: "all", start_date: "", end_date: "", search: "" });
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);

  const load = async () => {
    const params = {};
    Object.entries(filters).forEach(([k, v]) => { if (v && v !== "all") params[k] = v; });
    const r = await api.get("/transactions", { params });
    setItems(r.data);
  };

  useEffect(() => {
    api.get("/meta").then((r) => setMeta(r.data));
  }, []);
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [filters]);

  const totals = useMemo(() => {
    const t = { Revenue: 0, Cost: 0, Expense: 0 };
    items.forEach((i) => { t[i.type] = (t[i.type] || 0) + i.amount; });
    return t;
  }, [items]);

  const remove = async (id) => {
    if (!window.confirm("Delete this transaction?")) return;
    try {
      await api.delete(`/transactions/${id}`);
      toast.success("Deleted");
      load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const exportCsv = () => {
    const rows = [["Date", "Type", "Account", "Amount", "Project ID", "Notes"]];
    items.forEach((i) => rows.push([i.date?.slice(0, 10), i.type, i.account, i.amount, i.project_id, i.notes]));
    const csv = rows.map((r) => r.map((c) => `"${String(c ?? "").replace(/"/g, '""')}"`).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `transactions-${Date.now()}.csv`; a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Layout
      title="Transactions"
      subtitle={`${items.length} entries · Rev ${inr(totals.Revenue)} · Cost ${inr(totals.Cost)} · Exp ${inr(totals.Expense)}`}
      actions={
        <>
          <Button data-testid="export-csv-btn" variant="outline" className="rounded-none border-neutral-300" onClick={exportCsv}><DownloadSimple size={16} className="mr-2" /> Export CSV</Button>
          <Button data-testid="add-transaction-btn" className="rounded-none bg-neutral-900 hover:bg-neutral-700" onClick={() => { setEditing(null); setOpen(true); }}>
            <Plus size={16} className="mr-2" /> New Entry
          </Button>
        </>
      }
    >
      {/* Filters */}
      <div className="rudaya-card p-4 mb-4">
        <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
          <div className="col-span-2 md:col-span-2 relative">
            <MagnifyingGlass size={14} className="absolute left-3 top-2.5 text-neutral-400" />
            <Input data-testid="search-input" className="rounded-none pl-8" placeholder="Search notes, account, project…" value={filters.search} onChange={(e) => setFilters({ ...filters, search: e.target.value })} />
          </div>
          <Select value={filters.type} onValueChange={(v) => setFilters({ ...filters, type: v })}>
            <SelectTrigger data-testid="filter-type" className="rounded-none"><SelectValue placeholder="Type" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Types</SelectItem>
              {TYPES.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}
            </SelectContent>
          </Select>
          <Select value={filters.project_id} onValueChange={(v) => setFilters({ ...filters, project_id: v })}>
            <SelectTrigger data-testid="filter-project" className="rounded-none"><SelectValue placeholder="Project" /></SelectTrigger>
            <SelectContent className="max-h-72">
              <SelectItem value="all">All Projects</SelectItem>
              {meta.project_ids.map((p) => <SelectItem key={p.code} value={p.code}>{p.code}</SelectItem>)}
            </SelectContent>
          </Select>
          <Input data-testid="filter-start-date" type="date" className="rounded-none" value={filters.start_date} onChange={(e) => setFilters({ ...filters, start_date: e.target.value })} />
          <Input data-testid="filter-end-date" type="date" className="rounded-none" value={filters.end_date} onChange={(e) => setFilters({ ...filters, end_date: e.target.value })} />
        </div>
      </div>

      {/* Table */}
      <div className="rudaya-card overflow-hidden">
        <div className="max-h-[calc(100vh-320px)] overflow-auto rudaya-scroll">
          <table className="w-full" data-testid="transactions-table">
            <thead className="bg-neutral-50 border-b border-neutral-200 sticky top-0 z-10">
              <tr className="text-left text-[11px] uppercase tracking-wider text-neutral-500">
                <th className="px-4 py-2.5">Date</th>
                <th className="px-3 py-2.5">Type</th>
                <th className="px-3 py-2.5">Account</th>
                <th className="px-3 py-2.5">Project ID</th>
                <th className="px-3 py-2.5">Notes</th>
                <th className="px-4 py-2.5 text-right">Amount</th>
                <th className="px-3 py-2.5 w-24"></th>
              </tr>
            </thead>
            <tbody>
              {items.map((t) => (
                <tr key={t.id} className="border-b border-neutral-100 hover:bg-neutral-50 transition-colors">
                  <td className="px-4 py-2 font-mono-tab text-sm whitespace-nowrap">{t.date?.slice(0, 10)}</td>
                  <td className="px-3 py-2"><TypeBadge type={t.type} /></td>
                  <td className="px-3 py-2 text-sm">{t.account}</td>
                  <td className="px-3 py-2 font-mono-tab text-xs text-neutral-600">{t.project_id}</td>
                  <td className="px-3 py-2 text-sm text-neutral-700 max-w-[280px] truncate" title={t.notes}>{t.notes}</td>
                  <td className="px-4 py-2 text-right font-mono-tab text-sm font-medium" style={{ color: t.type === "Revenue" ? "#059669" : t.type === "Cost" ? "#DC2626" : "#D97706" }}>{inr(t.amount)}</td>
                  <td className="px-3 py-2 text-right">
                    <button data-testid={`edit-txn-${t.id}`} onClick={() => { setEditing(t); setOpen(true); }} className="p-1.5 hover:bg-neutral-200 mr-1"><PencilSimple size={14} /></button>
                    <button data-testid={`delete-txn-${t.id}`} onClick={() => remove(t.id)} className="p-1.5 hover:bg-red-100 text-red-600"><Trash size={14} /></button>
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr><td colSpan="7" className="px-4 py-12 text-center text-neutral-500 text-sm">No transactions match your filters.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <TxnDrawer open={open} onOpenChange={setOpen} editing={editing} meta={meta} onSaved={load} />
    </Layout>
  );
}

function TxnDrawer({ open, onOpenChange, editing, meta, onSaved }) {
  const [form, setForm] = useState({ date: "", type: "Revenue", account: "", amount: "", project_id: "", notes: "" });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (editing) {
      setForm({
        date: editing.date?.slice(0, 10) || "",
        type: editing.type, account: editing.account,
        amount: editing.amount, project_id: editing.project_id, notes: editing.notes || "",
      });
    } else {
      setForm({ date: new Date().toISOString().slice(0, 10), type: "Revenue", account: "", amount: "", project_id: "", notes: "" });
    }
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
    } finally { setSaving(false); }
  };

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
            <Label className="text-xs uppercase tracking-wider">Amount (₹)</Label>
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
          <Button data-testid="txn-save" onClick={save} disabled={saving || !form.account || !form.amount || !form.project_id || !form.date} className="w-full rounded-none bg-neutral-900 hover:bg-neutral-700 h-11">
            {saving ? "Saving…" : (editing ? "Update Entry" : "Create Entry")}
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}

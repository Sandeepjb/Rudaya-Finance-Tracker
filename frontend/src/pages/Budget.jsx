import React, { useCallback, useEffect, useMemo, useState } from "react";
import Layout from "@/components/Layout";
import { api, inr, formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { toast } from "sonner";
import { Plus, PencilSimple, Trash, Wallet, WarningCircle, CheckCircle } from "@phosphor-icons/react";

const currentYear = new Date().getFullYear();
const YEARS = [currentYear - 1, currentYear, currentYear + 1, currentYear + 2];

const STATUS_STYLE = {
  ok: "bg-emerald-50 text-emerald-700 border-emerald-300",
  risk: "bg-amber-50 text-amber-700 border-amber-300",
  over: "bg-red-50 text-red-700 border-red-300",
  unbudgeted: "bg-neutral-100 text-neutral-600 border-neutral-300",
};

function getSaveLabel(saving, editing) {
  if (saving) return "Saving…";
  if (editing) return "Update Budget";
  return "Create Budget";
}

export default function Budget() {
  const [year, setYear] = useState(currentYear);
  const [data, setData] = useState({ rows: [], totals: { budget: 0, actual: 0, remaining: 0, deficit: 0, utilization_pct: null } });
  const [meta, setMeta] = useState({ accounts: [] });
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [seedAccount, setSeedAccount] = useState("");

  const load = useCallback(async () => {
    const r = await api.get("/reports/budget-vs-actual", { params: { year } });
    setData(r.data);
  }, [year]);

  useEffect(() => {
    api.get("/meta").then((r) => setMeta(r.data));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { load(); }, [load]);

  const budgetedCount = useMemo(() => data.rows.filter((r) => r.budget_id).length, [data.rows]);

  const openNew = (accountName = "") => {
    setSeedAccount(accountName);
    setEditing(null);
    setOpen(true);
  };

  const openEdit = async (row) => {
    if (!row.budget_id) return openNew(row.account);
    // fetch the budget doc for the drawer (year + account + amount)
    const list = await api.get("/budgets", { params: { year } });
    const b = list.data.find((x) => x.id === row.budget_id);
    setEditing(b || { id: row.budget_id, year, account: row.account, amount: row.budget });
    setSeedAccount("");
    setOpen(true);
  };

  const remove = async (row) => {
    if (!row.budget_id) return;
    if (!window.confirm(`Delete the ${year} budget for '${row.account}'?`)) return;
    try {
      await api.delete(`/budgets/${row.budget_id}`);
      toast.success("Budget deleted");
      load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  return (
    <Layout
      title="Yearly Expense Budget"
      subtitle={`FY ${year} · ${budgetedCount} budgeted · Actual ${inr(data.totals.actual)} of ${inr(data.totals.budget)}`}
      actions={
        <>
          <Select value={String(year)} onValueChange={(v) => setYear(parseInt(v))}>
            <SelectTrigger data-testid="budget-year-select" className="rounded-none w-28"><SelectValue /></SelectTrigger>
            <SelectContent>{YEARS.map((y) => <SelectItem key={y} value={String(y)}>{y}</SelectItem>)}</SelectContent>
          </Select>
          <Button data-testid="add-budget-btn" className="rounded-none bg-neutral-900 hover:bg-neutral-700" onClick={() => openNew()}>
            <Plus size={16} className="mr-2" /> New Budget
          </Button>
        </>
      }
    >
      {/* KPI tiles */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <div className="rudaya-card p-5" data-testid="budget-tile-total">
          <div className="flex items-start justify-between">
            <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500">Annual Budget</div>
            <Wallet size={18} className="text-neutral-400" />
          </div>
          <div className="mt-3 font-mono-tab font-semibold text-2xl text-neutral-900">{inr(data.totals.budget)}</div>
        </div>
        <div className="rudaya-card p-5" data-testid="budget-tile-actual">
          <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500">Actual Expense</div>
          <div className="mt-3 font-mono-tab font-semibold text-2xl text-amber-700">{inr(data.totals.actual)}</div>
        </div>
        <div className="rudaya-card p-5" data-testid="budget-tile-remaining">
          <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500">
            {data.totals.deficit > 0 ? "Deficit" : "Remaining"}
          </div>
          <div className={`mt-3 font-mono-tab font-semibold text-2xl ${data.totals.deficit > 0 ? "text-red-700" : "text-emerald-700"}`}>
            {inr(data.totals.deficit > 0 ? data.totals.deficit : data.totals.remaining)}
          </div>
        </div>
        <div className="rudaya-card p-5" data-testid="budget-tile-utilization">
          <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500">Utilization</div>
          <div className="mt-3 font-mono-tab font-semibold text-2xl text-neutral-900">
            {data.totals.utilization_pct != null ? data.totals.utilization_pct.toFixed(1) + "%" : "—"}
          </div>
        </div>
      </div>

      {/* Rows table */}
      <div className="rudaya-card overflow-hidden">
        <div className="px-5 py-4 border-b border-neutral-200 flex items-center justify-between">
          <div>
            <h3 className="font-heading font-semibold text-lg">Budget vs Actual · FY {year}</h3>
            <p className="text-xs text-neutral-500 mt-0.5">Account IDs come from <b>Settings → Accounts</b>. One source of truth.</p>
          </div>
        </div>
        <div className="overflow-x-auto rudaya-scroll">
          <table className="w-full min-w-[820px]" data-testid="budget-table">
            <thead className="bg-neutral-50 border-b border-neutral-200">
              <tr className="text-left text-[11px] uppercase tracking-wider text-neutral-500">
                <th className="px-4 py-3">Account (Settings)</th>
                <th className="px-3 py-3 text-right">Annual Budget</th>
                <th className="px-3 py-3 text-right">Actual Expense</th>
                <th className="px-3 py-3 text-right">Remaining</th>
                <th className="px-3 py-3 text-right">Deficit</th>
                <th className="px-3 py-3 text-right">Utilization</th>
                <th className="px-3 py-3">Status</th>
                <th className="px-3 py-3 w-28"></th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={r.budget_id || `unb-${r.account}`} className="border-b border-neutral-100 hover:bg-neutral-50 transition-colors" data-testid={`budget-row-${r.account}`}>
                  <td className="px-4 py-2.5 text-sm">{r.account}</td>
                  <td className="px-3 py-2.5 text-right font-mono-tab text-sm text-neutral-900">{inr(r.budget)}</td>
                  <td className="px-3 py-2.5 text-right font-mono-tab text-sm text-amber-700">{inr(r.actual)}</td>
                  <td className="px-3 py-2.5 text-right font-mono-tab text-sm text-emerald-700">{inr(r.remaining)}</td>
                  <td className="px-3 py-2.5 text-right font-mono-tab text-sm text-red-700">{inr(r.deficit)}</td>
                  <td className="px-3 py-2.5 text-right font-mono-tab text-sm">
                    {r.utilization_pct != null ? r.utilization_pct.toFixed(1) + "%" : "—"}
                  </td>
                  <td className="px-3 py-2.5">
                    <span className={`inline-block text-[10px] uppercase tracking-wider px-2 py-0.5 border ${STATUS_STYLE[r.status] || STATUS_STYLE.unbudgeted}`}>{r.status}</span>
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    {r.budget_id ? (
                      <>
                        <button data-testid={`edit-budget-${r.account}`} onClick={() => openEdit(r)} className="p-1.5 hover:bg-neutral-200 mr-1"><PencilSimple size={14} /></button>
                        <button data-testid={`delete-budget-${r.account}`} onClick={() => remove(r)} className="p-1.5 hover:bg-red-100 text-red-600"><Trash size={14} /></button>
                      </>
                    ) : (
                      <button data-testid={`create-budget-${r.account}`} onClick={() => openNew(r.account)} className="text-[11px] uppercase tracking-wider px-2 py-1 border border-neutral-300 hover:bg-neutral-100">Set budget</button>
                    )}
                  </td>
                </tr>
              ))}
              {data.rows.length === 0 && (
                <tr><td colSpan="8" className="px-4 py-12 text-center text-neutral-500 text-sm">
                  <Wallet size={22} className="mx-auto text-neutral-300 mb-2" />
                  No budgets yet for FY {year}. Click <b>New Budget</b> and pick an account from Settings.
                </td></tr>
              )}
            </tbody>
            <tfoot className="bg-neutral-900 text-white">
              <tr>
                <td className="px-4 py-3 uppercase text-[11px] tracking-widest">Total</td>
                <td className="px-3 py-3 text-right font-mono-tab text-sm">{inr(data.totals.budget)}</td>
                <td className="px-3 py-3 text-right font-mono-tab text-sm">{inr(data.totals.actual)}</td>
                <td className="px-3 py-3 text-right font-mono-tab text-sm">{inr(data.totals.remaining)}</td>
                <td className="px-3 py-3 text-right font-mono-tab text-sm text-red-300">{inr(data.totals.deficit)}</td>
                <td className="px-3 py-3 text-right font-mono-tab text-sm">{data.totals.utilization_pct != null ? data.totals.utilization_pct.toFixed(1) + "%" : "—"}</td>
                <td colSpan="2"></td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>

      <BudgetDrawer
        open={open}
        onOpenChange={setOpen}
        editing={editing}
        seedAccount={seedAccount}
        year={year}
        accounts={meta.accounts || []}
        onSaved={load}
      />
    </Layout>
  );
}

function BudgetDrawer({ open, onOpenChange, editing, seedAccount, year, accounts, onSaved }) {
  const [form, setForm] = useState({ year, account: "", amount: "", notes: "" });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    if (editing) {
      setForm({ year: editing.year, account: editing.account, amount: editing.amount, notes: editing.notes || "" });
    } else {
      setForm({ year, account: seedAccount || "", amount: "", notes: "" });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editing, open, seedAccount, year]);

  const save = async () => {
    setSaving(true);
    try {
      const payload = {
        year: parseInt(form.year),
        account: form.account,
        amount: parseFloat(form.amount),
        notes: form.notes,
      };
      if (editing) await api.put(`/budgets/${editing.id}`, payload);
      else await api.post("/budgets", payload);
      toast.success(editing ? "Budget updated" : "Budget created");
      onOpenChange(false);
      onSaved();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setSaving(false); }
  };

  const disabled = saving || !form.account || !form.amount || isNaN(parseFloat(form.amount)) || parseFloat(form.amount) < 0;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full sm:max-w-md rounded-none border-l-2 border-l-neutral-900" data-testid="budget-drawer">
        <SheetHeader>
          <div className="text-[11px] uppercase tracking-[0.25em] text-neutral-500">{editing ? "Edit" : "New"} Budget</div>
          <SheetTitle className="font-heading text-2xl tracking-tight">Yearly Expense Budget</SheetTitle>
          <SheetDescription>
            Pick an existing account from <b>Settings → Accounts</b>. This screen never creates a new account.
          </SheetDescription>
        </SheetHeader>
        <div className="mt-6 space-y-4">
          <div>
            <Label className="text-xs uppercase tracking-wider">Financial Year</Label>
            <Select value={String(form.year)} onValueChange={(v) => setForm({ ...form, year: parseInt(v) })}>
              <SelectTrigger data-testid="budget-year" className="rounded-none mt-1"><SelectValue /></SelectTrigger>
              <SelectContent>{YEARS.map((y) => <SelectItem key={y} value={String(y)}>{y}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-xs uppercase tracking-wider">Account ID (from Settings)</Label>
            <Select value={form.account} onValueChange={(v) => setForm({ ...form, account: v })} disabled={!!editing}>
              <SelectTrigger data-testid="budget-account" className="rounded-none mt-1"><SelectValue placeholder="Select account" /></SelectTrigger>
              <SelectContent className="max-h-80">
                {accounts.map((a) => <SelectItem key={a.name} value={a.name}>{a.name}</SelectItem>)}
                {accounts.length === 0 && <div className="px-3 py-2 text-xs text-neutral-500">No accounts in Settings yet.</div>}
              </SelectContent>
            </Select>
            {editing && <p className="text-[10px] text-neutral-500 mt-1">Account is locked once created (linked to historical data).</p>}
          </div>
          <div>
            <Label className="text-xs uppercase tracking-wider">Annual Budget Amount (₹)</Label>
            <Input data-testid="budget-amount" type="number" step="0.01" min="0" className="rounded-none mt-1 font-mono-tab" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
          </div>
          <div>
            <Label className="text-xs uppercase tracking-wider">Notes</Label>
            <Input data-testid="budget-notes" className="rounded-none mt-1" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          </div>
          <Button data-testid="budget-save" onClick={save} disabled={disabled} className="w-full rounded-none bg-neutral-900 hover:bg-neutral-700 h-11">
            {getSaveLabel(saving, editing)}
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}

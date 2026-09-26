import React, { useCallback, useEffect, useState } from "react";
import { api, formatApiError, inr } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { TypeBadge } from "@/components/TypeBadge";
import { fmtDate } from "@/lib/bankInbox";
import { LinkSimple, LinkBreak, EyeSlash, ArrowsClockwise } from "@phosphor-icons/react";

const CLS = { matched: "border-emerald-600 text-emerald-700 bg-emerald-50", unmatched: "border-red-600 text-red-700 bg-red-50", partially_matched: "border-amber-600 text-amber-700 bg-amber-50", ignored: "border-neutral-400 text-neutral-500" };

function Badge({ s }) { return <span data-testid="recon-status" className={`text-[10px] uppercase tracking-wider px-2 py-0.5 border ${CLS[s] || CLS.unmatched}`}>{(s || "unmatched").replace("_", " ")}</span>; }

export default function ReconciliationTab() {
  const [summary, setSummary] = useState({});
  const [rows, setRows] = useState([]);
  const [unmatchedFin, setUnmatchedFin] = useState([]);
  const [filter, setFilter] = useState("unmatched");
  const [view, setView] = useState("bank");
  const load = useCallback(async () => {
    try {
      const [s, r, u] = await Promise.all([api.get("/bank-transactions/reconciliation/summary"), api.get("/bank-transactions/reconciliation", { params: { status: filter } }), api.get("/bank-transactions/reconciliation/unmatched-finance", { params: { limit: 200 } })]);
      setSummary(s.data); setRows(r.data); setUnmatchedFin(u.data);
    } catch { /* ignore */ }
  }, [filter]);
  useEffect(() => { load(); }, [load]);
  const act = async (fn, msg) => { try { await fn(); toast.success(msg); load(); } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); } };
  const auto = () => act(async () => { const r = await api.post("/bank-transactions/reconciliation/auto"); toast.info(`${r.data.matched} matched, ${r.data.orphaned} orphaned`); }, "Auto-reconciliation complete");

  return (
    <div className="space-y-3" data-testid="reconciliation-tab">
      <div className="grid grid-cols-2 md:grid-cols-6 gap-2" data-testid="recon-summary">
        {["matched", "partially_matched", "unmatched", "ignored"].map((k) => (
          <button key={k} data-testid={`recon-filter-${k}`} onClick={() => { setFilter(k); setView("bank"); }} className={`bg-white border p-3 text-left ${filter === k && view === "bank" ? "border-neutral-900" : "border-neutral-200"}`}>
            <div className="text-[10px] uppercase tracking-wider text-neutral-500">{k.replace("_", " ")}</div><div className="font-mono-tab text-xl">{summary[k] ?? 0}</div>
          </button>
        ))}
        <button data-testid="recon-filter-finance" onClick={() => setView("finance")} className={`bg-white border p-3 text-left ${view === "finance" ? "border-neutral-900" : "border-neutral-200"}`}>
          <div className="text-[10px] uppercase tracking-wider text-neutral-500">Finance w/o bank record</div><div className="font-mono-tab text-xl">{summary.finance_without_bank_record ?? 0}</div>
        </button>
        <div className="flex items-center"><Button data-testid="recon-auto-btn" variant="outline" className="rounded-none w-full" onClick={auto}><ArrowsClockwise size={14} className="mr-1" /> Auto-match</Button></div>
      </div>

      {view === "bank" ? (
        <div className="space-y-2" data-testid="recon-bank-list">
          {rows.map((r) => (
            <div key={r.id} className="bg-white border border-neutral-200 p-3" data-testid={`recon-row-${r.id}`}>
              <div className="flex items-center justify-between gap-3 flex-wrap">
                <div className="text-sm"><span className="font-mono-tab text-xs text-neutral-500">{fmtDate(r.transaction_date)}</span> · <b>{r.bank_name}</b> · <span className="font-mono-tab">{inr(r.amount)}</span> {r.direction} · {r.narration}</div>
                <div className="flex items-center gap-2">
                  <Badge s={r.reconciliation_status} />
                  {r.finance_transaction_id && <span className="text-[11px] font-mono-tab text-neutral-500" data-testid="recon-fin-link">fin {r.finance_transaction_id}</span>}
                  {r.status === "approved" && r.reconciliation_status !== "ignored" && r.reconciliation_status !== "unmatched" && <Button data-testid="recon-unmatch-btn" size="sm" variant="ghost" className="rounded-none" onClick={() => act(() => api.post(`/bank-transactions/${r.id}/reconcile/unmatch`), "Unmatched")}><LinkBreak size={14} /></Button>}
                  {r.status === "approved" && r.reconciliation_status !== "ignored" && <Button data-testid="recon-ignore-btn" size="sm" variant="ghost" className="rounded-none" onClick={() => act(() => api.post(`/bank-transactions/${r.id}/reconcile/ignore`), "Ignored")}><EyeSlash size={14} /></Button>}
                  {r.status === "pending" && <span className="text-[11px] text-neutral-500">awaiting approval</span>}
                </div>
              </div>
              {r.candidates?.length > 0 && (
                <div className="mt-2 border-t border-neutral-100 pt-2">
                  <div className="text-[10px] uppercase tracking-wider text-neutral-500 mb-1">Suggested finance matches (±3 days, ±2% amount)</div>
                  {r.candidates.slice(0, 3).map((c) => (
                    <div key={c.id} className="flex items-center justify-between text-xs py-1" data-testid="recon-candidate">
                      <div><span className="font-mono-tab">{fmtDate(c.date)}</span> <TypeBadge type={c.type} /> {c.account} · <span className="font-mono-tab">{c.project_id}</span> · <span className="font-mono-tab">{inr(c.amount)}</span> · {c.notes} <span className="text-neutral-400">({c.source}, score {c.score})</span></div>
                      <Button data-testid="recon-match-btn" size="sm" variant="outline" className="rounded-none" onClick={() => act(() => api.post(`/bank-transactions/${r.id}/reconcile/match`, { finance_transaction_id: c.id }), c.exact_amount ? "Matched" : "Partially matched")}><LinkSimple size={14} className="mr-1" /> Match</Button>
                    </div>
                  ))}
                </div>
              )}
              {r.status === "approved" && r.reconciliation_status === "unmatched" && !r.candidates?.length && <div className="text-xs text-neutral-500 mt-1">No finance candidates within window.</div>}
            </div>
          ))}
          {!rows.length && <div className="bg-white border border-neutral-200 p-8 text-center text-sm text-neutral-500" data-testid="recon-empty">Nothing in this state.</div>}
        </div>
      ) : (
        <div className="bg-white border border-neutral-200 overflow-auto" data-testid="recon-finance-list">
          <div className="p-2 text-xs text-neutral-600 border-b border-neutral-200">Finance entries with no linked bank transaction (manual / AI / CSV imports). Link them from an unmatched bank row, or they may be non-bank entries.</div>
          <table className="w-full text-xs"><thead className="bg-neutral-50 text-[10px] uppercase tracking-wider text-neutral-500"><tr><th className="p-2 text-left">Date</th><th className="p-2 text-left">Type</th><th className="p-2 text-left">Account</th><th className="p-2 text-left">Project</th><th className="p-2 text-right">Amount</th><th className="p-2 text-left">Notes</th><th className="p-2 text-left">Source</th></tr></thead>
            <tbody>{unmatchedFin.map((t) => <tr key={t.id} className="border-t border-neutral-100" data-testid="recon-fin-row"><td className="p-2 font-mono-tab">{fmtDate(t.date)}</td><td className="p-2"><TypeBadge type={t.type} /></td><td className="p-2">{t.account}</td><td className="p-2 font-mono-tab">{t.project_id}</td><td className="p-2 text-right font-mono-tab">{inr(t.amount)}</td><td className="p-2 truncate max-w-[240px]">{t.notes}</td><td className="p-2">{t.source}</td></tr>)}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}

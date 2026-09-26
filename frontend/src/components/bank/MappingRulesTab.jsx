import React, { useCallback, useEffect, useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { TypeBadge } from "@/components/TypeBadge";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { Trash, Power, PencilSimple, Check, X } from "@phosphor-icons/react";

const sel = "rounded-none border border-neutral-300 h-8 px-1 text-xs bg-white";

function RuleRow({ r, meta, reload }) {
  const [editing, setEditing] = useState(false);
  const [m, setM] = useState(r.mapping || {});
  const run = async (fn, msg) => {
    try { await fn(); toast.success(msg); reload(); } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  return (
    <tr className={`border-t border-neutral-100 ${r.enabled ? "" : "opacity-50"}`} data-testid={`rule-row-${r.id}`}>
      <td className="p-2 font-mono-tab text-xs">{r.pattern}<div className="text-[10px] text-neutral-500">{r.bank}</div></td>
      <td className="p-2 text-xs">
        {editing ? (
          <div className="flex gap-1 flex-wrap">
            <select data-testid="rule-edit-type" className={sel} value={m.type} onChange={(e) => setM({ ...m, type: e.target.value })}><option>Revenue</option><option>Cost</option><option>Expense</option></select>
            <select data-testid="rule-edit-account" className={sel} value={m.account} onChange={(e) => setM({ ...m, account: e.target.value })}>{(meta?.accounts || []).map((a) => <option key={a.name}>{a.name}</option>)}</select>
            <select data-testid="rule-edit-project" className={`${sel} font-mono-tab`} value={m.project_id} onChange={(e) => setM({ ...m, project_id: e.target.value })}>{(meta?.project_ids || []).map((p) => <option key={p.code}>{p.code}</option>)}</select>
          </div>
        ) : (
          <div className="flex items-center gap-2 flex-wrap"><TypeBadge type={r.mapping?.type} /> {r.mapping?.account} · <span className="font-mono-tab">{r.mapping?.project_id}</span></div>
        )}
      </td>
      <td className="p-2 text-right font-mono-tab text-xs" data-testid="rule-uses">{r.uses}</td>
      <td className="p-2 text-right font-mono-tab text-xs">{r.corrections}</td>
      <td className="p-2"><ConfidenceBadge value={r.confidence} showBar={false} /></td>
      <td className="p-2 text-xs">{r.enabled ? "Enabled" : "Disabled"}</td>
      <td className="p-2 text-right whitespace-nowrap">
        {editing ? (
          <>
            <Button data-testid="rule-save-btn" size="sm" variant="ghost" className="rounded-none" onClick={() => run(async () => { await api.put(`/bank-transactions/rules/${r.id}`, m); setEditing(false); }, "Rule updated")}><Check size={14} /></Button>
            <Button data-testid="rule-cancel-btn" size="sm" variant="ghost" className="rounded-none" onClick={() => setEditing(false)}><X size={14} /></Button>
          </>
        ) : (
          <>
            <Button data-testid="rule-edit-btn" size="sm" variant="ghost" className="rounded-none" onClick={() => setEditing(true)}><PencilSimple size={14} /></Button>
            <Button data-testid="rule-toggle-btn" size="sm" variant="ghost" className="rounded-none" onClick={() => run(() => api.put(`/bank-transactions/rules/${r.id}`, { enabled: !r.enabled }), r.enabled ? "Rule disabled" : "Rule enabled")}><Power size={14} /></Button>
            <Button data-testid="rule-delete-btn" size="sm" variant="ghost" className="rounded-none text-red-700" onClick={() => { if (window.confirm(`Delete rule '${r.pattern}'?`)) run(() => api.delete(`/bank-transactions/rules/${r.id}`), "Rule deleted"); }}><Trash size={14} /></Button>
          </>
        )}
      </td>
    </tr>
  );
}

export default function MappingRulesTab({ meta }) {
  const [rules, setRules] = useState([]);
  const load = useCallback(async () => {
    try { setRules((await api.get("/bank-transactions/rules")).data); } catch { /* ignore */ }
  }, []);
  useEffect(() => { load(); }, [load]);
  return (
    <div className="bg-white border border-neutral-200" data-testid="mapping-rules-tab">
      <div className="p-3 text-xs text-neutral-600 border-b border-neutral-200">
        Learned from approvals. A rule only drives suggestions once its confidence reaches 70% (≥2 consistent approvals, no corrections). One correction never overrides a rule by itself.
      </div>
      <table className="w-full text-sm">
        <thead className="bg-neutral-50 text-[10px] uppercase tracking-wider text-neutral-500">
          <tr><th className="text-left p-2">Pattern</th><th className="text-left p-2">Typical mapping</th><th className="text-right p-2">Approvals</th><th className="text-right p-2">Corrections</th><th className="text-left p-2">Confidence</th><th className="text-left p-2">State</th><th className="p-2"></th></tr>
        </thead>
        <tbody>
          {rules.map((r) => <RuleRow key={r.id} r={r} meta={meta} reload={load} />)}
          {!rules.length && <tr><td colSpan={7} className="p-6 text-center text-neutral-500 text-sm" data-testid="rules-empty">No learned rules yet — approve bank transactions to start learning.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

import React, { useState } from "react";
import { api, formatApiError, inr } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { Check, X, PencilSimple, Question, ArrowsClockwise, ClockCounterClockwise, Warning, ArrowsLeftRight } from "@phosphor-icons/react";
import { TypeBadge } from "@/components/TypeBadge";
import { ConfidenceBadge, DirectionBadge, StatusBadge } from "./ConfidenceBadge";
import { fmtDate, SOURCE_LABEL } from "@/lib/bankInbox";

function Row({ label, value, mono, modified }) {
  return (
    <div className="flex items-baseline gap-2 text-sm">
      <span className="text-[10px] uppercase tracking-wider text-neutral-500 w-16 shrink-0">{label}</span>
      <span className={mono ? "font-mono-tab" : ""}>{value ?? "—"}</span>
      {modified && <span className="text-[9px] px-1 border border-yellow-600 text-yellow-700 bg-yellow-50" data-testid="modified-tag">Modified</span>}
    </div>
  );
}

export default function BankTxnCard({ txn, onChanged, onEdit, onExplain, onAudit, onDuplicateReview, selectable, selected, onToggle }) {
  const [busy, setBusy] = useState(false);
  const s = txn.suggestion || {};
  const eff = { ...{ type: s.type, account: s.account, project_id: s.project_id, amount: txn.amount, date: txn.transaction_date }, ...(txn.final || txn.user_edits || {}) };
  const modified = new Set(txn.modified_fields || []);
  const pending = txn.status === "pending";

  const act = async (fn, okMsg) => {
    setBusy(true);
    try { await fn(); toast.success(okMsg); onChanged(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const approve = () => act(() => api.post(`/bank-transactions/${txn.id}/approve`), "Approved & posted to Transactions");
  const reject = () => {
    const reason = window.prompt("Rejection reason (optional):", "");
    if (reason === null) return;
    act(() => api.post(`/bank-transactions/${txn.id}/reject`, { reason }), "Bank transaction rejected");
  };
  const reclassify = () => act(() => api.post(`/bank-transactions/${txn.id}/reclassify`), "Re-classified");

  return (
    <div className={`bg-white border p-4 flex flex-col gap-3 transition-colors ${selected ? "border-emerald-600 ring-1 ring-emerald-600" : "border-neutral-200 hover:border-neutral-400"}`} data-testid={`bank-txn-card-${txn.id}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          {selectable && <input type="checkbox" data-testid="card-select" className="mt-1.5 h-4 w-4 accent-emerald-700" checked={!!selected} onChange={() => onToggle(txn.id)} />}
          <div>
          <div className="font-heading font-semibold text-neutral-900" data-testid="card-bank-name">{txn.bank_name} <span className="text-xs text-neutral-500 font-mono-tab font-normal">{txn.bank_account_masked}</span></div>
          <div className="text-xs text-neutral-500 font-mono-tab">{fmtDate(txn.transaction_date)} {txn.transaction_time}</div>
          </div>
        </div>
        <div className="text-right">
          <div className={`font-mono-tab text-lg ${txn.direction === "debit" ? "text-neutral-900" : "text-blue-700"}`} data-testid="card-amount">{inr(txn.amount)}</div>
          <div className="flex gap-1 justify-end"><DirectionBadge direction={txn.direction} /><StatusBadge status={txn.status} /></div>
        </div>
      </div>
      <div className="text-sm text-neutral-800 border-l-2 border-neutral-300 pl-2" data-testid="card-narration">{txn.narration}</div>
      {txn.bank_reference && <div className="text-[11px] text-neutral-500 font-mono-tab">Ref: {txn.bank_reference}</div>}

      {txn.status === "duplicate" || txn.status === "duplicate_rejected" ? (
        <div className={`text-xs border p-2 space-y-2 ${txn.status === "duplicate" ? "text-amber-900 bg-amber-50 border-amber-300" : "text-neutral-600 bg-neutral-50 border-neutral-200"}`} data-testid="duplicate-info">
          <div className="font-semibold tracking-wider flex items-center gap-1"><Warning size={14} /> {txn.status === "duplicate" ? "POSSIBLE DUPLICATE — needs your review" : "REJECTED AS DUPLICATE"}</div>
          <div>Matches bank transaction <span className="font-mono-tab">{(txn.duplicate_of || "").slice(-8)}</span>{txn.duplicate_score != null && <> · confidence <span className="font-mono-tab" data-testid="card-dup-score">{txn.duplicate_score}%</span></>}. No accounting entry created.</div>
          {txn.status === "duplicate_rejected" && <div data-testid="dup-rejected-by">Confirmed duplicate by {txn.duplicate_reviewed_by} on {(txn.duplicate_reviewed_at || "").slice(0, 10)}{txn.rejection_reason ? ` — ${txn.rejection_reason}` : ""}</div>}
          {txn.status === "duplicate" && (
            <div className="flex flex-wrap gap-2 justify-end pt-1">
              <Button data-testid="card-dup-compare-btn" size="sm" variant="ghost" className="rounded-none" onClick={() => onDuplicateReview(txn, "compare")}><ArrowsLeftRight size={14} className="mr-1" /> Compare</Button>
              <Button data-testid="card-dup-reject-btn" size="sm" variant="outline" className="rounded-none border-neutral-400" onClick={() => onDuplicateReview(txn, "reject")}><X size={14} className="mr-1" /> Reject as Duplicate</Button>
              <Button data-testid="card-dup-approve-btn" size="sm" className="rounded-none bg-emerald-700 hover:bg-emerald-600" onClick={() => onDuplicateReview(txn, "approve")}><Check size={14} className="mr-1" /> Approve as New Transaction</Button>
            </div>
          )}
        </div>
      ) : (
        <div className="bg-neutral-50 border border-neutral-200 p-3 space-y-1.5">
          {txn.duplicate_review_action === "approved_as_new" && (
            <div className="text-[11px] text-amber-800 border border-amber-300 bg-amber-50 px-2 py-1" data-testid="dup-override-note">
              Duplicate warning overridden by {txn.duplicate_reviewed_by}: {txn.duplicate_override_reason} <button type="button" className="underline ml-1" data-testid="dup-override-compare" onClick={() => onDuplicateReview(txn, "compare")}>view match</button>
            </div>
          )}
          <div className="flex items-center justify-between">
            <div className="text-[10px] uppercase tracking-[0.2em] text-neutral-500">{txn.status === "approved" ? "Approved classification" : "Suggested classification"}</div>
            <span className="text-[10px] text-neutral-500">{SOURCE_LABEL[s.source] || s.source || ""}</span>
          </div>
          <Row label="Type" value={eff.type ? <TypeBadge type={eff.type} /> : "—"} modified={modified.has("type")} />
          <Row label="Account" value={eff.account} modified={modified.has("account")} />
          <Row label="Project" value={eff.project_id} mono modified={modified.has("project_id")} />
          {(modified.has("amount") || modified.has("date")) && <Row label="Amount" value={`${inr(eff.amount)} · ${fmtDate(eff.date)}`} mono modified />}
          {modified.size > 0 && (
            <div className="text-[11px] text-neutral-500 pt-1" data-testid="original-suggestion-line">
              Originally suggested: {s.type || "—"} · {s.account || "—"} · <span className="font-mono-tab">{s.project_id || "—"}</span>
            </div>
          )}
          <div className="flex items-center justify-between pt-1">
            <ConfidenceBadge value={s.confidence} />
            <span className="text-[11px] text-neutral-500" data-testid="card-match-count">Historical matches: {(txn.matches || []).length}</span>
          </div>
          {txn.status === "rejected" && <div className="text-xs text-neutral-600" data-testid="rejection-reason">Rejected by {txn.rejected_by}: {txn.rejection_reason || "—"}</div>}
          {txn.finance_transaction_id && <div className="text-xs text-emerald-700 font-mono-tab" data-testid="finance-link">Finance txn: {txn.finance_transaction_id}</div>}
        </div>
      )}

      <div className="flex items-center justify-between gap-2 pt-1">
        <div className="flex gap-1">
          <Button data-testid="card-explain-btn" size="sm" variant="ghost" className="rounded-none text-xs" onClick={() => onExplain(txn)}><Question size={14} className="mr-1" /> Why this suggestion?</Button>
          <Button data-testid="card-audit-btn" size="sm" variant="ghost" className="rounded-none text-xs" onClick={() => onAudit(txn)}><ClockCounterClockwise size={14} /></Button>
        </div>
        {pending && (
          <div className="flex gap-2">
            <Button data-testid="card-reclassify-btn" size="sm" variant="ghost" className="rounded-none" onClick={reclassify} disabled={busy}><ArrowsClockwise size={14} /></Button>
            <Button data-testid="card-reject-btn" size="sm" variant="outline" className="rounded-none border-neutral-400" onClick={reject} disabled={busy}><X size={14} className="mr-1" /> Reject</Button>
            <Button data-testid="card-edit-btn" size="sm" variant="outline" className="rounded-none border-yellow-600 text-yellow-800" onClick={() => onEdit(txn)} disabled={busy}><PencilSimple size={14} className="mr-1" /> Edit</Button>
            <Button data-testid="card-approve-btn" size="sm" className="rounded-none bg-emerald-700 hover:bg-emerald-600" onClick={approve} disabled={busy}><Check size={14} className="mr-1" /> Approve & Post</Button>
          </div>
        )}
      </div>
    </div>
  );
}

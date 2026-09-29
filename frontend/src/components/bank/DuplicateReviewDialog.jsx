import React, { useEffect, useState } from "react";
import { api, formatApiError, inr } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import { Warning, Check, X } from "@phosphor-icons/react";
import { fmtDate } from "@/lib/bankInbox";

const FIELDS = [
  ["Bank / account", (t) => `${t.bank_name} ${t.bank_account_masked || ""}`],
  ["Date / time", (t) => `${fmtDate(t.transaction_date)} ${t.transaction_time || ""}`],
  ["Amount", (t) => inr(t.amount)],
  ["Debit / credit", (t) => t.direction],
  ["Narration", (t) => t.narration],
  ["Reference", (t) => t.bank_reference || t.utr_reference || "—"],
  ["Source", (t) => `${t.source}${t.source_message_id ? ` · ${t.source_message_id}` : ""}`],
  ["Status", (t) => t.status + (t.finance_transaction_id ? ` · finance ${t.finance_transaction_id.slice(-6)}` : "")],
];

function Column({ title, txn, accent }) {
  return (
    <div className={`border p-3 space-y-2 ${accent ? "border-amber-400 bg-amber-50/40" : "border-neutral-200 bg-neutral-50"}`} data-testid={accent ? "dup-current" : "dup-match"}>
      <div className="text-[10px] uppercase tracking-[0.2em] text-neutral-500">{title}</div>
      {!txn ? <div className="text-sm text-neutral-500">Original record not found</div> : FIELDS.map(([l, f]) => (
        <div key={l} className="text-sm"><span className="text-[10px] uppercase tracking-wider text-neutral-500 block">{l}</span><span className={l === "Amount" ? "font-mono-tab text-lg" : ""}>{f(txn)}</span></div>
      ))}
    </div>
  );
}

export default function DuplicateReviewDialog({ txn, mode, open, onOpenChange, onChanged }) {
  const [data, setData] = useState(null);
  const [step, setStep] = useState("compare");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open || !txn) return;
    setData(null); setReason(""); setStep(mode || "compare");
    api.get(`/bank-transactions/${txn.id}/duplicate`).then((r) => setData(r.data)).catch((e) => toast.error(formatApiError(e.response?.data?.detail)));
  }, [open, txn, mode]);

  const act = async (url, body, okMsg) => {
    setBusy(true);
    try { await api.post(url, body); toast.success(okMsg); onChanged(); onOpenChange(false); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const approve = () => act(`/bank-transactions/${txn?.id}/duplicate/approve`, { reason }, "Duplicate warning overridden — now in Pending for normal approval");
  const reject = () => act(`/bank-transactions/${txn?.id}/duplicate/reject`, { note: reason }, "Confirmed as duplicate — no accounting entry created");
  const reviewable = data?.reviewable;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl rounded-none" data-testid="duplicate-review-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 font-heading"><Warning size={18} className="text-amber-600" /> Possible duplicate — review</DialogTitle>
          <DialogDescription>Compare the incoming record with the suspected existing record. Nothing posts to accounting until you decide.</DialogDescription>
        </DialogHeader>
        {!data ? <div className="text-sm text-neutral-500" data-testid="dup-loading">Loading…</div> : (
          <div className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <Column title="Current transaction" txn={data.transaction} accent />
              <Column title="Possible match (existing)" txn={data.match} />
            </div>
            <div className="border border-neutral-200 p-3 text-sm" data-testid="dup-reasons">
              <div className="flex items-center justify-between">
                <span className="text-[10px] uppercase tracking-[0.2em] text-neutral-500">Matched because</span>
                <span className="font-mono-tab" data-testid="dup-score">Duplicate confidence: {data.score}%</span>
              </div>
              <ul className="list-disc pl-5 mt-1 space-y-0.5">{(data.reasons || []).map((r) => <li key={r}>{r}</li>)}</ul>
            </div>
            {data.transaction.duplicate_review_action && (
              <div className="text-xs text-neutral-600 border border-neutral-200 p-2" data-testid="dup-review-record">
                Reviewed by {data.transaction.duplicate_reviewed_by} on {data.transaction.duplicate_reviewed_at?.slice(0, 16).replace("T", " ")} — {data.transaction.duplicate_review_action.replace(/_/g, " ")}{data.transaction.duplicate_override_reason ? `: ${data.transaction.duplicate_override_reason}` : ""}
              </div>
            )}
            {reviewable && step === "compare" && (
              <div className="flex justify-end gap-2">
                <Button data-testid="dup-choose-reject" variant="outline" className="rounded-none border-neutral-400" onClick={() => setStep("reject")}><X size={14} className="mr-1" /> Reject as Duplicate</Button>
                <Button data-testid="dup-choose-approve" className="rounded-none bg-emerald-700 hover:bg-emerald-600" onClick={() => setStep("approve")}><Check size={14} className="mr-1" /> Approve as New Transaction</Button>
              </div>
            )}
            {reviewable && step === "approve" && (
              <div className="space-y-2 border border-emerald-600 p-3" data-testid="dup-approve-confirm">
                <div className="text-sm font-medium">Confirm: this is a separate legitimate transaction.</div>
                <div className="text-xs text-neutral-600">It will move to Pending and follow the normal Approve &amp; Post workflow. The original record is not modified. Your name, time and reason are recorded permanently.</div>
                <Textarea data-testid="dup-override-reason" className="rounded-none" placeholder="Override reason (required, min 5 chars) — e.g. Separate transaction with same vendor and amount" value={reason} onChange={(e) => setReason(e.target.value)} />
                <div className="flex justify-end gap-2">
                  <Button variant="ghost" className="rounded-none" onClick={() => setStep("compare")} disabled={busy}>Back</Button>
                  <Button data-testid="dup-approve-submit" className="rounded-none bg-emerald-700 hover:bg-emerald-600" onClick={approve} disabled={busy || reason.trim().length < 5}>Confirm — Approve as New</Button>
                </div>
              </div>
            )}
            {reviewable && step === "reject" && (
              <div className="space-y-2 border border-neutral-500 p-3" data-testid="dup-reject-confirm">
                <div className="text-sm font-medium">Confirm: this is a genuine duplicate.</div>
                <div className="text-xs text-neutral-600">No accounting entry will be created. The record is kept for audit with its link to the original.</div>
                <Textarea data-testid="dup-reject-note" className="rounded-none" placeholder="Note (optional)" value={reason} onChange={(e) => setReason(e.target.value)} />
                <div className="flex justify-end gap-2">
                  <Button variant="ghost" className="rounded-none" onClick={() => setStep("compare")} disabled={busy}>Back</Button>
                  <Button data-testid="dup-reject-submit" variant="outline" className="rounded-none border-neutral-500" onClick={reject} disabled={busy}>Confirm — Reject as Duplicate</Button>
                </div>
              </div>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

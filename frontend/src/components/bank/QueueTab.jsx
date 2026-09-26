import React, { useCallback, useEffect, useState } from "react";
import { api, formatApiError, inr } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Wrench, Trash } from "@phosphor-icons/react";

const STATUS_CLS = { received: "border-neutral-400 text-neutral-600", parsed: "border-blue-600 text-blue-700", parse_failed: "border-red-600 text-red-700 bg-red-50", duplicate: "border-amber-600 text-amber-700", pending: "border-emerald-600 text-emerald-700", discarded: "border-neutral-300 text-neutral-400" };

function ResolveDialog({ msg, open, onOpenChange, onDone }) {
  const [f, setF] = useState({});
  useEffect(() => {
    if (!msg) return;
    const p = msg.parsed_fields || {};
    setF({ bank_name: p.bank_name || msg.bank_hint || "", bank_account: "", transaction_date: p.transaction_date || (msg.received_at || "").slice(0, 10), direction: p.direction || "debit", amount: p.amount || "", narration: p.narration || msg.subject || "", bank_reference: p.bank_reference || "" });
  }, [msg]);
  if (!msg) return null;
  const set = (k) => (e) => setF((x) => ({ ...x, [k]: e.target.value }));
  const submit = async () => {
    try {
      await api.post(`/bank-transactions/queue/${msg.id}/resolve`, { ...f, amount: parseFloat(f.amount) });
      toast.success("Resolved — now in Pending for approval"); onDone(); onOpenChange(false);
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg rounded-none border-l-2 border-l-red-600" data-testid="queue-resolve-dialog">
        <DialogHeader><DialogTitle className="font-heading text-xl">Needs Parsing Review</DialogTitle><DialogDescription>Parser could not extract all fields ({(msg.parse_errors || []).join(", ")}). Fill them in manually; the record then enters the normal approval pipeline.</DialogDescription></DialogHeader>
        <pre className="text-[11px] bg-neutral-50 border border-neutral-200 p-2 max-h-28 overflow-auto whitespace-pre-wrap" data-testid="queue-body-preview">{msg.body || msg.body_preview}</pre>
        <div className="grid grid-cols-2 gap-2">
          <Input data-testid="resolve-bank" placeholder="Bank" className="rounded-none" value={f.bank_name || ""} onChange={set("bank_name")} />
          <Input data-testid="resolve-date" type="date" className="rounded-none" value={f.transaction_date || ""} onChange={set("transaction_date")} />
          <select data-testid="resolve-direction" className="rounded-none border border-neutral-300 h-9 px-2 text-sm bg-white" value={f.direction} onChange={set("direction")}><option value="debit">Debit</option><option value="credit">Credit</option></select>
          <Input data-testid="resolve-amount" type="number" step="0.01" placeholder="Amount" className="rounded-none font-mono-tab" value={f.amount} onChange={set("amount")} />
          <Input data-testid="resolve-narration" placeholder="Narration" className="rounded-none col-span-2" value={f.narration || ""} onChange={set("narration")} />
          <Input data-testid="resolve-reference" placeholder="Reference" className="rounded-none font-mono-tab" value={f.bank_reference || ""} onChange={set("bank_reference")} />
          <Input data-testid="resolve-account" placeholder="Bank account (optional)" className="rounded-none font-mono-tab" value={f.bank_account || ""} onChange={set("bank_account")} />
        </div>
        <div className="flex justify-end gap-2"><Button variant="outline" className="rounded-none" onClick={() => onOpenChange(false)}>Cancel</Button><Button data-testid="resolve-submit" className="rounded-none bg-neutral-900" onClick={submit}>Create pending bank transaction</Button></div>
      </DialogContent>
    </Dialog>
  );
}

export default function QueueTab() {
  const [rows, setRows] = useState([]);
  const [stats, setStats] = useState({});
  const [filter, setFilter] = useState("parse_failed");
  const [sel, setSel] = useState(null);
  const load = useCallback(async () => {
    try {
      const [r, s] = await Promise.all([api.get("/bank-transactions/queue", { params: { status: filter } }), api.get("/bank-transactions/queue/stats")]);
      setRows(r.data); setStats(s.data);
    } catch { /* ignore */ }
  }, [filter]);
  useEffect(() => { load(); }, [load]);
  const open = async (m) => { try { setSel((await api.get(`/bank-transactions/queue/${m.id}`)).data); } catch { setSel(m); } };
  const discard = async (m) => {
    if (!window.confirm("Discard this unparseable message? It stays in the queue log as discarded.")) return;
    try { await api.post(`/bank-transactions/queue/${m.id}/discard`); toast.success("Discarded"); load(); } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  return (
    <div className="space-y-3" data-testid="queue-tab">
      <div className="flex gap-1 flex-wrap" data-testid="queue-status-filters">
        {["parse_failed", "pending", "duplicate", "parsed", "received", "all"].map((s) => (
          <button key={s} data-testid={`queue-filter-${s}`} onClick={() => setFilter(s)} className={`text-xs px-3 py-1.5 border ${filter === s ? "bg-neutral-900 text-white border-neutral-900" : "bg-white border-neutral-300 text-neutral-600"}`}>
            {s === "parse_failed" ? "Needs Parsing Review" : s.replace("_", " ")} <span className="font-mono-tab opacity-70">{s === "all" ? Object.values(stats).reduce((a, b) => a + b, 0) : stats[s] ?? 0}</span>
          </button>
        ))}
      </div>
      <div className="bg-white border border-neutral-200 overflow-auto">
        <table className="w-full text-sm">
          <thead className="bg-neutral-50 text-[10px] uppercase tracking-wider text-neutral-500"><tr><th className="p-2 text-left">Received</th><th className="p-2 text-left">Source</th><th className="p-2 text-left">Sender</th><th className="p-2 text-left">Subject</th><th className="p-2 text-left">Parser</th><th className="p-2 text-left">Status</th><th className="p-2 text-left">Extracted</th><th className="p-2"></th></tr></thead>
          <tbody>
            {rows.map((m) => (
              <tr key={m.id} className="border-t border-neutral-100" data-testid={`queue-row-${m.id}`}>
                <td className="p-2 font-mono-tab text-xs">{(m.received_at || m.created_at || "").slice(0, 16).replace("T", " ")}</td>
                <td className="p-2 text-xs uppercase">{m.source}</td>
                <td className="p-2 text-xs">{m.sender_masked}</td>
                <td className="p-2 text-xs max-w-[220px] truncate" title={m.subject}>{m.subject || m.body_preview}</td>
                <td className="p-2 text-xs font-mono-tab">{m.parser || "—"}</td>
                <td className="p-2"><span data-testid="queue-status" className={`text-[10px] uppercase tracking-wider px-2 py-0.5 border ${STATUS_CLS[m.parsing_status] || ""}`}>{m.parsing_status === "parse_failed" ? "Needs Parsing Review" : m.parsing_status}</span></td>
                <td className="p-2 text-xs">{m.parsed_fields?.amount ? `${inr(m.parsed_fields.amount)} ${m.parsed_fields.direction} · ${m.parsed_fields.narration || ""}` : (m.parse_errors || []).join(", ")}</td>
                <td className="p-2 text-right whitespace-nowrap">
                  {m.parsing_status === "parse_failed" && <><Button data-testid="queue-resolve-btn" size="sm" variant="outline" className="rounded-none" onClick={() => open(m)}><Wrench size={14} className="mr-1" /> Resolve</Button> <Button data-testid="queue-discard-btn" size="sm" variant="ghost" className="rounded-none text-red-700" onClick={() => discard(m)}><Trash size={14} /></Button></>}
                </td>
              </tr>
            ))}
            {!rows.length && <tr><td colSpan={8} className="p-6 text-center text-neutral-500 text-sm" data-testid="queue-empty">No queue messages in this state.</td></tr>}
          </tbody>
        </table>
      </div>
      <ResolveDialog msg={sel} open={!!sel} onOpenChange={(o) => !o && setSel(null)} onDone={load} />
    </div>
  );
}

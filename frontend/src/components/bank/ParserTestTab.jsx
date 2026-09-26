import React, { useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import { Flask } from "@phosphor-icons/react";

const SAMPLE = "Dear Customer, Your Account XX2345 has been debited with INR 4,499.13 on 12-May-26. Info: MICROSOFT SUBSCRIPTION E080105RXG. The Available Balance is INR 1,20,000.00.";

export default function ParserTestTab() {
  const [f, setF] = useState({ body: SAMPLE, subject: "Transaction alert", sender: "alerts@icicibank.com", bank_hint: "", received_at: "" });
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF((x) => ({ ...x, [k]: e.target.value }));
  const [sending, setSending] = useState(false);
  const send = async () => {
    if (!window.confirm("Send this parsed alert into the Bank Inbox as a PENDING transaction (requires approval later)?")) return;
    setSending(true);
    try { const r = await api.post("/bank-transactions/parsers/submit", { ...f, source: "email" }); toast.success(`Sent to inbox — status ${r.data.parsing_status}`); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail?.message || e.response?.data?.detail)); }
    finally { setSending(false); }
  };
  const run = async () => {
    setBusy(true);
    try { setRes((await api.post("/bank-transactions/parsers/test", f)).data); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4" data-testid="parser-test-tab">
      <div className="bg-white border border-neutral-200 p-4 space-y-3">
        <div className="text-[10px] uppercase tracking-[0.2em] text-neutral-500">Simulate a Microsoft 365 queue payload — nothing is saved</div>
        <div className="grid grid-cols-2 gap-2">
          <Input data-testid="pt-sender" placeholder="Sender (e.g. alerts@icicibank.com)" className="rounded-none" value={f.sender} onChange={set("sender")} />
          <Input data-testid="pt-subject" placeholder="Subject" className="rounded-none" value={f.subject} onChange={set("subject")} />
          <Input data-testid="pt-bank-hint" placeholder="Bank hint (optional)" className="rounded-none" value={f.bank_hint} onChange={set("bank_hint")} />
          <Input data-testid="pt-received" type="datetime-local" className="rounded-none" value={f.received_at} onChange={set("received_at")} />
        </div>
        <textarea data-testid="pt-body" className="w-full rounded-none border border-neutral-300 p-2 text-sm font-mono-tab h-40" value={f.body} onChange={set("body")} />
        <Button data-testid="pt-run" className="rounded-none bg-neutral-900 hover:bg-neutral-700" onClick={run} disabled={busy || !f.body}><Flask size={16} className="mr-1" /> Run all parsers</Button>
      </div>
      <div className="space-y-3">
        {res && (
          <>
            <div className={`bg-white border-l-4 border border-neutral-200 p-4 ${res.ok ? "border-l-emerald-600" : "border-l-red-600"}`} data-testid="pt-result">
              <div className="text-[10px] uppercase tracking-[0.2em] text-neutral-500">Selected parser</div>
              <div className="font-heading text-lg" data-testid="pt-selected">{res.selected_parser} <span className="text-xs text-neutral-500 font-mono-tab">v{res.parser_version} · score {res.selected_score}</span>{res.result_parser !== res.selected_parser && <span className="text-xs text-amber-700 ml-2">→ fell back to {res.result_parser}</span>}</div>
              <div className="text-xs text-neutral-600 mt-0.5" data-testid="pt-selection">Detected bank: <b>{res.bank_name}</b> · method: <span className="font-mono-tab">{res.selection_method}</span> · parser confidence: <span className="font-mono-tab">{res.selection_confidence}%</span></div>
              <div className="text-sm mt-1">{res.ok ? "Parsed successfully" : `Parse failed: ${res.errors.join(", ")}`}</div>
              {(res.warnings?.length > 0 || res.missing_optional?.length > 0) && <div className="text-xs text-amber-700 mt-1" data-testid="pt-warnings">Warnings: {[...(res.warnings || []), ...(res.missing_optional || []).map((m) => `${m} missing`)].join("; ")}</div>}
              {res.ok && <Button data-testid="pt-send" size="sm" className="rounded-none mt-3 bg-emerald-700 hover:bg-emerald-600" onClick={send} disabled={sending}>{sending ? "Sending…" : "Send to Bank Inbox"}</Button>}
              <div className="grid grid-cols-2 md:grid-cols-3 gap-2 mt-3 text-xs" data-testid="pt-fields">
                {Object.entries(res.fields || {}).map(([k, v]) => <div key={k}><div className="text-neutral-500 uppercase text-[10px]">{k}</div><div className="font-mono-tab break-all">{String(v) || "—"}</div></div>)}
              </div>
            </div>
            <div className="bg-white border border-neutral-200">
              <table className="w-full text-xs" data-testid="pt-candidates">
                <thead className="bg-neutral-50 text-[10px] uppercase tracking-wider text-neutral-500"><tr><th className="p-2 text-left">Parser</th><th className="p-2 text-right">Score</th><th className="p-2 text-left">Result</th><th className="p-2 text-left">Amount / Dir / Date</th><th className="p-2 text-left">Narration</th></tr></thead>
                <tbody>{res.candidates.map((c) => (
                  <tr key={c.parser} className="border-t border-neutral-100" data-testid={`pt-candidate-${c.parser}`}>
                    <td className="p-2 font-mono-tab">{c.parser}</td><td className="p-2 text-right font-mono-tab">{c.score}</td>
                    <td className={`p-2 ${c.ok ? "text-emerald-700" : "text-red-700"}`}>{c.ok ? "ok" : c.errors.join(", ")}</td>
                    <td className="p-2 font-mono-tab">{c.fields.amount || "—"} / {c.fields.direction || "—"} / {c.fields.transaction_date || "—"}</td>
                    <td className="p-2 max-w-[200px] truncate" title={c.fields.narration}>{c.fields.narration || "—"}</td>
                  </tr>))}</tbody>
              </table>
            </div>
          </>
        )}
        {!res && <div className="bg-white border border-neutral-200 p-8 text-center text-sm text-neutral-500">Run the parsers to see which one is selected and what it extracts.</div>}
      </div>
    </div>
  );
}

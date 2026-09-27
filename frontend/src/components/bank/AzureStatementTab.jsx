import React, { useEffect, useRef, useState } from "react";
import { api, formatApiError, inr } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import { FilePdf, Cloud, Check, PaperPlaneTilt, PencilSimple } from "@phosphor-icons/react";
import { fmtDate } from "@/lib/bankInbox";
import { DirectionBadge } from "./ConfidenceBadge";

const STATUS_CLS = { MATCHED: "border-emerald-600 text-emerald-700 bg-emerald-50", WARNING: "border-amber-600 text-amber-800 bg-amber-50", FAILED: "border-red-600 text-red-700 bg-red-50" };
const money = (s) => (s == null ? "—" : inr(parseFloat(String(s).replace(/[^0-9.-]/g, ""))));

function ReconRow({ label, st, parsed, diff }) {
  const bad = diff != null && parseFloat(diff) !== 0;
  return (
    <tr className="border-t border-neutral-100" data-testid={`recon-${label.toLowerCase().replace(" ", "-")}`}>
      <td className="p-2 font-medium">{label}</td><td className="p-2 text-right font-mono-tab">{money(st)}</td>
      <td className="p-2 text-right font-mono-tab">{money(parsed)}</td>
      <td className={`p-2 text-right font-mono-tab ${bad ? "text-red-700 font-semibold" : "text-emerald-700"}`}>{diff == null ? "n/a" : money(diff)}</td>
    </tr>
  );
}

function RowEditor({ imp, row, onSaved, onClose }) {
  const [f, setF] = useState({ transaction_date: row.txn.transaction_date, direction: row.txn.direction || "debit", amount: row.txn.amount || "", narration: row.txn.narration, bank_reference: row.txn.bank_reference });
  const set = (k) => (e) => setF((x) => ({ ...x, [k]: e.target.value }));
  const save = async () => {
    try { const r = await api.put(`/bank-transactions/statement-imports/${imp.statement_import_id}/rows/${row.row}`, { ...f, amount: parseFloat(f.amount) }); toast.success("Row corrected"); onSaved(r.data); onClose(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  return (
    <tr className="bg-amber-50 border-t border-amber-200" data-testid="stmt-row-editor">
      <td colSpan={9} className="p-2">
        <div className="text-[10px] uppercase text-neutral-500 mb-1">Original extraction: {row.original?.transaction_date} · {row.original?.direction || "?"} · {row.original?.amount} · {row.original?.narration}</div>
        <div className="grid grid-cols-2 md:grid-cols-6 gap-2">
          <Input data-testid="stmt-edit-date" type="date" className="rounded-none" value={f.transaction_date} onChange={set("transaction_date")} />
          <select data-testid="stmt-edit-direction" className="rounded-none border border-neutral-300 h-9 px-2 text-sm bg-white" value={f.direction} onChange={set("direction")}><option value="debit">debit</option><option value="credit">credit</option></select>
          <Input data-testid="stmt-edit-amount" type="number" step="0.01" className="rounded-none font-mono-tab" value={f.amount} onChange={set("amount")} />
          <Input data-testid="stmt-edit-narration" className="rounded-none md:col-span-2" value={f.narration} onChange={set("narration")} />
          <Input data-testid="stmt-edit-reference" className="rounded-none font-mono-tab" value={f.bank_reference} onChange={set("bank_reference")} />
        </div>
        <div className="flex justify-end gap-2 mt-2"><Button size="sm" variant="outline" className="rounded-none" onClick={onClose}>Cancel</Button><Button data-testid="stmt-edit-save" size="sm" className="rounded-none bg-neutral-900" onClick={save}><Check size={14} className="mr-1" /> Save correction</Button></div>
      </td>
    </tr>
  );
}

export default function AzureStatementTab({ onSent }) {
  const [file, setFile] = useState(null);
  const [bank, setBank] = useState("");
  const [busy, setBusy] = useState(false);
  const [imp, setImp] = useState(null);
  const [prev, setPrev] = useState(null);
  const [status, setStatus] = useState(null);
  const [editing, setEditing] = useState(null);
  const [sel, setSel] = useState(new Set());
  const [sendRes, setSendRes] = useState(null);
  const ref = useRef(null);
  useEffect(() => { api.get("/bank-transactions/statement-imports/azure/status").then((r) => setStatus(r.data)).catch(() => {}); }, []);
  useEffect(() => { if (imp) setSel(new Set(imp.rows.filter((r) => r.status === "valid").map((r) => r.row))); }, [imp]);

  const analyze = async () => {
    setBusy(true); setPrev(null); setSendRes(null);
    try {
      const fd = new FormData(); fd.append("file", file); fd.append("bank_name", bank); fd.append("provider", "auto");
      const r = await api.post("/bank-transactions/statement-imports/analyze", fd);
      if (r.data.previously_analyzed) { setPrev(r.data.previous); toast.warning(r.data.message); } else { setImp(r.data); toast.success(`Analyzed ${r.data.transactions_detected} transactions`); }
    } catch (e) { const d = e.response?.data?.detail; toast.error(typeof d === "object" ? d.message : formatApiError(d)); }
    finally { setBusy(false); }
  };
  const viewPrev = async () => { const r = await api.get(`/bank-transactions/statement-imports/${prev.statement_import_id}`); setImp(r.data); setPrev(null); };
  const testAzure = async () => { try { const r = await api.post("/bank-transactions/statement-imports/azure/test"); toast[r.data.reachable ? "success" : "warning"](r.data.message); } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); } };
  const send = async () => {
    if (!window.confirm(`Send ${sel.size} valid transaction(s) to the Bank Inbox as PENDING? No Finance transactions will be created.`)) return;
    setBusy(true);
    try {
      const r = await api.post(`/bank-transactions/statement-imports/${imp.statement_import_id}/send`, { rows: [...sel] });
      setSendRes({ ...r.data, running: true });
      let cur = r.data;
      for (let i = 0; i < 400; i++) {
        await new Promise((res) => setTimeout(res, 2500));
        const d = (await api.get(`/bank-transactions/statement-imports/${imp.statement_import_id}`)).data;
        cur = d.send_progress || cur; setSendRes({ ...cur, running: d.processing_status === "sending" }); setImp(d);
        if (d.processing_status !== "sending") break;
      }
      toast.success(`${cur.sent} sent to inbox, ${cur.duplicates} duplicates`); onSent?.();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail) || "Send failed — check Pending inbox and retry"); setSendRes((s) => (s ? { ...s, running: false, error: true } : { error: true, sent: 0, duplicates: 0, skipped: [] })); }
    finally { setBusy(false); }
  };
  const exportReview = () => {
    const lines = [["Row", "Date", "Direction", "Amount", "Balance", "Narration", "Reference", "Confidence", "Status"].join(",")].concat(imp.rows.map((r) => [r.row, r.txn.transaction_date, r.txn.direction, r.txn.amount, r.running_balance ?? "", `"${(r.txn.narration || "").replace(/"/g, "'")}"`, r.txn.bank_reference, r.confidence_band, r.status].join(",")));
    const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" })); a.download = `statement-review-${imp.statement_import_id}.csv`; a.click(); URL.revokeObjectURL(a.href);
  };
  const rec = imp?.reconciliation;

  return (
    <div className="space-y-4" data-testid="azure-statement-tab">
      <div className="bg-white border border-neutral-200 p-4 grid grid-cols-1 md:grid-cols-4 gap-3 items-end">
        <div><div className="text-[10px] uppercase tracking-wider text-neutral-500">Bank</div><Input data-testid="az-bank" className="rounded-none mt-1" placeholder="Auto Detect" value={bank} onChange={(e) => setBank(e.target.value)} /></div>
        <div><div className="text-[10px] uppercase tracking-wider text-neutral-500">Statement file (PDF)</div>
          <input ref={ref} data-testid="az-file-input" type="file" accept="application/pdf,.pdf" className="hidden" onChange={(e) => { setFile(e.target.files?.[0] || null); setImp(null); setPrev(null); }} />
          <Button data-testid="az-choose-btn" variant="outline" className="rounded-none mt-1 w-full justify-start" onClick={() => ref.current?.click()}><FilePdf size={16} className="mr-1" /> {file ? file.name : "Choose PDF"}</Button></div>
        <div><div className="text-[10px] uppercase tracking-wider text-neutral-500">Extraction engine</div>
          <div className="mt-1 h-9 border border-neutral-300 px-2 flex items-center text-sm gap-2" data-testid="az-engine"><Cloud size={14} /> {status?.configured ? "Azure Document Intelligence" : `Local fallback (Azure ${status ? "not configured" : "…"})`}</div></div>
        <Button data-testid="az-analyze-btn" disabled={!file || busy} className="rounded-none bg-neutral-900 hover:bg-neutral-700" onClick={analyze}>{busy ? "Analyzing…" : "Analyze Statement"}</Button>
        <div className="md:col-span-4 text-xs text-neutral-600 flex items-center gap-3 flex-wrap" data-testid="az-diagnostics">
          <span>Azure configured: <b>{status?.configured ? "Yes" : "No"}</b></span><span>Key present: <b>{status?.key_present ? "Yes" : "No"}</b></span><span>Endpoint: <span className="font-mono-tab">{status?.endpoint_host || "—"}</span></span><span>Model: <span className="font-mono-tab">{status?.model_id}</span></span><span>Max upload: {status?.max_upload_mb} MB</span>
          <Button data-testid="az-test-btn" size="sm" variant="outline" className="rounded-none" onClick={testAzure}>Test Azure Connection</Button>
        </div>
      </div>

      {prev && <div className="bg-white border border-amber-500 border-l-4 p-3 text-sm flex items-center justify-between" data-testid="az-previous"><span>Statement previously analyzed/imported on {new Date(prev.created_at).toLocaleString("en-IN")} ({prev.transactions_detected} transactions, {prev.reconciliation_status}).</span><Button data-testid="az-view-previous" size="sm" variant="outline" className="rounded-none" onClick={viewPrev}>View Previous Analysis</Button></div>}

      {imp && (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="bg-white border border-neutral-200 p-4" data-testid="az-summary">
              <div className="text-[10px] uppercase tracking-[0.2em] text-neutral-500 mb-2">Bank statement analysis</div>
              <dl className="grid grid-cols-2 gap-y-1 text-sm">
                <dt className="text-neutral-500">Bank</dt><dd data-testid="az-bank-name">{imp.bank_name}</dd>
                <dt className="text-neutral-500">Statement account</dt><dd className="font-mono-tab">{imp.statement_account_masked || "—"}</dd>
                <dt className="text-neutral-500">Period</dt><dd>{fmtDate(imp.statement_period_from) || "?"} → {fmtDate(imp.statement_period_to) || "?"}</dd>
                <dt className="text-neutral-500">Pages</dt><dd>{imp.page_count}</dd>
                <dt className="text-neutral-500">Provider</dt><dd className="font-mono-tab text-xs">{imp.extraction_provider} / {imp.model_id}</dd>
                <dt className="text-neutral-500">Transactions</dt><dd data-testid="az-counts">{imp.transactions_detected} detected · {imp.transactions_valid} valid · {imp.transactions_ambiguous} needs review · {imp.transactions_duplicate} duplicate</dd>
              </dl>
            </div>
            <div className="bg-white border border-neutral-200 p-4" data-testid="az-reconciliation">
              <div className="flex items-center justify-between mb-2"><div className="text-[10px] uppercase tracking-[0.2em] text-neutral-500">Statement reconciliation</div><span data-testid="az-recon-status" className={`text-[10px] uppercase tracking-wider px-2 py-0.5 border ${STATUS_CLS[rec?.status] || ""}`}>{rec?.status}</span></div>
              <table className="w-full text-xs"><thead className="text-[10px] uppercase text-neutral-500"><tr><th></th><th className="text-right p-2">Statement</th><th className="text-right p-2">Parsed</th><th className="text-right p-2">Difference</th></tr></thead>
                <tbody><ReconRow label="Debit" st={rec?.statement_debit_total} parsed={rec?.parsed_debit_total} diff={rec?.debit_difference} /><ReconRow label="Credit" st={rec?.statement_credit_total} parsed={rec?.parsed_credit_total} diff={rec?.credit_difference} /><ReconRow label="Closing Balance" st={rec?.statement_closing_balance_value} parsed={rec?.parsed_closing_balance} diff={rec?.closing_balance_difference} /></tbody></table>
              <div className={`mt-2 text-xs p-2 border ${STATUS_CLS[rec?.status] || ""}`} data-testid="az-recon-message">{rec?.status === "MATCHED" ? "Statement reconciliation successful." : "RECONCILIATION WARNING — "}{rec?.status !== "MATCHED" && rec?.messages.join(" · ")}{rec?.ambiguous_rows ? ` · Ambiguous rows: ${rec.ambiguous_rows}` : ""}</div>
            </div>
          </div>

          <div className="bg-white border border-neutral-200">
            <div className="p-2 flex items-center justify-between flex-wrap gap-2 border-b border-neutral-200">
              <div className="text-xs text-neutral-600" data-testid="az-selection">Detected {imp.transactions_detected} · Valid {imp.transactions_valid} · Needs Review {imp.transactions_ambiguous} · Duplicates {imp.transactions_duplicate} · <b>Selected {sel.size}</b></div>
              <div className="flex gap-2"><Button data-testid="az-export-btn" size="sm" variant="outline" className="rounded-none" onClick={exportReview}>Export Review</Button>
                <Button data-testid="az-send-btn" size="sm" className="rounded-none bg-emerald-700 hover:bg-emerald-600" disabled={busy || !sel.size || imp.processing_status !== "analyzed"} title={imp.processing_status !== "analyzed" ? `Statement already ${imp.processing_status}` : ""} onClick={send}><PaperPlaneTilt size={14} className="mr-1" /> Send Valid Transactions to Bank Inbox ({sel.size})</Button></div>
            </div>
            <div className="max-h-[520px] overflow-auto">
              <table className="w-full text-xs" data-testid="az-rows-table">
                <thead className="bg-neutral-50 text-[10px] uppercase tracking-wider text-neutral-500 sticky top-0"><tr><th className="p-2"></th><th className="p-2 text-left">Date</th><th className="p-2 text-left">Dir</th><th className="p-2 text-right">Amount</th><th className="p-2 text-right">Balance</th><th className="p-2 text-left">Particulars</th><th className="p-2 text-left">Reference</th><th className="p-2 text-left">Confidence</th><th className="p-2 text-left">Status</th></tr></thead>
                <tbody>
                  {imp.rows.map((r) => editing === r.row ? <RowEditor key={r.row} imp={imp} row={r} onSaved={setImp} onClose={() => setEditing(null)} /> : (
                    <tr key={r.row} className={`border-t border-neutral-100 ${r.status === "needs_review" ? "bg-amber-50" : r.status === "duplicate" ? "bg-neutral-50 text-neutral-500" : ""}`} data-testid={`az-row-${r.row}`}>
                      <td className="p-2">{r.status === "valid" && <input type="checkbox" data-testid="az-row-select" checked={sel.has(r.row)} onChange={() => setSel((s) => { const n = new Set(s); n.has(r.row) ? n.delete(r.row) : n.add(r.row); return n; })} />}</td>
                      <td className="p-2 font-mono-tab">{fmtDate(r.txn.transaction_date) || "—"}</td>
                      <td className="p-2">{r.txn.direction ? <DirectionBadge direction={r.txn.direction} /> : "—"}</td>
                      <td className="p-2 text-right font-mono-tab">{r.txn.amount ? inr(r.txn.amount) : "—"}</td>
                      <td className="p-2 text-right font-mono-tab text-neutral-500">{r.running_balance != null ? `${inr(r.running_balance)} ${r.balance_direction || ""}` : "—"}</td>
                      <td className="p-2 max-w-[320px] truncate" title={r.txn.narration}>{r.txn.narration}</td>
                      <td className="p-2 font-mono-tab">{r.txn.bank_reference}</td>
                      <td className="p-2" data-testid="az-row-confidence">{r.confidence_band}{r.extraction_confidence != null ? ` (${Math.round(r.extraction_confidence * 100)}%)` : ""}</td>
                      <td className="p-2 whitespace-nowrap"><span data-testid="az-row-status" className={r.status === "needs_review" ? "text-amber-800" : r.status === "duplicate" ? "text-red-700" : r.status === "sent" ? "text-blue-700" : "text-emerald-700"}>{r.status === "needs_review" ? `Needs Review: ${r.errors.join("; ")}` : r.status === "duplicate" ? `Duplicate${r.duplicate_of_bank_transaction_id ? " of " + r.duplicate_of_bank_transaction_id.slice(-6) : r.duplicate_of_row ? " of row " + r.duplicate_of_row : ""}` : r.status}</span>
                        {imp.processing_status === "analyzed" && r.status !== "sent" && <button data-testid="az-row-edit" className="ml-2 text-neutral-500 hover:text-neutral-900" onClick={() => setEditing(r.row)}><PencilSimple size={12} /></button>}</td>
                    </tr>))}
                </tbody>
              </table>
            </div>
          </div>
          {sendRes && <div className={`bg-white border border-l-4 p-3 text-sm ${sendRes.error ? "border-red-600" : sendRes.running ? "border-amber-500" : "border-emerald-600"}`} data-testid="az-send-result">
            {sendRes.error ? "Send did not complete — some rows may already be in the Pending inbox; re-open this analysis to see per-row status." : sendRes.running ? `Sending… ${sendRes.done ?? 0} / ${sendRes.total ?? sel.size} processed (${sendRes.sent ?? 0} pending, ${sendRes.duplicates ?? 0} duplicates)` : `Sent ${sendRes.sent} to Bank Inbox (Pending approval), ${sendRes.duplicates} resolved as duplicates, ${(sendRes.skipped || []).length} skipped. No Finance transactions were created.`}
          </div>}
        </>
      )}
    </div>
  );
}

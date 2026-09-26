import React, { useRef, useState } from "react";
import { api, formatApiError, inr } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { UploadSimple, FileCsv, CheckCircle, WarningCircle } from "@phosphor-icons/react";
import { DirectionBadge } from "./ConfidenceBadge";
import { fmtDate } from "@/lib/bankInbox";

const FIELDS = ["date", "narration", "debit", "credit", "amount", "direction", "reference"];
const sel = "rounded-none border border-neutral-300 h-8 px-1 text-xs bg-white w-full";

export default function StatementImportTab({ onImported }) {
  const [file, setFile] = useState(null);
  const [bank, setBank] = useState("");
  const [acct, setAcct] = useState("");
  const [preview, setPreview] = useState(null);
  const [mapping, setMapping] = useState({});
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const ref = useRef(null);

  const fd = (extra = {}) => {
    const f = new FormData();
    f.append("file", file); f.append("bank_name", bank); f.append("bank_account", acct);
    f.append("mapping", JSON.stringify(mapping));
    Object.entries(extra).forEach(([k, v]) => f.append(k, v));
    return f;
  };

  const doPreview = async (m = mapping) => {
    if (!file) return;
    setBusy(true); setResult(null);
    try {
      const f = fd(); f.set("mapping", JSON.stringify(m));
      const r = await api.post("/bank-transactions/statement/preview", f);
      setPreview(r.data); setMapping(r.data.mapping); if (!bank) setBank(r.data.bank_name);
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  const doImport = async () => {
    setBusy(true);
    try {
      const r = await api.post("/bank-transactions/statement/import", fd({ skip_ingested: "true" }));
      setResult(r.data);
      toast.success(`Ingested ${r.data.ingested} rows (${r.data.pending} pending, ${r.data.duplicates} duplicates)`);
      onImported?.();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  return (
    <div className="space-y-4" data-testid="statement-import-tab">
      <div className="bg-white border border-neutral-200 p-4 grid grid-cols-1 md:grid-cols-4 gap-3 items-end">
        <div className="md:col-span-2">
          <Label className="text-[10px] uppercase tracking-wider text-neutral-500">Statement CSV (ICICI / HDFC / Saraswat / any)</Label>
          <div className="mt-1 flex gap-2">
            <input ref={ref} data-testid="statement-file-input" type="file" accept=".csv,text/csv" className="hidden" onChange={(e) => { setFile(e.target.files?.[0] || null); setPreview(null); setResult(null); setMapping({}); }} />
            <Button data-testid="statement-choose-btn" variant="outline" className="rounded-none" onClick={() => ref.current?.click()}><FileCsv size={16} className="mr-1" /> {file ? file.name : "Choose file"}</Button>
            <Button data-testid="statement-preview-btn" disabled={!file || busy} className="rounded-none bg-neutral-900 hover:bg-neutral-700" onClick={() => doPreview({})}><UploadSimple size={16} className="mr-1" /> Preview</Button>
          </div>
        </div>
        <div><Label className="text-[10px] uppercase tracking-wider text-neutral-500">Bank (auto-detected if blank)</Label><Input data-testid="statement-bank" className="rounded-none mt-1" value={bank} onChange={(e) => setBank(e.target.value)} /></div>
        <div><Label className="text-[10px] uppercase tracking-wider text-neutral-500">Bank account (masked in UI)</Label><Input data-testid="statement-account" className="rounded-none mt-1 font-mono-tab" value={acct} onChange={(e) => setAcct(e.target.value)} /></div>
      </div>

      {preview && (
        <>
          <div className="bg-white border border-neutral-200 p-4">
            <div className="text-[10px] uppercase tracking-[0.2em] text-neutral-500 mb-2">Column mapping · detected bank: <span className="text-neutral-900">{preview.bank_name}</span></div>
            <div className="grid grid-cols-2 md:grid-cols-7 gap-2" data-testid="statement-mapping">
              {FIELDS.map((f) => (
                <div key={f}>
                  <div className="text-[10px] uppercase text-neutral-500">{f}</div>
                  <select data-testid={`map-${f}`} className={sel} value={mapping[f] || ""} onChange={(e) => setMapping({ ...mapping, [f]: e.target.value })}>
                    <option value="">—</option>{preview.headers.map((h) => <option key={h} value={h}>{h}</option>)}
                  </select>
                </div>
              ))}
            </div>
            <div className="flex items-center justify-between mt-3">
              <div className="text-xs text-neutral-600 flex gap-4" data-testid="statement-summary">
                <span><CheckCircle size={14} className="inline text-emerald-600" /> {preview.valid} valid</span>
                <span><WarningCircle size={14} className="inline text-red-600" /> {preview.invalid} invalid</span>
                <span>{preview.already_ingested} already in inbox (skipped)</span>
                <span>{preview.total} rows</span>
              </div>
              <div className="flex gap-2">
                <Button data-testid="statement-remap-btn" variant="outline" className="rounded-none" disabled={busy} onClick={() => doPreview(mapping)}>Re-apply mapping</Button>
                <Button data-testid="statement-import-btn" disabled={busy || preview.valid - preview.already_ingested <= 0} className="rounded-none bg-emerald-700 hover:bg-emerald-600" onClick={doImport}>Import {preview.valid - preview.already_ingested} rows to Inbox</Button>
              </div>
            </div>
          </div>
          <div className="bg-white border border-neutral-200 overflow-auto max-h-[420px]">
            <table className="w-full text-xs" data-testid="statement-preview-table">
              <thead className="bg-neutral-50 text-[10px] uppercase tracking-wider text-neutral-500 sticky top-0">
                <tr><th className="p-2 text-left">#</th><th className="p-2 text-left">Date</th><th className="p-2 text-left">Dir</th><th className="p-2 text-right">Amount</th><th className="p-2 text-left">Narration</th><th className="p-2 text-left">Ref</th><th className="p-2 text-left">Status</th></tr>
              </thead>
              <tbody>
                {preview.rows.map((r) => (
                  <tr key={r.row} className={`border-t border-neutral-100 ${r.errors.length ? "bg-red-50" : r.already_ingested ? "opacity-50" : ""}`} data-testid="statement-row">
                    <td className="p-2 font-mono-tab">{r.row}</td>
                    <td className="p-2 font-mono-tab">{fmtDate(r.txn.transaction_date) || "—"}</td>
                    <td className="p-2">{r.txn.direction ? <DirectionBadge direction={r.txn.direction} /> : "—"}</td>
                    <td className="p-2 text-right font-mono-tab">{inr(r.txn.amount)}</td>
                    <td className="p-2 max-w-[320px] truncate" title={r.txn.narration}>{r.txn.narration}</td>
                    <td className="p-2 font-mono-tab">{r.txn.bank_reference}</td>
                    <td className="p-2">{r.errors.length ? <span className="text-red-700">{r.errors.join(", ")}</span> : r.already_ingested ? "already ingested" : <span className="text-emerald-700">ready</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {result && (
        <div className="bg-white border border-emerald-600 border-l-4 p-4 text-sm" data-testid="statement-result">
          Imported <b>{result.ingested}</b> of {result.total} rows from {result.bank_name}: {result.pending} pending review, {result.duplicates} duplicates, {result.invalid} invalid, {result.skipped_already_ingested} skipped. Switch to <b>Pending</b> to review suggestions.
        </div>
      )}
    </div>
  );
}

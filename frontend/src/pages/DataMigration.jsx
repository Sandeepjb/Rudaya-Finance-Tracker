import React, { useCallback, useEffect, useRef, useState } from "react";
import Layout from "@/components/Layout";
import { api, inr, formatApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { toast } from "sonner";
import {
  UploadSimple, FileCsv, CheckCircle, WarningCircle, ShieldWarning, ArrowsClockwise,
  Copy, ArrowLeft, ArrowRight, Prohibit,
} from "@phosphor-icons/react";

const TEMPLATE = "date,type,account,amount,project_id,notes\n2026-04-15,Revenue,Sales - Solar,250000,PRJ-01,April invoice\n15/04/2026,Cost,Materials,50000,PRJ-01,Panels\n15-04-2026,Expense,Travel,3200,PRJ-01,Site visit\n";

function StepChip({ n, label, active, done }) {
  const style = done
    ? "bg-emerald-600 text-white border-emerald-600"
    : active
    ? "bg-neutral-900 text-white border-neutral-900"
    : "bg-white text-neutral-500 border-neutral-300";
  return (
    <div className="flex items-center gap-2">
      <div className={`w-7 h-7 border font-mono-tab text-xs flex items-center justify-center ${style}`}>{done ? "✓" : n}</div>
      <div className={`text-xs uppercase tracking-[0.2em] ${active || done ? "text-neutral-900" : "text-neutral-500"}`}>{label}</div>
    </div>
  );
}

export default function DataMigration() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [step, setStep] = useState(1);
  const [file, setFile] = useState(null);
  const [previewing, setPreviewing] = useState(false);
  const [preview, setPreview] = useState(null);
  const [mode, setMode] = useState("skip_duplicates");
  const [importing, setImporting] = useState(false);
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState([]);
  const [showInvalidOnly, setShowInvalidOnly] = useState(false);
  const fileRef = useRef(null);

  const loadHistory = useCallback(async () => {
    if (!isAdmin) return;
    try {
      const r = await api.get("/migrations/history");
      setHistory(r.data);
    } catch { /* ignore */ }
  }, [isAdmin]);

  useEffect(() => { loadHistory(); }, [loadHistory]);

  const onPick = (f) => {
    if (!f) return;
    if (!/\.csv$/i.test(f.name)) {
      toast.error("Please pick a .csv file");
      return;
    }
    setFile(f);
    setPreview(null);
    setResult(null);
  };

  const runPreview = async () => {
    if (!file) return;
    setPreviewing(true);
    setResult(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await api.post("/migrations/preview", fd, { headers: { "Content-Type": "multipart/form-data" } });
      setPreview(r.data);
      setStep(2);
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    } finally {
      setPreviewing(false);
    }
  };

  const runImport = async () => {
    if (!file || !preview) return;
    const willReplace = mode === "replace_existing";
    const confirmMsg = willReplace
      ? `REPLACE MODE\n\nThis will backup all existing transactions to 'transaction_import_backups' and then delete the transactions collection before importing ${preview.valid_rows} rows.\n\nContinue?`
      : `Import ${preview.valid_rows - preview.duplicates} new transactions? (${preview.duplicates} duplicate(s) will be skipped)`;
    if (!window.confirm(confirmMsg)) return;
    setImporting(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("mode", mode);
      const r = await api.post("/migrations/import", fd, { headers: { "Content-Type": "multipart/form-data" } });
      setResult(r.data);
      setStep(3);
      loadHistory();
      toast.success(`Imported ${r.data.inserted} transactions`);
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    } finally {
      setImporting(false);
    }
  };

  const reset = () => {
    setFile(null);
    setPreview(null);
    setResult(null);
    setMode("skip_duplicates");
    setShowInvalidOnly(false);
    setStep(1);
    if (fileRef.current) fileRef.current.value = "";
  };

  const copyTemplate = async () => {
    try {
      await navigator.clipboard.writeText(TEMPLATE);
      toast.success("Template copied");
    } catch { toast.error("Copy failed"); }
  };

  if (!isAdmin) {
    return (
      <Layout title="Data Migration" subtitle="Administration">
        <div className="rudaya-card p-10 flex flex-col items-center text-center max-w-lg mx-auto" data-testid="migration-admin-only">
          <Prohibit size={48} className="text-red-600 mb-3" />
          <h2 className="font-heading font-bold text-xl mb-2">Admin only</h2>
          <p className="text-sm text-neutral-600">This module is restricted to administrators. Contact your workspace owner if you need access.</p>
        </div>
      </Layout>
    );
  }

  const rowsToShow = preview
    ? (showInvalidOnly ? preview.rows.filter((r) => !r.valid) : preview.rows).slice(0, 500)
    : [];

  return (
    <Layout
      title="Data Migration"
      subtitle="Administration · Import Transactions from CSV"
      actions={
        <Button data-testid="download-template-btn" variant="outline" className="rounded-none" onClick={copyTemplate}>
          <Copy size={16} className="mr-2" /> Copy CSV template
        </Button>
      }
    >
      {/* Stepper */}
      <div className="flex items-center gap-6 mb-6" data-testid="migration-stepper">
        <StepChip n={1} label="Upload & Preview" active={step === 1} done={step > 1} />
        <div className="flex-1 h-px bg-neutral-300" />
        <StepChip n={2} label="Choose Mode & Import" active={step === 2} done={step > 2} />
        <div className="flex-1 h-px bg-neutral-300" />
        <StepChip n={3} label="Result" active={step === 3} done={false} />
      </div>

      {/* Step 1 — Upload */}
      {step === 1 && (
        <div className="rudaya-card p-8">
          <div className="max-w-2xl">
            <h3 className="font-heading font-semibold text-lg mb-2">Upload a CSV of transactions</h3>
            <p className="text-sm text-neutral-600 mb-6">
              Required headers (exact, case-insensitive):&nbsp;
              <code className="bg-neutral-100 px-1.5 py-0.5 text-xs">date, type, account, amount, project_id, notes</code>.
              Dates accepted in <b>YYYY-MM-DD</b>, <b>DD/MM/YYYY</b>, or <b>DD-MM-YYYY</b>.
              Type must be Revenue, Cost, or Expense. Amount must be a positive number.
            </p>
            <label
              className="block border-2 border-dashed border-neutral-300 hover:border-neutral-900 hover:bg-neutral-50 transition-colors p-10 text-center cursor-pointer"
              data-testid="csv-dropzone"
            >
              <input
                ref={fileRef}
                type="file"
                accept=".csv"
                className="hidden"
                onChange={(e) => onPick(e.target.files?.[0])}
                data-testid="csv-file-input"
              />
              {file ? (
                <div className="flex flex-col items-center gap-2">
                  <FileCsv size={40} className="text-neutral-900" />
                  <div className="font-medium text-sm">{file.name}</div>
                  <div className="text-xs text-neutral-500">{(file.size / 1024).toFixed(1)} KB · Click to change</div>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-2 text-neutral-500">
                  <UploadSimple size={40} />
                  <div className="text-sm">Click to select a CSV file</div>
                  <div className="text-xs">or drag and drop (browser picker)</div>
                </div>
              )}
            </label>

            <div className="flex justify-end mt-6">
              <Button
                data-testid="csv-preview-btn"
                onClick={runPreview}
                disabled={!file || previewing}
                className="rounded-none bg-neutral-900 hover:bg-neutral-700 h-11 px-6"
              >
                {previewing ? "Validating…" : "Validate & Preview"} <ArrowRight size={16} className="ml-2" />
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Step 2 — Preview */}
      {step === 2 && preview && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-4">
            <SummaryTile testid="tile-total" label="Total rows" value={preview.total_rows} />
            <SummaryTile testid="tile-valid" label="Valid" value={preview.valid_rows} tone="emerald" />
            <SummaryTile testid="tile-invalid" label="Invalid" value={preview.invalid_rows} tone={preview.invalid_rows ? "red" : undefined} />
            <SummaryTile testid="tile-duplicates" label="Duplicates" value={preview.duplicates} tone={preview.duplicates ? "amber" : undefined} />
            <SummaryTile testid="tile-net-new" label="Net new" value={Math.max(0, preview.valid_rows - preview.duplicates)} tone="emerald" />
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-6">
            {["Revenue", "Cost", "Expense"].map((t) => (
              <div key={t} className="rudaya-card p-4" data-testid={`type-summary-${t.toLowerCase()}`}>
                <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500">{t}</div>
                <div className="mt-1 flex items-baseline justify-between">
                  <div className="font-mono-tab font-semibold text-xl">{inr(preview.by_type[t].total)}</div>
                  <div className="text-xs text-neutral-500">{preview.by_type[t].count} rows</div>
                </div>
              </div>
            ))}
          </div>

          <div className="rudaya-card overflow-hidden">
            <div className="px-5 py-4 border-b border-neutral-200 flex items-center justify-between">
              <div>
                <h3 className="font-heading font-semibold text-lg">Row-by-row preview</h3>
                <p className="text-xs text-neutral-500 mt-0.5">First 500 rows shown · scroll horizontally for full data</p>
              </div>
              <label className="text-xs flex items-center gap-2 cursor-pointer" data-testid="show-invalid-toggle">
                <input type="checkbox" checked={showInvalidOnly} onChange={(e) => setShowInvalidOnly(e.target.checked)} />
                Show invalid only
              </label>
            </div>
            <div className="overflow-x-auto rudaya-scroll max-h-[420px]">
              <table className="w-full min-w-[900px]" data-testid="preview-table">
                <thead className="bg-neutral-50 border-b border-neutral-200 sticky top-0">
                  <tr className="text-left text-[11px] uppercase tracking-wider text-neutral-500">
                    <th className="px-3 py-2 w-12">#</th>
                    <th className="px-3 py-2 w-24">Status</th>
                    <th className="px-3 py-2">Date</th>
                    <th className="px-3 py-2">Type</th>
                    <th className="px-3 py-2">Account</th>
                    <th className="px-3 py-2 text-right">Amount</th>
                    <th className="px-3 py-2">Project</th>
                    <th className="px-3 py-2">Notes / Errors</th>
                  </tr>
                </thead>
                <tbody>
                  {rowsToShow.map((r) => {
                    const rowClass = !r.valid ? "bg-red-50" : r.duplicate ? "bg-amber-50" : "";
                    let statusLabel; let statusStyle;
                    if (!r.valid) { statusLabel = "Invalid"; statusStyle = "bg-red-100 text-red-700 border-red-300"; }
                    else if (r.duplicate) { statusLabel = "Duplicate"; statusStyle = "bg-amber-100 text-amber-700 border-amber-300"; }
                    else { statusLabel = "OK"; statusStyle = "bg-emerald-100 text-emerald-700 border-emerald-300"; }
                    return (
                      <tr key={r.row_number} className={`border-b border-neutral-100 ${rowClass}`} data-testid={`preview-row-${r.row_number}`}>
                        <td className="px-3 py-2 text-xs font-mono-tab text-neutral-500">{r.row_number}</td>
                        <td className="px-3 py-2">
                          <span className={`inline-block text-[10px] uppercase tracking-wider px-2 py-0.5 border ${statusStyle}`}>{statusLabel}</span>
                        </td>
                        <td className="px-3 py-2 text-xs">{r.parsed?.date || r.raw.date}</td>
                        <td className="px-3 py-2 text-xs">{r.parsed?.type || r.raw.type}</td>
                        <td className="px-3 py-2 text-xs">{r.raw.account}</td>
                        <td className="px-3 py-2 text-xs text-right font-mono-tab">{r.parsed ? inr(r.parsed.amount) : r.raw.amount}</td>
                        <td className="px-3 py-2 text-xs">{r.raw.project_id}</td>
                        <td className="px-3 py-2 text-xs text-neutral-600">
                          {r.errors.length ? <span className="text-red-700">{r.errors.join("; ")}</span> : r.raw.notes}
                        </td>
                      </tr>
                    );
                  })}
                  {rowsToShow.length === 0 && (
                    <tr><td colSpan="8" className="px-4 py-10 text-center text-neutral-500 text-sm">No rows to show.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Import controls */}
          <div className="rudaya-card p-6 mt-6">
            <h3 className="font-heading font-semibold text-lg mb-4">Choose import mode</h3>
            <RadioGroup value={mode} onValueChange={setMode} className="space-y-3" data-testid="mode-radio">
              <div className="flex items-start gap-3 border border-neutral-200 p-4 hover:border-neutral-400 cursor-pointer" onClick={() => setMode("skip_duplicates")}>
                <RadioGroupItem value="skip_duplicates" id="mode-skip" className="mt-1" data-testid="mode-skip-duplicates" />
                <div>
                  <Label htmlFor="mode-skip" className="text-sm font-semibold cursor-pointer">Skip duplicates (recommended)</Label>
                  <p className="text-xs text-neutral-500 mt-1">
                    Keeps everything currently in the transactions collection and appends only rows whose fingerprint (date · type · account · amount · project_id · notes) does not already exist.
                  </p>
                </div>
              </div>
              <div className="flex items-start gap-3 border border-neutral-200 p-4 hover:border-red-400 cursor-pointer" onClick={() => setMode("replace_existing")}>
                <RadioGroupItem value="replace_existing" id="mode-replace" className="mt-1" data-testid="mode-replace-existing" />
                <div>
                  <Label htmlFor="mode-replace" className="text-sm font-semibold cursor-pointer flex items-center gap-2">
                    <ShieldWarning size={16} className="text-red-600" />
                    Replace existing (destructive)
                  </Label>
                  <p className="text-xs text-neutral-500 mt-1">
                    Backs up every existing transaction into <code>transaction_import_backups</code> with a timestamp, then <b>deletes the transactions collection</b> and imports these rows fresh. Only affects transactions — quotations, forecasts, budgets are untouched.
                  </p>
                </div>
              </div>
            </RadioGroup>

            <div className="flex justify-between mt-6">
              <Button data-testid="preview-back-btn" variant="outline" className="rounded-none" onClick={() => setStep(1)}>
                <ArrowLeft size={16} className="mr-2" /> Back
              </Button>
              <Button
                data-testid="run-import-btn"
                onClick={runImport}
                disabled={importing || preview.valid_rows === 0}
                className={`rounded-none h-11 px-6 ${mode === "replace_existing" ? "bg-red-700 hover:bg-red-800" : "bg-neutral-900 hover:bg-neutral-700"}`}
              >
                {importing ? "Importing…" : (mode === "replace_existing" ? "Backup & Replace" : `Import ${Math.max(0, preview.valid_rows - preview.duplicates)} rows`)}
              </Button>
            </div>
          </div>
        </>
      )}

      {/* Step 3 — Result */}
      {step === 3 && result && (
        <div className="rudaya-card p-8 max-w-2xl mx-auto text-center" data-testid="import-result">
          <CheckCircle size={56} className="text-emerald-600 mx-auto mb-3" />
          <h3 className="font-heading font-bold text-2xl mb-1">Import complete</h3>
          <p className="text-sm text-neutral-500 mb-6">Mode: <b>{result.mode.replace("_", " ")}</b></p>
          <div className="grid grid-cols-2 gap-3 mb-6">
            <SummaryTile testid="result-inserted" label="Inserted" value={result.inserted} tone="emerald" />
            <SummaryTile testid="result-skipped" label="Skipped (duplicate)" value={result.skipped_duplicate} tone="amber" />
            <SummaryTile testid="result-invalid" label="Invalid (ignored)" value={result.invalid_rows} tone={result.invalid_rows ? "red" : undefined} />
            <SummaryTile testid="result-backup" label={result.backup ? `Backed up (${result.backup.stamp})` : "Backup"} value={result.backup ? result.backup.count : 0} />
          </div>
          <Button data-testid="import-another-btn" onClick={reset} className="rounded-none bg-neutral-900 hover:bg-neutral-700">
            <ArrowsClockwise size={16} className="mr-2" /> Import another file
          </Button>
        </div>
      )}

      {/* History */}
      <div className="rudaya-card mt-8 overflow-hidden">
        <div className="px-5 py-4 border-b border-neutral-200">
          <h3 className="font-heading font-semibold text-lg">Import history</h3>
          <p className="text-xs text-neutral-500 mt-0.5">Last 50 imports · audit trail is retained in <code>import_history</code>.</p>
        </div>
        <div className="overflow-x-auto rudaya-scroll">
          <table className="w-full min-w-[800px]" data-testid="history-table">
            <thead className="bg-neutral-50 border-b border-neutral-200">
              <tr className="text-left text-[11px] uppercase tracking-wider text-neutral-500">
                <th className="px-3 py-2">Completed</th>
                <th className="px-3 py-2">File</th>
                <th className="px-3 py-2">Mode</th>
                <th className="px-3 py-2">Admin</th>
                <th className="px-3 py-2 text-right">Inserted</th>
                <th className="px-3 py-2 text-right">Skipped</th>
                <th className="px-3 py-2 text-right">Invalid</th>
                <th className="px-3 py-2">Backup</th>
              </tr>
            </thead>
            <tbody>
              {history.map((h) => (
                <tr key={h.id} className="border-b border-neutral-100 hover:bg-neutral-50" data-testid={`history-row-${h.id}`}>
                  <td className="px-3 py-2 text-xs">{h.completed_at?.slice(0, 19).replace("T", " ")}</td>
                  <td className="px-3 py-2 text-xs">{h.filename}</td>
                  <td className="px-3 py-2 text-xs">{h.mode?.replace("_", " ")}</td>
                  <td className="px-3 py-2 text-xs">{h.admin_email}</td>
                  <td className="px-3 py-2 text-xs text-right font-mono-tab text-emerald-700">{h.inserted}</td>
                  <td className="px-3 py-2 text-xs text-right font-mono-tab text-amber-700">{h.skipped_duplicate}</td>
                  <td className="px-3 py-2 text-xs text-right font-mono-tab text-red-700">{h.invalid_rows}</td>
                  <td className="px-3 py-2 text-xs">{h.backup_stamp ? `${h.backup_stamp} (${h.backed_up_count})` : "—"}</td>
                </tr>
              ))}
              {history.length === 0 && (
                <tr><td colSpan="8" className="px-4 py-8 text-center text-neutral-500 text-sm">No imports yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </Layout>
  );
}

function SummaryTile({ testid, label, value, tone }) {
  const toneClass = tone === "emerald" ? "text-emerald-700"
    : tone === "amber" ? "text-amber-700"
    : tone === "red" ? "text-red-700"
    : "text-neutral-900";
  return (
    <div className="rudaya-card p-4" data-testid={testid}>
      <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500">{label}</div>
      <div className={`mt-1 font-mono-tab font-semibold text-2xl ${toneClass}`}>{value}</div>
    </div>
  );
}

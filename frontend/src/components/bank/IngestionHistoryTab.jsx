import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Copy } from "@phosphor-icons/react";
import { toast } from "sonner";

export default function IngestionHistoryTab() {
  const [rows, setRows] = useState([]);
  const [guide, setGuide] = useState(null);
  const [showGuide, setShowGuide] = useState(false);
  useEffect(() => {
    api.get("/bank-transactions/ingestion-history").then((r) => setRows(r.data)).catch(() => {});
    api.get("/bank-transactions/guide").then((r) => setGuide(r.data)).catch(() => {});
  }, []);
  const copy = (t) => { navigator.clipboard?.writeText(t); toast.success("Copied"); };

  return (
    <div className="space-y-4" data-testid="ingestion-history-tab">
      <div className="bg-white border border-neutral-200">
        <div className="p-3 border-b border-neutral-200 flex items-center justify-between">
          <span className="text-[10px] uppercase tracking-[0.2em] text-neutral-500">Power Automate / Outlook connection guide</span>
          <Button data-testid="guide-toggle" size="sm" variant="outline" className="rounded-none" onClick={() => setShowGuide((s) => !s)}>{showGuide ? "Hide" : "Show guide"}</Button>
        </div>
        {showGuide && guide && (
          <div className="p-4 text-sm space-y-3" data-testid="pa-guide">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
              <div className="border border-neutral-200 p-2 flex items-center justify-between gap-2"><span className="font-mono-tab break-all">POST {guide.email_endpoint}</span><button data-testid="copy-email-endpoint" onClick={() => copy(guide.email_endpoint)}><Copy size={14} /></button></div>
              <div className="border border-neutral-200 p-2 flex items-center justify-between gap-2"><span className="font-mono-tab break-all">POST {guide.structured_endpoint}</span><button data-testid="copy-structured-endpoint" onClick={() => copy(guide.structured_endpoint)}><Copy size={14} /></button></div>
            </div>
            <div className="text-xs text-neutral-600">Header <span className="font-mono-tab">{guide.header_name}</span> = value of <span className="font-mono-tab">{guide.key_env_var}</span> in the server .env (never shown here).</div>
            <ol className="list-decimal pl-5 space-y-1 text-neutral-800">{guide.steps.map((s, i) => <li key={i}>{s}</li>)}</ol>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              <div><div className="text-[10px] uppercase text-neutral-500 mb-1">Email alert body</div><pre className="text-[11px] bg-neutral-50 border border-neutral-200 p-2 overflow-auto">{JSON.stringify(guide.email_body_example, null, 2)}</pre></div>
              <div><div className="text-[10px] uppercase text-neutral-500 mb-1">Structured (SharePoint) body</div><pre className="text-[11px] bg-neutral-50 border border-neutral-200 p-2 overflow-auto">{JSON.stringify(guide.structured_body_example, null, 2)}</pre></div>
            </div>
            <ul className="list-disc pl-5 text-xs text-neutral-600">{guide.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
          </div>
        )}
      </div>

      <div className="bg-white border border-neutral-200">
        <table className="w-full text-sm">
          <thead className="bg-neutral-50 text-[10px] uppercase tracking-wider text-neutral-500">
            <tr><th className="text-left p-2">Timestamp</th><th className="text-left p-2">Channel</th><th className="text-left p-2">Actor</th><th className="text-left p-2">Details</th><th className="text-right p-2">Count</th><th className="text-right p-2">Pending</th><th className="text-right p-2">Duplicates</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className={`border-t border-neutral-100 ${r.failed ? "bg-red-50" : ""}`} data-testid="ingestion-row">
                <td className="p-2 font-mono-tab text-xs">{new Date(r.timestamp).toLocaleString("en-IN")}</td>
                <td className="p-2 text-xs uppercase tracking-wider">{r.channel}</td>
                <td className="p-2 text-xs">{r.actor}</td>
                <td className="p-2 text-xs text-neutral-600">{[r.bank, r.template, r.filename, (r.sources || []).join(", "), r.errors ? `FAILED: ${r.errors.join(", ")}` : null].filter(Boolean).join(" · ")}</td>
                <td className="p-2 text-right font-mono-tab">{r.count}</td>
                <td className="p-2 text-right font-mono-tab">{r.pending}</td>
                <td className="p-2 text-right font-mono-tab text-red-700">{r.duplicates}</td>
              </tr>
            ))}
            {!rows.length && <tr><td colSpan={7} className="p-6 text-center text-neutral-500 text-sm">No ingestion events yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}

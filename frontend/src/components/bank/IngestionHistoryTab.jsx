import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";

export default function IngestionHistoryTab() {
  const [rows, setRows] = useState([]);
  useEffect(() => { api.get("/bank-transactions/ingestion-history").then((r) => setRows(r.data)).catch(() => {}); }, []);
  return (
    <div className="bg-white border border-neutral-200" data-testid="ingestion-history-tab">
      <table className="w-full text-sm">
        <thead className="bg-neutral-50 text-[10px] uppercase tracking-wider text-neutral-500">
          <tr><th className="text-left p-2">Timestamp</th><th className="text-left p-2">Channel</th><th className="text-left p-2">Actor</th><th className="text-left p-2">Sources</th><th className="text-right p-2">Count</th><th className="text-right p-2">Pending</th><th className="text-right p-2">Duplicates</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="border-t border-neutral-100" data-testid="ingestion-row">
              <td className="p-2 font-mono-tab text-xs">{new Date(r.timestamp).toLocaleString("en-IN")}</td>
              <td className="p-2 text-xs uppercase tracking-wider">{r.channel}</td>
              <td className="p-2 text-xs">{r.actor}</td>
              <td className="p-2 text-xs">{(r.sources || []).join(", ")}</td>
              <td className="p-2 text-right font-mono-tab">{r.count}</td>
              <td className="p-2 text-right font-mono-tab">{r.pending}</td>
              <td className="p-2 text-right font-mono-tab text-red-700">{r.duplicates}</td>
            </tr>
          ))}
          {!rows.length && <tr><td colSpan={7} className="p-6 text-center text-neutral-500 text-sm">No ingestion events yet.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

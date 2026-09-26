import React, { useCallback, useEffect, useState } from "react";
import { api, inr, formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { toast } from "sonner";
import { ArrowsClockwise, Archive, Eye, ShieldWarning, MagicWand } from "@phosphor-icons/react";

export default function BackupsTab({ onDidRestore }) {
  const [backups, setBackups] = useState([]);
  const [loading, setLoading] = useState(false);
  const [viewing, setViewing] = useState(null); // {stamp, count, rows}
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get("/migrations/backups");
      setBackups(r.data);
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const openSnapshot = async (stamp) => {
    setBusy(true);
    try {
      const r = await api.get(`/migrations/backups/${stamp}`);
      setViewing(r.data);
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  const restore = async (stamp, mode) => {
    const label = mode === "full" ? "FULL RESTORE" : "MERGE RESTORE";
    const msg = mode === "full"
      ? `${label}\n\nThis will backup the current transactions collection (as a safety net) and then REPLACE it with every row from snapshot ${stamp}.\n\nContinue?`
      : `${label}\n\nThis will insert rows from snapshot ${stamp} that don't already exist. Existing rows are untouched.\n\nContinue?`;
    if (!window.confirm(msg)) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("mode", mode);
      const r = await api.post(`/migrations/backups/${stamp}/restore`, fd, { headers: { "Content-Type": "multipart/form-data" } });
      toast.success(`Restored ${r.data.inserted} row(s) · skipped ${r.data.skipped_duplicate}`);
      setViewing(null);
      load();
      if (onDidRestore) onDidRestore();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  return (
    <div className="space-y-6">
      <div className="rudaya-card p-6">
        <div className="flex items-start gap-3">
          <ShieldWarning size={28} className="text-amber-600 shrink-0 mt-0.5" />
          <div>
            <h3 className="font-heading font-semibold text-lg">Backup snapshots</h3>
            <p className="text-sm text-neutral-600 mt-1">
              Every time you use <b>Replace existing</b> during a CSV import — or trigger a <b>Full restore</b> here — the previous
              transactions collection is stored under a timestamp in <code>transaction_import_backups</code>.
              You can preview any snapshot and restore it in two ways: <b>Merge</b> (insert only rows not already present), or
              <b>Full restore</b> (wipe current transactions after auto-backing them up, then insert the snapshot fresh).
            </p>
          </div>
        </div>
      </div>

      <div className="rudaya-card overflow-hidden">
        <div className="px-5 py-4 border-b border-neutral-200 flex items-center justify-between">
          <div>
            <h3 className="font-heading font-semibold text-lg">Available snapshots</h3>
            <p className="text-xs text-neutral-500 mt-0.5">{backups.length} snapshot{backups.length === 1 ? "" : "s"} stored.</p>
          </div>
          <Button data-testid="backups-refresh-btn" variant="outline" className="rounded-none" onClick={load} disabled={loading}>
            <ArrowsClockwise size={14} className="mr-2" /> Refresh
          </Button>
        </div>
        <div className="overflow-x-auto rudaya-scroll">
          <table className="w-full min-w-[820px]" data-testid="backups-table">
            <thead className="bg-neutral-50 border-b border-neutral-200">
              <tr className="text-left text-[11px] uppercase tracking-wider text-neutral-500">
                <th className="px-4 py-3">Stamp</th>
                <th className="px-3 py-3 text-right">Rows</th>
                <th className="px-3 py-3 text-right">Revenue</th>
                <th className="px-3 py-3 text-right">Cost</th>
                <th className="px-3 py-3 text-right">Expense</th>
                <th className="px-3 py-3">Backed up by</th>
                <th className="px-3 py-3">When</th>
                <th className="px-3 py-3 w-72"></th>
              </tr>
            </thead>
            <tbody>
              {backups.map((b) => (
                <tr key={b.stamp} className="border-b border-neutral-100 hover:bg-neutral-50" data-testid={`backup-row-${b.stamp}`}>
                  <td className="px-4 py-2.5 text-xs font-mono-tab flex items-center gap-2">
                    <Archive size={14} className="text-neutral-400" />{b.stamp}
                  </td>
                  <td className="px-3 py-2.5 text-right text-sm font-mono-tab">{b.count}</td>
                  <td className="px-3 py-2.5 text-right text-sm font-mono-tab text-emerald-700">{inr(b.totals.Revenue)}</td>
                  <td className="px-3 py-2.5 text-right text-sm font-mono-tab text-neutral-900">{inr(b.totals.Cost)}</td>
                  <td className="px-3 py-2.5 text-right text-sm font-mono-tab text-amber-700">{inr(b.totals.Expense)}</td>
                  <td className="px-3 py-2.5 text-xs">{b.admin_email}</td>
                  <td className="px-3 py-2.5 text-xs">{b.backed_up_at?.slice(0, 19).replace("T", " ")}</td>
                  <td className="px-3 py-2.5 text-right space-x-1">
                    <button data-testid={`backup-view-${b.stamp}`} onClick={() => openSnapshot(b.stamp)} disabled={busy} className="text-[11px] uppercase tracking-wider px-2 py-1 border border-neutral-300 hover:bg-neutral-100">
                      <Eye size={12} className="inline mr-1" /> Preview
                    </button>
                    <button data-testid={`backup-merge-${b.stamp}`} onClick={() => restore(b.stamp, "merge")} disabled={busy} className="text-[11px] uppercase tracking-wider px-2 py-1 border border-emerald-500 text-emerald-700 hover:bg-emerald-50">
                      <MagicWand size={12} className="inline mr-1" /> Merge
                    </button>
                    <button data-testid={`backup-full-${b.stamp}`} onClick={() => restore(b.stamp, "full")} disabled={busy} className="text-[11px] uppercase tracking-wider px-2 py-1 border border-red-500 text-red-700 hover:bg-red-50">
                      <ArrowsClockwise size={12} className="inline mr-1" /> Full restore
                    </button>
                  </td>
                </tr>
              ))}
              {backups.length === 0 && (
                <tr><td colSpan="8" className="px-4 py-12 text-center text-neutral-500 text-sm">
                  <Archive size={22} className="mx-auto text-neutral-300 mb-2" />
                  No backup snapshots yet. Any <b>Replace existing</b> CSV import will create one.
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <Dialog open={!!viewing} onOpenChange={(o) => !o && setViewing(null)}>
        <DialogContent className="max-w-4xl rounded-none border-l-2 border-l-neutral-900" data-testid="backup-preview-dialog">
          <DialogHeader>
            <div className="text-[11px] uppercase tracking-[0.25em] text-neutral-500">Snapshot preview</div>
            <DialogTitle className="font-heading text-2xl tracking-tight">{viewing?.stamp}</DialogTitle>
            <DialogDescription>
              {viewing?.count} row{viewing?.count === 1 ? "" : "s"} · showing first {Math.min(viewing?.rows?.length || 0, 500)}.
            </DialogDescription>
          </DialogHeader>
          <div className="overflow-x-auto rudaya-scroll max-h-[480px]">
            <table className="w-full min-w-[720px] text-xs" data-testid="backup-preview-table">
              <thead className="bg-neutral-50 sticky top-0 border-b border-neutral-200">
                <tr className="text-left uppercase tracking-wider text-[10px] text-neutral-500">
                  <th className="px-3 py-2">Date</th>
                  <th className="px-3 py-2">Type</th>
                  <th className="px-3 py-2">Account</th>
                  <th className="px-3 py-2 text-right">Amount</th>
                  <th className="px-3 py-2">Project</th>
                  <th className="px-3 py-2">Notes</th>
                </tr>
              </thead>
              <tbody>
                {viewing?.rows?.map((r, i) => (
                  <tr key={i} className="border-b border-neutral-100">
                    <td className="px-3 py-1.5">{(r.date || "").slice(0, 10)}</td>
                    <td className="px-3 py-1.5">{r.type}</td>
                    <td className="px-3 py-1.5">{r.account}</td>
                    <td className="px-3 py-1.5 text-right font-mono-tab">{inr(r.amount)}</td>
                    <td className="px-3 py-1.5">{r.project_id}</td>
                    <td className="px-3 py-1.5 text-neutral-600">{r.notes}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {viewing && (
            <div className="flex justify-end gap-2 mt-4">
              <Button data-testid="backup-preview-merge" variant="outline" className="rounded-none border-emerald-500 text-emerald-700 hover:bg-emerald-50" onClick={() => restore(viewing.stamp, "merge")} disabled={busy}>
                <MagicWand size={14} className="mr-2" /> Merge (safe)
              </Button>
              <Button data-testid="backup-preview-full" className="rounded-none bg-red-700 hover:bg-red-800" onClick={() => restore(viewing.stamp, "full")} disabled={busy}>
                <ArrowsClockwise size={14} className="mr-2" /> Full restore
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

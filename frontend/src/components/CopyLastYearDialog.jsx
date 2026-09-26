import React, { useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { Copy, CheckCircle, WarningCircle } from "@phosphor-icons/react";

const currentYear = new Date().getFullYear();
const YEARS = [currentYear, currentYear + 1, currentYear + 2, currentYear + 3];

export default function CopyLastYearDialog({ open, onOpenChange, onCopied }) {
  const [targetYear, setTargetYear] = useState(currentYear + 1);
  const [includeQuotations, setIncludeQuotations] = useState(false);
  const [overwrite, setOverwrite] = useState(false);
  const [copying, setCopying] = useState(false);
  const [result, setResult] = useState(null);

  const run = async () => {
    setCopying(true);
    setResult(null);
    try {
      const r = await api.post("/sales-forecast/copy-last-year", {
        target_year: targetYear,
        include_quotations: includeQuotations,
        overwrite,
      });
      setResult(r.data);
      const sf = r.data.sales_forecast;
      const q = r.data.quotations;
      const parts = [`${sf.copied} forecast row${sf.copied === 1 ? "" : "s"} copied`];
      if (sf.skipped) parts.push(`${sf.skipped} skipped`);
      if (q) parts.push(`${q.copied} quotation${q.copied === 1 ? "" : "s"} copied`);
      toast.success(parts.join(" · "));
      if (onCopied) onCopied();
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    } finally { setCopying(false); }
  };

  const reset = () => {
    setResult(null);
    setIncludeQuotations(false);
    setOverwrite(false);
  };

  return (
    <Dialog open={open} onOpenChange={(o) => { onOpenChange(o); if (!o) reset(); }}>
      <DialogContent className="max-w-lg rounded-none border-l-2 border-l-neutral-900" data-testid="copy-last-year-dialog">
        <DialogHeader>
          <div className="text-[11px] uppercase tracking-[0.25em] text-neutral-500">Sales Forecast</div>
          <DialogTitle className="font-heading text-2xl tracking-tight">Copy Last Year</DialogTitle>
          <DialogDescription>
            Clone every Sales Forecast line item from <b>{targetYear - 1}</b> into <b>{targetYear}</b>.
            Existing rows in the target year are kept unless you enable overwrite.
          </DialogDescription>
        </DialogHeader>

        {!result && (
          <div className="space-y-4 mt-2">
            <div>
              <Label className="text-xs uppercase tracking-wider">Target year</Label>
              <Select value={String(targetYear)} onValueChange={(v) => setTargetYear(parseInt(v))}>
                <SelectTrigger data-testid="copy-target-year" className="rounded-none mt-1"><SelectValue /></SelectTrigger>
                <SelectContent>{YEARS.map((y) => <SelectItem key={y} value={String(y)}>{y} (from {y - 1})</SelectItem>)}</SelectContent>
              </Select>
            </div>

            <label className="flex items-start gap-3 border border-neutral-200 p-3 cursor-pointer hover:border-neutral-400" data-testid="copy-quotations-toggle">
              <input type="checkbox" className="mt-1" checked={includeQuotations} onChange={(e) => setIncludeQuotations(e.target.checked)} />
              <div>
                <div className="text-sm font-medium">Also copy open quotations</div>
                <p className="text-xs text-neutral-500 mt-0.5">
                  Every non-lost quotation from {targetYear - 1} will be duplicated as a <b>draft</b> with expected year {targetYear} and a suffix
                  <code>-COPY{targetYear}</code> on the quotation number.
                </p>
              </div>
            </label>

            <label className="flex items-start gap-3 border border-neutral-200 p-3 cursor-pointer hover:border-red-400" data-testid="copy-overwrite-toggle">
              <input type="checkbox" className="mt-1" checked={overwrite} onChange={(e) => setOverwrite(e.target.checked)} />
              <div>
                <div className="text-sm font-medium flex items-center gap-2">
                  <WarningCircle size={14} className="text-amber-600" /> Overwrite matching rows
                </div>
                <p className="text-xs text-neutral-500 mt-0.5">
                  By default, a row that already exists in {targetYear} with the same month + type + project + notes is skipped.
                  Enable to always append.
                </p>
              </div>
            </label>

            <Button data-testid="copy-run-btn" onClick={run} disabled={copying} className="w-full rounded-none bg-neutral-900 hover:bg-neutral-700 h-11">
              <Copy size={16} className="mr-2" /> {copying ? "Copying…" : `Copy ${targetYear - 1} → ${targetYear}`}
            </Button>
          </div>
        )}

        {result && (
          <div className="mt-2 space-y-3" data-testid="copy-result">
            <div className="flex items-center gap-2 text-emerald-700"><CheckCircle size={22} /> <b>Done.</b></div>
            <div className="rudaya-card p-3">
              <div className="text-[10px] uppercase tracking-wider text-neutral-500">Sales Forecast</div>
              <div className="text-sm mt-1">{result.sales_forecast.copied} copied · {result.sales_forecast.skipped} skipped</div>
            </div>
            {result.quotations && (
              <div className="rudaya-card p-3">
                <div className="text-[10px] uppercase tracking-wider text-neutral-500">Quotations</div>
                <div className="text-sm mt-1">{result.quotations.copied} copied · {result.quotations.skipped} skipped (duplicate number)</div>
              </div>
            )}
            <Button data-testid="copy-close-btn" variant="outline" className="w-full rounded-none" onClick={() => { onOpenChange(false); reset(); }}>Close</Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

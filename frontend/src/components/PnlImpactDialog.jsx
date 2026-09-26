import React from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { inr } from "@/lib/api";

function Sparkline({ values, color = "#111", width = 90, height = 24 }) {
  if (!values || values.length === 0) return null;
  const abs = values.map((v) => Math.abs(v));
  const maxAbs = Math.max(1, ...abs);
  const w = width;
  const h = height;
  const step = w / Math.max(1, values.length - 1);
  const zero = h / 2;
  const pts = values.map((v, i) => {
    const x = i * step;
    const y = zero - (v / maxAbs) * (h / 2 - 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return (
    <svg width={w} height={h} className="block" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
      <line x1="0" y1={zero} x2={w} y2={zero} stroke="#d4d4d4" strokeWidth="0.5" strokeDasharray="2 2" />
      <polyline fill="none" stroke={color} strokeWidth="1.5" points={pts} />
      {values.map((v, i) => {
        const x = i * step;
        const y = zero - (v / maxAbs) * (h / 2 - 2);
        return <circle key={i} cx={x} cy={y} r="1.3" fill={color} />;
      })}
    </svg>
  );
}

function DeltaCell({ v }) {
  if (!v) return <span className="text-neutral-400">—</span>;
  const cls = v > 0 ? "text-emerald-700" : "text-red-700";
  const sign = v > 0 ? "+" : "";
  return <span className={`font-mono-tab ${cls}`}>{sign}{inr(v)}</span>;
}

function YearTab({ year, data }) {
  const netDeltaSeries = data.months.map((m) => m.delta.net);
  return (
    <div>
      <div className="grid grid-cols-4 gap-3 mb-4">
        <div className="rudaya-card p-4">
          <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500">Net (Before)</div>
          <div className="mt-1 font-mono-tab font-semibold text-lg">{inr(data.totals_before.net)}</div>
        </div>
        <div className="rudaya-card p-4">
          <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500">Net (After)</div>
          <div className="mt-1 font-mono-tab font-semibold text-lg">{inr(data.totals_after.net)}</div>
        </div>
        <div className="rudaya-card p-4">
          <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500">Net Δ</div>
          <div className="mt-1"><DeltaCell v={data.totals_delta.net} /></div>
        </div>
        <div className="rudaya-card p-4 flex flex-col">
          <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500 mb-1">Net Δ trend</div>
          <Sparkline values={netDeltaSeries} color="#dc2626" width={140} height={32} />
        </div>
      </div>
      <div className="overflow-x-auto rudaya-scroll max-h-[420px]">
        <table className="w-full min-w-[900px] text-xs" data-testid={`dryrun-year-table-${year}`}>
          <thead className="bg-neutral-50 sticky top-0 border-b border-neutral-200">
            <tr className="text-left uppercase tracking-wider text-[10px] text-neutral-500">
              <th className="px-3 py-2">Month</th>
              <th className="px-3 py-2 text-right">Rev Before</th>
              <th className="px-3 py-2 text-right">Rev After</th>
              <th className="px-3 py-2 text-right">Rev Δ</th>
              <th className="px-3 py-2 text-right">Cost Δ</th>
              <th className="px-3 py-2 text-right">Exp Δ</th>
              <th className="px-3 py-2 text-right">Net Before</th>
              <th className="px-3 py-2 text-right">Net After</th>
              <th className="px-3 py-2 text-right">Net Δ</th>
              <th className="px-3 py-2">Δ Trend</th>
            </tr>
          </thead>
          <tbody>
            {data.months.map((m) => {
              const highlight = Math.abs(m.delta.net) > 1;
              return (
                <tr key={m.month} className={`border-b border-neutral-100 ${highlight ? "bg-amber-50" : ""}`} data-testid={`dryrun-row-${year}-${m.month}`}>
                  <td className="px-3 py-1.5 font-medium">{m.label}</td>
                  <td className="px-3 py-1.5 text-right font-mono-tab">{inr(m.before.Revenue)}</td>
                  <td className="px-3 py-1.5 text-right font-mono-tab">{inr(m.after.Revenue)}</td>
                  <td className="px-3 py-1.5 text-right"><DeltaCell v={m.delta.Revenue} /></td>
                  <td className="px-3 py-1.5 text-right"><DeltaCell v={m.delta.Cost} /></td>
                  <td className="px-3 py-1.5 text-right"><DeltaCell v={m.delta.Expense} /></td>
                  <td className="px-3 py-1.5 text-right font-mono-tab">{inr(m.before.net)}</td>
                  <td className="px-3 py-1.5 text-right font-mono-tab">{inr(m.after.net)}</td>
                  <td className="px-3 py-1.5 text-right"><DeltaCell v={m.delta.net} /></td>
                  <td className="px-3 py-1.5">
                    <Sparkline values={[0, m.delta.net]} color={m.delta.net >= 0 ? "#059669" : "#dc2626"} width={60} height={16} />
                  </td>
                </tr>
              );
            })}
          </tbody>
          <tfoot className="bg-neutral-900 text-white text-xs">
            <tr>
              <td className="px-3 py-2 uppercase tracking-widest">Year Total</td>
              <td className="px-3 py-2 text-right font-mono-tab">{inr(data.totals_before.Revenue)}</td>
              <td className="px-3 py-2 text-right font-mono-tab">{inr(data.totals_after.Revenue)}</td>
              <td className="px-3 py-2 text-right"><DeltaCell v={data.totals_delta.Revenue} /></td>
              <td className="px-3 py-2 text-right"><DeltaCell v={data.totals_delta.Cost} /></td>
              <td className="px-3 py-2 text-right"><DeltaCell v={data.totals_delta.Expense} /></td>
              <td className="px-3 py-2 text-right font-mono-tab">{inr(data.totals_before.net)}</td>
              <td className="px-3 py-2 text-right font-mono-tab">{inr(data.totals_after.net)}</td>
              <td className="px-3 py-2 text-right"><DeltaCell v={data.totals_delta.net} /></td>
              <td></td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}

export default function PnlImpactDialog({ open, onOpenChange, data, mode, loading }) {
  const years = data ? Object.keys(data.years).sort() : [];
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-5xl rounded-none border-l-2 border-l-neutral-900" data-testid="dryrun-dialog">
        <DialogHeader>
          <div className="text-[11px] uppercase tracking-[0.25em] text-neutral-500">Dry run · {mode?.replace("_", " ")}</div>
          <DialogTitle className="font-heading text-2xl tracking-tight">P&amp;L Impact Preview</DialogTitle>
          <DialogDescription>
            Month-by-month Revenue / Cost / Expense / Net change if you import <b>{data?.would_insert ?? 0}</b> rows.
            Nothing has been saved yet.
          </DialogDescription>
        </DialogHeader>
        {loading && <div className="py-10 text-center text-neutral-500 text-sm">Calculating P&amp;L impact…</div>}
        {!loading && data && years.length > 0 && (
          <Tabs defaultValue={years[0]} className="mt-2">
            <TabsList className="rounded-none">
              {years.map((y) => <TabsTrigger key={y} value={y} className="rounded-none" data-testid={`dryrun-year-tab-${y}`}>FY {y}</TabsTrigger>)}
            </TabsList>
            {years.map((y) => (
              <TabsContent key={y} value={y} className="mt-4">
                <YearTab year={y} data={data.years[y]} />
              </TabsContent>
            ))}
          </Tabs>
        )}
        {!loading && data && years.length === 0 && (
          <div className="py-10 text-center text-neutral-500 text-sm">Nothing would be inserted — no P&amp;L change.</div>
        )}
      </DialogContent>
    </Dialog>
  );
}

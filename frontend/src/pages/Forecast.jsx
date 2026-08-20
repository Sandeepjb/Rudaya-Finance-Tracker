import React, { useEffect, useMemo, useState } from "react";
import Layout from "@/components/Layout";
import { api, inr, formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend, LineChart, Line } from "recharts";
import { FloppyDisk, Target } from "@phosphor-icons/react";
import { TICK_STYLE, TOOLTIP_STYLE, LEGEND_STYLE, yTickLakh, yTickPct } from "@/lib/format";

const currentYear = new Date().getFullYear();
const YEARS = [currentYear - 1, currentYear, currentYear + 1, currentYear + 2];

export default function Forecast() {
  const [year, setYear] = useState(currentYear);
  const [data, setData] = useState({ rows: [], total_forecast: 0, total_actual: 0 });
  const [edits, setEdits] = useState({}); // month -> string
  const [notesEdits, setNotesEdits] = useState({}); // month -> string
  const [saving, setSaving] = useState({});

  const load = async () => {
    const r = await api.get("/reports/forecast-vs-actual", { params: { year } });
    setData(r.data);
    setEdits({});
    setNotesEdits({});
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [year]);

  const save = async (month) => {
    const raw = edits[month];
    const amount = parseFloat(raw);
    if (isNaN(amount) || amount < 0) { toast.error("Enter a valid amount"); return; }
    setSaving((s) => ({ ...s, [month]: true }));
    try {
      await api.post("/forecast", { year, month, amount, notes: notesEdits[month] ?? "" });
      toast.success(`Forecast saved for ${new Date(year, month - 1, 1).toLocaleString("en-US", { month: "long" })} ${year}`);
      load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setSaving((s) => ({ ...s, [month]: false })); }
  };

  const chartData = useMemo(() => data.rows.map((r) => ({
    ...r,
    achievement: r.forecast > 0 ? Math.round((r.actual / r.forecast) * 100) : 0,
  })), [data.rows]);

  const totalVariance = data.total_actual - data.total_forecast;
  const overallPct = data.total_forecast > 0 ? (data.total_actual / data.total_forecast) * 100 : 0;

  return (
    <Layout
      title="Revenue Forecast"
      subtitle="Set month-wise revenue targets and track actual achievement"
      actions={
        <Select value={String(year)} onValueChange={(v) => setYear(parseInt(v))}>
          <SelectTrigger data-testid="forecast-year-select" className="rounded-none w-32"><SelectValue /></SelectTrigger>
          <SelectContent>
            {YEARS.map((y) => <SelectItem key={y} value={String(y)}>{y}</SelectItem>)}
          </SelectContent>
        </Select>
      }
    >
      {/* Summary tiles */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <div className="rudaya-card p-5" data-testid="fc-tile-forecast">
          <div className="flex items-start justify-between">
            <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500">Total Forecast · {year}</div>
            <Target size={18} className="text-neutral-400" />
          </div>
          <div className="mt-3 font-mono-tab font-semibold text-2xl text-neutral-900">{inr(data.total_forecast)}</div>
        </div>
        <div className="rudaya-card p-5" data-testid="fc-tile-actual">
          <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500">Total Actual</div>
          <div className="mt-3 font-mono-tab font-semibold text-2xl text-emerald-700">{inr(data.total_actual)}</div>
        </div>
        <div className="rudaya-card p-5" data-testid="fc-tile-variance">
          <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500">Variance</div>
          <div className={`mt-3 font-mono-tab font-semibold text-2xl ${totalVariance >= 0 ? "text-blue-700" : "text-red-700"}`}>
            {totalVariance >= 0 ? "+" : ""}{inr(totalVariance)}
          </div>
        </div>
        <div className="rudaya-card p-5" data-testid="fc-tile-achievement">
          <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500">Achievement</div>
          <div className="mt-3 font-mono-tab font-semibold text-2xl text-neutral-900">
            {data.total_forecast > 0 ? overallPct.toFixed(1) + "%" : "—"}
          </div>
        </div>
      </div>

      {/* Chart */}
      <div className="rudaya-card p-5 mb-6">
        <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500">FY {year}</div>
        <h3 className="font-heading font-semibold text-lg mb-4">Forecast vs Actual Revenue</h3>
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="0" stroke="#E5E7EB" vertical={false} />
              <XAxis dataKey="label" stroke="#6B7280" tick={TICK_STYLE} />
              <YAxis stroke="#6B7280" tick={TICK_STYLE} tickFormatter={yTickLakh} />
              <Tooltip formatter={(v) => inr(v)} contentStyle={TOOLTIP_STYLE} />
              <Legend wrapperStyle={LEGEND_STYLE} />
              <Bar dataKey="forecast" fill="#111827" name="Forecast" />
              <Bar dataKey="actual" fill="#059669" name="Actual" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Editable grid */}
      <div className="rudaya-card overflow-hidden">
        <div className="px-5 py-4 border-b border-neutral-200">
          <h3 className="font-heading font-semibold text-lg">Month-wise Entry</h3>
          <p className="text-xs text-neutral-500 mt-0.5">Type a forecast amount for each month and hit Save.</p>
        </div>
        <table className="w-full" data-testid="forecast-table">
          <thead className="bg-neutral-50 border-b border-neutral-200">
            <tr className="text-left text-[11px] uppercase tracking-wider text-neutral-500">
              <th className="px-4 py-3">Month</th>
              <th className="px-3 py-3 text-right">Forecast ₹</th>
              <th className="px-3 py-3 text-right">Actual ₹</th>
              <th className="px-3 py-3 text-right">Variance</th>
              <th className="px-3 py-3 text-right">Achv.</th>
              <th className="px-3 py-3">Notes</th>
              <th className="px-4 py-3 w-24"></th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => {
              const currentAmt = edits[r.month] !== undefined ? edits[r.month] : (r.forecast || "");
              const currentNotes = notesEdits[r.month] !== undefined ? notesEdits[r.month] : "";
              const dirty = edits[r.month] !== undefined || notesEdits[r.month] !== undefined;
              return (
                <tr key={r.month} className="border-b border-neutral-100 hover:bg-neutral-50 transition-colors" data-testid={`fc-row-${r.month}`}>
                  <td className="px-4 py-2 font-mono-tab text-sm">{r.label} {r.year}</td>
                  <td className="px-3 py-2 text-right">
                    <Input
                      data-testid={`fc-input-${r.month}`}
                      type="number" step="1" min="0"
                      className="rounded-none text-right font-mono-tab h-9 max-w-[180px] ml-auto"
                      value={currentAmt}
                      onChange={(e) => setEdits((s) => ({ ...s, [r.month]: e.target.value }))}
                      placeholder="0"
                    />
                  </td>
                  <td className="px-3 py-2 text-right font-mono-tab text-sm text-emerald-700">{inr(r.actual)}</td>
                  <td className={`px-3 py-2 text-right font-mono-tab text-sm ${r.variance >= 0 ? "text-blue-700" : "text-red-700"}`}>
                    {r.forecast ? ((r.variance >= 0 ? "+" : "") + inr(r.variance)) : "—"}
                  </td>
                  <td className="px-3 py-2 text-right font-mono-tab text-sm">
                    {r.forecast ? (r.achievement_pct?.toFixed(0) + "%") : "—"}
                  </td>
                  <td className="px-3 py-2">
                    <Input
                      data-testid={`fc-notes-${r.month}`}
                      className="rounded-none h-9 text-sm"
                      value={currentNotes}
                      onChange={(e) => setNotesEdits((s) => ({ ...s, [r.month]: e.target.value }))}
                      placeholder="Optional"
                    />
                  </td>
                  <td className="px-4 py-2 text-right">
                    <Button
                      data-testid={`fc-save-${r.month}`}
                      onClick={() => save(r.month)}
                      disabled={!dirty || saving[r.month]}
                      className="rounded-none h-9 bg-neutral-900 hover:bg-neutral-700 disabled:opacity-40"
                    >
                      <FloppyDisk size={14} className="mr-1" /> {saving[r.month] ? "…" : "Save"}
                    </Button>
                  </td>
                </tr>
              );
            })}
          </tbody>
          <tfoot className="bg-neutral-900 text-white">
            <tr>
              <td className="px-4 py-3 uppercase text-[11px] tracking-widest">Total</td>
              <td className="px-3 py-3 text-right font-mono-tab text-sm">{inr(data.total_forecast)}</td>
              <td className="px-3 py-3 text-right font-mono-tab text-sm">{inr(data.total_actual)}</td>
              <td className={`px-3 py-3 text-right font-mono-tab text-sm ${totalVariance >= 0 ? "text-blue-300" : "text-red-300"}`}>
                {totalVariance >= 0 ? "+" : ""}{inr(totalVariance)}
              </td>
              <td className="px-3 py-3 text-right font-mono-tab text-sm">{data.total_forecast > 0 ? overallPct.toFixed(0) + "%" : "—"}</td>
              <td colSpan="2"></td>
            </tr>
          </tfoot>
        </table>
      </div>

      {/* Trend line */}
      <div className="rudaya-card p-5 mt-6">
        <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500">Achievement Trend</div>
        <h3 className="font-heading font-semibold text-lg mb-4">Achievement % by Month</h3>
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="0" stroke="#E5E7EB" vertical={false} />
              <XAxis dataKey="label" stroke="#6B7280" tick={TICK_STYLE} />
              <YAxis stroke="#6B7280" tick={TICK_STYLE} tickFormatter={yTickPct} />
              <Tooltip formatter={yTickPct} contentStyle={TOOLTIP_STYLE} />
              <Line type="monotone" dataKey="achievement" stroke="#2563EB" strokeWidth={2} dot={{ r: 3 }} name="Achievement %" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </Layout>
  );
}

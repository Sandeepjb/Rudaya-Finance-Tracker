import React, { useEffect, useMemo, useState } from "react";
import Layout from "@/components/Layout";
import { Link } from "react-router-dom";
import { api, inr } from "@/lib/api";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend, LineChart, Line } from "recharts";
import { Target, ArrowRight } from "@phosphor-icons/react";
import { TICK_STYLE, TOOLTIP_STYLE, LEGEND_STYLE, yTickLakh, yTickPct } from "@/lib/format";

const LINE_DOT = { r: 3 };

const currentYear = new Date().getFullYear();
const YEARS = [currentYear - 1, currentYear, currentYear + 1, currentYear + 2];

export default function Forecast() {
  const [year, setYear] = useState(currentYear);
  const [data, setData] = useState({ rows: [], total_forecast: 0, total_actual: 0 });

  useEffect(() => {
    let alive = true;
    api.get("/reports/forecast-vs-actual", { params: { year } })
      .then((r) => { if (alive) setData(r.data); });
    return () => { alive = false; };
  }, [year]);

  const chartData = useMemo(
    () => data.rows.map((r) => ({
      ...r,
      achievement: r.forecast > 0 ? Math.round((r.actual / r.forecast) * 100) : 0,
    })),
    [data.rows]
  );

  const totalVariance = data.total_actual - data.total_forecast;
  const overallPct = data.total_forecast > 0 ? (data.total_actual / data.total_forecast) * 100 : 0;

  return (
    <Layout
      title="Forecast vs Actual"
      subtitle="Consolidated monthly sales forecast compared with actual revenue"
      actions={
        <div className="flex items-center gap-3">
          <Link
            to="/sales-forecast"
            data-testid="link-to-sales-forecast"
            className="inline-flex items-center gap-1.5 text-xs uppercase tracking-wider text-neutral-700 hover:text-neutral-900 border border-neutral-300 px-3 py-2 hover:bg-neutral-100 transition-colors"
          >
            Manage Sales Forecast <ArrowRight size={14} />
          </Link>
          <Select value={String(year)} onValueChange={(v) => setYear(parseInt(v))}>
            <SelectTrigger data-testid="forecast-year-select" className="rounded-none w-32"><SelectValue /></SelectTrigger>
            <SelectContent>{YEARS.map((y) => <SelectItem key={y} value={String(y)}>{y}</SelectItem>)}</SelectContent>
          </Select>
        </div>
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
          <ResponsiveContainer width="100%" height="100%" minHeight={280}>
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

      {/* Consolidated table (read-only) */}
      <div className="rudaya-card overflow-hidden">
        <div className="px-5 py-4 border-b border-neutral-200 flex items-center justify-between">
          <div>
            <h3 className="font-heading font-semibold text-lg">Monthly Consolidation</h3>
            <p className="text-xs text-neutral-500 mt-0.5">Forecast values are aggregated from the Sales Forecast line items.</p>
          </div>
          <Link
            to="/sales-forecast"
            className="text-xs uppercase tracking-wider text-neutral-600 hover:text-neutral-900"
            data-testid="table-link-to-sales-forecast"
          >
            Edit entries →
          </Link>
        </div>
        <table className="w-full" data-testid="forecast-table">
          <thead className="bg-neutral-50 border-b border-neutral-200">
            <tr className="text-left text-[11px] uppercase tracking-wider text-neutral-500">
              <th className="px-4 py-3">Month</th>
              <th className="px-3 py-3 text-right">Line items</th>
              <th className="px-3 py-3 text-right">Forecast ₹</th>
              <th className="px-3 py-3 text-right">Actual ₹</th>
              <th className="px-3 py-3 text-right">Variance</th>
              <th className="px-4 py-3 text-right">Achv.</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={r.month} className="border-b border-neutral-100 hover:bg-neutral-50 transition-colors" data-testid={`fc-row-${r.month}`}>
                <td className="px-4 py-2.5 font-mono-tab text-sm">{r.label} {r.year}</td>
                <td className="px-3 py-2.5 text-right font-mono-tab text-sm text-neutral-500">{r.line_items || 0}</td>
                <td className="px-3 py-2.5 text-right font-mono-tab text-sm text-neutral-900">{inr(r.forecast)}</td>
                <td className="px-3 py-2.5 text-right font-mono-tab text-sm text-emerald-700">{inr(r.actual)}</td>
                <td className={`px-3 py-2.5 text-right font-mono-tab text-sm ${r.variance >= 0 ? "text-blue-700" : "text-red-700"}`}>
                  {r.forecast ? ((r.variance >= 0 ? "+" : "") + inr(r.variance)) : "—"}
                </td>
                <td className="px-4 py-2.5 text-right font-mono-tab text-sm">
                  {r.forecast ? (r.achievement_pct?.toFixed(0) + "%") : "—"}
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot className="bg-neutral-900 text-white">
            <tr>
              <td colSpan="2" className="px-4 py-3 uppercase text-[11px] tracking-widest">Total</td>
              <td className="px-3 py-3 text-right font-mono-tab text-sm">{inr(data.total_forecast)}</td>
              <td className="px-3 py-3 text-right font-mono-tab text-sm">{inr(data.total_actual)}</td>
              <td className={`px-3 py-3 text-right font-mono-tab text-sm ${totalVariance >= 0 ? "text-blue-300" : "text-red-300"}`}>
                {totalVariance >= 0 ? "+" : ""}{inr(totalVariance)}
              </td>
              <td className="px-4 py-3 text-right font-mono-tab text-sm font-semibold">{data.total_forecast > 0 ? overallPct.toFixed(0) + "%" : "—"}</td>
            </tr>
          </tfoot>
        </table>
      </div>

      {/* Trend line */}
      <div className="rudaya-card p-5 mt-6">
        <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500">Achievement Trend</div>
        <h3 className="font-heading font-semibold text-lg mb-4">Achievement % by Month</h3>
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%" minHeight={200}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="0" stroke="#E5E7EB" vertical={false} />
              <XAxis dataKey="label" stroke="#6B7280" tick={TICK_STYLE} />
              <YAxis stroke="#6B7280" tick={TICK_STYLE} tickFormatter={yTickPct} />
              <Tooltip formatter={yTickPct} contentStyle={TOOLTIP_STYLE} />
              <Line type="monotone" dataKey="achievement" stroke="#2563EB" strokeWidth={2} dot={LINE_DOT} name="Achievement %" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </Layout>
  );
}

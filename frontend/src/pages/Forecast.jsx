import React, { useEffect, useMemo, useState } from "react";
import Layout from "@/components/Layout";
import { Link } from "react-router-dom";
import { api, inr } from "@/lib/api";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend } from "recharts";
import { Target, ArrowRight } from "@phosphor-icons/react";
import { TICK_STYLE, TOOLTIP_STYLE, LEGEND_STYLE, yTickLakh } from "@/lib/format";

const currentYear = new Date().getFullYear();
const YEARS = [currentYear - 1, currentYear, currentYear + 1, currentYear + 2];
const TYPES = ["Revenue", "Cost", "Expense"];
const TYPE_COLORS_F = { Revenue: "#111827", Cost: "#7f1d1d", Expense: "#78350f" }; // forecast bars
const TYPE_COLORS_A = { Revenue: "#059669", Cost: "#DC2626", Expense: "#D97706" }; // actual bars

const EMPTY_DATA = {
  year: currentYear, types: TYPES, rows: [],
  total_forecast: { Revenue: 0, Cost: 0, Expense: 0 },
  total_actual: { Revenue: 0, Cost: 0, Expense: 0 },
  total_forecast_all: 0, total_actual_all: 0,
};

export default function Forecast() {
  const [year, setYear] = useState(currentYear);
  const [activeType, setActiveType] = useState("Revenue");
  const [data, setData] = useState(EMPTY_DATA);

  useEffect(() => {
    let alive = true;
    api.get("/reports/forecast-vs-actual", { params: { year } })
      .then((r) => { if (alive) setData(r.data); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [year]);

  const chartData = useMemo(
    () => data.rows.map((r) => ({
      label: r.label,
      forecast: r.forecast?.[activeType] || 0,
      actual: r.actual?.[activeType] || 0,
    })),
    [data.rows, activeType]
  );

  const tot = {
    forecast: data.total_forecast[activeType] || 0,
    actual: data.total_actual[activeType] || 0,
  };
  const variance = tot.actual - tot.forecast;
  const pct = tot.forecast > 0 ? (tot.actual / tot.forecast) * 100 : 0;

  return (
    <Layout
      title="Forecast vs Actual"
      subtitle="Monthly forecast (Sales Forecast + Quotations) vs actual transactions, by type"
      actions={
        <div className="flex items-center gap-3">
          <Link
            to="/sales-forecast"
            data-testid="link-to-sales-forecast"
            className="inline-flex items-center gap-1.5 text-xs uppercase tracking-wider text-neutral-700 hover:text-neutral-900 border border-neutral-300 px-3 py-2 hover:bg-neutral-100 transition-colors"
          >
            Sales Forecast <ArrowRight size={14} />
          </Link>
          <Link
            to="/quotations"
            data-testid="link-to-quotations"
            className="inline-flex items-center gap-1.5 text-xs uppercase tracking-wider text-neutral-700 hover:text-neutral-900 border border-neutral-300 px-3 py-2 hover:bg-neutral-100 transition-colors"
          >
            Quotations <ArrowRight size={14} />
          </Link>
          <Select value={String(year)} onValueChange={(v) => setYear(parseInt(v))}>
            <SelectTrigger data-testid="forecast-year-select" className="rounded-none w-32"><SelectValue /></SelectTrigger>
            <SelectContent>{YEARS.map((y) => <SelectItem key={y} value={String(y)}>{y}</SelectItem>)}</SelectContent>
          </Select>
        </div>
      }
    >
      {/* Type tabs */}
      <div className="flex gap-2 mb-6" data-testid="fc-type-tabs">
        {TYPES.map((t) => (
          <button
            key={t}
            data-testid={`fc-tab-${t}`}
            onClick={() => setActiveType(t)}
            className={`px-4 py-2 border text-xs uppercase tracking-wider transition-colors ${
              activeType === t
                ? "bg-neutral-900 text-white border-neutral-900"
                : "bg-white text-neutral-700 border-neutral-300 hover:bg-neutral-100"
            }`}
          >
            {t}
            <span className="ml-2 font-mono-tab text-[10px] opacity-80">
              {inr(data.total_forecast[t] || 0)}
            </span>
          </button>
        ))}
      </div>

      {/* KPI tiles for active type */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <div className="rudaya-card p-5" data-testid="fc-tile-forecast">
          <div className="flex items-start justify-between">
            <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500">Forecast {activeType} · {year}</div>
            <Target size={18} className="text-neutral-400" />
          </div>
          <div className="mt-3 font-mono-tab font-semibold text-2xl text-neutral-900">{inr(tot.forecast)}</div>
        </div>
        <div className="rudaya-card p-5" data-testid="fc-tile-actual">
          <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500">Actual {activeType}</div>
          <div className="mt-3 font-mono-tab font-semibold text-2xl" style={{ color: TYPE_COLORS_A[activeType] }}>{inr(tot.actual)}</div>
        </div>
        <div className="rudaya-card p-5" data-testid="fc-tile-variance">
          <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500">Variance</div>
          <div className={`mt-3 font-mono-tab font-semibold text-2xl ${variance >= 0 ? "text-blue-700" : "text-red-700"}`}>
            {variance >= 0 ? "+" : ""}{inr(variance)}
          </div>
        </div>
        <div className="rudaya-card p-5" data-testid="fc-tile-achievement">
          <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500">Achievement</div>
          <div className="mt-3 font-mono-tab font-semibold text-2xl text-neutral-900">
            {tot.forecast > 0 ? pct.toFixed(1) + "%" : "—"}
          </div>
        </div>
      </div>

      {/* Chart for active type */}
      <div className="rudaya-card p-5 mb-6">
        <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500">FY {year} · {activeType}</div>
        <h3 className="font-heading font-semibold text-lg mb-4">Forecast vs Actual</h3>
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%" minHeight={280}>
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="0" stroke="#E5E7EB" vertical={false} />
              <XAxis dataKey="label" stroke="#6B7280" tick={TICK_STYLE} />
              <YAxis stroke="#6B7280" tick={TICK_STYLE} tickFormatter={yTickLakh} />
              <Tooltip formatter={(v) => inr(v)} contentStyle={TOOLTIP_STYLE} />
              <Legend wrapperStyle={LEGEND_STYLE} />
              <Bar dataKey="forecast" fill={TYPE_COLORS_F[activeType]} name={`${activeType} Forecast`} />
              <Bar dataKey="actual" fill={TYPE_COLORS_A[activeType]} name={`${activeType} Actual`} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Consolidated three-type table */}
      <div className="rudaya-card overflow-hidden">
        <div className="px-5 py-4 border-b border-neutral-200 flex items-center justify-between">
          <div>
            <h3 className="font-heading font-semibold text-lg">Monthly Consolidation · All Types</h3>
            <p className="text-xs text-neutral-500 mt-0.5">Forecast = Sales Forecast entries + Quotation lines (non-lost). Actual = transactions.</p>
          </div>
        </div>
        <div className="overflow-x-auto rudaya-scroll">
          <table className="w-full min-w-[900px]" data-testid="forecast-table">
            <thead className="bg-neutral-50 border-b border-neutral-200">
              <tr className="text-left text-[10px] uppercase tracking-wider text-neutral-500">
                <th className="px-4 py-3" rowSpan="2">Month</th>
                <th className="px-3 py-2 text-center border-l border-neutral-200" colSpan="3">Revenue</th>
                <th className="px-3 py-2 text-center border-l border-neutral-200" colSpan="3">Cost</th>
                <th className="px-3 py-2 text-center border-l border-neutral-200" colSpan="3">Expense</th>
              </tr>
              <tr className="text-right text-[10px] uppercase tracking-wider text-neutral-500 bg-neutral-50 border-b border-neutral-200">
                <th className="px-2 py-1.5 border-l border-neutral-200">F</th>
                <th className="px-2 py-1.5">A</th>
                <th className="px-2 py-1.5">Var</th>
                <th className="px-2 py-1.5 border-l border-neutral-200">F</th>
                <th className="px-2 py-1.5">A</th>
                <th className="px-2 py-1.5">Var</th>
                <th className="px-2 py-1.5 border-l border-neutral-200">F</th>
                <th className="px-2 py-1.5">A</th>
                <th className="px-2 py-1.5">Var</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={r.month} className="border-b border-neutral-100 hover:bg-neutral-50 transition-colors" data-testid={`fc-row-${r.month}`}>
                  <td className="px-4 py-2 font-mono-tab text-xs whitespace-nowrap">{r.label} {r.year}</td>
                  {TYPES.map((t) => {
                    const f = r.forecast?.[t] || 0;
                    const a = r.actual?.[t] || 0;
                    const v = r.variance?.[t] || 0;
                    return (
                      <React.Fragment key={t}>
                        <td className="px-2 py-2 text-right font-mono-tab text-xs text-neutral-900 border-l border-neutral-100">{inr(f)}</td>
                        <td className="px-2 py-2 text-right font-mono-tab text-xs" style={{ color: TYPE_COLORS_A[t] }}>{inr(a)}</td>
                        <td className={`px-2 py-2 text-right font-mono-tab text-xs ${v >= 0 ? "text-blue-700" : "text-red-700"}`}>{f ? ((v >= 0 ? "+" : "") + inr(v)) : "—"}</td>
                      </React.Fragment>
                    );
                  })}
                </tr>
              ))}
            </tbody>
            <tfoot className="bg-neutral-900 text-white">
              <tr>
                <td className="px-4 py-3 uppercase text-[10px] tracking-widest">Total</td>
                {TYPES.map((t) => {
                  const f = data.total_forecast[t] || 0;
                  const a = data.total_actual[t] || 0;
                  const v = a - f;
                  return (
                    <React.Fragment key={t}>
                      <td className="px-2 py-3 text-right font-mono-tab text-xs border-l border-neutral-700">{inr(f)}</td>
                      <td className="px-2 py-3 text-right font-mono-tab text-xs">{inr(a)}</td>
                      <td className={`px-2 py-3 text-right font-mono-tab text-xs ${v >= 0 ? "text-blue-300" : "text-red-300"}`}>{v >= 0 ? "+" : ""}{inr(v)}</td>
                    </React.Fragment>
                  );
                })}
              </tr>
            </tfoot>
          </table>
        </div>
      </div>
    </Layout>
  );
}

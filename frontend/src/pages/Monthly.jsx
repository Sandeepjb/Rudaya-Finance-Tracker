import React, { useEffect, useState } from "react";
import Layout from "@/components/Layout";
import { api, inr } from "@/lib/api";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend } from "recharts";
import { TICK_STYLE, TOOLTIP_STYLE, LEGEND_STYLE, yTickLakh } from "@/lib/format";

export default function Monthly() {
  const [rows, setRows] = useState([]);
  useEffect(() => { api.get("/reports/monthly").then((r) => setRows(r.data)); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  return (
    <Layout title="Revenue vs Expense" subtitle="Monthly breakdown across the fiscal year">
      <div className="rudaya-card p-5 mb-4">
        <div className="h-80">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rows}>
              <CartesianGrid strokeDasharray="0" stroke="#E5E7EB" vertical={false} />
              <XAxis dataKey="label" stroke="#6B7280" tick={TICK_STYLE} />
              <YAxis stroke="#6B7280" tick={TICK_STYLE} tickFormatter={yTickLakh} />
              <Tooltip formatter={(v) => inr(v)} contentStyle={TOOLTIP_STYLE} />
              <Legend wrapperStyle={LEGEND_STYLE} />
              <Bar dataKey="revenue" fill="#059669" name="Revenue" />
              <Bar dataKey="cost" fill="#DC2626" name="Cost" />
              <Bar dataKey="expense" fill="#D97706" name="Expense" />
              <Bar dataKey="net_profit" fill="#2563EB" name="Net Profit" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="rudaya-card overflow-hidden">
        <table className="w-full" data-testid="monthly-table">
          <thead className="bg-neutral-50 border-b border-neutral-200">
            <tr className="text-left text-[11px] uppercase tracking-wider text-neutral-500">
              <th className="px-4 py-3">Month</th>
              <th className="px-3 py-3 text-right">Revenue</th>
              <th className="px-3 py-3 text-right">Cost</th>
              <th className="px-3 py-3 text-right">Gross Profit</th>
              <th className="px-3 py-3 text-right">Expense</th>
              <th className="px-4 py-3 text-right">Net Profit</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.label} className="border-b border-neutral-100 hover:bg-neutral-50 transition-colors">
                <td className="px-4 py-2.5 font-mono-tab text-sm">{r.label}</td>
                <td className="px-3 py-2.5 text-right font-mono-tab text-sm text-emerald-700">{inr(r.revenue)}</td>
                <td className="px-3 py-2.5 text-right font-mono-tab text-sm text-red-700">{inr(r.cost)}</td>
                <td className={`px-3 py-2.5 text-right font-mono-tab text-sm ${r.gross_profit >= 0 ? "text-neutral-900" : "text-red-700"}`}>{inr(r.gross_profit)}</td>
                <td className="px-3 py-2.5 text-right font-mono-tab text-sm text-amber-700">{inr(r.expense)}</td>
                <td className={`px-4 py-2.5 text-right font-mono-tab text-sm font-semibold ${r.net_profit >= 0 ? "text-blue-700" : "text-red-700"}`}>{inr(r.net_profit)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Layout>
  );
}

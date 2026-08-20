import React, { useEffect, useState } from "react";
import Layout from "@/components/Layout";
import { api, inr } from "@/lib/api";
import { TrendUp, TrendDown, Wallet, ChartLine, Bank } from "@phosphor-icons/react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend, LineChart, Line } from "recharts";

const Kpi = ({ label, value, color, icon: Icon, testid }) => (
  <div className="rudaya-card p-5" data-testid={testid}>
    <div className="flex items-start justify-between">
      <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500">{label}</div>
      <Icon size={18} className="text-neutral-400" />
    </div>
    <div className="mt-3 font-mono-tab font-semibold text-2xl tracking-tight" style={{ color }}>{inr(value)}</div>
  </div>
);

export default function Dashboard() {
  const [summary, setSummary] = useState(null);
  const [monthly, setMonthly] = useState([]);
  const [recent, setRecent] = useState([]);

  useEffect(() => {
    (async () => {
      const [s, m, t] = await Promise.all([
        api.get("/reports/summary"),
        api.get("/reports/monthly"),
        api.get("/transactions"),
      ]);
      setSummary(s.data);
      setMonthly(m.data);
      setRecent(t.data.slice(0, 8));
    })();
  }, []);

  return (
    <Layout title="Dashboard" subtitle="Overview of financial performance across all projects">
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <Kpi testid="kpi-total-revenue" label="Total Revenue" value={summary?.revenue || 0} color="#059669" icon={TrendUp} />
        <Kpi testid="kpi-total-cost" label="Total Cost" value={summary?.cost || 0} color="#DC2626" icon={TrendDown} />
        <Kpi testid="kpi-gross-profit" label="Gross Profit" value={summary?.gross_profit || 0} color="#111827" icon={ChartLine} />
        <Kpi testid="kpi-total-expense" label="Total Expense" value={summary?.expense || 0} color="#D97706" icon={Wallet} />
        <Kpi testid="kpi-net-profit" label="Net Profit" value={summary?.net_profit || 0} color="#2563EB" icon={Bank} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mt-6">
        <div className="rudaya-card p-5 lg:col-span-2" data-testid="chart-monthly-rev-vs-exp">
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500">Monthly</div>
              <h3 className="font-heading font-semibold text-lg">Revenue vs Cost vs Expense</h3>
            </div>
          </div>
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={monthly}>
                <CartesianGrid strokeDasharray="0" stroke="#E5E7EB" vertical={false} />
                <XAxis dataKey="label" stroke="#6B7280" tick={{ fontSize: 11, fontFamily: "JetBrains Mono" }} />
                <YAxis stroke="#6B7280" tick={{ fontSize: 11, fontFamily: "JetBrains Mono" }} tickFormatter={(v) => (v / 100000).toFixed(1) + "L"} />
                <Tooltip formatter={(v) => inr(v)} contentStyle={{ border: "1px solid #111827", borderRadius: 0, fontSize: 12 }} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="revenue" fill="#059669" name="Revenue" />
                <Bar dataKey="cost" fill="#DC2626" name="Cost" />
                <Bar dataKey="expense" fill="#D97706" name="Expense" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="rudaya-card p-5" data-testid="chart-net-profit-trend">
          <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500">Trend</div>
          <h3 className="font-heading font-semibold text-lg mb-4">Net Profit</h3>
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={monthly}>
                <CartesianGrid strokeDasharray="0" stroke="#E5E7EB" vertical={false} />
                <XAxis dataKey="label" stroke="#6B7280" tick={{ fontSize: 10, fontFamily: "JetBrains Mono" }} />
                <YAxis stroke="#6B7280" tick={{ fontSize: 10, fontFamily: "JetBrains Mono" }} tickFormatter={(v) => (v / 100000).toFixed(1) + "L"} />
                <Tooltip formatter={(v) => inr(v)} contentStyle={{ border: "1px solid #111827", borderRadius: 0, fontSize: 12 }} />
                <Line type="monotone" dataKey="net_profit" stroke="#2563EB" strokeWidth={2} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      <div className="rudaya-card mt-6" data-testid="recent-transactions">
        <div className="px-5 py-4 border-b border-neutral-200 flex items-center justify-between">
          <h3 className="font-heading font-semibold text-lg">Recent Transactions</h3>
          <a href="/transactions" className="text-xs uppercase tracking-wider text-neutral-600 hover:text-neutral-900">View all →</a>
        </div>
        <table className="w-full">
          <thead className="bg-neutral-50 border-b border-neutral-200">
            <tr className="text-left text-[11px] uppercase tracking-wider text-neutral-500">
              <th className="px-5 py-2">Date</th>
              <th className="px-3 py-2">Type</th>
              <th className="px-3 py-2">Account</th>
              <th className="px-3 py-2">Project</th>
              <th className="px-5 py-2 text-right">Amount</th>
            </tr>
          </thead>
          <tbody>
            {recent.map((t) => (
              <tr key={t.id} className="border-b border-neutral-100 hover:bg-neutral-50 transition-colors">
                <td className="px-5 py-2.5 font-mono-tab text-sm">{t.date?.slice(0, 10)}</td>
                <td className="px-3 py-2.5"><TypeBadge type={t.type} /></td>
                <td className="px-3 py-2.5 text-sm">{t.account}</td>
                <td className="px-3 py-2.5 font-mono-tab text-xs text-neutral-600">{t.project_id}</td>
                <td className="px-5 py-2.5 text-right font-mono-tab text-sm font-medium" style={{ color: t.type === "Revenue" ? "#059669" : t.type === "Cost" ? "#DC2626" : "#D97706" }}>{inr(t.amount)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Layout>
  );
}

export function TypeBadge({ type }) {
  const map = {
    Revenue: "border-emerald-600 text-emerald-700 bg-emerald-50",
    Cost: "border-red-600 text-red-700 bg-red-50",
    Expense: "border-amber-600 text-amber-700 bg-amber-50",
  };
  return <span className={`inline-block text-[10px] uppercase tracking-wider px-2 py-0.5 border ${map[type] || "border-neutral-400 text-neutral-700 bg-neutral-50"}`}>{type}</span>;
}

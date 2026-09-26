import React, { useCallback, useEffect, useState } from "react";
import { api, inr, formatApiError } from "@/lib/api";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";
import { TrendUp, TrendDown, Buildings, ListChecks, ChartLineUp, FileText } from "@phosphor-icons/react";
import { TypeBadge } from "@/components/TypeBadge";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, BarChart, Bar,
} from "recharts";

const currentYear = new Date().getFullYear();
const YEARS = [currentYear - 1, currentYear, currentYear + 1, currentYear + 2];

function Tile({ label, value, tone, testid }) {
  const cls = tone === "emerald" ? "text-emerald-700"
    : tone === "red" ? "text-red-700"
    : tone === "amber" ? "text-amber-700"
    : tone === "blue" ? "text-blue-700"
    : "text-neutral-900";
  return (
    <div className="rudaya-card p-4" data-testid={testid}>
      <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500">{label}</div>
      <div className={`mt-1 font-mono-tab font-semibold text-xl ${cls}`}>{value}</div>
    </div>
  );
}

export default function ProjectDetailDrawer({ projectId, open, onOpenChange }) {
  const [year, setYear] = useState(currentYear);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    try {
      const r = await api.get(`/reports/project-detail/${encodeURIComponent(projectId)}`, { params: { year } });
      setData(r.data);
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setLoading(false); }
  }, [projectId, year]);

  useEffect(() => { if (open) load(); }, [open, load]);

  const chartData = data?.rows?.map((r) => ({
    month: r.label,
    "Forecast Revenue": r.forecast.Revenue,
    "Actual Revenue": r.actual.Revenue,
    "Forecast Cost": r.forecast.Cost,
    "Actual Cost": r.actual.Cost,
  })) || [];

  const netProfit = data?.totals?.net_profit ?? 0;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full sm:max-w-4xl overflow-y-auto rounded-none border-l-2 border-l-neutral-900" data-testid="project-detail-drawer">
        <SheetHeader>
          <div className="text-[11px] uppercase tracking-[0.25em] text-neutral-500 flex items-center gap-2">
            <Buildings size={14} /> Project Drilldown
          </div>
          <SheetTitle className="font-heading text-2xl tracking-tight font-mono-tab" data-testid="pd-project-id">{projectId}</SheetTitle>
          <SheetDescription>
            Transactions, forecast vs actual and quotations scoped to this project.
          </SheetDescription>
        </SheetHeader>

        <div className="flex items-center justify-between mt-6 mb-4">
          <div className="text-xs uppercase tracking-wider text-neutral-500">FY view</div>
          <Select value={String(year)} onValueChange={(v) => setYear(parseInt(v))}>
            <SelectTrigger data-testid="pd-year-select" className="rounded-none w-28"><SelectValue /></SelectTrigger>
            <SelectContent>{YEARS.map((y) => <SelectItem key={y} value={String(y)}>{y}</SelectItem>)}</SelectContent>
          </Select>
        </div>

        {loading && <div className="py-16 text-center text-neutral-500 text-sm">Loading project details…</div>}

        {!loading && data && (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
              <Tile testid="pd-total-revenue" label="Revenue (all time)" value={inr(data.totals.revenue)} tone="emerald" />
              <Tile testid="pd-total-cost" label="Cost (all time)" value={inr(data.totals.cost)} tone="red" />
              <Tile testid="pd-total-expense" label="Expense (all time)" value={inr(data.totals.expense)} tone="amber" />
              <Tile testid="pd-total-net" label="Net Profit" value={inr(netProfit)} tone={netProfit >= 0 ? "blue" : "red"} />
            </div>

            <Tabs defaultValue="forecast" className="mt-4">
              <TabsList className="rounded-none">
                <TabsTrigger value="forecast" className="rounded-none" data-testid="pd-tab-forecast">
                  <ChartLineUp size={14} className="mr-2" /> Forecast vs Actual
                </TabsTrigger>
                <TabsTrigger value="transactions" className="rounded-none" data-testid="pd-tab-transactions">
                  <ListChecks size={14} className="mr-2" /> Transactions ({data.transaction_count})
                </TabsTrigger>
                <TabsTrigger value="quotations" className="rounded-none" data-testid="pd-tab-quotations">
                  <FileText size={14} className="mr-2" /> Quotations ({data.quotations.length})
                </TabsTrigger>
              </TabsList>

              <TabsContent value="forecast" className="mt-4 space-y-4">
                <div className="rudaya-card p-4">
                  <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500 mb-2">Revenue: forecast vs actual · {year}</div>
                  <div style={{ width: "100%", height: 220 }}>
                    <ResponsiveContainer>
                      <LineChart data={chartData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#e5e5e5" />
                        <XAxis dataKey="month" tick={{ fontSize: 11 }} />
                        <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `${(v / 100000).toFixed(0)}L`} />
                        <Tooltip formatter={(v) => inr(v)} />
                        <Legend wrapperStyle={{ fontSize: 11 }} />
                        <Line type="monotone" dataKey="Forecast Revenue" stroke="#64748b" strokeDasharray="4 2" dot={false} />
                        <Line type="monotone" dataKey="Actual Revenue" stroke="#059669" strokeWidth={2} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </div>

                <div className="rudaya-card p-4">
                  <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500 mb-2">Cost: forecast vs actual · {year}</div>
                  <div style={{ width: "100%", height: 200 }}>
                    <ResponsiveContainer>
                      <BarChart data={chartData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#e5e5e5" />
                        <XAxis dataKey="month" tick={{ fontSize: 11 }} />
                        <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `${(v / 100000).toFixed(0)}L`} />
                        <Tooltip formatter={(v) => inr(v)} />
                        <Legend wrapperStyle={{ fontSize: 11 }} />
                        <Bar dataKey="Forecast Cost" fill="#94a3b8" />
                        <Bar dataKey="Actual Cost" fill="#dc2626" />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>

                <div className="rudaya-card overflow-hidden">
                  <div className="overflow-x-auto rudaya-scroll max-h-[320px]">
                    <table className="w-full min-w-[720px] text-xs" data-testid="pd-forecast-table">
                      <thead className="bg-neutral-50 border-b border-neutral-200 sticky top-0">
                        <tr className="text-left uppercase tracking-wider text-[10px] text-neutral-500">
                          <th className="px-3 py-2">Month</th>
                          <th className="px-3 py-2 text-right">Rev F</th>
                          <th className="px-3 py-2 text-right">Rev A</th>
                          <th className="px-3 py-2 text-right">Rev %</th>
                          <th className="px-3 py-2 text-right">Cost F</th>
                          <th className="px-3 py-2 text-right">Cost A</th>
                          <th className="px-3 py-2 text-right">Cost %</th>
                          <th className="px-3 py-2 text-right">Exp A</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.rows.map((r) => (
                          <tr key={r.month} className="border-b border-neutral-100 hover:bg-neutral-50">
                            <td className="px-3 py-1.5 font-medium">{r.label}</td>
                            <td className="px-3 py-1.5 text-right font-mono-tab">{inr(r.forecast.Revenue)}</td>
                            <td className="px-3 py-1.5 text-right font-mono-tab text-emerald-700">{inr(r.actual.Revenue)}</td>
                            <td className="px-3 py-1.5 text-right font-mono-tab text-neutral-500">
                              {r.achievement_pct.Revenue != null ? `${r.achievement_pct.Revenue.toFixed(0)}%` : "—"}
                            </td>
                            <td className="px-3 py-1.5 text-right font-mono-tab">{inr(r.forecast.Cost)}</td>
                            <td className="px-3 py-1.5 text-right font-mono-tab text-red-700">{inr(r.actual.Cost)}</td>
                            <td className="px-3 py-1.5 text-right font-mono-tab text-neutral-500">
                              {r.achievement_pct.Cost != null ? `${r.achievement_pct.Cost.toFixed(0)}%` : "—"}
                            </td>
                            <td className="px-3 py-1.5 text-right font-mono-tab text-amber-700">{inr(r.actual.Expense)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </TabsContent>

              <TabsContent value="transactions" className="mt-4">
                <div className="rudaya-card overflow-hidden">
                  <div className="overflow-x-auto rudaya-scroll max-h-[520px]">
                    <table className="w-full text-xs" data-testid="pd-transactions-table">
                      <thead className="bg-neutral-50 border-b border-neutral-200 sticky top-0">
                        <tr className="text-left uppercase tracking-wider text-[10px] text-neutral-500">
                          <th className="px-3 py-2">Date</th>
                          <th className="px-3 py-2">Type</th>
                          <th className="px-3 py-2">Account</th>
                          <th className="px-3 py-2 text-right">Amount</th>
                          <th className="px-3 py-2">Notes</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.transactions.map((t) => (
                          <tr key={t.id} className="border-b border-neutral-100 hover:bg-neutral-50">
                            <td className="px-3 py-1.5 font-mono-tab">{(t.date || "").slice(0, 10)}</td>
                            <td className="px-3 py-1.5"><TypeBadge type={t.type} /></td>
                            <td className="px-3 py-1.5">{t.account}</td>
                            <td className="px-3 py-1.5 text-right font-mono-tab">{inr(t.amount)}</td>
                            <td className="px-3 py-1.5 text-neutral-600">{t.notes}</td>
                          </tr>
                        ))}
                        {data.transactions.length === 0 && (
                          <tr><td colSpan="5" className="px-4 py-10 text-center text-neutral-400">No transactions for this project.</td></tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </TabsContent>

              <TabsContent value="quotations" className="mt-4">
                <div className="rudaya-card overflow-hidden">
                  <div className="overflow-x-auto rudaya-scroll max-h-[520px]">
                    <table className="w-full text-xs" data-testid="pd-quotations-table">
                      <thead className="bg-neutral-50 border-b border-neutral-200 sticky top-0">
                        <tr className="text-left uppercase tracking-wider text-[10px] text-neutral-500">
                          <th className="px-3 py-2">Number</th>
                          <th className="px-3 py-2">Client</th>
                          <th className="px-3 py-2">Expected</th>
                          <th className="px-3 py-2">Status</th>
                          <th className="px-3 py-2 text-right">Rev</th>
                          <th className="px-3 py-2 text-right">Cost</th>
                          <th className="px-3 py-2 text-right">Net</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.quotations.map((q) => (
                          <tr key={q.id} className="border-b border-neutral-100 hover:bg-neutral-50">
                            <td className="px-3 py-1.5 font-mono-tab">{q.quotation_number}</td>
                            <td className="px-3 py-1.5">{q.client_name || "—"}</td>
                            <td className="px-3 py-1.5">{q.expected_year}-{String(q.expected_month || 1).padStart(2, "0")}</td>
                            <td className="px-3 py-1.5 uppercase tracking-wider text-[10px]">{q.status}</td>
                            <td className="px-3 py-1.5 text-right font-mono-tab text-emerald-700">{inr(q.totals.Revenue)}</td>
                            <td className="px-3 py-1.5 text-right font-mono-tab text-red-700">{inr(q.totals.Cost)}</td>
                            <td className={`px-3 py-1.5 text-right font-mono-tab font-medium ${q.totals.net >= 0 ? "text-blue-700" : "text-red-700"}`}>{inr(q.totals.net)}</td>
                          </tr>
                        ))}
                        {data.quotations.length === 0 && (
                          <tr><td colSpan="7" className="px-4 py-10 text-center text-neutral-400">No non-lost quotations for this project.</td></tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </TabsContent>
            </Tabs>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}

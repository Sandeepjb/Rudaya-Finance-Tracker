import React, { useEffect, useMemo, useState } from "react";
import Layout from "@/components/Layout";
import { api, inr } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { MagnifyingGlass, ArrowRight } from "@phosphor-icons/react";
import ProjectDetailDrawer from "@/components/ProjectDetailDrawer";

export default function ProjectPnl() {
  const [rows, setRows] = useState([]);
  const [q, setQ] = useState("");
  const [openProject, setOpenProject] = useState(null);

  useEffect(() => { api.get("/reports/project-pnl").then((r) => setRows(r.data)); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  const filtered = useMemo(
    () => rows.filter((r) => !q || r.project_id.toLowerCase().includes(q.toLowerCase())),
    [rows, q]
  );

  const totals = filtered.reduce(
    (a, r) => ({
      revenue: a.revenue + r.revenue, cost: a.cost + r.cost, expense: a.expense + r.expense,
      gross_profit: a.gross_profit + r.gross_profit, net_profit: a.net_profit + r.net_profit,
    }),
    { revenue: 0, cost: 0, expense: 0, gross_profit: 0, net_profit: 0 }
  );

  return (
    <Layout title="Project-wise P&L" subtitle="Click any row for the full drilldown · transactions, forecast vs actual, quotations">
      <div className="rudaya-card p-4 mb-4">
        <div className="relative max-w-sm">
          <MagnifyingGlass size={14} className="absolute left-3 top-2.5 text-neutral-400" />
          <Input data-testid="pnl-search" className="rounded-none pl-8" placeholder="Search Project ID…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
      </div>

      <div className="rudaya-card overflow-hidden">
        <div className="max-h-[calc(100vh-260px)] overflow-auto rudaya-scroll">
          <table className="w-full" data-testid="project-pnl-table">
            <thead className="bg-neutral-50 border-b border-neutral-200 sticky top-0 z-10">
              <tr className="text-left text-[11px] uppercase tracking-wider text-neutral-500">
                <th className="px-4 py-3">Project ID</th>
                <th className="px-3 py-3 text-right">Revenue</th>
                <th className="px-3 py-3 text-right">Cost</th>
                <th className="px-3 py-3 text-right">Gross Profit</th>
                <th className="px-3 py-3 text-right">Expense</th>
                <th className="px-4 py-3 text-right">Net Profit</th>
                <th className="px-3 py-3 w-10"></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => (
                <tr
                  key={r.project_id}
                  className="border-b border-neutral-100 hover:bg-neutral-50 transition-colors cursor-pointer"
                  onClick={() => setOpenProject(r.project_id)}
                  data-testid={`project-row-${r.project_id}`}
                >
                  <td className="px-4 py-2.5 font-mono-tab text-xs text-blue-700 underline underline-offset-2 decoration-dotted">{r.project_id}</td>
                  <td className="px-3 py-2.5 text-right font-mono-tab text-sm text-emerald-700">{inr(r.revenue)}</td>
                  <td className="px-3 py-2.5 text-right font-mono-tab text-sm text-red-700">{inr(r.cost)}</td>
                  <td className={`px-3 py-2.5 text-right font-mono-tab text-sm font-medium ${r.gross_profit >= 0 ? "text-neutral-900" : "text-red-700"}`}>{inr(r.gross_profit)}</td>
                  <td className="px-3 py-2.5 text-right font-mono-tab text-sm text-amber-700">{inr(r.expense)}</td>
                  <td className={`px-4 py-2.5 text-right font-mono-tab text-sm font-semibold ${r.net_profit >= 0 ? "text-blue-700" : "text-red-700"}`}>{inr(r.net_profit)}</td>
                  <td className="px-3 py-2.5 text-neutral-400"><ArrowRight size={14} /></td>
                </tr>
              ))}
            </tbody>
            <tfoot className="bg-neutral-900 text-white sticky bottom-0">
              <tr>
                <td className="px-4 py-3 uppercase text-[11px] tracking-widest">Total</td>
                <td className="px-3 py-3 text-right font-mono-tab text-sm">{inr(totals.revenue)}</td>
                <td className="px-3 py-3 text-right font-mono-tab text-sm">{inr(totals.cost)}</td>
                <td className="px-3 py-3 text-right font-mono-tab text-sm">{inr(totals.gross_profit)}</td>
                <td className="px-3 py-3 text-right font-mono-tab text-sm">{inr(totals.expense)}</td>
                <td className="px-4 py-3 text-right font-mono-tab text-sm font-semibold">{inr(totals.net_profit)}</td>
                <td></td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>

      <ProjectDetailDrawer
        projectId={openProject}
        open={!!openProject}
        onOpenChange={(o) => !o && setOpenProject(null)}
      />
    </Layout>
  );
}

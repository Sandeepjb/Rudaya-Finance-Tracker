import React, { useCallback, useEffect, useState } from "react";
import Layout from "@/components/Layout";
import { api, inr } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Plus, SquaresFour, ListBullets } from "@phosphor-icons/react";
import BankTxnCard from "@/components/bank/BankTxnCard";
import BankFilters, { EMPTY_FILTERS, filtersToParams } from "@/components/bank/BankFilters";
import BankEditDialog from "@/components/bank/BankEditDialog";
import ExplainDialog from "@/components/bank/ExplainDialog";
import AuditDialog from "@/components/bank/AuditDialog";
import ManualBankTxnDialog from "@/components/bank/ManualBankTxnDialog";
import MappingRulesTab from "@/components/bank/MappingRulesTab";
import IngestionHistoryTab from "@/components/bank/IngestionHistoryTab";
import StatementImportTab from "@/components/bank/StatementImportTab";
import ParsingTemplatesTab from "@/components/bank/ParsingTemplatesTab";
import BulkApproveBar from "@/components/bank/BulkApproveBar";
import QueueTab from "@/components/bank/QueueTab";
import ParserTestTab from "@/components/bank/ParserTestTab";
import ReconciliationTab from "@/components/bank/ReconciliationTab";
import AzureStatementTab from "@/components/bank/AzureStatementTab";
import DuplicateReviewDialog from "@/components/bank/DuplicateReviewDialog";
import { ConfidenceBadge, DirectionBadge, StatusBadge } from "@/components/bank/ConfidenceBadge";
import { TypeBadge } from "@/components/TypeBadge";
import { STATUS_TABS, fmtDate } from "@/lib/bankInbox";

function TableView({ rows, onSelect }) {
  return (
    <div className="bg-white border border-neutral-200 overflow-auto" data-testid="bank-table-view">
      <table className="w-full text-sm">
        <thead className="bg-neutral-50 text-[10px] uppercase tracking-wider text-neutral-500">
          <tr><th className="text-left p-2">Date</th><th className="text-left p-2">Bank</th><th className="text-left p-2">Dir</th><th className="text-right p-2">Amount</th><th className="text-left p-2">Narration</th><th className="text-left p-2">Suggested</th><th className="text-left p-2">Confidence</th><th className="text-left p-2">Status</th></tr>
        </thead>
        <tbody>
          {rows.map((t) => (
            <tr key={t.id} className="border-t border-neutral-100 hover:bg-neutral-50 cursor-pointer" onClick={() => onSelect(t)} data-testid={`bank-table-row-${t.id}`}>
              <td className="p-2 font-mono-tab text-xs">{fmtDate(t.transaction_date)}</td>
              <td className="p-2 text-xs">{t.bank_name}</td>
              <td className="p-2"><DirectionBadge direction={t.direction} /></td>
              <td className="p-2 text-right font-mono-tab">{inr(t.amount)}</td>
              <td className="p-2 text-xs max-w-[260px] truncate" title={t.narration}>{t.narration}</td>
              <td className="p-2 text-xs">{t.suggestion?.type && <TypeBadge type={(t.final || t.user_edits || t.suggestion).type} />} {(t.final || t.user_edits || t.suggestion)?.account} · <span className="font-mono-tab">{(t.final || t.user_edits || t.suggestion)?.project_id}</span></td>
              <td className="p-2"><ConfidenceBadge value={t.suggestion?.confidence} showBar={false} /></td>
              <td className="p-2"><StatusBadge status={t.status} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function BankTransactions() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [tab, setTab] = useState("pending");
  const [rows, setRows] = useState([]);
  const [stats, setStats] = useState({});
  const [meta, setMeta] = useState(null);
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [view, setView] = useState("cards");
  const [loading, setLoading] = useState(false);
  const [editTxn, setEditTxn] = useState(null);
  const [explainTxn, setExplainTxn] = useState(null);
  const [auditTxn, setAuditTxn] = useState(null);
  const [dupReview, setDupReview] = useState(null);
  const [manualOpen, setManualOpen] = useState(false);
  const [selected, setSelected] = useState(new Set());
  const toggle = (id) => setSelected((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });

  const load = useCallback(async () => {
    if (!isAdmin) return;
    setLoading(true);
    try {
      const status = STATUS_TABS.some((t) => t.key === tab) ? tab : "all";
      const [r, s] = await Promise.all([
        api.get("/bank-transactions", { params: { status, ...filtersToParams(filters) } }),
        api.get("/bank-transactions/stats"),
      ]);
      setRows(status === "duplicate" ? [...r.data].sort((a, b) => (a.status === "duplicate" ? 0 : 1) - (b.status === "duplicate" ? 0 : 1)) : r.data); setStats(s.data);
    } catch { /* ignore */ } finally { setLoading(false); }
  }, [isAdmin, tab, filters]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { api.get("/meta").then((r) => setMeta(r.data)).catch(() => {}); }, []);

  if (!isAdmin) {
    return (
      <Layout title="Bank Transactions" subtitle="Bank Transaction Inbox">
        <div className="bg-white border border-neutral-200 p-8 text-center text-neutral-600" data-testid="bank-admin-only">Bank transactions are restricted to administrators.</div>
      </Layout>
    );
  }

  const showList = STATUS_TABS.some((t) => t.key === tab);

  return (
    <Layout
      title="Bank Transactions"
      subtitle="AI-assisted inbox · human-in-the-loop approval · nothing posts without you"
      actions={
        <Button data-testid="manual-bank-btn" onClick={() => setManualOpen(true)} className="rounded-none bg-neutral-900 hover:bg-neutral-700"><Plus size={16} className="mr-1" /> Manual Bank Transaction</Button>
      }
    >
      <Tabs value={tab} onValueChange={setTab}>
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <TabsList className="rounded-none bg-white border border-neutral-200 h-auto p-1 flex-wrap">
            {STATUS_TABS.map((t) => (
              <TabsTrigger key={t.key} value={t.key} data-testid={`tab-${t.key}`} className="rounded-none data-[state=active]:bg-neutral-900 data-[state=active]:text-white text-xs">
                {t.label} <span className="ml-1.5 font-mono-tab text-[10px] opacity-70">{stats[t.key] ?? 0}{t.key === "duplicate" && stats.duplicate_rejected ? ` +${stats.duplicate_rejected}` : ""}</span>
              </TabsTrigger>
            ))}
            <TabsTrigger value="rules" data-testid="tab-rules" className="rounded-none data-[state=active]:bg-neutral-900 data-[state=active]:text-white text-xs">Mapping Rules</TabsTrigger>
            <TabsTrigger value="import" data-testid="tab-import" className="rounded-none data-[state=active]:bg-neutral-900 data-[state=active]:text-white text-xs">Import Statement</TabsTrigger>
            <TabsTrigger value="azure" data-testid="tab-azure" className="rounded-none data-[state=active]:bg-neutral-900 data-[state=active]:text-white text-xs">Import Bank Statement</TabsTrigger>
            <TabsTrigger value="queue" data-testid="tab-queue" className="rounded-none data-[state=active]:bg-neutral-900 data-[state=active]:text-white text-xs">M365 Queue</TabsTrigger>
            <TabsTrigger value="parsers" data-testid="tab-parsers" className="rounded-none data-[state=active]:bg-neutral-900 data-[state=active]:text-white text-xs">Parser Test</TabsTrigger>
            <TabsTrigger value="reconciliation" data-testid="tab-reconciliation" className="rounded-none data-[state=active]:bg-neutral-900 data-[state=active]:text-white text-xs">Reconciliation</TabsTrigger>
            <TabsTrigger value="templates" data-testid="tab-templates" className="rounded-none data-[state=active]:bg-neutral-900 data-[state=active]:text-white text-xs">Parsing Templates</TabsTrigger>
            <TabsTrigger value="history" data-testid="tab-history" className="rounded-none data-[state=active]:bg-neutral-900 data-[state=active]:text-white text-xs">Ingestion History</TabsTrigger>
          </TabsList>
          {showList && (
            <div className="flex border border-neutral-200 bg-white">
              <button data-testid="view-cards" onClick={() => setView("cards")} className={`p-2 ${view === "cards" ? "bg-neutral-900 text-white" : "text-neutral-600"}`}><SquaresFour size={16} /></button>
              <button data-testid="view-table" onClick={() => setView("table")} className={`p-2 ${view === "table" ? "bg-neutral-900 text-white" : "text-neutral-600"}`}><ListBullets size={16} /></button>
            </div>
          )}
        </div>

        {STATUS_TABS.map((t) => (
          <TabsContent key={t.key} value={t.key} className="mt-4 space-y-4">
            <BankFilters f={filters} setF={setFilters} meta={meta} onReset={() => setFilters(EMPTY_FILTERS)} />
            {t.key === "pending" && rows.length > 0 && <BulkApproveBar rows={rows} selected={selected} setSelected={setSelected} onDone={load} />}
            {loading && <div className="text-sm text-neutral-500" data-testid="bank-loading">Loading…</div>}
            {!loading && !rows.length && <div className="bg-white border border-neutral-200 p-10 text-center text-neutral-500 text-sm" data-testid="bank-empty">No {t.key === "all" ? "" : t.key} bank transactions.</div>}
            {!loading && rows.length > 0 && (view === "cards" ? (
              <div className="grid grid-cols-1 xl:grid-cols-2 gap-4" data-testid="bank-card-grid">
                {rows.map((x) => <BankTxnCard key={x.id} txn={x} onChanged={load} onEdit={setEditTxn} onExplain={setExplainTxn} onAudit={setAuditTxn} onDuplicateReview={(x, mode) => setDupReview({ txn: x, mode })} selectable={t.key === "pending"} selected={selected.has(x.id)} onToggle={toggle} />)}
              </div>
            ) : <TableView rows={rows} onSelect={setExplainTxn} />)}
          </TabsContent>
        ))}
        <TabsContent value="rules" className="mt-4"><MappingRulesTab meta={meta} /></TabsContent>
        <TabsContent value="import" className="mt-4"><StatementImportTab onImported={load} /></TabsContent>
        <TabsContent value="templates" className="mt-4"><ParsingTemplatesTab /></TabsContent>
        <TabsContent value="queue" className="mt-4"><QueueTab /></TabsContent>
        <TabsContent value="azure" className="mt-4"><AzureStatementTab onSent={load} /></TabsContent>
        <TabsContent value="parsers" className="mt-4"><ParserTestTab /></TabsContent>
        <TabsContent value="reconciliation" className="mt-4"><ReconciliationTab /></TabsContent>
        <TabsContent value="history" className="mt-4"><IngestionHistoryTab /></TabsContent>
      </Tabs>

      <BankEditDialog txn={editTxn} meta={meta} open={!!editTxn} onOpenChange={(o) => !o && setEditTxn(null)} onSaved={load} />
      <ExplainDialog txn={explainTxn} open={!!explainTxn} onOpenChange={(o) => !o && setExplainTxn(null)} />
      <AuditDialog txn={auditTxn} open={!!auditTxn} onOpenChange={(o) => !o && setAuditTxn(null)} />
      <DuplicateReviewDialog txn={dupReview?.txn} mode={dupReview?.mode} open={!!dupReview} onOpenChange={(o) => !o && setDupReview(null)} onChanged={load} />
      <ManualBankTxnDialog open={manualOpen} onOpenChange={setManualOpen} onCreated={() => { setTab("pending"); load(); }} />
    </Layout>
  );
}

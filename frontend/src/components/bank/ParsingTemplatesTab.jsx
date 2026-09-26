import React, { useCallback, useEffect, useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { Plus, Trash, FloppyDisk, Flask, Power } from "@phosphor-icons/react";

const KEYS = ["amount", "debit", "credit", "date", "narration", "reference", "account"];
const EMPTY = { bank_name: "", name: "", enabled: true, priority: 10, patterns: Object.fromEntries(KEYS.map((k) => [k, ""])), sample: "" };

function TemplateEditor({ tpl, onSaved, onDeleted }) {
  const [form, setForm] = useState(tpl);
  const [test, setTest] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setForm(tpl); setTest(null); }, [tpl]);
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const setP = (k, v) => setForm((f) => ({ ...f, patterns: { ...f.patterns, [k]: v } }));

  const run = async (fn, msg) => {
    setBusy(true);
    try { const r = await fn(); if (msg) toast.success(msg); return r; }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const save = () => run(async () => {
    const body = { ...form, priority: parseInt(form.priority) || 10 };
    const r = form.id ? await api.put(`/bank-transactions/templates/${form.id}`, body) : await api.post("/bank-transactions/templates", body);
    onSaved(r.data);
  }, "Template saved");
  const doTest = () => run(async () => {
    const r = await api.post("/bank-transactions/templates/test", { raw_text: form.sample, patterns: form.patterns, bank_name: form.bank_name });
    setTest(r.data);
  });
  const del = () => { if (window.confirm("Delete this template?")) run(async () => { await api.delete(`/bank-transactions/templates/${form.id}`); onDeleted(); }, "Template deleted"); };

  return (
    <div className="bg-white border border-neutral-200 p-4 space-y-3" data-testid="template-editor">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div><Label className="text-[10px] uppercase tracking-wider text-neutral-500">Bank</Label><Input data-testid="tpl-bank" className="rounded-none mt-1" value={form.bank_name} onChange={(e) => set("bank_name", e.target.value)} /></div>
        <div><Label className="text-[10px] uppercase tracking-wider text-neutral-500">Template name</Label><Input data-testid="tpl-name" className="rounded-none mt-1" value={form.name} onChange={(e) => set("name", e.target.value)} /></div>
        <div><Label className="text-[10px] uppercase tracking-wider text-neutral-500">Priority (low = first)</Label><Input data-testid="tpl-priority" type="number" className="rounded-none mt-1 font-mono-tab" value={form.priority} onChange={(e) => set("priority", e.target.value)} /></div>
        <div className="flex items-end"><Button data-testid="tpl-enabled" variant="outline" className={`rounded-none w-full ${form.enabled ? "border-emerald-600 text-emerald-700" : "border-neutral-400 text-neutral-500"}`} onClick={() => set("enabled", !form.enabled)}><Power size={14} className="mr-1" /> {form.enabled ? "Enabled" : "Disabled"}</Button></div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        {KEYS.map((k) => (
          <div key={k}>
            <Label className="text-[10px] uppercase tracking-wider text-neutral-500">{k} regex {k === "amount" && "(required, group 1 = value)"}</Label>
            <Input data-testid={`tpl-pattern-${k}`} className="rounded-none mt-1 font-mono-tab text-xs" value={form.patterns?.[k] || ""} onChange={(e) => setP(k, e.target.value)} />
          </div>
        ))}
      </div>
      <div>
        <Label className="text-[10px] uppercase tracking-wider text-neutral-500">Sample alert text (used by Test)</Label>
        <textarea data-testid="tpl-sample" className="w-full mt-1 rounded-none border border-neutral-300 p-2 text-sm font-mono-tab h-24" value={form.sample} onChange={(e) => set("sample", e.target.value)} />
      </div>
      {test && (
        <div className={`border p-3 text-xs ${test.errors.length ? "border-red-400 bg-red-50" : "border-emerald-500 bg-emerald-50"}`} data-testid="tpl-test-result">
          <div className="font-medium mb-1">{test.errors.length ? `Parse issues: ${test.errors.join(", ")}` : "Parsed successfully"}</div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            {Object.entries(test.fields || {}).map(([k, v]) => <div key={k}><span className="text-neutral-500 uppercase text-[10px]">{k}</span><div className="font-mono-tab break-all">{String(v) || "—"}</div></div>)}
          </div>
        </div>
      )}
      <div className="flex justify-between">
        {form.id ? <Button data-testid="tpl-delete" variant="ghost" className="rounded-none text-red-700" onClick={del} disabled={busy}><Trash size={14} className="mr-1" /> Delete</Button> : <span />}
        <div className="flex gap-2">
          <Button data-testid="tpl-test" variant="outline" className="rounded-none" onClick={doTest} disabled={busy || !form.sample}><Flask size={14} className="mr-1" /> Test against sample</Button>
          <Button data-testid="tpl-save" className="rounded-none bg-neutral-900 hover:bg-neutral-700" onClick={save} disabled={busy}><FloppyDisk size={14} className="mr-1" /> Save</Button>
        </div>
      </div>
    </div>
  );
}

export default function ParsingTemplatesTab() {
  const [tpls, setTpls] = useState([]);
  const [sel, setSel] = useState(null);
  const load = useCallback(async () => {
    try { const r = await api.get("/bank-transactions/templates"); setTpls(r.data); return r.data; } catch { return []; }
  }, []);
  useEffect(() => { load().then((d) => { if (d.length && !sel) setSel(d[0]); }); }, [load]); // eslint-disable-line

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4" data-testid="parsing-templates-tab">
      <div className="bg-white border border-neutral-200">
        <div className="p-3 border-b border-neutral-200 flex items-center justify-between">
          <span className="text-[10px] uppercase tracking-[0.2em] text-neutral-500">Per-bank alert templates</span>
          <Button data-testid="tpl-new" size="sm" variant="outline" className="rounded-none" onClick={() => setSel({ ...EMPTY })}><Plus size={14} className="mr-1" /> New</Button>
        </div>
        {tpls.map((t) => (
          <button key={t.id} data-testid={`tpl-item-${t.id}`} onClick={() => setSel(t)} className={`w-full text-left px-3 py-2 border-b border-neutral-100 text-sm hover:bg-neutral-50 ${sel?.id === t.id ? "bg-neutral-100 border-l-2 border-l-neutral-900" : ""} ${t.enabled ? "" : "opacity-50"}`}>
            <div className="font-medium">{t.bank_name}</div>
            <div className="text-xs text-neutral-500">{t.name} · used {t.uses}× {t.is_default && "· default"}</div>
          </button>
        ))}
        {!tpls.length && <div className="p-4 text-sm text-neutral-500">No templates.</div>}
      </div>
      <div className="lg:col-span-2">
        {sel ? <TemplateEditor tpl={sel} onSaved={(t) => { load(); setSel(t); }} onDeleted={() => { load().then((d) => setSel(d[0] || null)); }} /> : <div className="bg-white border border-neutral-200 p-8 text-center text-sm text-neutral-500">Select or create a template.</div>}
      </div>
    </div>
  );
}

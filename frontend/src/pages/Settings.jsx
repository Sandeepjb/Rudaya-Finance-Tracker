import React, { useEffect, useState } from "react";
import Layout from "@/components/Layout";
import { api, formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";

export default function Settings() {
  const [meta, setMeta] = useState({ project_ids: [], accounts: [] });
  const [newProj, setNewProj] = useState({ code: "", description: "" });
  const [newAcc, setNewAcc] = useState("");

  const load = () => api.get("/meta").then((r) => setMeta(r.data));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, []);

  const addProject = async () => {
    try {
      await api.post("/meta/project-ids", newProj);
      toast.success("Project ID added");
      setNewProj({ code: "", description: "" });
      load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  const addAccount = async () => {
    try {
      await api.post("/meta/accounts", { name: newAcc });
      toast.success("Account added");
      setNewAcc("");
      load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  return (
    <Layout title="Settings" subtitle="Manage projects and accounts used in transactions">
      <div className="grid md:grid-cols-2 gap-4">
        <div className="rudaya-card p-5">
          <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500 mb-1">Master Data</div>
          <h3 className="font-heading font-semibold text-lg mb-4">Project IDs ({meta.project_ids.length})</h3>
          <div className="flex gap-2 mb-4">
            <Input data-testid="new-project-code" className="rounded-none" placeholder="Code (e.g. FRD_GJ_0007)" value={newProj.code} onChange={(e) => setNewProj({ ...newProj, code: e.target.value })} />
            <Input data-testid="new-project-desc" className="rounded-none" placeholder="Description" value={newProj.description} onChange={(e) => setNewProj({ ...newProj, description: e.target.value })} />
            <Button data-testid="add-project-btn" onClick={addProject} disabled={!newProj.code} className="rounded-none bg-neutral-900">Add</Button>
          </div>
          <div className="max-h-80 overflow-auto rudaya-scroll border border-neutral-200">
            {meta.project_ids.map((p) => (
              <div key={p.code} className="px-3 py-2 border-b border-neutral-100 text-sm flex justify-between">
                <span className="font-mono-tab text-xs">{p.code}</span>
                <span className="text-neutral-500 text-xs">{p.description}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="rudaya-card p-5">
          <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500 mb-1">Master Data</div>
          <h3 className="font-heading font-semibold text-lg mb-4">Accounts ({meta.accounts.length})</h3>
          <div className="flex gap-2 mb-4">
            <Input data-testid="new-account" className="rounded-none" placeholder="Account name" value={newAcc} onChange={(e) => setNewAcc(e.target.value)} />
            <Button data-testid="add-account-btn" onClick={addAccount} disabled={!newAcc} className="rounded-none bg-neutral-900">Add</Button>
          </div>
          <div className="max-h-80 overflow-auto rudaya-scroll border border-neutral-200">
            {meta.accounts.map((a) => (
              <div key={a.name} className="px-3 py-2 border-b border-neutral-100 text-sm">{a.name}</div>
            ))}
          </div>
        </div>
      </div>
    </Layout>
  );
}

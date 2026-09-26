import React, { useCallback, useEffect, useRef, useState } from "react";
import { api, formatApiError, API } from "@/lib/api";
import { toast } from "sonner";
import { Paperclip, FileArrowDown, Trash, FilePdf, UploadSimple } from "@phosphor-icons/react";

/**
 * Reusable attachments panel for transactions and quotations.
 * Requires the entity to be persisted (entityId must exist) — hides itself otherwise.
 */
export default function AttachmentsPanel({ entityType, entityId, max = 10 }) {
  const [items, setItems] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [loading, setLoading] = useState(false);
  const fileRef = useRef(null);

  const load = useCallback(async () => {
    if (!entityId) return;
    setLoading(true);
    try {
      const r = await api.get(`/attachments/${entityType}/${entityId}`);
      setItems(r.data);
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setLoading(false); }
  }, [entityType, entityId]);

  useEffect(() => { load(); }, [load]);

  const onFile = async (f) => {
    if (!f) return;
    if (!/\.pdf$/i.test(f.name) || f.type !== "application/pdf") {
      toast.error("Only PDF files are accepted");
      return;
    }
    if (f.size > 10 * 1024 * 1024) {
      toast.error("File exceeds 10 MB limit");
      return;
    }
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", f);
      const r = await api.post(`/attachments/${entityType}/${entityId}`, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setItems((prev) => [r.data, ...prev]);
      toast.success("Attachment uploaded");
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const remove = async (id) => {
    if (!window.confirm("Delete this attachment?")) return;
    try {
      await api.delete(`/attachments/${id}`);
      setItems((prev) => prev.filter((x) => x.id !== id));
      toast.success("Deleted");
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const download = async (att) => {
    try {
      const r = await api.get(`/attachments/${att.id}/download`, { responseType: "blob" });
      const url = URL.createObjectURL(r.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = att.filename || "invoice.pdf";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  if (!entityId) {
    return (
      <div className="border border-dashed border-neutral-300 p-3 text-xs text-neutral-500" data-testid="attachments-locked">
        <Paperclip size={14} className="inline mr-1" /> Save this record first to add PDF attachments.
      </div>
    );
  }

  const atLimit = items.length >= max;

  return (
    <div data-testid={`attachments-${entityType}-${entityId}`}>
      <div className="flex items-center justify-between mb-2">
        <div className="text-[11px] uppercase tracking-wider text-neutral-500 flex items-center gap-1">
          <Paperclip size={12} /> PDF Attachments · {items.length}/{max}
        </div>
      </div>

      <label className={`block border-2 border-dashed p-3 text-center text-xs cursor-pointer transition-colors ${atLimit ? "border-neutral-200 text-neutral-400 cursor-not-allowed" : "border-neutral-300 hover:border-neutral-900 hover:bg-neutral-50"}`}>
        <input
          ref={fileRef}
          type="file"
          accept="application/pdf"
          className="hidden"
          disabled={uploading || atLimit}
          onChange={(e) => onFile(e.target.files?.[0])}
          data-testid={`attach-upload-${entityType}`}
        />
        <UploadSimple size={16} className="inline mr-1" />
        {atLimit ? "Attachment limit reached" : uploading ? "Uploading…" : "Click to upload a PDF (max 10 MB)"}
      </label>

      {items.length > 0 && (
        <ul className="mt-2 space-y-1 max-h-40 overflow-y-auto rudaya-scroll">
          {items.map((a) => (
            <li key={a.id} className="flex items-center justify-between bg-neutral-50 border border-neutral-200 px-2 py-1.5 text-xs" data-testid={`attach-row-${a.id}`}>
              <div className="flex items-center gap-2 min-w-0">
                <FilePdf size={14} className="text-red-600 shrink-0" />
                <span className="truncate" title={a.filename}>{a.filename}</span>
                <span className="text-[10px] text-neutral-500 whitespace-nowrap">{Math.round(a.size / 1024)} KB</span>
              </div>
              <div className="flex items-center gap-1 shrink-0">
                <button data-testid={`attach-download-${a.id}`} onClick={() => download(a)} className="p-1 hover:bg-neutral-200" title="Download">
                  <FileArrowDown size={13} />
                </button>
                <button data-testid={`attach-delete-${a.id}`} onClick={() => remove(a.id)} className="p-1 hover:bg-red-100 text-red-600" title="Delete">
                  <Trash size={13} />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {loading && items.length === 0 && <div className="text-xs text-neutral-400 mt-1">Loading…</div>}
    </div>
  );
}

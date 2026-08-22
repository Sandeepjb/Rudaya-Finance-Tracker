import React, { useEffect, useRef, useState, useCallback } from "react";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import { Sparkle, PaperPlaneRight, User as UserIcon, Robot, Microphone, MicrophoneSlash, Check, X, Clock } from "@phosphor-icons/react";
import { API, api, inr } from "@/lib/api";

const SUGGESTIONS = [
  "Which project made the highest net profit so far?",
  "Log a Cost of ₹25,000 on Aug 22 for FRD_GJ_0002, account 'Petrol', note 'diesel refill'.",
  "Add a Revenue sales forecast of ₹4,00,000 for Nov 2026 under project AAM-CH_0001.",
  "Create quotation Q-2026-Ford-02 for Ford India, project FRD_GJ_0002, expected Dec 2026, status sent, one Revenue line 'Panel batch' ₹20,00,000.",
];

function renderInline(text) {
  // strip <propose>...</propose> from what the user sees
  const clean = text.replace(/<propose>[\s\S]*?<\/propose>/g, "").trim();
  const parts = [];
  const re = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g;
  let last = 0, m, i = 0;
  while ((m = re.exec(clean)) !== null) {
    if (m.index > last) parts.push(clean.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("**")) parts.push(<strong key={`b${i++}`}>{tok.slice(2, -2)}</strong>);
    else if (tok.startsWith("`")) parts.push(<code key={`c${i++}`} className="font-mono-tab bg-neutral-100 px-1 text-[13px]">{tok.slice(1, -1)}</code>);
    else parts.push(<em key={`i${i++}`}>{tok.slice(1, -1)}</em>);
    last = re.lastIndex;
  }
  if (last < clean.length) parts.push(clean.slice(last));
  return parts;
}

function summariseProposal(p) {
  const d = p.data || {};
  if (p.kind === "transaction") return `${d.type} · ${inr(d.amount)} · ${d.account || "?"} · ${d.project_id || "-"} · ${d.date || "?"}`;
  if (p.kind === "sales_forecast") return `Forecast ${d.type} · ${inr(d.amount)} · ${d.month}/${d.year} · ${d.project_id || "unallocated"}`;
  if (p.kind === "quotation") {
    const rev = (d.lines || []).filter((l) => l.type === "Revenue").reduce((a, l) => a + (l.amount || 0), 0);
    return `Quotation ${d.quotation_number} · ${d.client_name || ""} · Rev ${inr(rev)} · ${d.status}`;
  }
  return p.kind;
}

export default function AiAssistant() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [sessionId, setSessionId] = useState("");
  const [pending, setPending] = useState([]);
  const [listening, setListening] = useState(false);
  const [voiceSupported, setVoiceSupported] = useState(false);
  const scrollRef = useRef(null);
  const recogRef = useRef(null);

  const loadPending = useCallback(async () => {
    try {
      const r = await api.get("/ai/pending", { params: { status: "pending" } });
      setPending(r.data);
    } catch (e) { /* toast on demand */ }
  }, []);

  useEffect(() => {
    if (!open) return;
    if (!sessionId) setSessionId(`sess-${Date.now()}`);
    loadPending();
  }, [open, sessionId, loadPending]);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages]);

  useEffect(() => {
    const Ctor = typeof window !== "undefined" && (window.SpeechRecognition || window.webkitSpeechRecognition);
    if (!Ctor) return;
    setVoiceSupported(true);
    const rec = new Ctor();
    rec.lang = "en-IN"; rec.interimResults = false; rec.continuous = false;
    rec.onresult = (e) => {
      const text = e.results[0][0].transcript;
      setInput((prev) => (prev ? prev + " " : "") + text);
    };
    rec.onerror = () => setListening(false);
    rec.onend = () => setListening(false);
    recogRef.current = rec;
    return () => { try { rec.stop(); } catch (_e) {} };
  }, []);

  const toggleMic = () => {
    if (!recogRef.current) return;
    if (listening) { recogRef.current.stop(); setListening(false); return; }
    try { recogRef.current.start(); setListening(true); }
    catch (_e) { setListening(false); }
  };

  const send = async (text) => {
    const msg = (text ?? input).trim();
    if (!msg || streaming) return;
    setInput("");
    const now = Date.now();
    setMessages((m) => [...m, { id: `u-${now}`, role: "user", content: msg }, { id: `a-${now}`, role: "assistant", content: "" }]);
    setStreaming(true);
    try {
      const resp = await fetch(`${API}/ai/chat`, {
        method: "POST", credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg, session_id: sessionId }),
      });
      if (!resp.ok || !resp.body) throw new Error(`AI error ${resp.status}`);
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const parts = buf.split("\n\n"); buf = parts.pop() || "";
        for (const p of parts) {
          const line = p.replace(/^data:\s*/, "").trim();
          if (!line) continue;
          try {
            const data = JSON.parse(line);
            if (data.delta) {
              setMessages((m) => {
                const copy = [...m];
                copy[copy.length - 1] = { ...copy[copy.length - 1], content: copy[copy.length - 1].content + data.delta };
                return copy;
              });
            } else if (data.done && Array.isArray(data.proposals) && data.proposals.length) {
              toast.success(`${data.proposals.length} proposal(s) queued for approval`);
              loadPending();
            } else if (data.error) {
              throw new Error(data.error);
            }
          } catch (parseErr) { /* skip empty */ }
        }
      }
    } catch (e) {
      toast.error("AI request failed: " + e.message);
    } finally { setStreaming(false); }
  };

  const approve = async (id) => {
    try { await api.post(`/ai/pending/${id}/approve`); toast.success("Approved & saved"); loadPending(); }
    catch (e) { toast.error(e.response?.data?.detail || "Approve failed"); }
  };
  const reject = async (id) => {
    try { await api.post(`/ai/pending/${id}/reject`); toast.success("Rejected"); loadPending(); }
    catch (e) { toast.error(e.response?.data?.detail || "Reject failed"); }
  };

  return (
    <>
      <button
        data-testid="ai-fab"
        onClick={() => setOpen(true)}
        className="fixed bottom-6 right-6 z-40 bg-neutral-900 hover:bg-neutral-700 text-white px-4 py-3 shadow-xl border border-neutral-900 flex items-center gap-2 transition-all hover:-translate-y-0.5"
        style={{ borderRadius: 2 }}
      >
        <Sparkle weight="fill" size={18} className="text-yellow-400" />
        <span className="text-xs uppercase tracking-[0.15em] font-semibold">Ask RudayaAI</span>
        {pending.length > 0 && (
          <span className="ml-1 bg-yellow-400 text-neutral-900 text-[10px] font-bold px-1.5 py-0.5" data-testid="ai-pending-badge">{pending.length}</span>
        )}
      </button>

      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent className="w-full sm:max-w-lg rounded-none border-l-2 border-l-yellow-400 flex flex-col p-0" data-testid="ai-drawer">
          <SheetHeader className="p-5 border-b border-neutral-200 bg-neutral-900 text-white">
            <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.25em] text-yellow-400">
              <Sparkle weight="fill" size={14} /> RudayaAI · Claude Sonnet 4.6
            </div>
            <SheetTitle className="font-heading text-xl tracking-tight text-white">Insights + Write Access</SheetTitle>
            <SheetDescription className="text-neutral-400 text-xs">
              Ask questions or tell me to add transactions, forecasts, quotations. Every entry needs your approval before it is saved.
            </SheetDescription>
          </SheetHeader>

          {pending.length > 0 && (
            <div className="border-b border-neutral-200 bg-yellow-50 p-3 max-h-56 overflow-y-auto rudaya-scroll" data-testid="ai-pending-list">
              <div className="text-[10px] uppercase tracking-[0.2em] text-yellow-800 font-semibold flex items-center gap-1 mb-2"><Clock size={12} /> Pending approval · {pending.length}</div>
              {pending.map((p) => (
                <div key={p.id} className="bg-white border border-yellow-300 p-2 mb-2 flex items-center justify-between gap-2" data-testid={`pending-${p.id}`}>
                  <div className="flex-1 min-w-0">
                    <div className="text-[10px] uppercase tracking-wider text-neutral-500">{p.kind.replace("_", " ")}</div>
                    <div className="text-xs text-neutral-800 font-mono-tab truncate" title={summariseProposal(p)}>{summariseProposal(p)}</div>
                  </div>
                  <button data-testid={`approve-${p.id}`} onClick={() => approve(p.id)} className="p-1.5 bg-emerald-600 hover:bg-emerald-700 text-white" title="Approve"><Check size={14} weight="bold" /></button>
                  <button data-testid={`reject-${p.id}`} onClick={() => reject(p.id)} className="p-1.5 bg-neutral-200 hover:bg-red-200 text-red-700" title="Reject"><X size={14} weight="bold" /></button>
                </div>
              ))}
            </div>
          )}

          <div ref={scrollRef} className="flex-1 overflow-y-auto rudaya-scroll p-5 space-y-4 bg-neutral-50" data-testid="ai-messages">
            {messages.length === 0 && (
              <div className="space-y-3">
                <div className="text-xs uppercase tracking-wider text-neutral-500">Try one of these</div>
                {SUGGESTIONS.map((s) => (
                  <button key={s} data-testid="ai-suggestion" onClick={() => send(s)} disabled={streaming}
                    className="block w-full text-left text-sm p-3 border border-neutral-300 bg-white hover:bg-neutral-100 transition-colors disabled:opacity-50">
                    {s}
                  </button>
                ))}
              </div>
            )}
            {messages.map((m) => (
              <div key={m.id} className={`flex gap-3 ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                {m.role === "assistant" && (
                  <div className="w-7 h-7 shrink-0 bg-yellow-400 flex items-center justify-center">
                    <Robot weight="fill" size={16} className="text-neutral-900" />
                  </div>
                )}
                <div className={`max-w-[80%] px-3 py-2 text-sm whitespace-pre-wrap ${m.role === "user" ? "bg-neutral-900 text-white" : "bg-white border border-neutral-200 text-neutral-900"}`}>
                  {m.content ? renderInline(m.content) : <span className="opacity-40">…</span>}
                </div>
                {m.role === "user" && (
                  <div className="w-7 h-7 shrink-0 bg-neutral-200 flex items-center justify-center">
                    <UserIcon size={14} className="text-neutral-700" />
                  </div>
                )}
              </div>
            ))}
          </div>

          <div className="p-4 border-t border-neutral-200 bg-white">
            <form onSubmit={(e) => { e.preventDefault(); send(); }} className="flex gap-2">
              {voiceSupported && (
                <Button
                  type="button"
                  data-testid="ai-mic"
                  onClick={toggleMic}
                  disabled={streaming}
                  className={`rounded-none h-10 px-3 ${listening ? "bg-red-600 hover:bg-red-700 animate-pulse" : "bg-neutral-100 hover:bg-neutral-200 text-neutral-900"}`}
                  title={listening ? "Stop listening" : "Speak"}
                >
                  {listening ? <MicrophoneSlash size={16} /> : <Microphone size={16} />}
                </Button>
              )}
              <Input data-testid="ai-input" value={input} onChange={(e) => setInput(e.target.value)}
                placeholder={listening ? "Listening…" : "Ask, or say 'Add a cost of ₹25,000…'"} className="rounded-none" disabled={streaming} />
              <Button data-testid="ai-send" type="submit" disabled={streaming || !input.trim()} className="rounded-none bg-neutral-900 hover:bg-neutral-700 h-10 px-4">
                <PaperPlaneRight size={16} />
              </Button>
            </form>
            {!voiceSupported && (
              <div className="text-[10px] text-neutral-400 mt-2">Voice input needs Chrome/Edge with mic permission.</div>
            )}
          </div>
        </SheetContent>
      </Sheet>
    </>
  );
}

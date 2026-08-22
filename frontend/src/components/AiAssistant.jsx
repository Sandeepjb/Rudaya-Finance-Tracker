import React, { useEffect, useRef, useState } from "react";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import { Sparkle, PaperPlaneRight, User as UserIcon, Robot } from "@phosphor-icons/react";
import { API } from "@/lib/api";

const SUGGESTIONS = [
  "Which project made the highest net profit so far?",
  "Are we ahead or behind on Jul-2026 revenue forecast, and why?",
  "What are my top 3 cost accounts this year?",
  "Summarise open quotations by client.",
];

// Minimal inline markdown: **bold**, *italic*, `code`. Splits into React nodes.
function renderInline(text) {
  const parts = [];
  const re = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g;
  let last = 0;
  let m;
  let i = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("**")) parts.push(<strong key={`b${i++}`}>{tok.slice(2, -2)}</strong>);
    else if (tok.startsWith("`")) parts.push(<code key={`c${i++}`} className="font-mono-tab bg-neutral-100 px-1 text-[13px]">{tok.slice(1, -1)}</code>);
    else parts.push(<em key={`i${i++}`}>{tok.slice(1, -1)}</em>);
    last = re.lastIndex;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

export default function AiAssistant() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [sessionId, setSessionId] = useState("");
  const scrollRef = useRef(null);

  useEffect(() => {
    if (!open || sessionId) return;
    // start a fresh session per open
    setSessionId(`sess-${Date.now()}`);
  }, [open, sessionId]);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages]);

  const send = async (text) => {
    const msg = (text ?? input).trim();
    if (!msg || streaming) return;
    setInput("");
    const now = Date.now();
    setMessages((m) => [
      ...m,
      { id: `u-${now}`, role: "user", content: msg },
      { id: `a-${now}`, role: "assistant", content: "" },
    ]);
    setStreaming(true);
    try {
      const resp = await fetch(`${API}/ai/chat`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg, session_id: sessionId }),
      });
      if (!resp.ok || !resp.body) throw new Error(`AI error ${resp.status}`);
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";
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
            } else if (data.error) {
              throw new Error(data.error);
            }
          } catch (parseErr) {
            // Ignore malformed SSE frames — they can occur when the buffer splits mid-chunk.
            if (typeof window !== "undefined" && window.__DEV__) {
              // eslint-disable-next-line no-console
              console.warn("ai-chat: skipped malformed SSE frame", parseErr);
            }
          }
        }
      }
    } catch (e) {
      toast.error("AI request failed: " + e.message);
      setMessages((m) => {
        const copy = [...m];
        if (copy.length && copy[copy.length - 1].role === "assistant" && !copy[copy.length - 1].content) {
          copy.pop();
        }
        return copy;
      });
    } finally {
      setStreaming(false);
    }
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
      </button>

      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent className="w-full sm:max-w-lg rounded-none border-l-2 border-l-yellow-400 flex flex-col p-0" data-testid="ai-drawer">
          <SheetHeader className="p-5 border-b border-neutral-200 bg-neutral-900 text-white">
            <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.25em] text-yellow-400">
              <Sparkle weight="fill" size={14} /> RudayaAI · Claude Sonnet 4.6
            </div>
            <SheetTitle className="font-heading text-xl tracking-tight text-white">Financial Insights Assistant</SheetTitle>
            <SheetDescription className="text-neutral-400 text-xs">
              Ask questions about your live transactions, forecast, quotations, and projects.
            </SheetDescription>
          </SheetHeader>

          <div ref={scrollRef} className="flex-1 overflow-y-auto rudaya-scroll p-5 space-y-4 bg-neutral-50" data-testid="ai-messages">
            {messages.length === 0 && (
              <div className="space-y-3">
                <div className="text-xs uppercase tracking-wider text-neutral-500">Try one of these</div>
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    data-testid="ai-suggestion"
                    onClick={() => send(s)}
                    disabled={streaming}
                    className="block w-full text-left text-sm p-3 border border-neutral-300 bg-white hover:bg-neutral-100 transition-colors disabled:opacity-50"
                  >
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
                <div
                  className={`max-w-[80%] px-3 py-2 text-sm whitespace-pre-wrap ${
                    m.role === "user"
                      ? "bg-neutral-900 text-white"
                      : "bg-white border border-neutral-200 text-neutral-900"
                  }`}
                >
                  {m.content
                    ? renderInline(m.content)
                    : <span className="opacity-40">…</span>}
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
            <form
              onSubmit={(e) => { e.preventDefault(); send(); }}
              className="flex gap-2"
            >
              <Input
                data-testid="ai-input"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Ask about revenue, costs, forecasts, projects…"
                className="rounded-none"
                disabled={streaming}
              />
              <Button
                data-testid="ai-send"
                type="submit"
                disabled={streaming || !input.trim()}
                className="rounded-none bg-neutral-900 hover:bg-neutral-700 h-10 px-4"
              >
                <PaperPlaneRight size={16} />
              </Button>
            </form>
          </div>
        </SheetContent>
      </Sheet>
    </>
  );
}

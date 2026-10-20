import { useEffect, useRef, useState, type FormEvent } from "react";
import { MessageCircle } from "lucide-react";
import { api } from "../api/client";
import { useMe } from "../api/useMe";
import { NO_AGENT } from "../ui/copy";
import { useAskState } from "./AskContext";
import { Turn } from "./AskPanel";
import type { EntityRef } from "../api/types";

/** Ask in place: a small control that appears when you point at a row, a tile or a chip. The question and its answer open beside what they are about, one line to follow up; a long thread moves to the panel. */
export function AskHere({ about, context }: { about: string; context: EntityRef }) {
  const { me } = useMe();
  const { openRun } = useAskState();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [asked, setAsked] = useState<{ runId: string; question: string } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const down = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", down); window.addEventListener("keydown", key);
    return () => { document.removeEventListener("mousedown", down); window.removeEventListener("keydown", key); };
  }, [open]);
  const ask = (text: string) => {
    const question = text.trim();
    if (!question) return;
    setErr(null);
    api.ask(question, context, me ?? "").then((r) => { setAsked({ runId: r.run_id, question }); setQ(""); }, (e: Error) => setErr(e.message === "no-model" ? NO_AGENT : "Ask could not be reached. Try again."));
  };
  const submit = (e: FormEvent) => { e.preventDefault(); ask(q); };
  return (
    <div className="askhere" ref={box}>
      <button type="button" className="askhere-btn" aria-haspopup="dialog" aria-expanded={open} aria-label={`Ask about ${about}`} onClick={() => setOpen(!open)}><MessageCircle size={16} strokeWidth={1.5} aria-hidden /><span>Ask</span></button>
      {open && (
        <div className="askhere-pop" role="dialog" aria-label={`Ask about ${about}`}>
          {asked && <Turn runId={asked.runId} question={asked.question} onClose={() => setOpen(false)} onRetry={() => ask(asked.question)} />}
          {err && <p className="turn-err" role="status">{err}</p>}
          <form onSubmit={submit}>
            <input autoFocus aria-label={asked ? "Ask a follow-up" : `Ask about ${about}`} placeholder={asked ? "Ask a follow-up…" : `Ask about ${about.length > 40 ? about.slice(0, 39) + "…" : about}…`} value={q} onChange={(e) => setQ(e.target.value)} />
          </form>
          {asked && <button type="button" className="linkbtn" onClick={() => { openRun(asked.runId, asked.question); setOpen(false); }}>Open in panel</button>}
        </div>
      )}
    </div>
  );
}

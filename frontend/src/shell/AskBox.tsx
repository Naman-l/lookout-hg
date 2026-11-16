import { useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowUp, Check, ChevronDown } from "lucide-react";
import { useMedia } from "../ui/useMedia";
import { useAskState } from "./AskContext";
import { isNoAgent } from "../ui/copy";
import { rankExamples, shortAbout } from "../sections/agents/ask";

export const NOT_CONNECTED = "No model is connected here: Lookout answers from the records by rule.";

/** The follow-up composer at the foot of the answer panel (`inPanel`): a chip names what the question is about, Enter sends, the answer joins the
 * thread above. New questions start in the command bar at the top of every page (CommandBar), which owns "/" and Command-K. */
export function AskComposer({ inPanel = false }: { inPanel?: boolean }) {
  const phone = useMedia("(max-width: 760px)");
  const { about, context, err, examples, send, scope, setScope, open, thread, prefill, takePrefill } = useAskState();
  const [menu, setMenu] = useState(false);
  const [q, setQ] = useState("");
  const [near, setNear] = useState(false); // the composer has focus: the no-agent note and its examples show only then, never on every page
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => { if (inPanel && !phone) input.current?.focus(); }, [inPanel, phone]);
  useEffect(() => { if (prefill && (inPanel || !open)) { setQ(prefill); takePrefill(); setTimeout(() => { const el = input.current; if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); } }, 0); } }, [prefill, inPanel, open, takePrefill]); // the bottom bar gives way to this one when an answer opens: typing carries on here
  if (phone) return null;
  const go = (text: string) => send(text).then((ok) => { if (ok) setQ(""); });
  const submit = (e: FormEvent) => { e.preventDefault(); go(q); };
  const short = shortAbout(about);
  const chip = short.length > 26 ? short.slice(0, 25) + "…" : short;
  const shown = rankExamples(examples, scope === "all" ? null : context, about).slice(0, 5);
  return (
    <div className={`composer-wrap${inPanel ? " in-panel" : ""}`} onFocus={() => setNear(true)} onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setNear(false); }}>
      {err && !(inPanel && isNoAgent(err)) && <p className={`composer-note${isNoAgent(err) ? " down" : ""}`} role="status">{isNoAgent(err) ? NOT_CONNECTED : err}</p>}
      {near && !q && shown.length > 0 && !(open && thread.length) && (
        <div className="ask-ex" role="listbox" aria-label={`Questions about ${scope === "all" ? "everything" : short}`}>
          <p className="ask-ex-h">About {scope === "all" ? "everything" : short}</p>
          {shown.map((x) => <button key={x.question} type="button" role="option" aria-selected={false} onClick={() => send(x.question, x.context ?? null)}>{x.question}</button>)}
          <p className="ask-ex-f">Answered from the records by code; no model is connected here.</p>
        </div>
      )}
      <form className="composer" onSubmit={submit} role="search">
        <div className="scope">
          <button type="button" className="scope-btn" aria-haspopup="menu" aria-expanded={menu} onClick={() => setMenu(!menu)} onKeyDown={(e) => { if (e.key === "Escape") setMenu(false); }}>
            <span>About: {scope === "all" ? "Everything" : chip}</span><ChevronDown size={14} strokeWidth={1.5} aria-hidden />
          </button>
          {menu && (
            <div className="scope-menu" role="menu" onKeyDown={(e) => { if (e.key === "Escape") setMenu(false); }}>
              <button type="button" role="menuitemradio" aria-checked={scope === "page"} onClick={() => { setScope("page"); setMenu(false); }}>{scope === "page" && <Check size={16} strokeWidth={1.5} aria-hidden />}<span><b>This page</b><small>{about}</small></span></button>
              <button type="button" role="menuitemradio" aria-checked={scope === "all"} onClick={() => { setScope("all"); setMenu(false); }}>{scope === "all" && <Check size={16} strokeWidth={1.5} aria-hidden />}<span><b>Everything</b><small>all the data</small></span></button>
            </div>
          )}
        </div>
        <input ref={input} aria-label={`Ask Lookout about ${scope === "all" ? "everything" : about}`} placeholder={open && thread.length ? "Ask a follow-up…" : scope === "all" ? "Ask about anything…" : "Ask Lookout…"} value={q} onChange={(e) => setQ(e.target.value)} />
        <button type="submit" className="go" aria-label="Send" disabled={!q.trim()}><ArrowUp size={16} strokeWidth={2} /></button>
      </form>
    </div>
  );
}

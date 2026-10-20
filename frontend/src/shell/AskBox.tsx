import { useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowUp, Check, ChevronDown } from "lucide-react";
import { useMedia } from "../ui/useMedia";
import { useAskState } from "./AskContext";
import { isNoAgent } from "../ui/copy";
import { rankExamples, shortAbout } from "../sections/agents/ask";

export const NOT_CONNECTED = "The agent is not connected: start the app with a key or LOOKOUT_LIVE=1. The example questions show saved answers.";

/** Ask: one rounded composer floating at the bottom of the main area; while the answer panel is open the same composer sits at the foot of the panel (`inPanel`) and the bottom one is gone. A chip names what the question is about, "/" focuses the input, Enter sends; the answer opens in the rail and this stays for follow-ups. Main reserves its height. */
export function AskComposer({ inPanel = false }: { inPanel?: boolean }) {
  const phone = useMedia("(max-width: 760px)");
  const { about, context, err, connected, examples, send, scope, setScope, open, thread, prefill, takePrefill } = useAskState();
  const [menu, setMenu] = useState(false);
  const [q, setQ] = useState("");
  const [near, setNear] = useState(false); // the composer has focus: the no-agent note and its examples show only then, never on every page
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => { if (inPanel && !phone) input.current?.focus(); }, [inPanel, phone]);
  useEffect(() => { if (prefill && (inPanel || !open)) { setQ(prefill); takePrefill(); setTimeout(() => { const el = input.current; if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); } }, 0); } }, [prefill, inPanel, open, takePrefill]); // the bottom bar gives way to this one when an answer opens: typing carries on here
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (e.key !== "/" || e.metaKey || e.ctrlKey || t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable) return;
      e.preventDefault(); input.current?.focus();
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);
  if (phone) return null;
  const go = (text: string) => send(text).then((ok) => { if (ok) setQ(""); });
  const submit = (e: FormEvent) => { e.preventDefault(); go(q); };
  const short = shortAbout(about);
  const chip = short.length > 26 ? short.slice(0, 25) + "…" : short;
  const down = connected === false || isNoAgent(err);
  const shown = rankExamples(examples, scope === "all" ? null : context, about).slice(0, 5);
  return (
    <div className={`composer-wrap${inPanel ? " in-panel" : ""}`} onFocus={() => setNear(true)} onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setNear(false); }}>
      {err && !(inPanel && isNoAgent(err)) && <p className={`composer-note${isNoAgent(err) ? " down" : ""}`} role="status">{isNoAgent(err) ? NOT_CONNECTED : err}</p>}
      {near && !q && shown.length > 0 && !(open && thread.length) && (
        <div className="ask-ex" role="listbox" aria-label={`Questions about ${scope === "all" ? "everything" : short}`}>
          <p className="ask-ex-h">About {scope === "all" ? "everything" : short}</p>
          {shown.map((x) => <button key={x.question} type="button" role="option" aria-selected={false} onClick={() => send(x.question, x.context ?? null)}>{x.question}</button>)}
          {down && <p className="ask-ex-f">Recorded answers. A new question needs the live agent.</p>}
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
        <kbd className="askbar-key" aria-hidden>/</kbd>
        <button type="submit" className="go" aria-label="Send" disabled={!q.trim()}><ArrowUp size={16} strokeWidth={2} /></button>
      </form>
    </div>
  );
}

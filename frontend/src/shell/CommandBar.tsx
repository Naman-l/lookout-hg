import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowUpRight, Building2, Check, ChevronDown, ClipboardList, CornerDownLeft, FileText, History, ListTodo, Mail, MapPin, MessageSquareText, Package, Radar, Sparkles, User, X, type LucideIcon } from "lucide-react";
import { useAskState, recentAsked } from "./AskContext";
import { useCompany } from "../api/useCompany";
import { isNoAgent } from "../ui/copy";
import { rankExamples, shortAbout } from "../sections/agents/ask";
import type { EntityRef } from "../api/types";

/** One hit of the deterministic search (GET /api/search): what it is, its words, where it opens. */
type Hit = { type: string; label: string; sublabel?: string | null; url: string };
const GROUPS: [string, string, LucideIcon][] = [["project", "Projects", MapPin], ["supplier", "Vendors", Building2], ["po", "POs", FileText], ["pr", "PRs", ClipboardList],
  ["material", "Materials", Package], ["item", "Cases", ListTodo], ["message", "Messages", Mail], ["person", "People", User]];
/** A row of the bar's list: a question Lookout answers from the records, or a record to open. */
type Opt = { kind: "ask"; text: string; ctx: EntityRef | null | "page"; icon: "ask" | "recent" | "suggest" } | { kind: "open"; hit: Hit; Icon: LucideIcon };
type Section = { label: string; opts: Opt[] };

const words = (s: string) => s.toLowerCase().split(/[^a-z0-9&]+/).filter((w) => w.length > 1);
/** The part of a label the query names, marked; a hit found in its body is shown plain. */
function Marked({ text, q }: { text: string; q: string }) {
  const at = q ? text.toLowerCase().indexOf(q.toLowerCase()) : -1;
  return at >= 0 ? <>{text.slice(0, at)}<mark>{text.slice(at, at + q.length)}</mark>{text.slice(at + q.length)}</> : <>{text}</>;
}

/** The one place to type, at the top of every page: ask Lookout anything about the company's records, or jump to a record. As you type it offers
 * "Ask Lookout" first (Enter), the questions it already knows how to answer, and the records whose names match (vendors, projects, POs, PRs,
 * materials, cases, messages, people). The answer opens in the panel beside the page, the work shown step by step. Command-K or "/" focuses it.
 * On a phone it is a full-screen sheet (`sheet`), opened from the header or the tab bar. */
export function CommandBar({ sheet = false, onClose }: { sheet?: boolean; onClose?: () => void }) {
  const { about, context, examples, everywhere, send, scope, setScope, err, open: panelOpen, thread } = useAskState();
  const company = useCompany();
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [focus, setFocus] = useState(sheet);
  const [active, setActive] = useState(-1);
  const [hits, setHits] = useState<Hit[]>([]);
  const [shown, setShown] = useState("");
  const [menu, setMenu] = useState(false);
  const [busy, setBusy] = useState(false);
  const [recent, setRecent] = useState<string[]>([]);
  const input = useRef<HTMLInputElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const text = q.trim();
  const short = shortAbout(about);
  const where = scope === "all" ? `across ${company.short}` : `about ${short.length > 28 ? short.slice(0, 27) + "…" : short}`;

  useEffect(() => {
    if (sheet) { input.current?.focus(); return; }
    const h = (e: globalThis.KeyboardEvent) => {
      const t = e.target as HTMLElement;
      const typing = t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable;
      if (((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") || (e.key === "/" && !typing && !e.metaKey && !e.ctrlKey)) { e.preventDefault(); input.current?.focus(); input.current?.select(); }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [sheet]);
  useEffect(() => { if (focus) setRecent(recentAsked()); }, [focus, thread.length]);
  useEffect(() => {
    if (text.length < 2) { setHits([]); setShown(text); return; }
    const ctl = new AbortController();
    const t = setTimeout(() => {
      fetch(`/api/search?q=${encodeURIComponent(text)}&limit=14`, { signal: ctl.signal }).then((r) => (r.ok ? r.json() : [])).then((d) => { setHits(Array.isArray(d) ? d.filter((h: Hit) => h.url) : []); setShown(text); }).catch(() => {});
    }, 140);
    return () => { clearTimeout(t); ctl.abort(); };
  }, [text]);

  const sections = useMemo<Section[]>(() => {
    const pageQs = rankExamples(examples, scope === "all" ? null : context, about);
    if (!text) {
      const seen = new Set<string>();
      // a question about this page goes with the page; one about the whole company goes with nothing
      const take = (xs: { question: string; context?: EntityRef | null }[], n: number, icon: "suggest" | "recent", global = false) =>
        xs.filter((x) => !seen.has(x.question) && seen.add(x.question)).slice(0, n).map((x): Opt => ({ kind: "ask", text: x.question, ctx: global ? null : x.context ?? "page", icon }));
      const out: Section[] = [];
      if (scope !== "all" && pageQs.length) out.push({ label: `Ask about ${short}`, opts: take(pageQs, 4, "suggest") });
      if (everywhere.length) out.push({ label: `Across ${company.short}`, opts: take(everywhere, scope === "all" ? 6 : 3, "suggest", true) });
      if (recent.length) out.push({ label: "You asked", opts: take(recent.map((question) => ({ question })), 3, "recent") });
      return out.filter((s) => s.opts.length);
    }
    const ws = words(text);
    const known = [...pageQs, ...everywhere].filter((x, i, all) => all.findIndex((y) => y.question === x.question) === i)
      .filter((x) => ws.length && ws.every((w) => x.question.toLowerCase().includes(w)) && x.question.toLowerCase() !== text.toLowerCase()).slice(0, 3);
    const out: Section[] = [{ label: "", opts: [{ kind: "ask", text, ctx: "page", icon: "ask" }] }];
    if (known.length) out.push({ label: "Questions Lookout answers", opts: known.map((x): Opt => ({ kind: "ask", text: x.question, ctx: everywhere.includes(x) ? null : x.context ?? "page", icon: "suggest" })) });
    let left = 8;
    for (const [type, label, Icon] of GROUPS) {
      const of = hits.filter((h) => h.type === type || (type === "item" && h.type === "action_item")).slice(0, Math.min(3, left));
      if (of.length) { out.push({ label, opts: of.map((hit): Opt => ({ kind: "open", hit, Icon })) }); left -= of.length; }
      if (left <= 0) break;
    }
    return out;
  }, [text, examples, everywhere, recent, hits, scope, context, about, short, company.short]);
  const flat = useMemo(() => sections.flatMap((s) => s.opts), [sections]);
  useEffect(() => { setActive(text ? 0 : -1); }, [text]);

  const close = () => { setFocus(false); setMenu(false); input.current?.blur(); onClose?.(); };
  const run = async (o: Opt | undefined) => {
    if (!o) return;
    if (o.kind === "open") { nav(o.hit.url); setQ(""); close(); return; }
    setBusy(true);
    const ok = await send(o.text, o.ctx === "page" ? undefined : o.ctx);      // undefined: the page's record, or nothing when the scope is Everything
    setBusy(false);
    if (ok) { setQ(""); close(); }
  };
  const key = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((n) => Math.min(n + 1, flat.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((n) => Math.max(n - 1, text ? 0 : -1)); }
    else if (e.key === "Enter") { e.preventDefault(); if (active >= 0) run(flat[active]); else if (text) run({ kind: "ask", text, ctx: "page", icon: "ask" }); }
    else if (e.key === "Escape") { e.preventDefault(); if (q) setQ(""); else close(); }
  };
  const showList = focus && (flat.length > 0 || !!err);
  let n = -1;
  return (
    <div className={`cmd${sheet ? " cmd-sheet" : ""}${focus ? " on" : ""}`} ref={box}
      onFocus={() => setFocus(true)} onBlur={(e) => { if (!sheet && !e.currentTarget.contains(e.relatedTarget as Node | null)) { setFocus(false); setMenu(false); } }}>
      <div className="cmd-bar" role="search">
        <span className={`cmd-mark${busy ? " busy" : ""}`} aria-hidden><Radar size={16} strokeWidth={1.75} /></span>
        <input ref={input} role="combobox" aria-expanded={showList} aria-controls="cmd-list" aria-autocomplete="list" aria-activedescendant={active >= 0 ? `cmd-opt-${active}` : undefined}
          aria-label={`Ask Lookout ${where}, or find a vendor, project, PO, PR, material or case`}
          placeholder={sheet ? "Ask Lookout or find a record…" : panelOpen && thread.length ? "Ask a follow-up, or find a record…" : `Ask Lookout ${where}, or find a record…`}
          value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={key} />
        {q && <button type="button" className="cmd-x" aria-label="Clear" onClick={() => { setQ(""); input.current?.focus(); }}><X size={14} strokeWidth={1.75} aria-hidden /></button>}
        <div className="cmd-scope">
          <button type="button" className="cmd-scope-btn" aria-haspopup="menu" aria-expanded={menu} title="What the question is about" onClick={() => setMenu(!menu)}
            onKeyDown={(e) => { if (e.key === "Escape") { e.stopPropagation(); setMenu(false); } }}>
            <span>{scope === "all" ? "Everything" : short.length > 18 ? short.slice(0, 17) + "…" : short}</span><ChevronDown size={14} strokeWidth={1.5} aria-hidden />
          </button>
          {menu && (
            <div className="scope-menu cmd-scope-menu" role="menu">
              <button type="button" role="menuitemradio" aria-checked={scope === "page"} onClick={() => { setScope("page"); setMenu(false); input.current?.focus(); }}>{scope === "page" && <Check size={16} strokeWidth={1.5} aria-hidden />}<span><b>This page</b><small>{about}</small></span></button>
              <button type="button" role="menuitemradio" aria-checked={scope === "all"} onClick={() => { setScope("all"); setMenu(false); input.current?.focus(); }}>{scope === "all" && <Check size={16} strokeWidth={1.5} aria-hidden />}<span><b>Everything</b><small>all of {company.short}'s records</small></span></button>
            </div>
          )}
        </div>
        {sheet ? <button type="button" className="cmd-cancel" onClick={close}>Cancel</button> : <kbd className="cmd-key" aria-hidden>⌘K</kbd>}
      </div>
      {showList && (
        <div className={`cmd-list${text.length > 1 && shown !== text ? " stale" : ""}`} id="cmd-list" role="listbox" aria-label="Ask or open">
          {err && <p className={`cmd-note${isNoAgent(err) ? "" : " bad"}`} role="status">{err}</p>}
          {sections.map((s) => (
            <div key={s.label || "ask"} role="group" aria-label={s.label || "Ask"}>
              {s.label && <p className="cmd-h">{s.label}</p>}
              {s.opts.map((o) => {
                n += 1;
                const i = n;
                return (
                  <button key={o.kind === "ask" ? `a:${o.icon}:${o.text}` : `o:${o.hit.url}:${o.hit.label}`} id={`cmd-opt-${i}`} type="button" role="option" aria-selected={active === i}
                    className={`cmd-row${active === i ? " on" : ""}${o.kind === "ask" && o.icon === "ask" ? " lead" : ""}`} onMouseDown={(e) => e.preventDefault()} onMouseEnter={() => setActive(i)} onClick={() => run(o)}>
                    {o.kind === "ask" ? <AskRow o={o} where={where} /> : (
                      <><o.Icon size={16} strokeWidth={1.5} aria-hidden className="cmd-ic" /><span className="cmd-t"><b><Marked text={o.hit.label} q={shown} /></b>{o.hit.sublabel && <small>{o.hit.sublabel}</small>}</span><ArrowUpRight size={14} strokeWidth={1.5} aria-hidden className="cmd-go" /></>
                    )}
                  </button>
                );
              })}
            </div>
          ))}
          <p className="cmd-foot"><span><CornerDownLeft size={12} strokeWidth={1.75} aria-hidden /> {text ? "ask" : "choose"}</span><span>↑↓ move</span><span>esc close</span>
            <em>Answered from {company.short}'s records by code: each figure from its row, each row linked.</em></p>
        </div>
      )}
    </div>
  );
}

function AskRow({ o, where }: { o: Extract<Opt, { kind: "ask" }>; where: string }): ReactNode {
  if (o.icon === "ask") return <><span className="cmd-ai" aria-hidden><Sparkles size={14} strokeWidth={1.75} /></span><span className="cmd-t"><b>Ask Lookout: “{o.text}”</b><small>Answered {where}, step by step, from the records</small></span><kbd className="cmd-enter" aria-hidden>↵</kbd></>;
  const Icon = o.icon === "recent" ? History : MessageSquareText;
  return <><Icon size={16} strokeWidth={1.5} aria-hidden className="cmd-ic" /><span className="cmd-t"><b>{o.text}</b></span></>;
}

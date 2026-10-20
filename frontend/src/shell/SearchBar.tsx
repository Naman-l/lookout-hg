import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Building2, Cog, FileText, ListTodo, Mail, Search, User, type LucideIcon } from "lucide-react";
import { useMedia } from "../ui/useMedia";

/** One hit of the deterministic search (GET /api/search): what it is, its words, where it opens, and which part of the label matched. */
type Hit = { type: string; label: string; sublabel?: string | null; url: string; highlight?: { start: number; end: number } | [number, number] | null };
const GROUPS: [string, string, LucideIcon][] = [["item", "Items", ListTodo], ["message", "Messages", Mail], ["supplier", "Suppliers", Building2], ["part", "Parts", Cog], ["po_line", "Orders", FileText], ["person", "People", User]];
/** The match is marked only where the title itself contains the query (LOOKOUT #57): a hit found in a body or a sublabel is shown plain. */
function Marked({ hit, q }: { hit: Hit; q: string }) {
  const at = q ? hit.label.toLowerCase().indexOf(q.toLowerCase()) : -1;
  const r: [number, number] | null = at >= 0 ? [at, at + q.length] : null;
  return r ? <>{hit.label.slice(0, r[0])}<mark>{hit.label.slice(r[0], r[1])}</mark>{hit.label.slice(r[1])}</> : <>{hit.label}</>;
}

/** The top bar's one field: search. It looks things up as you type (records, items, messages) and Enter opens the top hit; it never starts an Ask. Command-K focuses it. */
/** A closed order line sorts last and reads quieter (DATA-13). */
const closed = (h: { type: string; sublabel?: string | null }) => h.type === "po_line" && /\bclosed\b/i.test(h.sublabel ?? "");

export function SearchBar() {
  const phone = useMedia("(max-width: 760px)");
  const [focus, setFocus] = useState(false);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[]>([]);
  const [active, setActive] = useState(0);
  const [asked, setAsked] = useState(false);
  const [shown, setShown] = useState("");      // the query the results on screen answer: older results dim until the new ones arrive (#58)
  const input = useRef<HTMLInputElement>(null);
  const nav = useNavigate();
  useEffect(() => {
    const h = (e: globalThis.KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); input.current?.focus(); } };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);
  useEffect(() => {
    const text = q.trim();
    if (text.length < 2) { setHits([]); setAsked(false); return; }
    const ctl = new AbortController();
    const t = setTimeout(() => {
      fetch(`/api/search?q=${encodeURIComponent(text)}&limit=12`, { signal: ctl.signal }).then((r) => (r.ok ? r.json() : [])).then((d) => { setHits(Array.isArray(d) ? d : Array.isArray(d?.hits) ? d.hits : []); setActive(0); setAsked(true); setShown(text); }).catch(() => {});
    }, 150);
    return () => { clearTimeout(t); ctl.abort(); };
  }, [q]);
  const grouped = useMemo(() => GROUPS.map(([type, label, Icon]) => ({ label, Icon, hits: hits.filter((h) => h.type === type || (type === "item" && h.type === "action_item")).sort((a, b) => Number(closed(a)) - Number(closed(b))) })).filter((g) => g.hits.length > 0), [hits]);
  const flat = useMemo(() => grouped.flatMap((g) => g.hits), [grouped]);
  const open = (n: number) => { if (flat[n]) { nav(flat[n].url); setQ(""); setHits([]); input.current?.blur(); } };
  const key = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((n) => Math.min(n + 1, flat.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((n) => Math.max(n - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); open(active); }
    else if (e.key === "Escape") { setQ(""); setHits([]); }
  };
  if (phone) return null;
  return (
    <div className="askbar" role="search">
      <Search size={16} strokeWidth={1.5} aria-hidden className="askbar-ic" />
      <input ref={input} role="combobox" aria-expanded={focus && flat.length > 0} aria-controls="askbar-results" aria-label="Search records, items and messages" placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={key} onFocus={() => setFocus(true)} onBlur={() => setTimeout(() => setFocus(false), 150)} />
      <kbd className="askbar-key" aria-hidden>⌘K</kbd>
      {focus && q.trim().length > 1 && (
        <div className={`askbar-results${shown !== q.trim() ? " stale" : ""}`} id="askbar-results" role="listbox" aria-busy={shown !== q.trim()}>
          {flat.length === 0 && asked && <p className="ar-none">Nothing found for “{q.trim()}”.</p>}
          {grouped.map((g) => (
            <div key={g.label} role="group" aria-label={g.label}>
              <p className="ar-h">{g.label}</p>
              {g.hits.map((h) => {
                const n = flat.indexOf(h);
                return (
                  <button key={h.url + h.label} type="button" role="option" aria-selected={active === n} className={`ar-row${active === n ? " on" : ""}`} onMouseDown={(e) => e.preventDefault()} onMouseEnter={() => setActive(n)} onClick={() => open(n)}>
                    <g.Icon size={16} strokeWidth={1.5} aria-hidden /><span className="ar-t"><b><Marked hit={h} q={shown} /></b>{h.sublabel && <small className={closed(h) ? "ar-closed" : undefined}>{h.sublabel}</small>}</span>
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

import { useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ChevronDown } from "lucide-react";
import { api } from "../../api/client";
import { useResource } from "../../api/useResource";
import { useMe } from "../../api/useMe";
import type { Action, ActionItem, Part, PoLine } from "../../api/types";
import { RobotIcon, useRobots, type Robot } from "../../components/domain";
import { actBy, owners, statusOf, type Status } from "../../components/domain/caseStatus";
import { caseShort, day, indexCases, legalShort, rankCases, supplierShorts } from "./model";
import "../today.css";
import "./records.css";

/** What every Records screen reads: the cases (with the viewer's status words), the robots, each part's robots, the open lines and the data date. */
export function useRecords({ orders = true, parts = true }: { orders?: boolean; parts?: boolean } = {}) {
  const { me } = useMe();
  const items = useResource(() => api.actionItems());
  const acts = useResource(() => api.actions().catch(() => [] as Action[]));
  const health = useResource(api.health);
  const lines = useResource(() => (orders ? api.orders() : Promise.resolve([] as PoLine[])), [orders]);
  const partList = useResource(() => (parts ? api.parts() : Promise.resolve([] as Part[])), [parts]);
  const robots = useRobots();
  const asOf = health.data?.as_of ?? null;
  const draftOwner = useMemo(() => new Map((acts.data ?? []).map((a) => [a.action_id, (a as Action & { owner?: string | null }).owner ?? ""])), [acts.data]);
  const idx = useMemo(() => indexCases(items.data ?? [], lines.data ?? []), [items.data, lines.data]);
  const partById = useMemo(() => new Map((partList.data ?? []).map((p) => [p.ref.id ?? "", p])), [partList.data]);
  const shortName = useMemo(() => supplierShorts(items.data ?? []), [items.data]);
  const sups = useResource(() => api.suppliers().catch(() => []));
  const shorts = useMemo(() => new Map((sups.data ?? []).map((x) => [x.ref.id ?? "", (x as { short?: string }).short ?? ""])), [sups.data]);
  // The name a buyer says (the brand word, not the legal form), as Today, the Inbox and the cases use it; the legal name only as a fallback while it loads.
  const supName = (id: string | null | undefined, legal?: string | null) => (id && shorts.get(id)) || legalShort(legal) || legal || id || "";
  const robotsOf = useMemo(() => new Map((partList.data ?? []).map((p) => [p.ref.id ?? "", p.robots ?? []])), [partList.data]);
  return {
    me, asOf, year: asOf?.slice(0, 4), robots, idx, shortName, supName, partById, robotsOf, items, lines, parts: partList,
    status: (i: ActionItem) => statusOf(i, me, draftOwner, health.data?.boot ?? ""),
    rank: (cases: ActionItem[] | undefined) => rankCases(cases ?? [], asOf),
    actBy: (i: ActionItem) => actBy(i, asOf),
  };
}
export type Records = ReturnType<typeof useRecords>;

/** The three robots in their fixed slots: coloured when the record concerns that robot, grey otherwise; the hover says how. */
export function RobotSlots({ robots, lit, on, off }: { robots: Robot[]; lit: Iterable<string>; on: string | ((id: string) => string); off: string }) {
  const set = new Set(lit);
  return (
    <span className="rc-rb">
      {robots.map((r) => {
        const tip = `${r.name} · ${set.has(r.id) ? (typeof on === "string" ? on : on(r.id)) : off}`;
        return <i key={r.id} className={set.has(r.id) ? `on r-${(r.slot % 3) + 1}` : undefined} title={tip} aria-label={tip}><RobotIcon slot={r.slot} /></i>;
      })}
    </span>
  );
}

/** The column header over the robot slots: the robots' short names. */
export const RobotHead = ({ robots, cell = true }: { robots: Robot[]; cell?: boolean }) => <span className="rc-rl" role={cell ? "columnheader" : undefined} aria-label={cell ? "Robots" : undefined}>{robots.map((r) => <span key={r.id}>{r.key}</span>)}</span>;

/** T2 P5 H1 as filters (OR), kept in the URL as ?r=T2,P5. */
export function useRobotFilter(robots: Robot[]) {
  const [params, setParams] = useSearchParams();
  const keys = new Set((params.get("r") ?? "").split(",").filter(Boolean));
  const ids = new Set(robots.filter((r) => keys.has(r.key)).map((r) => r.id));
  const toggle = (r: Robot) => {
    const n = new Set(keys);
    if (n.has(r.key)) n.delete(r.key); else n.add(r.key);
    setParam(setParams, "r", [...n].join(","));
  };
  const node = (
    <span className="td-rf" role="group" aria-label="Robots">
      {robots.map((r) => (
        <button key={r.id} type="button" aria-pressed={keys.has(r.key)} title={`Only records that concern ${r.name}`} className={keys.has(r.key) ? `on r-${(r.slot % 3) + 1}` : undefined} onClick={() => toggle(r)}>{r.key}</button>
      ))}
    </span>
  );
  return { ids, node, active: ids.size > 0, matches: (lit: Iterable<string>) => ids.size === 0 || [...lit].some((x) => ids.has(x)) };
}

/** One URL parameter set or cleared, the rest kept, without a new history entry. */
export function setParam(setParams: ReturnType<typeof useSearchParams>[1], key: string, value: string | null | undefined) {
  setParams((p) => { const n = new URLSearchParams(p); if (value) n.set(key, value); else n.delete(key); return n; }, { replace: true });
}

/** The search box, kept in the URL as ?q=; Escape clears it. */
export function SearchBox({ label }: { label: string }) {
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  useEffect(() => { const t = setTimeout(() => setParam(setParams, "q", q.trim()), 150); return () => clearTimeout(t); }, [q, setParams]);
  return <input className="td-f td-q" type="search" placeholder={label} aria-label={label} value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => { if (e.key === "Escape") setQ(""); }} />;
}

/** "N of M · clear", only while a filter is on. */
export function Showing({ n, of, clear }: { n: number; of: number; clear: () => void }) {
  return <span className="td-showing" role="status">{n} of {of} · <button type="button" onClick={clear}>clear</button></span>;
}

/** The status word in Today's colours: Held red, Decide and Approve blue, the rest ink or grey. */
export const Word = ({ st }: { st: Status }) => <span className={`rc-w k-${st.tone}`} title={st.full}>{st.word}</span>;

/** A list's Case cell: the case's short name (a link to the case), then its status word, act-by date and "+n more". */
export function CaseCell({ cases, r, more, title }: { cases: ActionItem[]; r: Records; more?: string; title?: (i: ActionItem) => string }) {
  if (cases.length === 0) return <span className="rc-case" role="cell" />;
  const top = cases[0], d = r.actBy(top);
  const name = caseShort(title ? title(top) : top.title);
  return (
    <span className="rc-case" role="cell">
      <Link className="rc-cl" to={`/items/${encodeURIComponent(top.key)}`} title={top.title}>{name}</Link>
      <small><Word st={r.status(top)} />{top.group === "trust" && <> · {/do not order/i.test(top.title) ? "do not order" : "do not pay"}</>}{d && <> · {day(d, r.year)}</>}{cases.length > 1 && (more ? <> · <Link className="rc-more" to={more}>+{cases.length - 1} more</Link></> : <> · +{cases.length - 1} more</>)}</small>
    </span>
  );
}

/** The case a PO line row names: the short name only, a link to the case. */
export function CaseName({ i, title }: { i?: ActionItem; title?: string }) {
  if (!i) return <span className="rc-case" role="cell" />;
  return <span className="rc-case" role="cell"><Link className="rc-cl" to={`/items/${encodeURIComponent(i.key)}`} title={i.title}>{caseShort(title ?? i.title)}</Link></span>;
}

/** "In a case n": every case the record is in, soonest act-by first; a row opens the case. A message held in the supplier's name says what it asked and who to call. */
export function CaseBlock({ cases, r, held, retitle }: { cases: ActionItem[]; r: Records; held?: (i: ActionItem) => string | null; retitle?: (i: ActionItem) => string }) {
  if (cases.length === 0) return null;
  return (
    <section className="rc-sec" id="cases" aria-label="In a case">
      <h2 className="rc-h2">In a case <em>{cases.length}</em></h2>
      <div className="rc-cb" role="table" aria-label="In a case">
        <div className="rc-cb-h" role="row"><span role="columnheader">Case</span><span role="columnheader" className="n">Act by</span><span role="columnheader">Status</span></div>
        {cases.map((i) => {
          const d = r.actBy(i);
          const sub = (held && held(i)) || owners(i).join(" · ");
          return (
            <div key={i.key} className="rc-cb-r rc-hit" role="row">
              <span role="cell" className="rc-cb-t">
                <Link className="rc-stretch" to={`/items/${encodeURIComponent(i.key)}`}>{retitle ? retitle(i) : i.title}</Link>
                {sub && <small>{sub}</small>}
              </span>
              <span role="cell" className={`n${d ? "" : " none"}`}>{d ? day(d, r.year) : "—"}</span>
              <span role="cell"><Word st={r.status(i)} /></span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

/** A small menu filter (Promised ▾): a button opening a short list; Escape, a click outside or a choice closes it; arrow keys move. */
export function PickMenu<K extends string>({ label, options, value, onChange }: { label: string; options: Record<K, string>; value: K | null; onChange: (v: K | null) => void }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const button = () => root.current?.querySelector<HTMLButtonElement>(".td-dd");
  useEffect(() => {
    if (!open) return;
    const down = (e: PointerEvent) => { if (!root.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("pointerdown", down);
    (root.current?.querySelector<HTMLButtonElement>("[role=menuitemradio][aria-checked=true]") ?? root.current?.querySelector<HTMLButtonElement>("[role=menuitemradio]"))?.focus();
    return () => document.removeEventListener("pointerdown", down);
  }, [open]);
  const keys = (e: ReactKeyboardEvent) => {
    if (!open) return;
    const items = [...(root.current?.querySelectorAll<HTMLButtonElement>("[role=menuitemradio]") ?? [])];
    const at = items.indexOf(document.activeElement as HTMLButtonElement);
    if (e.key === "Escape") { e.stopPropagation(); setOpen(false); button()?.focus(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); items[(at + 1) % items.length]?.focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); items[(at - 1 + items.length) % items.length]?.focus(); }
    else if (e.key === "Tab") setOpen(false);
  };
  const pick = (v: K | null) => { onChange(v); setOpen(false); button()?.focus(); };
  return (
    <div className="td-ddw" ref={root} onKeyDown={keys}>
      <button type="button" className={`td-f td-dd${value ? " on" : ""}`} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>
        {value ? options[value] : label}<ChevronDown size={14} strokeWidth={1.75} aria-hidden />
      </button>
      {open && (
        <div className="td-menu" role="menu" aria-label={label}>
          {(Object.keys(options) as K[]).map((k) => <button key={k} type="button" role="menuitemradio" aria-checked={value === k} className={value === k ? "on" : undefined} onClick={() => pick(value === k ? null : k)}>{options[k]}</button>)}
          {value && <button type="button" role="menuitemradio" aria-checked={false} className="any" onClick={() => pick(null)}>Any date</button>}
        </div>
      )}
    </div>
  );
}

/** Text tabs in Today's style (2px underline, counts in grey). */
export function TextTabs<K extends string>({ label, tabs, value, onChange }: { label: string; tabs: { id: K; label: string; count?: number; to?: string }[]; value: K; onChange?: (k: K) => void }) {
  return (
    <div className="td-tabs rc-tabs" role="tablist" aria-label={label}>
      {tabs.map((t) => t.to
        ? <Link key={t.id} to={t.to} role="tab" aria-selected={value === t.id} className={value === t.id ? "on" : undefined}>{t.label}{t.count != null && <em>{t.count}</em>}</Link>
        : <button key={t.id} type="button" role="tab" aria-selected={value === t.id} className={value === t.id ? "on" : undefined} onClick={() => onChange?.(t.id)}>{t.label}{t.count != null && <em>{t.count}</em>}</button>)}
    </div>
  );
}

/** Loading rows, as Today shows them. */
export const SkeletonRows = ({ n = 6 }: { n?: number }) => <>{Array.from({ length: n }, (_, k) => <div key={k} className="td-sk" aria-hidden><i className="w" /><i /><i /><i /><i /></div>)}</>;

export const Title = ({ children, sub, right }: { children: ReactNode; sub?: ReactNode; right?: ReactNode }) => (
  <div className="rc-title"><div><h1>{children}</h1>{sub && <p>{sub}</p>}</div>{right}</div>
);

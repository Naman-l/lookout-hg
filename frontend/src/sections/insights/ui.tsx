// Insights building blocks: a figure that opens the records it rests on, the Sources drawer, the section links, page states and two small charts.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, NavLink } from "react-router-dom";
import { X } from "lucide-react";
import { EmptyState, NotFound, Notice } from "../../ds";
import { LoadError } from "../../ds/LoadError";
import { VerticalIcon, verticalName } from "../../components/domain/Vertical";
import { ReadError, type Figure } from "./api";
import "./insights.css";

/** Where a record opens: PR and PO lines open their PR or PO, a case its page, a project its Insights page. Records with no page of their own (a quote,
 * a CS, a look-ahead row) are listed by name only. */
export function refPath(ref: string): string | null {
  const i = ref.indexOf(":");
  const kind = ref.slice(0, i), id = ref.slice(i + 1);
  switch (kind) {
    case "pr_line": case "pr": return `/prs/${encodeURIComponent(id.split("/")[0])}`;
    case "po_line": case "po": return `/pos/${encodeURIComponent(id.split("/")[0])}`;
    case "item": return `/items/${encodeURIComponent(id)}`;
    case "material": return `/materials/${encodeURIComponent(id)}`;
    case "supplier": return `/vendors/${encodeURIComponent(id)}`;
    case "project": return `/insights/projects/${encodeURIComponent(id)}`;
    case "requirement": case "fund_line": return "/requirements";
    default: return null;
  }
}

const KIND: Record<string, string> = {
  pr_line: "PR", pr: "PR", po_line: "PO", po: "PO", item: "Case", material: "Material", supplier: "Vendor", project: "Project", requirement: "Requirement row",
  fund_line: "Fund-sheet line", cs: "CS", quote: "Quote", lookahead: "Look-ahead item", budget_rate: "Budget rate", receipt: "Goods receipt",
};

/** The records behind a figure, one entry per page they open (a PR's lines together), in the order the server gave them. */
export function groupRefs(refs: string[]): { key: string; label: string; to: string | null; lines: string[] }[] {
  const out = new Map<string, { key: string; label: string; to: string | null; lines: string[] }>();
  for (const r of refs) {
    const i = r.indexOf(":");
    const kind = r.slice(0, i), id = r.slice(i + 1);
    const to = refPath(r);
    const [head, line] = id.split("/");
    const multi = kind === "pr_line" || kind === "po_line";
    const key = to && multi ? to : r;
    const label = multi ? `${KIND[kind]} ${head}` : kind === "item" ? id : `${KIND[kind] ?? kind} ${id}`;
    const g = out.get(key) ?? { key, label, to, lines: [] };
    if (multi && line) g.lines.push(line);
    out.set(key, g);
  }
  return [...out.values()];
}

type Open = { title: string; f: Figure };
const SourcesCtx = createContext<(o: Open) => void>(() => {});

/** The drawer every figure opens: the rule that computed it and each record it rests on, linked. One per page. */
export function Sources({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState<Open | null>(null);
  const close = useCallback(() => setOpen(null), []);
  return (
    <SourcesCtx.Provider value={setOpen}>
      {children}
      {open && <SourcesDrawer {...open} onClose={close} />}
    </SourcesCtx.Provider>
  );
}

const SHOW = 120;
function SourcesDrawer({ title, f, onClose }: Open & { onClose: () => void }) {
  const done = useRef<HTMLButtonElement>(null);
  const groups = useMemo(() => groupRefs(f.refs ?? []), [f.refs]);
  const [all, setAll] = useState(false);
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    done.current?.focus();
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", key);
    return () => { window.removeEventListener("keydown", key); before?.focus?.(); };
  }, [onClose]);
  const shown = all ? groups : groups.slice(0, SHOW);
  return (
    <>
      <div className="ins-dim" onClick={onClose} aria-hidden />
      <aside className="ins-src" role="dialog" aria-modal="true" aria-label={`Sources: ${title}`}>
        <div className="ins-src-h">
          <div><small>{title}</small><b>{f.text}</b></div>
          <button type="button" ref={done} onClick={onClose} aria-label="Close"><X size={18} strokeWidth={1.5} aria-hidden /></button>
        </div>
        <p className="ins-src-rule">{f.rule}{f.note ? <span> · {f.note}</span> : null}</p>
        <p className="ins-src-n">{groups.length === 0 ? "No records: nothing to count." : `${f.refs.length.toLocaleString("en-IN")} ${f.refs.length === 1 ? "record" : "records"}${groups.length !== f.refs.length ? `, ${groups.length.toLocaleString("en-IN")} to open` : ""}`}</p>
        <ul className="ins-src-l">
          {shown.map((g) => (
            <li key={g.key}>
              {g.to ? <Link to={g.to} onClick={onClose}>{g.label}</Link> : <span>{g.label}</span>}
              {g.lines.length > 0 && <small>{g.lines.length === 1 ? `line ${g.lines[0]}` : `lines ${g.lines.slice(0, 8).join(", ")}${g.lines.length > 8 ? ` +${g.lines.length - 8}` : ""}`}</small>}
            </li>
          ))}
        </ul>
        {!all && groups.length > SHOW && <button type="button" className="ins-more" onClick={() => setAll(true)}>Show all {groups.length.toLocaleString("en-IN")}</button>}
      </aside>
    </>
  );
}

/** A figure: its text, and a click that opens the records it rests on. With no records behind it, it is plain text with the rule as its tooltip.
 * The line under it (`sub`) sits beside the button, never inside it, so it may hold figures of its own. */
export function Fig({ f, title, sub, quiet }: { f: Figure | null | undefined; title: string; sub?: ReactNode; quiet?: boolean }) {
  const open = useContext(SourcesCtx);
  const cls = `ins-fig${quiet ? " quiet" : ""}`;
  const main = !f ? <span className={`${cls} none`}>—</span>
    : !f.refs?.length ? <span className={`${cls}${f.value == null ? " none" : ""}`} title={f.rule}>{f.text}</span>
    : <button type="button" className={`${cls} link`} title={`${f.rule} · open the records`} onClick={() => open({ title, f })}>{f.text}</button>;
  return sub ? <span className="ins-figw">{main}<small>{sub}</small></span> : main;
}

const PAGES = [
  { to: "/insights/team", label: "Team" }, { to: "/insights/projects", label: "Projects" },
  { to: "/insights/pricing", label: "Pricing" }, { to: "/insights/estimates", label: "Estimates" },
];
/** The four Insights pages, one tap apart on a phone too. */
export const InsightsNav = () => (
  <nav className="ins-nav" aria-label="Insights">
    {PAGES.map((p) => <NavLink key={p.to} to={p.to} className={({ isActive }) => (isActive ? "on" : "")}>{p.label}</NavLink>)}
  </nav>
);

/** The read error the page should explain, if any (useResource keeps only the message). */
export function useReadError<T>(load: () => Promise<T>, deps: unknown[]): { data?: T; error?: ReadError; loading: boolean } {
  const [state, setState] = useState<{ data?: T; error?: ReadError; loading: boolean }>({ loading: true });
  useEffect(() => {
    let live = true;
    setState({ loading: true });
    load().then((data) => live && setState({ data, loading: false }), (e: unknown) => live && setState({ loading: false, error: e instanceof ReadError ? e : new ReadError(0, String(e)) }));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return state;
}

export function ReadFailed({ e, what, notFound }: { e: ReadError; what: string; notFound: { title: string; line: string } }) {
  if (e.status === 404) return <NotFound title={notFound.title} line={notFound.line} />;
  if (e.status === 403) return <Notice>{e.detail || "This page is not yours to see."}</Notice>;
  return <LoadError what={what} retry={() => window.location.reload()} />;
}

/** A vertical's icon and name. */
export const Vert = ({ id, short }: { id: string; short?: boolean }) => (
  <span className="ins-vert"><VerticalIcon id={id} size={14} />{!short && <span>{verticalName(id)}</span>}</span>
);

/** A row of label-value pairs that wraps on a phone. */
export const Facts = ({ items }: { items: [ReactNode, ReactNode][] }) => (
  <dl className="ins-facts">{items.map(([k, v], i) => <div key={i}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
);

/** A small trend line over months (nulls are gaps), drawn in ink; the last point is marked. Decorative beside its figure, so hidden from readers. */
export function Spark({ values, width = 96, height = 24 }: { values: (number | null)[]; width?: number; height?: number }) {
  const pts = values.map((v, i) => (v == null ? null : [i, v] as const)).filter(Boolean) as (readonly [number, number])[];
  if (pts.length < 2) return <span className="ins-spark-none" aria-hidden>—</span>;
  const lo = Math.min(...pts.map((p) => p[1])), hi = Math.max(...pts.map((p) => p[1]));
  const x = (i: number) => (i / Math.max(1, values.length - 1)) * (width - 4) + 2;
  const y = (v: number) => (hi === lo ? height / 2 : height - 3 - ((v - lo) / (hi - lo)) * (height - 6));
  const d = pts.map((p, n) => `${n ? "L" : "M"}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join(" ");
  const last = pts[pts.length - 1];
  return (
    <svg className="ins-spark" width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden>
      <path d={d} fill="none" stroke="currentColor" strokeWidth={1.4} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={x(last[0])} cy={y(last[1])} r={2.2} fill="currentColor" />
    </svg>
  );
}

/** A horizontal bar for a share of the largest value in a set; the figure beside it is the reading, the bar only the shape. */
export const Bar = ({ value, max, tone }: { value: number; max: number; tone?: "muted" | "accent" }) => (
  <span className={`ins-bar${tone ? ` ${tone}` : ""}`} aria-hidden><i style={{ width: `${max > 0 ? Math.max(1.5, (100 * value) / max) : 0}%` }} /></span>
);

export const Empty = EmptyState;

/** Whose move a function is, as the ladder names it, and its token class (a dot plus the word, never colour alone). */
export const FUNCTIONS = ["SCM", "Projects", "Vendor", "QA", "Finance", "Management"] as const;
export const WhoDot = ({ who, n }: { who: string; n?: number }) => <span className="ins-who"><i className={`w-${who.toLowerCase()}`} aria-hidden />{who}{n != null ? ` ${n}` : ""}</span>;

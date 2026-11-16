// Records: what every Records screen shares. The tab row, Yours / Everyone, the project picker, links from a record ref, dates and money as HG writes them.
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Link, NavLink, useSearchParams } from "react-router-dom";
import { Check, ChevronDown, Search, X } from "lucide-react";
import { api } from "../../api/client";
import { invalidate, useResource } from "../../api/useResource";
import type { EntityRef, Money, ProjectRow } from "../../api/types";
import { Skeleton } from "../../ds";
import { LoadError } from "../../ds/LoadError";
import { NotFound } from "../../ds/NotFound";
import { VERTICALS, VerticalIcon, verticalName } from "../../components/domain/Vertical";
import { baseOf, enIn, inr, longDate, shortDate } from "../../ui/format";
import "../../components/domain/domain.css";      // the five vertical colours the icons wear
import "./records.css";

const TABS = [
  { to: "/vendors", label: "Vendors" }, { to: "/materials", label: "Materials" }, { to: "/prs", label: "PRs" }, { to: "/pos", label: "POs" },
  { to: "/requirements", label: "Requirements" }, { to: "/workfronts", label: "Work fronts" },
];

/** The Records tab row: one link per list. A record page shows it too, its list marked, so the way back is always one tap. */
export function RecordsTabs() {
  return (
    <nav className="rc-tabs" aria-label="Records">
      {TABS.map((t) => <NavLink key={t.to} to={t.to} className={({ isActive }) => (isActive ? "on" : undefined)}>{t.label}</NavLink>)}
    </nav>
  );
}

/** A list page's title row: the title, a quiet line under it, and a control on the right (Yours / Everyone). */
export function ListTitle({ title, sub, right }: { title: string; sub?: ReactNode; right?: ReactNode }) {
  return (
    <div className="rc-title">
      <div><h1>{title}</h1>{sub && <p>{sub}</p>}</div>
      {right}
    </div>
  );
}

/** Yours (the viewer's purchasing group) or Everyone, each with its count. */
export function WhoSwitch({ value, onChange, mine, all, me }: { value: "mine" | "all"; onChange: (v: "mine" | "all") => void; mine?: number; all?: number; me: string | null }) {
  return (
    <div className="rc-who" role="group" aria-label="Whose lines">
      {(["mine", "all"] as const).map((w) => (
        <button key={w} type="button" aria-pressed={value === w} disabled={w === "mine" && !me} title={w === "mine" ? (me ? `The lines on ${me}'s purchasing group` : "Choose who you are first") : "Every purchasing group"}
          onClick={() => onChange(w)}>
          {w === "mine" ? "Yours" : "Everyone"}{(w === "mine" ? mine : all) != null && <em>{enIn((w === "mine" ? mine : all)!)}</em>}
        </button>
      ))}
    </div>
  );
}

/** The URL holds a list's filters, so Back returns to the same slice and a link can share it. */
export function useUrl() {
  const [params, setParams] = useSearchParams();
  const get = (k: string) => params.get(k) ?? undefined;
  const set = (patch: Record<string, string | null | undefined>) =>
    setParams((p) => {
      const n = new URLSearchParams(p);
      for (const [k, v] of Object.entries(patch)) { if (v) n.set(k, v); else n.delete(k); }
      return n;
    }, { replace: true });
  return { get, set };
}

/** Every project, by id, with what a picker matches on (name, aliases, plant codes). Loaded once per page. */
export function useProjects() {
  const r = useResource(api.projects);
  const byId = useMemo(() => new Map((r.data ?? []).map((p) => [p.ref.id, p])), [r.data]);
  return { list: r.data ?? [], byId, loading: r.loading, error: r.error };
}
export type Projects = ReturnType<typeof useProjects>;

const projectText = (p: ProjectRow) => `${p.name} ${p.aliases.join(" ")} ${p.plants.join(" ")} ${verticalName(p.vertical)}`.toLowerCase();
/** Whether a project matches typed text by its name, any alias the sheets use, or a plant code. */
export const projectMatches = (p: ProjectRow | undefined, q: string) => !!p && projectText(p).includes(q.trim().toLowerCase());

/** A project picker that finds a project by name or by any name the sheets and SAP use for it (an alias in a sheet finds its project), grouped by vertical. */
export function ProjectPicker({ projects, value, onChange, only, label = "Project" }: { projects: ProjectRow[]; value?: string; onChange: (id: string | undefined) => void; only?: (p: ProjectRow) => boolean; label?: string }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const btn = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const chosen = projects.find((p) => p.ref.id === value);
  const shown = projects.filter((p) => (!only || only(p)) && (!q.trim() || projectMatches(p, q)));
  useLayoutEffect(() => {
    if (!open || !btn.current) return;
    const r = btn.current.getBoundingClientRect();
    setPos({ top: r.bottom + 4, left: Math.max(8, Math.min(r.left, window.innerWidth - 328)) });
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const down = (e: PointerEvent) => { if (!menu.current?.contains(e.target as Node) && !btn.current?.contains(e.target as Node)) setOpen(false); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); btn.current?.focus(); } };
    const resize = () => setOpen(false);
    document.addEventListener("pointerdown", down); window.addEventListener("keydown", key); window.addEventListener("resize", resize);
    return () => { document.removeEventListener("pointerdown", down); window.removeEventListener("keydown", key); window.removeEventListener("resize", resize); };
  }, [open]);
  const pick = (id: string | undefined) => { onChange(id); setOpen(false); setQ(""); btn.current?.focus(); };
  return (
    <div className="fb-chip-wrap rc-pp">
      <button ref={btn} type="button" className={`fb-chip${chosen ? " on" : ""}`} aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span>{chosen ? `${label}: ${chosen.name}` : label}</span><ChevronDown size={14} strokeWidth={1.5} aria-hidden />
      </button>
      {chosen && <button type="button" className="fb-clear" aria-label={`Clear ${label.toLowerCase()}`} onClick={() => pick(undefined)}><X size={14} strokeWidth={1.5} aria-hidden /></button>}
      {open && createPortal(
        <div ref={menu} className="fb-menu fb-float rc-pp-menu" role="dialog" aria-label={`Choose a ${label.toLowerCase()}`} style={pos ? { top: pos.top, left: pos.left } : { visibility: "hidden" }}>
          <label className="rc-pp-q">
            <Search size={16} strokeWidth={1.5} aria-hidden />
            <input autoFocus placeholder="Name, other name or plant code" aria-label="Find a project" value={q} onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && shown.length) { e.preventDefault(); pick(shown[0].ref.id); } }} />
          </label>
          {shown.length === 0 && <p className="rc-pp-none">No project goes by that name.</p>}
          {VERTICALS.map((v) => {
            const ps = shown.filter((p) => p.vertical === v.id);
            if (!ps.length) return null;
            return (
              <div key={v.id} role="group" aria-label={v.name}>
                <div className="fb-group-h">{v.name}</div>
                {ps.map((p) => {
                  const alias = q.trim() && !p.name.toLowerCase().includes(q.trim().toLowerCase()) ? p.aliases.find((a) => a.toLowerCase().includes(q.trim().toLowerCase())) : undefined;
                  return (
                    <button key={p.ref.id} type="button" aria-pressed={p.ref.id === value} onClick={() => pick(p.ref.id === value ? undefined : p.ref.id)}>
                      {p.ref.id === value ? <Check size={16} strokeWidth={1.5} aria-hidden /> : <VerticalIcon id={p.vertical} />}
                      <span>{p.name}{alias && <small className="rc-pp-alias"> · {alias}</small>}</span>
                      <small>{p.plants.join(", ") || "no plant yet"}</small>
                    </button>
                  );
                })}
              </div>
            );
          })}
        </div>,
        document.body,
      )}
    </div>
  );
}

/** A record ref as a link target: a vendor, a material, a PR or PO (by its line), a message in the Inbox, a case on Today, a project's requirement. */
export function refTo(r: EntityRef | null | undefined): string | null {
  if (!r) return null;
  const id = r.id;
  switch (r.type) {
    case "supplier": case "supplier_record": return `/vendors/${encodeURIComponent(id)}`;
    case "material": return `/materials/${encodeURIComponent(id)}`;
    case "pr": case "pr_line": return `/prs/${encodeURIComponent(id.split("/")[0])}`;
    case "po": case "po_line": case "milestone": return `/pos/${encodeURIComponent(id.split("/")[0])}`;
    case "message": return `/inbox/${encodeURIComponent(id)}`;
    case "item": return `/items/${encodeURIComponent(id)}`;
    case "project": return `/requirements?project=${encodeURIComponent(id)}`;
    default: return null;
  }
}

/** A ref as a link with its name, the id after it where the name is not the id ("<vendor> · <code>"). */
export function RefLink({ r, id = true, children }: { r: EntityRef | null | undefined; id?: boolean; children?: ReactNode }) {
  if (!r) return <span className="none">—</span>;
  const to = refTo(r);
  const label = children ?? (r.label && id && r.label !== r.id ? <>{r.label} <span className="rc-id">· {r.id}</span></> : r.label || r.id);
  return to ? <Link className="rc-link" to={to}>{label}</Link> : <span>{label}</span>;
}

/** "<PR or PO number>/<item>" -> its PR or PO page; the line id is what people quote. */
export const lineTo = (kind: "pr" | "po", lineId: string) => `/${kind}s/${encodeURIComponent(lineId.split("/")[0])}`;

// Dates: day first; the year only when it is not the data's own year (the records run Nov 2025 to Oct 2026).
let YEAR = "";
/** Loads the data date once and remembers its year, so "8 Nov 2025" keeps its year and "13 Oct" does not need one. */
export function useAsOf(): string | null {
  const h = useResource(api.health);
  const asOf = h.data?.as_of ?? null;
  if (asOf) YEAR = asOf.slice(0, 4);
  return asOf;
}
export const day = (iso: string | null | undefined) => (!iso ? "—" : YEAR && iso.slice(0, 4) === YEAR ? shortDate(iso) : longDate(iso));

/** Money as the screens say it (₹1.4 Cr, ₹15 L, ₹8,500); `exact` writes every rupee. */
export const rs = (m: Money | number | string | null | undefined, exact = false) => (m == null ? "—" : typeof m === "object" ? inr(baseOf(m), exact) : inr(m, exact));
/** A rate per unit: "₹1,550/MT". */
export const rate = (x: number | string | null | undefined, uom?: string | null) => (x == null ? "—" : `${inr(x, true)}${uom ? `/${uom}` : ""}`);
export const days = (n: number | null | undefined) => (n == null ? "—" : `${enIn(n)} ${Math.abs(n) === 1 ? "day" : "days"}`);
export const pct = (n: number | null | undefined, signed = true) => (n == null ? "—" : `${signed && n > 0 ? "+" : ""}${n.toLocaleString("en-IN", { maximumFractionDigits: 1 })}%`);
export const plural = (n: number, one: string, many = `${one}s`) => `${enIn(n)} ${n === 1 ? one : many}`;

/** The library writes verticals by name; the app's verticals have ids and icons. */
const LIB: Record<string, string> = { roads: "roads", railway: "railway", bess: "bess", solar: "solar", "t&d": "td", td: "td" };
export const verticalId = (name: string) => LIB[name.trim().toLowerCase()] ?? name.trim().toLowerCase();

/** A vertical as its icon and name. */
export const Vertical = ({ id, name = true }: { id: string; name?: boolean }) => (
  <span className="rc-vert"><VerticalIcon id={id} title={name ? undefined : verticalName(id)} />{name && verticalName(id)}</span>
);

/** The plain-word flags a line carries ("PO with no PR"). */
export const Flags = ({ flags }: { flags: string[] }) => (flags.length ? <span className="rc-flags">{flags.map((f) => <span key={f} className="ds-chip">{f}</span>)}</span> : <span className="none">—</span>);

/** A record page's section: the one heading style with its count, then the body. */
export function Block({ title, count, id, note, children }: { title: string; count?: number | string; id?: string; note?: ReactNode; children: ReactNode }) {
  return (
    <section className="rc-sec" id={id} aria-label={title}>
      <h2 className="ds-st">{title}{count != null && <em className="rc-n">{typeof count === "number" ? enIn(count) : count}</em>}</h2>
      {note && <p className="rc-note">{note}</p>}
      {children}
    </section>
  );
}

/** Facts as label and value, two columns on a desktop, stacked on a phone. A missing value is a dash, never a guess. */
export function Facts({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="rc-kv">
      {rows.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v == null || v === "" ? <span className="none">—</span> : v}</dd></div>)}
    </dl>
  );
}

/** A record page that could not load: not found for a 404, a retry for anything else, skeletons while loading. */
export function PageState({ what, error, kind }: { what: string; error?: string; kind: string }) {
  if (error?.startsWith("404")) return <NotFound title={`No such ${kind}`} line={`Nothing in the records goes by ${what}.`} />;
  if (error) return <><RecordsTabs /><LoadError what={what} retry={invalidate} /></>;
  return <div className="rc"><RecordsTabs /><LoadingRows n={6} /></div>;
}

/** Loading rows for a list. */
export const LoadingRows = ({ n = 8 }: { n?: number }) => (
  <div className="rc-sk" aria-busy="true" aria-label="Loading">{Array.from({ length: n }, (_, k) => <div key={k}><Skeleton width="38%" /><Skeleton width="14%" /><Skeleton width="10%" /></div>)}</div>
);

/** A long list shows its first rows, then more on request (a buyer searches; nobody scrolls 2,000 lines). */
export function useMore<T>(rows: T[], step = 150, reset: unknown = null) {
  const [n, setN] = useState(step);
  useEffect(() => { setN(step); }, [reset, step]);
  const shown = rows.slice(0, n);
  const more = rows.length > n
    ? <button type="button" className="rc-more" onClick={() => setN(n + step)}>{rows.length - n > step ? <>Show {enIn(step)} more <span>({enIn(rows.length - n)} not shown)</span></> : <>Show the last {enIn(rows.length - n)}</>}</button>
    : null;
  return { shown, more };
}

/** "Showing 12 of 2,051 · Clear" while a filter narrows a list. */
export const Showing = ({ n, of, what }: { n: number; of: number; what: string }) => <p className="rc-count" role="status">{n === of ? `${enIn(of)} ${what}` : `${enIn(n)} of ${enIn(of)} ${what}`}</p>;

/** Whose move, as a person says it: "With Projects". */
export const withWho = (w: string | null | undefined) => (w ? `With ${w}` : "");

import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, ChevronRight } from "lucide-react";
import { useFits } from "./useFits";
import type { ButtonHTMLAttributes, MouseEventHandler, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { useMedia } from "../ui/useMedia";
import { Sheet } from "./Sheet";

/* Lookout DS v1: the components every screen is made of. Phone and desktop share each one; only the layout changes. */
export { Sheet } from "./Sheet";
export { NotFound } from "./NotFound";
export { RightPanel } from "./RightPanel";
export { Value as ProvenanceLink } from "../domain-ui/Value";
export { AgentMark } from "../ui/AgentMark";

export type State = "done" | "expected" | "late" | "disrupted" | "unknown" | "na" | "high" | "med" | "low";
export type Tone = "critical" | "caution" | "positive" | "unknown";

/** A state is a dot plus a word, never colour alone: pair this with text. */
export const StateDot = ({ state }: { state: State }) => <i className={`ds-dot ${state}`} aria-hidden />;
export const StateChip = ({ tone, children }: { tone?: Tone; children: ReactNode }) => <span className={`ds-chip${tone ? ` tone-${tone}` : ""}`}>{children}</span>;

/** One primary per view. A link when `to` is given, a button otherwise. */
export function Button({ variant = "secondary", to, children, ...rest }: { variant?: "primary" | "secondary" | "quiet"; to?: string; children: ReactNode } & ButtonHTMLAttributes<HTMLButtonElement>) {
  const cls = `ds-btn${variant === "secondary" ? "" : ` ${variant}`}`;
  if (to) return <Link className={cls} to={to} onClick={rest.onClick as unknown as MouseEventHandler<HTMLAnchorElement>}>{children}</Link>;
  return <button type="button" className={cls} {...rest}>{children}</button>;
}

const TONE_STATE: Record<Tone, State> = { critical: "disrupted", caution: "late", positive: "done", unknown: "unknown" };
/** A figure in ink and its label; the tone is a small dot before the label, never a coloured number. */
export function Tile({ figure, label, tone }: { figure: ReactNode; label: ReactNode; tone?: Tone }) {
  return <div className="ds-tile"><b>{figure}</b><span>{tone && <StateDot state={TONE_STATE[tone]} />}{label}</span></div>;
}
export const Tiles = ({ children }: { children: ReactNode }) => <div className="ds-tiles">{children}</div>;

/** A list row: a state dot, a title (wraps to two lines), a second line (clamped with an ellipsis) and a figure on the right. Any part may be absent. */
export function Row({ to, onClick, state, title, sub, figure, note, active, onHover, owner, date, stage }: { to?: string; onClick?: () => void; active?: boolean; onHover?: () => void; state?: State; title: ReactNode; sub?: ReactNode; figure?: ReactNode; note?: ReactNode; owner?: ReactNode; date?: ReactNode; stage?: ReactNode }) {
  const inner = (
    <>
      {state ? <StateDot state={state} /> : <span />}
      <span className="t">{title}</span>
      {sub !== undefined && <span className="s">{sub}</span>}
      {owner !== undefined && <span className="own">{owner}</span>}
      {(figure !== undefined || note !== undefined) && <span className="f">{figure}{note !== undefined && <small>{note}</small>}</span>}
      {date !== undefined && <span className="dt">{date}</span>}
      {stage !== undefined && <span className="stg-cell">{stage}</span>}
    </>
  );
  const cls = `ds-row${active ? " active" : ""}${owner !== undefined || stage !== undefined ? " wide" : ""}`;
  if (to) return <Link className={cls} to={to} onMouseEnter={onHover}>{inner}</Link>;
  if (onClick) return <button type="button" className={cls} onClick={onClick} onMouseEnter={onHover}>{inner}</button>;
  return <div className={cls}>{inner}</div>;
}
export const RowGroup = ({ children }: { children: ReactNode }) => <div className="ds-group">{children}</div>;

export type SegItem = { id: string; label: string; count?: number | string };
export function SegmentedControl({ items, value, onChange, label = "Sections" }: { items: SegItem[]; value: string; onChange: (id: string) => void; label?: string }) {
  const { box, full, fits } = useFits();
  const [open, setOpen] = useState(false);
  const menu = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const down = (e: MouseEvent) => { if (!menu.current?.contains(e.target as Node)) setOpen(false); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", down); window.addEventListener("keydown", key);
    return () => { document.removeEventListener("mousedown", down); window.removeEventListener("keydown", key); };
  }, [open]);
  const cur = items.find((x) => x.id === value);
  const tabs = (
    <div ref={full} className={`ds-seg${fits ? "" : " ds-ghost"}`} role={fits ? "tablist" : undefined} aria-label={fits ? label : undefined} aria-hidden={fits ? undefined : true}
      {...(fits ? {} : { inert: "" as unknown as boolean })} onKeyDown={(e) => {
      const n = items.findIndex((x) => x.id === value);
      const to = e.key === "ArrowRight" ? n + 1 : e.key === "ArrowLeft" ? n - 1 : e.key === "Home" ? 0 : e.key === "End" ? items.length - 1 : -1;
      if (to < 0) return;
      e.preventDefault();
      const next = items[(to + items.length) % items.length];
      const tabBox = e.currentTarget;
      onChange(next.id);
      requestAnimationFrame(() => (tabBox.querySelector('[aria-selected="true"]') as HTMLElement | null)?.focus());
    }}>
      {items.map((x) => (
        <button key={x.id} type="button" role="tab" tabIndex={x.id === value ? 0 : -1} aria-selected={x.id === value} onClick={() => onChange(x.id)}>
          {x.label}{x.count !== undefined && <em>{x.count}</em>}
        </button>
      ))}
    </div>
  );
  return (
    <div className="ds-fit" ref={box}>
      {tabs}
      {!fits && (
        <div className="ds-seg-one" ref={menu}>
          <button type="button" className="ds-seg-btn" aria-haspopup="menu" aria-expanded={open} aria-label={`${label}: ${cur?.label ?? ""}`} onClick={() => setOpen(!open)}>
            <span>{cur?.label ?? label}</span>{cur?.count !== undefined && <em>{cur.count}</em>}<ChevronDown size={14} strokeWidth={1.5} aria-hidden />
          </button>
          {open && (
            <div className="fb-menu" role="menu" aria-label={label}>
              {items.map((x) => (
                <button key={x.id} type="button" role="menuitemradio" aria-checked={x.id === value} onClick={() => { onChange(x.id); setOpen(false); }}>
                  {x.id === value ? <Check size={16} strokeWidth={1.5} aria-hidden /> : <i aria-hidden />}<span>{x.label}</span>{x.count !== undefined && <small>{x.count}</small>}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export type SectionDef = SegItem & { render: () => ReactNode };
/** Sections, not scrolls: on a desktop a segmented control shows one section at a time; on a phone the first section is the page and the rest are rows that open a sheet. */
export function Section({ sections, current, onSelect }: { sections: SectionDef[]; current: string; onSelect: (id: string) => void }) {
  const phone = useMedia("(max-width: 760px)");
  const active = sections.find((x) => x.id === current) ?? sections[0];
  if (!phone) {
    return (
      <>
        <SegmentedControl items={sections} value={active.id} onChange={onSelect} />
        <div className="ds-panel" role="tabpanel" style={{ marginTop: "var(--s5)" }}>{active.render()}</div>
      </>
    );
  }
  const [first, ...rest] = sections;
  const open = rest.find((x) => x.id === current);
  return (
    <>
      {first.render()}
      <div className="ds-rows" style={{ marginTop: "var(--s2)" }}>
        {rest.map((x) => <button key={x.id} type="button" className="x" onClick={() => onSelect(x.id)}><span>{x.label}</span><span>{x.count !== undefined ? `${x.count} ›` : "›"}</span></button>)}
      </div>
      {open && <Sheet title={open.label} hint={open.count !== undefined ? String(open.count) : undefined} onClose={() => onSelect(first.id)}>{open.render()}</Sheet>}
    </>
  );
}

/** `flow` lets the header scroll away with the page (a long log of steps beneath it reads better than a pinned title). */
export function PageHeader({ back, title, meta, actions, flow = false }: { back?: { to: string; label: string }; title: ReactNode; meta?: ReactNode; actions?: ReactNode; flow?: boolean }) {
  const ref = useRef<HTMLElement>(null);
  const [stuck, setStuck] = useState(false);
  // The title row stays under the top bar while the page scrolls; past 48 px it shrinks to the title and its action, and the rest of the page keeps its place beneath it (--hd-h).
  useEffect(() => {
    const el = ref.current; if (!el) return;
    const root = document.documentElement;
    const size = () => root.style.setProperty("--hd-h", `${el.offsetHeight}px`);
    const scroll = () => setStuck((was) => (was ? window.scrollY > 16 : window.scrollY > 48));
    const ro = new ResizeObserver(size); ro.observe(el); size(); scroll();
    window.addEventListener("scroll", scroll, { passive: true });
    return () => { ro.disconnect(); window.removeEventListener("scroll", scroll); root.style.removeProperty("--hd-h"); };
  }, []);
  return (
    <header className={`ds-hd${flow ? " flow" : stuck ? " stuck" : ""}`} ref={ref}>
      {back && <Link className="back" to={back.to}>{back.label}</Link>}
      <div className="hd-row"><h1>{title}</h1>{actions}</div>
      {meta && <div className="meta">{meta}</div>}
    </header>
  );
}

export const Notice = ({ tone, children }: { tone?: "risk"; children: ReactNode }) => <div className={`ds-notice${tone ? ` ${tone}` : ""}`} role={tone ? "alert" : "status"}>{children}</div>;
export const EmptyState = ({ children }: { children: ReactNode }) => <p className="ds-empty">{children}</p>;
export const Skeleton = ({ width = 240 }: { width?: number | string }) => <span className="ds-skel" style={{ width }} aria-hidden />;

export function Field(props: ({ kind?: "input" } & InputHTMLAttributes<HTMLInputElement>) | ({ kind: "textarea" } & TextareaHTMLAttributes<HTMLTextAreaElement>) | ({ kind: "select" } & SelectHTMLAttributes<HTMLSelectElement>)) {
  if (props.kind === "textarea") { const { kind: _k, ...r } = props; return <textarea className="ds-field" {...r} />; }
  if (props.kind === "select") { const { kind: _k, ...r } = props; return <select className="ds-field" {...r} />; }
  const { kind: _k, ...r } = props; return <input className="ds-field" {...r} />;
}

export type NavDef = { to: string; match?: string[]; label: string; icon?: ReactNode; count?: ReactNode; tip?: string; hot?: boolean; end?: boolean; sepBefore?: boolean; section?: string; onClick?: () => void };
/** The sections of the app: a sidebar on a desktop, five tabs on a phone. */
export function SideNav({ items }: { items: NavDef[] }) {
  const here = useLocation().pathname;
  return (
  <nav className="ds-nav" aria-label="Sections">
    {items.map((x) => (
      <div key={x.to} style={{ display: "contents" }}>
        {x.sepBefore && <div className="sep" />}
        {x.section && <div className="sec">{x.section}</div>}
        <NavLink to={x.to} end={x.end} className={({ isActive }) => ((x.match ? x.match.some((m) => here === m || here.startsWith(m + "/")) : isActive) ? "on" : "")}>{x.icon}{x.label}{x.count !== undefined && x.count !== null && <span className="n" title={x.tip}>{x.count}</span>}</NavLink>
      </div>
    ))}
  </nav>
  );
}
export const TabBar = ({ items, isOn }: { items: NavDef[]; isOn?: (to: string) => boolean }) => (
  <nav className="ds-tabs" aria-label="Main">
    {items.map((x) => x.onClick
      ? <button key={x.to} type="button" onClick={x.onClick} aria-label={x.label}>{x.icon}<span>{x.label}</span></button>
      : <NavLink key={x.to} to={x.to} end={x.end} className={isOn?.(x.to) ? "on" : ""} aria-label={x.label}>{x.icon}<span>{x.label}</span>{x.hot && x.count ? <b>{x.count}</b> : null}</NavLink>)}
  </nav>
);

/** A quiet button that opens or closes more of the same thing: a chevron says which, the whole button is the target. */
export function Disclose({ open, onClick, children, className = "" }: { open: boolean; onClick: () => void; children: ReactNode; className?: string }) {
  return (
    <button type="button" className={`disclose ${className}`.trim()} aria-expanded={open} onClick={onClick}>
      {children}{open ? <ChevronDown size={16} strokeWidth={1.5} aria-hidden /> : <ChevronRight size={16} strokeWidth={1.5} aria-hidden />}
    </button>
  );
}

/** The one section heading (14/600, sentence case, flush to the content edge) and the one field label (12/500, muted): every other heading style folds into these two. */
export const SectionTitle = ({ children }: { children: ReactNode }) => <h2 className="ds-st">{children}</h2>;
export const FieldLabel = ({ children }: { children: ReactNode }) => <span className="ds-fl">{children}</span>;

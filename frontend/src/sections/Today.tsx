import { useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { Link } from "react-router-dom";
import { ChevronDown, SlidersHorizontal } from "lucide-react";
import { api } from "../api/client";
import { useResource } from "../api/useResource";
import type { ActionItem, ProjectRow } from "../api/types";
import { baseOf, inr, shortDate } from "../ui/format";
import { useMe } from "../api/useMe";
import { useMedia } from "../ui/useMedia";
import { VERTICALS, VerticalIcon } from "../components/domain";
import { first, owners, statusOf, yourMove, type Status } from "../components/domain/caseStatus";
import "./today.css";
import { LoadError } from "../ds/LoadError";
import { invalidate } from "../api/useResource";

/** The tabs a buyer reads Today by: one per kind of case, set by the detector that raised it. */
const TABS = [["requirement", "Requirement"], ["after_po", "After PO"], ["price", "Price"], ["payments", "Payments"], ["vendor_risk", "Vendor risk"], ["trust", "Trust"],
  ["unknown", "Unknowns"]] as const;
type Tab = (typeof TABS)[number][0];
const tabName = (t: string) => TABS.find(([k]) => k === t)?.[1] ?? t;

const BY = { overdue: "Overdue", week: "This week", two: "2 weeks", month: "This month", none: "No date" } as const;
type By = keyof typeof BY;
const WAITING = ["SCM", "Projects", "Finance", "QA", "Vendor", "Management"] as const;

/** Yours / Everyone lasts for this browser tab only: a new visit always opens on Yours. */
const remember = (k: string, v?: string): string | null => {
  try { if (v !== undefined) sessionStorage.setItem(k, v); return sessionStorage.getItem(k); } catch { return null; }
};
const daysFrom = (d: string, asOf: string) => Math.round((Date.parse(d) - Date.parse(asOf)) / 864e5);

/** The figure in the ₹ column, the way the column reads it; what it means is in the tooltip. */
function stake(i: ActionItem): { text: string | null; tip: string } {
  const v = baseOf(i.at_stake);
  // an unknown reads "unknown" (the records cannot say yet, and the tooltip says who can); a blank is a case with no ₹ figure at all
  if (v == null || !v) return i.at_stake && "owner" in (i.at_stake as object)
    ? { text: "unknown", tip: `Unknown: ${(i.at_stake as { question?: string }).question ?? ""}` }
    : { text: null, tip: "Not computable from the records: the case says why" };
  const label = i.at_stake_label && i.at_stake_label !== "at stake" ? i.at_stake_label : "";
  const team = i.team_total ? ` · the whole case: ${inr(baseOf(i.team_total))}` : "";
  return { text: inr(v), tip: `${label ? label[0].toUpperCase() + label.slice(1) : "At stake"}: ${i.at_stake_rule}${team}` };
}

/** The five verticals, always in the same slots: lit in the vertical's colour when the case touches it; the tooltip names its projects and the site impact. */
function Verticals({ i }: { i: ActionItem }) {
  return (
    <span className="td-vt">
      {VERTICALS.map((v) => {
        const on = (i.verticals ?? []).includes(v.id);
        const pj = (i.projects ?? []).filter((p) => p.label).map((p) => p.label).slice(0, 4).join(", ");
        const imp = (i.site_impact ?? []).slice(0, 2).map((s) => `${s.project.label} · ${s.front} stops ~${shortDate(s.stops_on)}`).join("; ");
        const tip = on ? `${v.name} · ${[pj, imp].filter(Boolean).join(" · ") || "touches this vertical"}` : `${v.name} · not affected`;
        return <i key={v.id} className={on ? "on" : undefined} title={tip} aria-label={tip}><VerticalIcon id={v.id} on={on} size={15} /></i>;
      })}
    </span>
  );
}

/** Where it stands: a hairline through the seven stages with the current one marked, and the one word under it. */
function StatusCell({ st }: { st: Status }) {
  const x = (j: number) => 4 + (j * 80) / 6;
  return (
    <span className="td-st" title={st.full}>
      <svg viewBox="0 0 88 8" width="88" height="8" aria-hidden>
        <line className="todo" x1="4" y1="4" x2="84" y2="4" />
        {st.step > 0 && <line className="past" x1="4" y1="4" x2={x(st.step)} y2="4" />}
        {[0, 1, 2, 3, 4, 5, 6].map((j) => (j === st.step ? null : <circle key={j} className={j < st.step ? "past" : "todo"} cx={x(j)} cy="4" r="2" />))}
        <circle className={`now k-${st.tone}`} cx={x(st.step)} cy="4" r="3.5" />
      </svg>
      <span className={`w k-${st.tone}`}>{st.word}</span>
    </span>
  );
}

/** A filter menu: a button that opens a short list; Escape, a click outside or a choice closes it; arrow keys move. */
function Menu<T extends string>({ label, value, options, onChange }: { label: string; value: T | null; options: [T, string][]; onChange: (v: T | null) => void }) {
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
    if (e.key === "Escape") { setOpen(false); button()?.focus(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); items[(at + 1) % items.length]?.focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); items[(at - 1 + items.length) % items.length]?.focus(); }
    else if (e.key === "Tab") setOpen(false);
  };
  const pick = (v: T | null) => { onChange(v); setOpen(false); button()?.focus(); };
  const shown = options.find(([k]) => k === value)?.[1];
  return (
    <div className="td-ddw" ref={root} onKeyDown={keys}>
      <button type="button" className={`td-f td-dd${value ? " on" : ""}`} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>
        {shown ?? label}<ChevronDown size={14} strokeWidth={1.75} aria-hidden />
      </button>
      {open && (
        <div className="td-menu" role="menu" aria-label={label}>
          {options.map(([k, l]) => <button key={k} type="button" role="menuitemradio" aria-checked={value === k} className={value === k ? "on" : undefined} onClick={() => pick(value === k ? null : k)}>{l}</button>)}
          {value && <button type="button" role="menuitemradio" aria-checked={false} className="any" onClick={() => pick(null)}>Any</button>}
        </div>
      )}
    </div>
  );
}

/** Ranking is the server's (code only: a work front that stops first, then held mail, then ₹, then days left); here, signed or sent cases sink and the
 * viewer's own moves come first. */
const finished = (i: ActionItem) => ["approved", "sent", "answered", "signed"].includes(i.stage?.key ?? "");

/** The home: what needs a decision, ranked for the viewer, with the verticals and projects each case touches. */
export function Today() {
  const { me } = useMe();
  const phone = useMedia("(max-width: 760px)");
  const [scope, setScope] = useState<"mine" | "all">(remember("lookout.scope") === "all" ? "all" : "mine");
  const everyone = useResource(() => api.actionItems());
  const yours = useResource(() => (me ? api.actionItems(me) : Promise.resolve(null)), [me]);
  const health = useResource(api.health);
  const projects = useResource(() => api.projects().catch(() => [] as ProjectRow[]));
  const asOf = health.data?.as_of ?? null;
  const [tab, setTab] = useState<Tab | "all">("all");
  const [q, setQ] = useState("");
  const [by, setBy] = useState<By | null>(null);
  const [lit, setLit] = useState<Set<string>>(new Set());
  const [project, setProject] = useState<string | null>(null);
  const [waiting, setWaiting] = useState<string | null>(null);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  useEffect(() => { if (listRef.current) listRef.current.scrollTop = 0; }, [scope, tab, q, by, lit, project, waiting]);

  const mineView = scope === "mine" && !!me;
  const all = (mineView ? yours.data : everyone.data) ?? [];
  const loading = mineView ? !yours.data && !yours.error : !everyone.data && !everyone.error;
  const aliases = useMemo(() => new Map((projects.data ?? []).map((p) => [p.ref.id, [p.name, ...p.aliases, ...p.plants].join(" ").toLowerCase()])), [projects.data]);
  const text = (i: ActionItem) => [i.title, i.summary ?? "", ...(i.refs ?? []).flatMap((r) => [r.id, r.label ?? ""]), ...(i.projects ?? []).map((p) => aliases.get(p.id) ?? "")].join(" ").toLowerCase();
  const inTab = all.filter((i) => tab === "all" || i.tab === tab);
  const shown = inTab.filter((i) => {
    if (q.trim() && !text(i).includes(q.trim().toLowerCase())) return false;
    if (lit.size && !(i.verticals ?? []).some((v) => lit.has(v))) return false;
    if (project && !(i.projects ?? []).some((p) => p.id === project)) return false;
    if (waiting && i.waiting_on !== waiting) return false;
    if (by) {
      const d = i.act_by;
      if (by === "none") return !d;
      if (!d || !asOf) return false;
      const n = daysFrom(d, asOf);
      return by === "overdue" ? n < 0 : n >= 0 && n <= (by === "week" ? 7 : by === "two" ? 14 : 31);
    }
    return true;
  });
  const band1 = shown.filter((i) => yourMove(i, me));
  const others = shown.filter((i) => !yourMove(i, me));
  const band2 = mineView ? [...others.filter((i) => !finished(i)), ...others.filter(finished)] : [];
  const rows = mineView ? band1 : [...shown.filter((i) => !finished(i)), ...shown.filter(finished)];
  const filtered = !!(q.trim() || by || lit.size || project || waiting);
  const clear = () => { setQ(""); setBy(null); setLit(new Set()); setProject(null); setWaiting(null); };
  const count = (k: Tab | "all") => all.filter((i) => k === "all" || i.tab === k).length;
  const yourCount = me && yours.data ? yours.data.filter((i) => yourMove(i, me)).length : "";

  // The count line: every figure computed from the rows on screen.
  const monthEnd = asOf ? `${asOf.slice(0, 7)}-31` : "";
  const line = useMemo(() => {
    const base = mineView ? yours.data ?? [] : everyone.data ?? [];
    const sign = base.filter((i) => ["Approve", "Countersign"].includes(statusOf(i, me).word) && (!mineView || yourMove(i, me))).length;
    const held = base.filter((i) => i.tab === "trust").length;
    const month = base.filter((i) => i.tab !== "trust" && i.act_by && i.act_by <= monthEnd && !["covers", "if those sites paid the median", "where a rate exists", "open, outside the library"].includes(i.at_stake_label ?? ""))
      .reduce((a, i) => a + (baseOf(i.at_stake) ?? 0), 0);
    const proj = base.filter((i) => i.waiting_on === "Projects").length;
    return [sign ? `${sign} to sign` : "", held ? `${held} held` : "", month ? `${inr(month)} at stake this month` : "", proj ? `${proj} waiting on Projects` : ""].filter(Boolean).join(" · ");
  }, [mineView, yours.data, everyone.data, me, monthEnd]);

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA" || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key !== "j" && e.key !== "k") return;
      const links = [...(listRef.current?.querySelectorAll<HTMLAnchorElement>("a.td-row") ?? [])];
      if (!links.length) return;
      const at = links.indexOf(document.activeElement as HTMLAnchorElement);
      (links[e.key === "j" ? Math.min(at + 1, links.length - 1) : Math.max(at - 1, 0)] ?? links[0]).focus();
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  const row = (i: ActionItem) => {
    const st = statusOf(i, me), amt = stake(i), d = i.act_by;
    const folded = i.dated?.length ? ` · +${i.dated.length} folded under it` : "";
    const sub = [tab === "all" ? tabName(i.tab) : "", (i.summary ?? "").replace(/^[^·]+· /, "") + folded].filter(Boolean).join(" · ");
    const who = owners(i);
    const late = d && asOf && d < asOf;
    return (
      <Link key={i.key} to={`/items/${encodeURIComponent(i.key)}`} className="td-row" role="row" aria-label={`${i.title}. ${st.word}`}>
        <span className="td-it" role="cell"><b title={i.title}>{i.title}</b>{sub && <small title={sub}>{sub}</small>}</span>
        {!mineView && <span className="td-own" role="cell" title={who.join(" · ")}>{who.map(first).join(" · ")}</span>}
        <span role="cell" className="td-vtc"><Verticals i={i} /></span>
        <span role="cell" className={`td-n td-amt${amt.text && amt.text !== "unknown" ? "" : " none"}`} title={amt.tip}>{amt.text ?? "—"}{amt.text && i.at_stake_label === "claimed" && <small> claimed</small>}{amt.text && i.team_total && <small> yours</small>}</span>
        <span role="cell" className={`td-n td-by${d ? "" : " none"}${late ? " late" : ""}`} title={late ? "Past the act-by date" : undefined}>{d ? shortDate(d) : "—"}</span>
        <span role="cell" className="td-stc"><StatusCell st={st} /></span>
      </Link>
    );
  };

  const filters = (
    <>
      <input className="td-f td-q" type="search" placeholder="Search cases, projects, PR/PO numbers" aria-label="Search cases" value={q} onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Escape") setQ(""); }} />
      <Menu label="Act by" value={by} options={Object.entries(BY) as [By, string][]} onChange={setBy} />
      <span className="td-rf" role="group" aria-label="Verticals">
        {VERTICALS.map((v) => (
          <button key={v.id} type="button" aria-pressed={lit.has(v.id)} title={`Only cases that touch ${v.name}`} className={lit.has(v.id) ? `on v-${v.id}` : undefined}
            onClick={() => { const n = new Set(lit); if (n.has(v.id)) n.delete(v.id); else n.add(v.id); setLit(n); }}>{v.short}</button>
        ))}
      </span>
      <Menu label="Project" value={project} options={(projects.data ?? []).map((p) => [p.ref.id, p.name] as [string, string])} onChange={setProject} />
      <Menu label="Waiting on" value={waiting} options={WAITING.map((w) => [w, w] as [string, string])} onChange={setWaiting} />
    </>
  );

  return (
    <div className={`td${mineView ? "" : " td-ev"}${phone ? " phone" : ""}`}>
      <div className="td-head">
        <div className="td-title">
          <h1>Today</h1>
          <div className="td-seg" role="group" aria-label="Whose cases">
            {(["mine", "all"] as const).map((s) => (
              <button key={s} type="button" aria-pressed={scope === s} className={scope === s ? "on" : undefined} disabled={s === "mine" && !me}
                onClick={() => { setScope(s); remember("lookout.scope", s); }}>
                {s === "mine" ? "Yours" : "Everyone"} <em>{s === "mine" ? yourCount : (everyone.data?.length ?? "")}</em>
              </button>
            ))}
          </div>
        </div>
        {line && <p className="td-line" role="status">{line}</p>}
        <div className="td-tabs" role="group" aria-label="Kinds">
          {([["all", "All"], ...TABS] as [Tab | "all", string][]).map(([k, l]) => (
            <button key={k} type="button" aria-pressed={tab === k} className={tab === k ? "on" : undefined} onClick={() => setTab(k)}>
              {l} {!loading && !everyone.error && !yours.error && <em>{count(k)}</em>}
            </button>
          ))}
        </div>
        <div className="td-filters">
          {phone ? (
            <>
              <button type="button" className={`td-f td-dd${filtered ? " on" : ""}`} aria-expanded={filtersOpen} onClick={() => setFiltersOpen(!filtersOpen)}>
                <SlidersHorizontal size={14} strokeWidth={1.75} aria-hidden /> Filters{filtered ? " · on" : ""}
              </button>
              {filtersOpen && <div className="td-fold">{filters}</div>}
            </>
          ) : filters}
          {filtered && !loading && <span className="td-showing" role="status">{shown.length} of {inTab.length} · <button type="button" onClick={clear}>clear</button></span>}
        </div>
        {!phone && (
          <div className="td-hdr" role="row">
            <span role="columnheader">Case</span>
            {!mineView && <span role="columnheader">Owner</span>}
            <span role="columnheader" className="td-vl" aria-label="Verticals">{VERTICALS.map((v) => <span key={v.id} title={v.name}><VerticalIcon id={v.id} size={13} title={v.name} /></span>)}</span>
            <span role="columnheader" className="td-n">₹ at stake</span>
            <span role="columnheader" className="td-n">Act by</span>
            <span role="columnheader">Status</span>
          </div>
        )}
      </div>
      <div className="td-rows" role="table" aria-label="Today" ref={listRef}>
        {loading ? [0, 1, 2, 3, 4].map((n) => <div key={n} className="td-sk" aria-hidden><i className="w" /><i /><i /><i /><i /></div>)
          : (everyone.error || yours.error) ? <LoadError what="Today" retry={invalidate} />
          : all.length === 0 ? <p className="td-empty">Nothing needs you today.</p>
          : rows.length + band2.length === 0 ? <p className="td-empty">Nothing here today.</p>
          : [...rows.map(row), mineView && band2.length > 0 && <div key="td-band" className="td-band" role="row"><span role="cell">Waiting on others · {band2.length}</span></div>, ...band2.map(row)]}
      </div>
    </div>
  );
}

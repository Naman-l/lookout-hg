import { useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ChevronDown } from "lucide-react";
import { api } from "../api/client";
import { useResource } from "../api/useResource";
import { isMoney, type Action, type ActionItem } from "../api/types";
import { shortDate } from "../ui/format";
import { useMe } from "../api/useMe";
import { useMedia } from "../ui/useMedia";
import { RobotIcon, useRobots, type Robot } from "../components/domain";
import { actBy, first, myChosenCases, myDraftCases, owners, statusOf, yourMove, type Status } from "../components/domain/caseStatus";
export { first, owners, statusOf, type Status } from "../components/domain/caseStatus";      // the robot page reads them from here too
import "./today.css";
import { LoadError } from "../ds/LoadError";
import { invalidate } from "../api/useResource";

/** The kinds a buyer reads Today by (F3, F35): one tab each, in this order. */
const KINDS = ["Disruption", "Supplier risk", "Trust", "Deadlines", "Import duty", "Unknowns"] as const;
type Kind = (typeof KINDS)[number];
const kindOf = (i: ActionItem): Kind =>
  i.key.startsWith("risk:") ? "Supplier risk" : i.group === "trust" ? "Trust" : i.group === "deadline" ? "Deadlines" : i.group === "tariff" ? "Import duty" : i.group === "unknown" ? "Unknowns" : "Disruption";

const BY = { week: "Within 7 days", month: "Within 30 days", none: "No date" } as const;
type By = keyof typeof BY;

/** Yours / Everyone lasts for this browser tab only: a new visit always opens on Yours. */
const remember = (k: string, v?: string): string | null => {
  try { if (v !== undefined) sessionStorage.setItem(k, v); return sessionStorage.getItem(k); } catch { return null; }
};

/** Dollars only, the way the column reads them: $1.43M, $396K, $7.5K, $950. Anything that is not money is "—". */
function dollars(i: ActionItem, usd?: number | null): string | null {
  const v = i.at_stake;
  if (usd == null && (!v || !isMoney(v) || v.usd == null)) return null;
  const x = usd ?? Number((v as { usd: string }).usd);
  return x >= 1e6 ? `$${(x / 1e6).toFixed(2)}M` : x >= 1e4 ? `$${Math.round(x / 1e3)}K` : x >= 1e3 ? `$${(x / 1e3).toFixed(1)}K` : `$${Math.round(x)}`;
}
const usdOf = (i: ActionItem) => (i.at_stake && isMoney(i.at_stake) && i.at_stake.usd != null ? Number(i.at_stake.usd) : 0);

const daysFrom = (d: string, asOf: string) => Math.round((Date.parse(d) - Date.parse(asOf)) / 864e5);


/** Within each part of the list (the viewer's moves first, then the rest, one continuous list): held, then the act-by date (past due first), a build short before cost only, more money first; no date last. */
function order(rows: ActionItem[], asOf: string | null) {
  const at = new Map(rows.map((r, n) => [r.key + r.title, n]));
  return [...rows].sort((a, b) => {
    const ta = a.group === "trust" ? 0 : 1, tb = b.group === "trust" ? 0 : 1;
    if (ta !== tb) return ta - tb;
    const da = actBy(a, asOf), db = actBy(b, asOf);
    if (!da !== !db) return da ? -1 : 1;
    if (da && db && da !== db) return da < db ? -1 : 1;
    const oa = a.key === "deadline:chase" ? 0 : 1, ob = b.key === "deadline:chase" ? 0 : 1;      // past due before merely due that day
    if (oa !== ob) return oa - ob;
    const sa = a.robots_short?.length ? 0 : 1, sb = b.robots_short?.length ? 0 : 1;
    if (sa !== sb) return sa - sb;
    if (usdOf(a) !== usdOf(b)) return usdOf(b) - usdOf(a);
    return (at.get(a.key + a.title) ?? 0) - (at.get(b.key + b.title) ?? 0);
  });
}

/** The three robots, always in the same slots: lit in the robot's colour when the item touches it, else faint. */
function Robots({ i, robots }: { i: ActionItem; robots: Robot[] }) {
  const short = i.robots_short ?? [];
  const lit = new Set([...(i.robots ?? []).map((r) => r.id), ...short.map((r) => r.product.id)]);
  const notes = (i.robot_notes ?? {}) as Record<string, string>;
  return (
    <span className="td-rb">
      {robots.map((r) => {
        const s = short.filter((x) => x.product.id === r.id).sort((a, b) => a.month.localeCompare(b.month))[0];
        const tip = s ? `${r.name} · Shortfall ${shortDate(`${s.month}-01`).split(" ")[0]} · ${s.robots}` : notes[r.id] ? `${r.name} · ${notes[r.id]}` : lit.has(r.id) ? `${r.name} · uses parts in this case` : `${r.name} · not affected`;
        return <i key={r.id} className={lit.has(r.id) ? `on r-${(r.slot % 3) + 1}` : undefined} title={tip} aria-label={tip}><RobotIcon slot={r.slot} /></i>;
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

/** The Act by menu: a button that opens a short list; Escape, a click outside or a choice closes it; arrow keys move. */
function ActByMenu({ value, onChange }: { value: By | null; onChange: (v: By | null) => void }) {
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
  const pick = (v: By | null) => { onChange(v); setOpen(false); button()?.focus(); };
  return (
    <div className="td-ddw" ref={root} onKeyDown={keys}>
      <button type="button" className={`td-f td-dd${value ? " on" : ""}`} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>
        {value ? BY[value] : "Act by"}<ChevronDown size={14} strokeWidth={1.75} aria-hidden />
      </button>
      {open && (
        <div className="td-menu" role="menu" aria-label="Act by">
          {(Object.keys(BY) as By[]).map((k) => <button key={k} type="button" role="menuitemradio" aria-checked={value === k} className={value === k ? "on" : undefined} onClick={() => pick(value === k ? null : k)}>{BY[k]}</button>)}
          {value && <button type="button" role="menuitemradio" aria-checked={false} className="any" onClick={() => pick(null)}>Any date</button>}
        </div>
      )}
    </div>
  );
}

/** The home: what needs a decision, ranked for the viewer, with the robots each item touches (FINAL 02). */
export function Today() {
  const { me } = useMe();
  const phone = useMedia("(max-width: 760px)");
  const [scope, setScope] = useState<"mine" | "all">(remember("lookout.scope") === "all" ? "all" : "mine");
  const everyone = useResource(() => api.actionItems());
  const yours = useResource(() => (me ? api.actionItems(me) : Promise.resolve(null)), [me]);
  const acts = useResource(() => api.actions().catch(() => [] as Action[]));
  const health = useResource(api.health);
  // In Yours, the duty row shows the viewer's share of the duty owed (the case's duty_share:<first name> figure), not the team total.
  const dutyKey = yours.data?.find((i) => i.group === "tariff")?.key;
  const duty = useResource(() => (me && dutyKey ? api.item(dutyKey, me) : Promise.resolve(null)), [me, dutyKey]);
  const myDuty = useMemo(() => {
    const n = (duty.data?.numbers ?? []).find((x) => x.id === `duty_share:${first(me ?? "")}`);
    return n?.value && isMoney(n.value) && n.value.usd != null ? Number(n.value.usd) : null;
  }, [duty.data, me]);
  const asOf = health.data?.as_of ?? null;
  const [tab, setTab] = useState<Kind | "All">("All");
  const [q, setQ] = useState("");
  const [by, setBy] = useState<By | null>(null);
  const robots = useRobots();
  const [lit, setLit] = useState<Set<string>>(new Set());
  // A robot page's "+ N more on Today" opens Everyone with that robot lit (?r=T2): read once, when the robots are known.
  const [params] = useSearchParams();
  const fromRobot = params.get("r");
  useEffect(() => {
    if (!fromRobot || !robots.length) return;
    const ids = robots.filter((r) => fromRobot.split(",").includes(r.key)).map((r) => r.id);
    if (ids.length) { setLit(new Set(ids)); setScope("all"); }
  }, [fromRobot, robots.length]);      // eslint-disable-line react-hooks/exhaustive-deps
  const listRef = useRef<HTMLDivElement>(null);
  // A new scope, kind or filter starts the rows at the top (the rows scroll on their own, under a fixed header).
  useEffect(() => { if (listRef.current) listRef.current.scrollTop = 0; }, [scope, tab, q, by, lit]);

  const mineView = scope === "mine" && !!me;
  const all = (mineView ? yours.data : everyone.data) ?? [];
  const loading = mineView ? !yours.data && !yours.error : !everyone.data && !everyone.error;
  const draftOwner = useMemo(() => new Map((acts.data ?? []).map((a) => [a.action_id, (a as Action & { owner?: string | null }).owner ?? ""])), [acts.data]);
  const inTab = all.filter((i) => tab === "All" || kindOf(i) === tab);
  const robotIds = new Set(robots.filter((r) => lit.has(r.id)).map((r) => r.id));
  const text = (i: ActionItem) => [i.title, i.summary ?? "", ...(i.refs ?? []).filter((r) => r.type === "supplier" || r.type === "part").flatMap((r) => [r.id, r.label ?? ""])].join(" ").toLowerCase();
  const shown = inTab.filter((i) => {
    if (q.trim() && !text(i).includes(q.trim().toLowerCase())) return false;
    if (robotIds.size && ![...(i.robots ?? []).map((r) => r.id), ...(i.robots_short ?? []).map((r) => r.product.id)].some((id) => robotIds.has(id))) return false;
    if (by) {
      const d = actBy(i, asOf);
      if (by === "none") return !d;
      if (!d || !asOf) return false;
      return daysFrom(d, asOf) <= (by === "week" ? 7 : 30);
    }
    return true;
  });
  const myDrafts = useMemo(() => myDraftCases(acts.data, me), [acts.data, me]);
  const myChosen = useMemo(() => myChosenCases(acts.data, me), [acts.data, me]);
  const status = (i: ActionItem) => statusOf(i, me, draftOwner, health.data?.boot ?? "", myDrafts, myChosen);
  const band1 = order(shown.filter((i) => yourMove(i, status(i), me)), asOf);
  const finished = (i: ActionItem) => (["approved", "sent", "answered"] as (string | undefined)[]).includes(i.stage?.key);      // signed or out: it moves to the bottom
  const others = shown.filter((i) => !yourMove(i, status(i), me));
  const band2 = [...order(others.filter((i) => !finished(i)), asOf), ...order(others.filter(finished), asOf)];
  const filtered = !!(q.trim() || by || lit.size);
  const clear = () => { setQ(""); setBy(null); setLit(new Set()); };
  const count = (k: Kind | "All") => all.filter((i) => k === "All" || kindOf(i) === k).length;
  // Yours counts what needs you (your move), as the sidebar does; what waits on others sits below a divider.
  const yourCount = me && yours.data ? yours.data.filter((i) => yourMove(i, status(i), me)).length : "";

  // j / k move between rows (Enter opens the focused one, as any link): the list is usable without a mouse.
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
    const mine = mineView && i.group === "tariff" && myDuty != null;
    const st = status(i), amt = dollars(i, mine ? myDuty : null), d = actBy(i, asOf);
    const sub = [tab === "All" ? kindOf(i) : "", i.summary ?? ""].filter(Boolean).join(" · ");
    const who = owners(i);
    return (
      <Link key={i.key + i.title} to={`/items/${encodeURIComponent(i.key)}`} className="td-row" role="row" aria-label={`${i.title}. ${st.word}`}>
        <span className="td-it" role="cell"><b title={i.title}>{i.title}</b>{sub && <small title={sub}>{sub}</small>}</span>
        {!mineView && <span className="td-own" role="cell" title={who.join(" · ")}>{who.map(first).join(" · ")}</span>}
        <span role="cell" className="td-rbc"><Robots i={i} robots={robots} /></span>
        <span role="cell" className={`td-n td-amt${amt ? "" : " none"}`} title={amt && i.group === "trust" ? `Amount claimed: ${amt}` : mine ? `${first(me ?? "")}'s share of the duty owed; the team owes ${dollars(i)}` : undefined}>{amt ?? "—"}{amt && i.group === "trust" && <small> claimed</small>}</span>
        <span role="cell" className={`td-n td-by${d ? "" : " none"}`}>{d ? shortDate(d) : "—"}</span>
        <span role="cell" className="td-stc"><StatusCell st={st} /></span>
      </Link>
    );
  };

  return (
    <div className={`td${mineView ? "" : " td-ev"}${phone ? " phone" : ""}`}>
      <div className="td-head">
        <div className="td-title">
          <h1>Today</h1>
          <div className="td-seg" role="group" aria-label="Whose items">
            {(["mine", "all"] as const).map((s) => (
              <button key={s} type="button" aria-pressed={scope === s} className={scope === s ? "on" : undefined} disabled={s === "mine" && !me}
                onClick={() => { setScope(s); remember("lookout.scope", s); }}>
                {s === "mine" ? "Yours" : "Everyone"} <em>{s === "mine" ? yourCount : (everyone.data?.length ?? "")}</em>
              </button>
            ))}
          </div>
        </div>
        <div className="td-tabs" role="group" aria-label="Kinds">
          {(["All", ...KINDS] as const).map((k) => (
            <button key={k} type="button" aria-pressed={tab === k} className={tab === k ? "on" : undefined} onClick={() => setTab(k)}>
              {k} {!loading && !everyone.error && !yours.error && <em>{count(k)}</em>}
            </button>
          ))}
        </div>
        <div className="td-filters">
          <input className="td-f td-q" type="search" placeholder="Search items" aria-label="Search items" value={q} onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Escape") setQ(""); }} />
          <ActByMenu value={by} onChange={setBy} />
          <span className="td-rf" role="group" aria-label="Robots">
            {robots.map((r) => (
              <button key={r.id} type="button" aria-pressed={lit.has(r.id)} title={`Only items that affect ${r.name}`} className={lit.has(r.id) ? `on r-${(r.slot % 3) + 1}` : undefined}
                onClick={() => { const n = new Set(lit); if (n.has(r.id)) n.delete(r.id); else n.add(r.id); setLit(n); }}>{r.key}</button>
            ))}
          </span>
          {filtered && !loading && <span className="td-showing" role="status">{shown.length} of {inTab.length} · <button type="button" onClick={clear}>clear</button></span>}
        </div>
        {!phone && (
          <div className="td-hdr" role="row">
            <span role="columnheader">Item</span>
            {!mineView && <span role="columnheader">Owner</span>}
            <span role="columnheader" className="td-rl">{robots.map((r) => <span key={r.id}>{r.key}</span>)}</span>
            <span role="columnheader" className="td-n">Exposure</span>
            <span role="columnheader" className="td-n">Act by</span>
            <span role="columnheader">Status</span>
          </div>
        )}
      </div>
      <div className="td-rows" role="table" aria-label="Today" ref={listRef}>
        {loading ? [0, 1, 2, 3, 4].map((n) => <div key={n} className="td-sk" aria-hidden><i className="w" /><i /><i /><i /><i /></div>)
          : (everyone.error || yours.error) ? <LoadError what="Today" retry={invalidate} />
          : all.length === 0 ? <p className="td-empty">Nothing needs you today.</p>
          : band1.length + band2.length === 0 ? <p className="td-empty">Nothing here today.</p>
          : [...band1.map(row), mineView && band2.length > 0 && <div key="td-band" className="td-band" role="row"><span role="cell">Waiting on others · {band2.length}</span></div>, ...band2.map(row)]}
      </div>
    </div>
  );
}

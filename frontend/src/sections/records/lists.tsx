import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../../api/client";
import { useResource } from "../../api/useResource";
import { LoadError } from "../../ds/LoadError";
import { invalidate } from "../../api/useResource";
import { shortDate } from "../../ui/format";
import { useMedia } from "../../ui/useMedia";
import type { ActionItem, Part, PoLine, Supplier } from "../../api/types";
import { RobotIcon } from "../../components/domain";
import { rowTotal, totals } from "../forecast/model";
import { caseShort, htsText, isRollup, openByPart, partName, supplierRobots, usd, whenMatches, type When } from "./model";
import { PoLineTable } from "./PoLineTable";
import { CaseCell, PickMenu, RobotHead, RobotSlots, SearchBox, Showing, SkeletonRows, TextTabs, Title, setParam, useRecords, useRobotFilter, type Records } from "./ui";

const CAP = 100;

/** The part of a list page that scrolls (Today's pattern, a1807c5): from 761 px the title, tabs and filters hold still and only this body scrolls,
 * ending at the Ask bar; a new filter or search starts it at the top (unfolding an order row does not). */
export function ListBody({ children, reset = "" }: { children: ReactNode; reset?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [params] = useSearchParams();
  const filters = [...params.entries()].filter(([k]) => k !== "open").map(([k, v]) => `${k}=${v}`).join("&");
  useEffect(() => { if (ref.current) ref.current.scrollTop = 0; }, [filters, reset]);
  return <div ref={ref} className="rc-scroll">{children}</div>;
}

type Column<T> = { id: string; head: ReactNode; w: string; cell: (x: T) => ReactNode; end?: boolean; mid?: boolean; phone?: boolean };

/** A record list (Suppliers, Parts): the rows in a case first, a hairline, then the rest; a row opens its record, a case link opens the case. */
function RecordTable<T>({ label, first, cols, inCase, rest, to, name, full, sub, rowKey }: {
  label: string; first: string; cols: Column<T>[]; inCase: T[]; rest: T[]; to: (x: T) => string; name: (x: T) => string; full?: (x: T) => string; sub: (x: T) => ReactNode; rowKey: (x: T) => string;
}) {
  const mid = useMedia("(max-width: 1100px)"), phone = useMedia("(max-width: 760px)");
  const [all, setAll] = useState(false);
  const shown = cols.filter((c) => !(mid && c.mid) && !(phone && c.phone));
  const template = ["minmax(0,1fr)", ...shown.map((c) => c.w)].join(" ");
  const restShown = all ? rest : rest.slice(0, CAP);
  const row = (x: T) => (
    <div key={rowKey(x)} className="rc-r rc-hit" role="row" style={{ gridTemplateColumns: template }}>
      <span role="cell" className="rc-two"><Link className="rc-stretch" to={to(x)}><b title={full?.(x)}>{name(x)}</b></Link><small>{sub(x)}</small></span>
      {shown.map((c) => <span key={c.id} role="cell" className={c.end ? "n" : undefined} style={{ minWidth: 0 }}>{c.cell(x)}</span>)}
    </div>
  );
  return (
    <div className="rc-list" role="table" aria-label={label}>
      <div className="rc-hd" role="row" style={{ gridTemplateColumns: template }}>
        <span role="columnheader">{first}</span>
        {shown.map((c) => <span key={c.id} role="columnheader" className={c.end ? "n" : undefined}>{c.head}</span>)}
      </div>
      {inCase.map(row)}
      {inCase.length > 0 && rest.length > 0 && <div className="rc-gap" aria-hidden />}
      {restShown.map(row)}
      {rest.length > restShown.length && <button type="button" className="dm-more" onClick={() => setAll(true)}>Show all {rest.length + inCase.length}</button>}
    </div>
  );
}

const robotsCol = <T,>(r: Records, lit: (x: T) => Iterable<string>, on: string, off: string): Column<T> =>
  ({ id: "robots", head: <RobotHead robots={r.robots} cell={false} />, w: "80px", mid: true, phone: true, cell: (x) => <RobotSlots robots={r.robots} lit={lit(x)} on={on} off={off} /> });

const actOrLast = (r: Records, i?: ActionItem) => (i ? r.actBy(i) ?? "9999" : "9999");

/** Suppliers (FINAL 06 §1): the supplier record line, the ones in a case first. */
export function Suppliers() {
  const r = useRecords();
  const sup = useResource(api.suppliers);
  const [params, setParams] = useSearchParams();
  const q = (params.get("q") ?? "").toLowerCase();
  const rf = useRobotFilter(r.robots);
  const lit = useMemo(() => supplierRobots(r.lines.data ?? [], r.robotsOf), [r.lines.data, r.robotsOf]);
  const all = sup.data ?? [];
  const shown = all.filter((s) => (!q || `${s.ref.id} ${s.ref.label ?? ""} ${s.country}`.toLowerCase().includes(q)) && rf.matches(lit.get(s.ref.id ?? "") ?? []));
  const cases = (s: Supplier) => r.rank(r.idx.supplier.get(s.ref.id ?? ""));
  const open = (s: Supplier) => Number(s.open_value?.usd ?? s.open_value?.amount ?? 0);
  const inCase = shown.filter((s) => cases(s).length).sort((a, b) => {
    const ca = cases(a)[0], cb = cases(b)[0];
    return (isRollup(ca.key) ? 1 : 0) - (isRollup(cb.key) ? 1 : 0) || actOrLast(r, ca).localeCompare(actOrLast(r, cb)) || open(b) - open(a);
  });
  const rest = shown.filter((s) => !cases(s).length).sort((a, b) => open(b) - open(a));
  const cols: Column<Supplier>[] = [
    robotsCol(r, (s) => lit.get(s.ref.id ?? "") ?? [], "its open lines go into it", "none of its open lines"),
    { id: "open", head: "Open $", w: "96px", end: true, cell: (s) => <span className="fig">{usd(open(s))}</span> },
    { id: "late", head: "Past due", w: "76px", end: true, mid: true, phone: true, cell: (s) => (s.past_due_lines ? s.past_due_lines : <span className="none">—</span>) },
    // one measure per column (h5d): the all-time on-time share, and the current late streak beside it
    { id: "ontime", head: "On time", w: "72px", end: true, phone: true, cell: (s) => (s.delivery && s.delivery.n > 0 ? <span title={`${s.delivery.on_time} of ${s.delivery.n} closed lines`}>{Math.round(s.delivery.on_time_pct * 100)}%</span> : <span className="none">—</span>) },
    { id: "streak", head: "Late in a row", w: "92px", end: true, mid: true, phone: true, cell: (s) => (s.delivery?.streak ? <span title={s.delivery.streak.line}>{s.delivery.streak.late_in_row}</span> : <span className="none">—</span>) },
    { id: "case", head: "Case", w: "230px", phone: true, cell: (s) => <CaseCell cases={cases(s)} r={r} more={`/suppliers/${encodeURIComponent(s.ref.id ?? "")}#cases`} /> },
  ];
  const filtered = !!q || rf.active;
  return (
    <div className="rc rc-fixed">
      <RecordsHead on="suppliers" />
      <div className="td-filters">
        <SearchBox label="Search suppliers" />
        {rf.node}
        {filtered && sup.data && <Showing n={shown.length} of={all.length} clear={() => setParams({}, { replace: true })} />}
      </div>
      <ListBody>{sup.loading && !sup.data ? <SkeletonRows /> : sup.error ? <LoadError what="suppliers" retry={invalidate} /> : shown.length === 0 ? <p className="rc-empty">No suppliers match.</p> : (
        <RecordTable label="Suppliers" first="Supplier" cols={cols} inCase={inCase} rest={rest} rowKey={(s) => s.ref.id ?? ""} to={(s) => `/suppliers/${encodeURIComponent(s.ref.id ?? "")}`} name={(s) => r.supName(s.ref.id, s.ref.label)} full={(s) => s.ref.label ?? ""}
          sub={(s) => [s.status === "hold" ? "On hold" : s.status === "inactive" ? "Inactive" : "", s.country, s.terms, s.incoterms].filter(Boolean).join(" · ")} />
      )}</ListBody>
    </div>
  );
}

/** Parts (FINAL 06 §4): All parts, and the Bill of materials as a second tab. */
export function Parts() {
  const r = useRecords();
  const [params, setParams] = useSearchParams();
  const q = (params.get("q") ?? "").toLowerCase();
  const rf = useRobotFilter(r.robots);
  const openOf = useMemo(() => openByPart(r.lines.data ?? []), [r.lines.data]);
  const all = r.parts.data ?? [];
  const shown = all.filter((p) => (!q || `${p.ref.id} ${p.description} ${p.preferred_supplier?.label ?? ""}`.toLowerCase().includes(q)) && rf.matches(p.robots ?? []));
  const cases = (p: Part) => r.rank(r.idx.part.get(p.ref.id ?? ""));
  const open = (p: Part) => openOf.get(p.ref.id ?? "") ?? 0;
  const inCase = shown.filter((p) => cases(p).length).sort((a, b) => open(b) - open(a));
  const rest = shown.filter((p) => !cases(p).length).sort((a, b) => open(b) - open(a) || (a.ref.id ?? "").localeCompare(b.ref.id ?? ""));
  const cols: Column<Part>[] = [
    robotsCol(r, (p) => p.robots ?? [], "goes into it", "not in it"),
    { id: "sup", head: "Supplier", w: "260px", mid: true, phone: true, cell: (p) => <span className="rc-sup" title={p.preferred_supplier?.label ?? ""}>{p.preferred_supplier?.label ? r.supName(p.preferred_supplier.id, p.preferred_supplier.label) : <span className="none">—</span>}</span> },
    { id: "open", head: "Open $", w: "96px", end: true, cell: (p) => (open(p) ? <span className="fig">{usd(open(p))}</span> : <span className="none">—</span>) },
    { id: "case", head: "Case", w: "210px", phone: true, cell: (p) => <CaseCell cases={cases(p)} r={r} more={`/parts/${encodeURIComponent(p.ref.id ?? "")}#cases`} /> },
  ];
  const filtered = !!q || rf.active;
  return (
    <div className="rc rc-fixed">
      <RecordsHead on="parts" />
      <PartsTabs on="all" count={r.parts.data?.length} />
      <div className="td-filters">
        <SearchBox label="Search part, id or supplier" />
        {rf.node}
        {filtered && r.parts.data && <Showing n={shown.length} of={all.length} clear={() => setParams({}, { replace: true })} />}
      </div>
      <ListBody>{r.parts.loading && !r.parts.data ? <SkeletonRows /> : r.parts.error ? <LoadError what="parts" retry={invalidate} /> : shown.length === 0 ? <p className="rc-empty">No parts match.</p> : (
        <RecordTable label="Parts" first="Part" cols={cols} inCase={inCase} rest={rest} rowKey={(p) => p.ref.id ?? ""} to={(p) => `/parts/${encodeURIComponent(p.ref.id ?? "")}`} name={(p) => partName(p.description)}
          sub={(p) => [p.ref.id, typeof p.coo === "string" ? `Made in ${p.coo}` : "Origin not on file", typeof p.hts === "string" ? `HTS ${htsText(p.hts)}` : "HTS not on file"].join(" · ")} />
      )}</ListBody>
    </div>
  );
}

type RecordTab = "suppliers" | "parts" | "orders" | "forecast";
/** Records as one page (Khalid 11:49, "compact the records thing"): the same title and tab row on all four lists, so moving between them never moves the header. */
export function RecordsHead({ on, right }: { on: RecordTab; right?: ReactNode }) {
  return (
    <>
      <Title right={right}>Records</Title>
      <RecordsTabs on={on} />
    </>
  );
}
/** The Records tab row alone: on a supplier or a part it sits above the record's own header and is the way back to the list. */
export const RecordsTabs = ({ on }: { on: RecordTab }) => (
  <TextTabs<RecordTab> label="Records" value={on} tabs={[{ id: "suppliers", label: "Suppliers", to: "/suppliers" }, { id: "parts", label: "Parts", to: "/parts" }, { id: "orders", label: "Orders", to: "/orders" }, { id: "forecast", label: "Forecast", to: "/forecast" }]} />
);

/** All parts · Bill of materials: the two views of Parts. */
export function PartsTabs({ on, count }: { on: "all" | "bom"; count?: number }) {
  return <TextTabs label="Parts" value={on} tabs={[{ id: "all", label: "All parts", count, to: "/parts" }, { id: "bom", label: "Bill of materials", to: "/parts/bom" }]} />;
}

const WHEN: Record<When, string> = { late: "Past due", month: "This month", none: "No date" };

/** Orders (FINAL 06 §3): the viewer's open PO lines (or everyone's), past due first, each row unfolding its promise history. */
export function Orders() {
  const r = useRecords();
  const [params, setParams] = useSearchParams();
  const yours = useResource(() => (r.me ? api.actionItems(r.me) : Promise.resolve([] as ActionItem[])), [r.me]);
  const everyone = params.get("who") === "everyone" || !r.me;
  const late = params.get("late") === "1";
  const when = (params.get("when") as When | null) ?? null;
  const q = (params.get("q") ?? "").toLowerCase();
  const rf = useRobotFilter(r.robots);
  const lines = r.lines.data ?? [];
  const isOpen = (l: PoLine) => !l.stale;
  const scoped = lines.filter((l) => everyone || l.buyer === r.me);
  const lateLines = scoped.filter((l) => isOpen(l) && (l.days_past_due ?? 0) > 0);
  const pastDue = lateLines.length;
  // Why the count differs from Today's chase row: some past-due lines are already inside a case of their own (the fire).
  const mine = new Map((yours.data ?? []).map((i) => [i.key, i.title]));
  const inCases = new Map<string, number>(), inTeam = new Map<string, number>();
  // A case named as briefly as a buyer would: the fire by its short title, a supplier-risk case by the supplier, the team chase as "chase".
  const hoverName = (i: ActionItem) => (i.key === "deadline:chase" ? "chase" : i.key.startsWith("risk:") ? r.supName((i.refs ?? []).find((x) => x.type === "supplier")?.id, null) || caseShort(i.title) : caseShort(i.title));
  for (const l of lateLines) {
    const ranked = r.rank(r.idx.line.get(l.ref.id ?? ""));
    const own = ranked.find((i) => !isRollup(i.key)), team = ranked[0];
    // the hover names the case the row's own Case cell shows (a team list in the viewer's own words), so the two never disagree
    const add = (m: Map<string, number>, k: string) => m.set(k, (m.get(k) ?? 0) + 1);
    if (own) add(inCases, hoverName(own)); else if (team) add(inTeam, hoverName(team));
  }
  const owned = [...inCases.values()].reduce((a, b) => a + b, 0);
  const lateTip = pastDue ? [`${pastDue} past due`, ...[...inCases, ...inTeam].map(([k, n]) => `${n} ${k}`)].join(" · ") : undefined;
  const name = (l: PoLine) => r.partById.get(l.part.id ?? "")?.description ?? "";
  const shown = scoped.filter((l) => (!q || `${l.ref.id} ${l.part.id} ${name(l)} ${l.supplier.label ?? ""} ${l.buyer}`.toLowerCase().includes(q))
    && (!late || (isOpen(l) && (l.days_past_due ?? 0) > 0)) && (!when || whenMatches(l, when, r.asOf)) && rf.matches(r.robotsOf.get(l.part.id ?? "") ?? []));
  const filtered = !!q || late || !!when || rf.active;
  const loading = r.lines.loading && !r.lines.data;
  return (
    <div className="rc rc-fixed">
      <RecordsHead on="orders" right={
        <div className="td-seg" role="group" aria-label="Whose lines">
          {(["mine", "everyone"] as const).map((s) => (
            <button key={s} type="button" aria-pressed={(s === "everyone") === everyone} className={(s === "everyone") === everyone ? "on" : undefined} disabled={s === "mine" && !r.me}
              onClick={() => setParam(setParams, "who", s === "everyone" ? "everyone" : null)}>
              {s === "mine" ? "Yours" : "Everyone"} <em>{r.lines.data ? lines.filter((l) => isOpen(l) && (s === "everyone" || l.buyer === r.me)).length : ""}</em>
            </button>
          ))}
        </div>
      } />
      <div className="td-filters">
        <SearchBox label="Search line, part or supplier" />
        <button type="button" className={`td-f rc-tg${late ? " on" : ""}`} aria-pressed={late} title={lateTip} onClick={() => setParam(setParams, "late", late ? null : "1")}>Past due <em>{r.lines.data ? pastDue : ""}</em>{r.lines.data && owned > 0 && <small className="rc-tg-x"> · {owned} in {inCases.size === 1 ? [...inCases.keys()][0] : "cases"}</small>}</button>
        <PickMenu label="Promised" options={WHEN} value={when} onChange={(v) => setParam(setParams, "when", v)} />
        {rf.node}
        {filtered && r.lines.data && <Showing n={shown.filter(isOpen).length} of={scoped.filter(isOpen).length} clear={() => setParams(everyone && r.me ? { who: "everyone" } : {}, { replace: true })} />}
      </div>
      <ListBody>{loading ? <SkeletonRows /> : r.lines.error ? <LoadError what="orders" retry={invalidate} /> : shown.length === 0 ? <p className="rc-empty">No open PO lines match.</p> : (
        <PoLineTable label="Open PO lines" lines={shown} r={r} everyone={everyone} open={params.get("open")} onOpen={(id) => setParam(setParams, "open", id)}
          caseTitle={everyone ? undefined : (i) => mine.get(i.key) ?? i.title} />
      )}</ListBody>
    </div>
  );
}

const MONTH = (m: string, first: boolean) => { const [y, n] = m.split("-"); const name = shortDate(`${m}-01`).split(" ")[0]; return first || n === "01" ? `${name} ’${y.slice(2)}` : name; };

/** Forecast (FINAL 06 §6): robots planned per month; this month's build is a link to its page. */
export function Forecast() {
  const r = useRecords({ orders: false, parts: false });
  const fc = useResource(api.forecast);
  const rows = fc.data ?? [];
  const t = totals(rows);
  const robot = (name: string) => r.robots.find((x) => x.name === name);
  return (
    <div className="rc rc-fixed">
      <RecordsHead on="forecast" />
      <ListBody>{fc.loading && !fc.data ? <SkeletonRows n={3} /> : fc.error ? <LoadError what="the forecast" retry={invalidate} /> : rows.length === 0 ? <p className="rc-empty">No forecast is loaded.</p> : (
        <div className="rc-fc" role="table" aria-label="Robots planned per month">
          <span className="h l" role="columnheader">Robot</span>
          {t.months.map((m, n) => <span key={m} className={`h${n > 2 ? " late" : ""}`} role="columnheader">{MONTH(m, n === 0)}</span>)}
          <span className="h" role="columnheader">12 months</span>
          {rows.map((row) => {
            const rb = robot(row.product);
            return [
              <span key={`${row.product}-n`} className="l row" role="rowheader">{rb && <RobotIcon slot={rb.slot} />}{row.product}</span>,
              ...row.months.map((m, n) => <span key={`${row.product}-${m.month}`} className={`row${n > 2 ? " late" : ""}`} role="cell">{m.units}</span>),
              <span key={`${row.product}-t`} className="row t" role="cell">{rowTotal(row).toLocaleString("en-US")}</span>,
            ];
          })}
          <span className="f l" role="rowheader">All robots</span>
          {t.byMonth.map((u, n) => <span key={n} className={`f${n > 2 ? " late" : ""}`} role="cell">{u}</span>)}
          <span className="f" role="cell">{t.all.toLocaleString("en-US")}</span>
        </div>
      )}</ListBody>
    </div>
  );
}

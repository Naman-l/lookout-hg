// Requirements (MAPPING 8.7) and Work fronts (8.9): the 3-month sheets per project and material with the fund sheet's figure beside each head,
// and how each work front's requirement is covered month by month, worst first ("up to": site stock is not in the data).
import { Fragment, useMemo, useState, type CSSProperties } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { invalidate, useResource } from "../../api/useResource";
import type { FrontStatus, ProjectRow, RequirementRow } from "../../api/types";
import { EmptyState, Notice } from "../../ds";
import { DataTable, TitleCell, type Col } from "../../ds/DataTable";
import { FilterBar, type FilterDef } from "../../ds/FilterBar";
import { LoadError } from "../../ds/LoadError";
import { VERTICALS } from "../../components/domain/Vertical";
import { enIn, monthYear, qty } from "../../ui/format";
import { ListTitle, LoadingRows, ProjectPicker, RecordsTabs, Vertical, day, plural, rate, rs, useAsOf, useProjects, useUrl, type Projects } from "./shared";

type Cell = RequirementRow;
type MatRow = { key: string; row: string; unit: string | null; materials: string[]; srcFile: string; srcRow: string; months: Map<string, Cell> };
type Head = { name: string; rows: MatRow[]; amount: Map<string, number>; fund: Map<string, number> };
type ProjectSheet = { id: string; name: string; sheet: string; file: string; heads: Head[]; total: Map<string, number> };

const NO_HEAD = "No fund head";
/** "sheets/Railway … (15.10.26).csv r6 c10" -> its file, row and column. */
const src = (s: string) => { const m = s.match(/^(.*?)\s+r(\d+)\s+c(\d+)$/); return m ? { file: m[1].replace(/^sheets\//, "").replace(/\.csv$/, ""), row: m[2], col: m[3] } : { file: s, row: "", col: "" }; };

/** The long-form rows folded back into the sheet's shape: project, then fund head, then each material row with its months. */
function fold(rows: RequirementRow[], projects: Projects): ProjectSheet[] {
  const out = new Map<string, ProjectSheet>();
  for (const r of rows) {
    const pid = r.project ?? r.project_name;
    let p = out.get(pid);
    if (!p) { p = { id: pid, name: r.project_name, sheet: r.sheet, file: src(r.src).file, heads: [], total: new Map() }; out.set(pid, p); }
    const hn = r.fund_head ?? NO_HEAD;
    let h = p.heads.find((x) => x.name === hn);
    if (!h) { h = { name: hn, rows: [], amount: new Map(), fund: new Map() }; p.heads.push(h); }
    const s = src(r.src);
    const key = `${r.sheet}|${s.row}|${r.row}`;
    let m = h.rows.find((x) => x.key === key);
    if (!m) { m = { key, row: r.row, unit: r.unit, materials: r.materials, srcFile: s.file, srcRow: s.row, months: new Map() }; h.rows.push(m); }
    m.months.set(r.month, r);
    if (r.amount != null) { h.amount.set(r.month, (h.amount.get(r.month) ?? 0) + r.amount); p.total.set(r.month, (p.total.get(r.month) ?? 0) + r.amount); }
    if (r.fund != null) h.fund.set(r.month, (h.fund.get(r.month) ?? 0) + r.fund);
  }
  const order = new Map(projects.list.map((p, i) => [p.ref.id, i]));
  return [...out.values()].map((p) => ({ ...p, heads: p.heads.sort((a, b) => (a.name === NO_HEAD ? 1 : b.name === NO_HEAD ? -1 : 0)) }))
    .sort((a, b) => (order.get(a.id) ?? 99) - (order.get(b.id) ?? 99) || a.name.localeCompare(b.name));
}

/** Requirements: each project's 3-month material requirement as the sheet has it, the fund sheet's figure for the same head and month beside it. */
export function Requirements() {
  useAsOf();
  const r = useResource(() => api.requirements());
  const pj = useProjects();
  const mats = useResource(api.materials);
  const u = useUrl();
  const project = u.get("project");
  const q = (u.get("q") ?? "").trim().toLowerCase();
  const f = { vertical: u.get("vertical"), sheet: u.get("sheet") };
  const all = r.data ?? [];
  const has = new Set(all.map((x) => x.project));
  const vert = (x: RequirementRow) => pj.byId.get(x.project ?? "")?.vertical;
  const filters: FilterDef[] = [
    { id: "vertical", label: "Vertical", options: VERTICALS.map((v) => ({ value: v.id, label: v.name, count: all.filter((x) => vert(x) === v.id).length })).filter((o) => o.count) },
    { id: "sheet", label: "Sheet", options: [...new Set(all.map((x) => x.sheet))].map((s) => ({ value: s, label: s === "roads" ? "Roads major materials" : s === "railway" ? "Railway quantity summary" : s, count: all.filter((x) => x.sheet === s).length })) },
  ];
  const names = useMemo(() => new Map((mats.data ?? []).map((m) => [m.code, m.description])), [mats.data]);
  const rows = all.filter((x) => (!project || x.project === project) && (!f.vertical || vert(x) === f.vertical) && (!f.sheet || x.sheet === f.sheet)
    && (!q || `${x.row} ${x.materials.join(" ")} ${x.materials.map((c) => names.get(c) ?? "").join(" ")} ${x.fund_head ?? ""} ${x.project_name}`.toLowerCase().includes(q)));
  const sheets = fold(rows, pj);
  const months = [...new Set(all.map((x) => x.month))].sort();
  return (
    <div className="rc pg-fix">
      <RecordsTabs />
      <ListTitle title="Requirements" sub="The 3-month material requirement sheets, as each project wrote them (quantity, rate, amount per month), with the fund requirement sheet's figure for the same head and month." />
      <div className="rc-bar">
        <FilterBar label="requirements" search={u.get("q") ?? ""} onSearch={(s) => u.set({ q: s })} placeholder="Material, code or fund head" filters={filters}
          value={f} onChange={(v) => u.set({ vertical: v.vertical, sheet: v.sheet })} />
        <ProjectPicker projects={pj.list} value={project} onChange={(id) => u.set({ project: id })} only={(p) => has.has(p.ref.id)} />
      </div>
      {r.data && <p className="rc-count" role="status">{plural(sheets.length, "project")} · {plural(sheets.reduce((s, p) => s + p.heads.reduce((t, h) => t + h.rows.length, 0), 0), "material row")} · {months.map(monthYear).join(", ")}</p>}
      <div className="pg-body">
        {r.loading && !r.data ? <LoadingRows /> : r.error ? <LoadError what="the requirement sheets" retry={invalidate} />
          : project && !has.has(project) ? <EmptyState>{pj.byId.get(project)?.name ?? "This project"} has no rows in the requirement sheets.</EmptyState>
          : sheets.length === 0 ? <EmptyState>No requirement row matches.</EmptyState>
          : sheets.map((p) => <Sheet key={p.id} p={p} months={months} project={pj.byId.get(p.id)} names={names} />)}
      </div>
    </div>
  );
}

function Sheet({ p, months, project, names }: { p: ProjectSheet; months: string[]; project?: ProjectRow; names: Map<string, string> }) {
  const style = { "--rq-months": months.length } as CSSProperties;
  return (
    <section className="rq" aria-label={p.name} style={style}>
      <header className="rq-h">
        <h2>{project && <Vertical id={project.vertical} name={false} />}{p.name}</h2>
        <span className="rq-file" title={p.file}>{p.file}</span>
        <Link className="rq-wf" to={`/workfronts?project=${encodeURIComponent(p.id)}`}>Work fronts</Link>
      </header>
      <div className="rq-t" role="table" aria-label={`${p.name} requirement`}>
        <div className="rq-r rq-hd" role="row">
          <span role="columnheader">Material</span>
          {months.map((m) => <span key={m} role="columnheader" className="end">{monthYear(m)}</span>)}
        </div>
        {p.heads.map((h) => (
          <Fragment key={h.name}>
            <div className="rq-r rq-head" role="row">
              <span role="rowheader"><b>{h.name}</b></span>
              {months.map((m) => (
                <span key={m} role="cell" className="end" data-label={monthYear(m)}>
                  <b title="The sheet's amounts for this head, added">{h.amount.has(m) ? rs(h.amount.get(m)) : "—"}</b>
                  {h.name !== NO_HEAD && <small title="The fund requirement sheet's figure for this project, head and month">{h.fund.has(m) ? `fund ${rs(h.fund.get(m))}` : "no fund line"}</small>}
                </span>
              ))}
            </div>
            {h.rows.map((x) => (
              <div key={x.key} className="rq-r" role="row">
                <span role="rowheader" className="rq-m">
                  <b>{x.row}{x.unit && <span className="rc-id"> · {x.unit}</span>}</b>
                  <small>
                    {x.materials.length ? x.materials.map((c, k) => <Fragment key={c}>{k > 0 && ", "}<Link to={`/materials/${encodeURIComponent(c)}`} title={c}>{names.get(c) ?? c}</Link></Fragment>) : "no material code"}
                    {x.srcRow && <> · row {x.srcRow}</>}
                  </small>
                </span>
                {months.map((m) => {
                  const c = x.months.get(m);
                  return (
                    <span key={m} role="cell" className="end" data-label={monthYear(m)} title={c ? c.src : "No cell for this month"}>
                      {c ? <>{qty(c.qty, x.unit)}<small>{c.rate != null ? rate(c.rate) : "no rate"} · {c.amount != null ? rs(c.amount) : "no amount"}</small></> : <span className="none">—</span>}
                    </span>
                  );
                })}
              </div>
            ))}
          </Fragment>
        ))}
        <div className="rq-r rq-tot" role="row">
          <span role="rowheader"><b>All heads</b></span>
          {months.map((m) => <span key={m} role="cell" className="end" data-label={monthYear(m)}><b>{p.total.has(m) ? rs(p.total.get(m)) : "—"}</b></span>)}
        </div>
      </div>
    </section>
  );
}

type FrontRow = FrontStatus & { project: string; name: string; vertical: string };

/** Work fronts: per project, front and month, how its requirement lines are covered; the fronts with the most lines not covered in time first. */
export function WorkFronts() {
  const asOf = useAsOf();
  const pj = useProjects();
  const mats = useResource(api.materials);
  const u = useUrl();
  const project = u.get("project");
  const withFronts = pj.list.filter((p) => p.work_fronts.length);
  const ids = (project ? withFronts.filter((p) => p.ref.id === project) : withFronts).map((p) => p.ref.id);
  const r = useResource(() => (pj.list.length ? Promise.all(ids.map((id) => api.workfronts(id).then((fs) => fs.map((x) => ({ ...x, project: id, name: pj.byId.get(id)?.name ?? id, vertical: pj.byId.get(id)?.vertical ?? "" }))))).then((a) => a.flat()) : Promise.resolve(null)),
    [ids.join(",")]);
  const [open, setOpen] = useState<string | null>(null);
  const names = useMemo(() => new Map((mats.data ?? []).map((m) => [m.code, m.description])), [mats.data]);
  const all: FrontRow[] = r.data ?? [];
  const months = [...new Set(all.map((x) => x.month))].sort();
  const f = { month: u.get("month"), vertical: u.get("vertical"), show: u.get("show") };
  const bad = (x: FrontStatus) => x.late + x.disrupted + x.no_po;
  const filters: FilterDef[] = [
    { id: "month", label: "Month", options: months.map((m) => ({ value: m, label: monthYear(m), count: all.filter((x) => x.month === m).length })) },
    { id: "vertical", label: "Vertical", options: VERTICALS.map((v) => ({ value: v.id, label: v.name, count: all.filter((x) => x.vertical === v.id).length })).filter((o) => o.count) },
    { id: "show", label: "Show", options: [{ value: "risk", label: "Not all covered in time", count: all.filter((x) => bad(x) > 0).length }, { value: "disrupted", label: "Under a disruption", count: all.filter((x) => x.disrupted > 0).length }, { value: "nopo", label: "With lines on no PO", count: all.filter((x) => x.no_po > 0).length }] },
  ];
  const q = (u.get("q") ?? "").trim().toLowerCase();
  const rows = all.filter((x) => (!f.month || x.month === f.month) && (!f.vertical || x.vertical === f.vertical)
    && (!f.show || (f.show === "risk" ? bad(x) > 0 : f.show === "disrupted" ? x.disrupted > 0 : x.no_po > 0))
    && (!q || `${x.name} ${x.front} ${x.materials.map((c) => names.get(c) ?? c).join(" ")}`.toLowerCase().includes(q)))
    .sort((a, b) => bad(b) - bad(a) || a.month.localeCompare(b.month) || a.name.localeCompare(b.name) || a.front.localeCompare(b.front));
  const key = (x: FrontRow) => `${x.project}|${x.front}|${x.month}`;
  const cols: Col<FrontRow>[] = [
    { id: "f", head: "Work front", width: "minmax(0,1fr)", cell: (x) => <TitleCell title={x.front} sub={<>{x.name} · {monthYear(x.month)}</>} /> },
    { id: "c", head: "Cover", width: "140px", label: "", phone: "hide", cell: (x) => <CoverBar x={x} /> },
    { id: "l", head: "Lines", width: "60px", end: true, label: "Lines", cell: (x) => enIn(x.lines) },
    { id: "i", head: "In time", width: "70px", end: true, label: "In time", cell: (x) => enIn(x.in_time) },
    { id: "la", head: "Late", width: "60px", end: true, label: "Late", cell: (x) => (x.late ? <b className="rc-warn">{x.late}</b> : <span className="none">0</span>) },
    { id: "d", head: "Disrupted", width: "84px", end: true, label: "Disrupted", cell: (x) => (x.disrupted ? <b className="rc-bad">{x.disrupted}</b> : <span className="none">0</span>) },
    { id: "n", head: "No PO", width: "64px", end: true, label: "No PO", cell: (x) => (x.no_po ? <b>{x.no_po}</b> : <span className="none">0</span>) },
    { id: "s", head: "May stop from", width: "120px", label: "May stop from", cell: (x) => (x.stops_on ? <span>{day(x.stops_on)}<small>{asOf && x.stops_on <= asOf ? "date passed" : "at the earliest"}</small></span> : <span className="none">covered</span>) },
  ];
  return (
    <div className="rc pg-fix">
      <RecordsTabs />
      <ListTitle title="Work fronts" sub="Each work front's requirement lines for the month: covered by a PO due in time, by one due late, by one under a closure or strike, or by no PO at all." />
      <div className="rc-bar">
        <FilterBar label="work fronts" search={u.get("q") ?? ""} onSearch={(s) => u.set({ q: s })} placeholder="Front, project or material" filters={filters}
          value={f} onChange={(v) => u.set({ month: v.month, vertical: v.vertical, show: v.show })} />
        <ProjectPicker projects={pj.list} value={project} onChange={(id) => u.set({ project: id })} only={(p) => p.work_fronts.length > 0} />
      </div>
      <Notice>Up to: site stock is not in the data, so a line with no PO may be covered by stock nobody has counted, and a stop date is the earliest it could stop.</Notice>
      {r.data && <p className="rc-count" role="status">{plural(rows.length, "front-month")}{rows.length ? `, the most lines not covered in time first` : ""} · <span className="rc-legend"><i className="k-in" />in time <i className="k-late" />late <i className="k-dis" />disrupted <i className="k-no" />no PO</span></p>}
      <div className="pg-body">
        {(r.loading && !r.data) || pj.loading ? <LoadingRows /> : r.error || pj.error ? <LoadError what="work-front readiness" retry={invalidate} />
          : !all.length ? <EmptyState>{project ? `${pj.byId.get(project)?.name ?? "This project"} has no requirement lines for its work fronts.` : "No work front has requirement lines."}</EmptyState>
          : rows.length === 0 ? <EmptyState>No work front matches.</EmptyState>
          : <DataTable label="Work-front readiness" rows={rows} rowKey={key} cols={cols} two onClick={(x) => setOpen(open === key(x) ? null : key(x))} active={(x) => open === key(x)}
              expand={(x) => (open === key(x) ? (
                <div className="rc-x">
                  <p><b>Materials the front consumes in {monthYear(x.month)}</b></p>
                  <p>{x.materials.map((c, k) => <Fragment key={c}>{k > 0 && " · "}<Link to={`/materials/${encodeURIComponent(c)}`}>{names.get(c) ?? c}</Link></Fragment>)}</p>
                  <p><Link to={`/requirements?project=${encodeURIComponent(x.project)}`}>{x.name}'s requirement sheet</Link> · <Link to={`/pos?project=${encodeURIComponent(x.project)}`}>its open PO lines</Link></p>
                </div>
              ) : null)} />}
      </div>
    </div>
  );
}

/** The month's lines as one bar: in time, late, disrupted, no PO, in that order; the counts beside it carry the numbers. */
function CoverBar({ x }: { x: FrontStatus }) {
  const parts: [string, number][] = [["k-in", x.in_time], ["k-late", x.late], ["k-dis", x.disrupted], ["k-no", x.no_po]];
  return (
    <span className="rc-cover" aria-hidden title={`${x.in_time} in time · ${x.late} late · ${x.disrupted} disrupted · ${x.no_po} no PO`}>
      {parts.filter(([, n]) => n > 0).map(([k, n]) => <i key={k} className={k} style={{ flexGrow: n }} />)}
    </span>
  );
}

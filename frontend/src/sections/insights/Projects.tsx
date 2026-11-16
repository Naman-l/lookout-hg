// Projects (MAPPING 10.2): every project by vertical, and one project's page: where its lines stand on the ladder and whose move it is, work-front
// readiness, top materials, its Today cases, and requirement against fund and received by month.
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { SectionTitle, StateChip, Tile, Tiles } from "../../ds";
import { DataTable, TitleCell, type Col } from "../../ds/DataTable";
import { FilterBar, type FilterValue } from "../../ds/FilterBar";
import { useAskContext } from "../../shell/AskContext";
import { monthShort, monthYear, shortDate } from "../../ui/format";
import { insights, type EstimateMonth, type ProjectFigures, type ProjectPage as Page } from "./api";
import { Frame } from "./Frame";
import { Bar, Empty, Facts, Fig, FUNCTIONS, ReadFailed, Sources, useReadError, Vert, WhoDot } from "./ui";

const VERTS = ["roads", "railway", "bess", "solar", "td"];
const STAGE: Record<string, string> = { new: "New", running: "Running", nearing_completion: "Nearing completion" };

function projectCols(): Col<ProjectFigures>[] {
  return [
    { id: "p", head: "Project", width: "minmax(170px,1fr)", cell: (p) => <TitleCell title={<Link to={`/insights/projects/${encodeURIComponent(p.id)}`}>{p.name}</Link>} sub={[STAGE[p.stage] ?? p.stage, p.plants.join(", ") || "no SAP plant"].join(" · ")} /> },
    { id: "open", head: "Open PRs", width: "88px", end: true, label: "Open PRs", cell: (p) => <Fig f={p.open_prs} title={`${p.name}: open PR lines`} sub={<><Fig f={p.cancelled} title={`${p.name}: cancelled PR lines`} quiet /> cancelled</>} /> },
    { id: "tat", head: "PR → PO", width: "100px", end: true, label: "PR → PO", cell: (p) => <Fig f={p.turnaround} title={`${p.name}: median PR → PO`} sub={p.target_days != null ? `target ${p.target_days} days` : undefined} /> },
    { id: "bud", head: "Bought vs budget", width: "130px", end: true, label: "Bought vs budget", hide: "narrow", cell: (p) => <Fig f={p.actual} title={`${p.name}: PO value on lines with a budget rate`} sub={p.budget.value != null ? <>budget <Fig f={p.budget} title={`${p.name}: budget value`} quiet /></> : "no budget rate"} /> },
    { id: "req", head: "Required · fund · received", width: "190px", end: true, label: "Required · fund · received", cell: (p) => <RFR p={p} /> },
    { id: "ll", head: "Long-lead", width: "110px", end: true, label: "Long-lead", hide: "mid", cell: (p) => <Fig f={p.longlead} title={`${p.name}: look-ahead items ordered`} sub={p.longlead_open.value ? <><Fig f={p.longlead_open} title="Not yet ordered" quiet /> open</> : undefined} /> },
    { id: "risk", head: "₹ at risk", width: "110px", end: true, label: "₹ at risk", cell: (p) => <Fig f={p.at_risk} title={`${p.name}: Today's cases on it alone`} sub={p.at_risk_shared.value ? <>+<Fig f={p.at_risk_shared} title="Cases shared with other projects" quiet /> shared</> : undefined} /> },
    { id: "proj", head: "Held by Projects", width: "120px", end: true, label: "Held by Projects", cell: (p) => <Fig f={p.held_by_projects} title={`${p.name}: days held by Projects`} sub={p.waiting_on_projects.value ? <><Fig f={p.waiting_on_projects} title="Waiting on Projects now" quiet /> now</> : undefined} /> },
  ];
}

const RFR = ({ p }: { p: ProjectFigures }) => (
  <span className="ins-rfr">
    <Fig f={p.requirement} title={`${p.name}: requirement`} />
    <small>fund <Fig f={p.fund} title={`${p.name}: fund sheets`} quiet /> · got <Fig f={p.received} title={`${p.name}: received`} quiet /></small>
  </span>
);

/** /insights/projects */
export function Projects() {
  const r = useReadError(() => insights.projects(), []);
  const [q, setQ] = useState("");
  const [f, setF] = useState<FilterValue>({});
  const d = r.data;
  const rows = useMemo(() => (d?.rows ?? []).filter((p) => (!f.v || p.vertical === f.v) && (!f.s || p.stage === f.s)
    && (!f.w || (f.w === "risk" ? (p.at_risk.value ?? 0) + (p.at_risk_shared.value ?? 0) > 0 : f.w === "projects" ? (p.waiting_on_projects.value ?? 0) > 0 : (p.open_prs.value ?? 0) > 0))
    && (!q.trim() || `${p.name} ${p.plants.join(" ")} ${p.head ?? ""} ${p.planner ?? ""}`.toLowerCase().includes(q.trim().toLowerCase()))), [d, f, q]);
  const cols = projectCols();
  return (
    <Sources>
      <Frame title="Projects" meta={d ? <><span>{d.rows.length} projects</span><span className="sep">·</span><span>requirement and fund {monthYear(d.sheet_months[0])} – {monthYear(d.sheet_months[d.sheet_months.length - 1])}</span><span className="sep">·</span><span>received {monthYear(d.received_months[0])} – {monthYear(d.received_months[d.received_months.length - 1])}</span></> : undefined}>
        {r.loading ? <div className="ins-sk" aria-busy="true" aria-label="Loading projects"><i /><i /><i /><i /></div>
          : r.error || !d ? <ReadFailed e={r.error!} what="projects" notFound={{ title: "Projects", line: "No projects on file." }} />
          : (
            <>
              <FilterBar label="projects" search={q} onSearch={setQ} placeholder="Search projects, plants, people" value={f} onChange={setF} filters={[
                { id: "v", label: "Vertical", options: d.verticals.map((v) => ({ value: v.id, label: v.name, count: v.projects })) },
                { id: "s", label: "Stage", options: Object.entries(STAGE).map(([value, label]) => ({ value, label, count: d.rows.filter((p) => p.stage === value).length })).filter((o) => o.count) },
                { id: "w", label: "Show", options: [{ value: "open", label: "With open PRs" }, { value: "risk", label: "With ₹ at risk" }, { value: "projects", label: "Waiting on Projects now" }] },
              ]} />
              <div className="ins-body">
                {rows.length === 0 ? <Empty>No project matches.</Empty> : VERTS.map((v) => ({ v, list: rows.filter((p) => p.vertical === v) })).filter((x) => x.list.length).map(({ v, list }, n) => (
                  <section key={v} className="ins-sec">
                    <div className="ins-group"><Vert id={v} /><small>{list.length} {list.length === 1 ? "project" : "projects"}</small></div>
                    <DataTable label={`Projects: ${v}`} cols={cols} rows={list} rowKey={(p) => p.id} header={n === 0} two />
                  </section>
                ))}
              </div>
              <ul className="ins-notes">{d.notes.map((x) => <li key={x}>{x}</li>)}</ul>
            </>
          )}
      </Frame>
    </Sources>
  );
}

/** Requirement, fund and received by month: the sheet's months beside what MB51 received. */
export function MonthTable({ months, label }: { months: EstimateMonth[]; label: string }) {
  const max = Math.max(1, ...months.flatMap((m) => [m.requirement?.value ?? 0, m.fund?.value ?? 0, m.received?.value ?? 0]));
  return (
    <div className="ins-months" role="table" aria-label={label}>
      <div className="ins-mr ins-mh" role="row"><span role="columnheader">Month</span><span role="columnheader" aria-hidden /><span role="columnheader" className="n">Required</span><span role="columnheader" className="n">Fund</span><span role="columnheader" className="n">Received</span></div>
      {months.map((m) => (
        <div key={m.month} className={`ins-mr${m.over ? " over" : ""}`} role="row">
          <span role="cell">{monthShort(m.month)} {m.month.slice(2, 4)}{m.partial ? <small> to date</small> : null}{m.over ? <small className="ins-over"> over-ask</small> : null}</span>
          <span role="cell" className="ins-mb" aria-hidden>
            {m.requirement && <Bar value={m.requirement.value ?? 0} max={max} tone="accent" />}
            {m.fund && <Bar value={m.fund.value ?? 0} max={max} />}
            {m.received && <Bar value={m.received.value ?? 0} max={max} tone="muted" />}
          </span>
          <span role="cell" className="n" data-label="required"><Fig f={m.requirement} title={`Requirement, ${monthYear(m.month)}`} /></span>
          <span role="cell" className="n" data-label="fund"><Fig f={m.fund} title={`Fund sheet, ${monthYear(m.month)}`} sub={m.fund_shared_with.length ? `with ${m.fund_shared_with.join(", ")}` : undefined} /></span>
          <span role="cell" className="n" data-label="received"><Fig f={m.received} title={`Received, ${monthYear(m.month)}`} /></span>
        </div>
      ))}
    </div>
  );
}

/** /insights/projects/:id */
export function ProjectPage() {
  const { id = "" } = useParams();
  const r = useReadError(() => insights.project(id), [id]);
  const d = r.data;
  useAskContext(d ? { type: "project", id: d.row.id, label: d.row.name } : null);
  return (
    <Sources>
      <Frame back={{ to: "/insights/projects", label: "Projects" }} title={d?.row.name ?? "Project"}
        meta={d ? <><Vert id={d.row.vertical} /><span className="sep">·</span><span>{STAGE[d.row.stage] ?? d.row.stage}</span>{d.state && <><span className="sep">·</span><span>{d.state}</span></>}<span className="sep">·</span><span>{d.row.plants.length ? `plant ${d.row.plants.join(", ")}` : "no SAP plant yet"}</span>{d.row.head && <><span className="sep">·</span><span>head {d.row.head}</span></>}{d.row.planner && <><span className="sep">·</span><span>planner {d.row.planner}</span></>}</> : undefined}>
        {r.loading ? <div className="ins-sk" aria-busy="true" aria-label="Loading the project"><i /><i /><i /><i /></div>
          : r.error || !d ? <ReadFailed e={r.error!} what="this project" notFound={{ title: "No such project", line: `No project “${id}” is on file.` }} />
          : <ProjectBody d={d} />}
      </Frame>
    </Sources>
  );
}

function ProjectBody({ d }: { d: Page }) {
  const p = d.row;
  const maxRung = Math.max(1, ...d.ladder.map((x) => (x.waiting?.value ?? 0) + (x.standing?.value ?? 0)));
  return (
    <div className="ins-body">
      <Tiles>
        <Tile figure={<Fig f={p.open_prs} title="Open PR lines" />} label={`open PR lines · ${p.cancelled.text} cancelled`} />
        <Tile figure={<Fig f={p.turnaround} title="Median PR → PO" />} label={p.target_days != null ? `PR → PO median · target ${p.target_days} days` : "PR → PO median"} />
        <Tile figure={<Fig f={p.at_risk} title="₹ at risk on its own cases" />} label={p.at_risk_shared.value ? `at risk · +${p.at_risk_shared.text} on shared cases` : "at risk on Today"} />
        <Tile figure={<Fig f={p.held_by_projects} title="Days held by Projects" />} label={`held by Projects${p.held_by_projects.note ? ` ${p.held_by_projects.note}` : ""} · ${p.waiting_on_projects.text} waiting now`} />
      </Tiles>

      <section className="ins-sec">
        <SectionTitle>Where its lines stand</SectionTitle>
        {d.ladder.length === 0 ? <Empty>No PR or PO lines on this project yet.</Empty> : (
          <div className="ins-ladder" role="table" aria-label="Lines by rung">
            {d.ladder.map((x) => (
              <div key={x.key} className="ins-lr" role="row">
                <span role="cell" className="ins-ll">{x.label}</span>
                <span role="cell" className="ins-lb" aria-hidden>
                  <span className="ins-stackbar">
                    {FUNCTIONS.filter((fn) => x.who[fn]).map((fn) => <i key={fn} className={`w-${fn.toLowerCase()}`} style={{ width: `${(100 * x.who[fn]) / maxRung}%` }} />)}
                    {x.standing && <i className="stand" style={{ width: `${(100 * (x.standing.value ?? 0)) / maxRung}%` }} />}
                  </span>
                </span>
                <span role="cell" className="ins-lf">
                  {x.waiting && <span><Fig f={x.waiting} title={`Waiting for ${x.label}`} /> waiting{Object.keys(x.who).length ? <> · {Object.entries(x.who).map(([w, n]) => <WhoDot key={w} who={w} n={n} />)}</> : null}</span>}
                  {x.standing && <span className="ins-quiet"><Fig f={x.standing} title={x.label} quiet /> {x.key === "closed" ? "closed" : x.key === "cancelled" ? "cancelled" : "stand here"}</span>}
                </span>
              </div>
            ))}
          </div>
        )}
        {d.whose_move.length > 0 && (
          <div className="ins-move">
            <h3>Whose move now</h3>
            <Facts items={d.whose_move.map((m) => [<WhoDot key={m.function} who={m.function} />, <Fig key="f" f={m.lines} title={`Waiting on ${m.function}`} sub={<><Fig f={m.days} title={`Days waited on ${m.function}`} quiet /> between them</>} />])} />
          </div>
        )}
        {d.oldest_waits.length > 0 && (
          <>
            <h3 className="ins-h3">Oldest waits</h3>
            <DataTable label="Oldest waits" rows={d.oldest_waits} rowKey={(w) => w.ref} cols={[
              { id: "l", head: "Line", width: "minmax(180px,1fr)", cell: (w) => { const [, id] = w.ref.split(":"); const no = id.split("/")[0]; const kind = w.ref.startsWith("po_line") ? "pos" : "prs"; return <TitleCell title={<Link to={`/${kind}/${no}`}>{w.text || id}</Link>} sub={`${kind === "pos" ? "PO" : "PR"} ${id}`} />; } },
              { id: "r", head: "Waiting for", width: "150px", label: "waiting for", cell: (w) => w.rung },
              { id: "w", head: "On", width: "120px", label: "on", cell: (w) => <WhoDot who={w.waiting_on} /> },
              { id: "s", head: "Since", width: "90px", label: "since", cell: (w) => shortDate(w.since) },
              { id: "d", head: "Days", width: "70px", end: true, label: "days", cell: (w) => w.days.toLocaleString("en-IN") },
            ]} />
          </>
        )}
      </section>

      <section className="ins-sec">
        <SectionTitle>Work-front readiness</SectionTitle>
        {d.fronts.length === 0 ? <Empty>No requirement sheet covers this project, so its work fronts cannot be read against supply.</Empty> : (
          <DataTable label="Work-front readiness" rows={d.fronts} rowKey={(x) => `${x.front}:${x.month}`} cols={[
            { id: "f", head: "Work front", width: "minmax(160px,1fr)", cell: (x) => <TitleCell title={x.front} sub={monthYear(x.month)} /> },
            { id: "l", head: "Lines", width: "70px", end: true, label: "lines", cell: (x) => x.lines },
            { id: "t", head: "In time", width: "80px", end: true, label: "in time", cell: (x) => x.in_time },
            { id: "late", head: "Late", width: "70px", end: true, label: "late", cell: (x) => (x.late ? <StateChip tone="caution">{x.late}</StateChip> : 0) },
            { id: "dis", head: "Disrupted", width: "90px", end: true, label: "disrupted", cell: (x) => (x.disrupted ? <StateChip tone="critical">{x.disrupted}</StateChip> : 0) },
            { id: "no", head: "No PO", width: "80px", end: true, label: "no PO", cell: (x) => (x.no_po ? <StateChip tone="unknown">{x.no_po}</StateChip> : 0) },
            { id: "s", head: "Stops up to", width: "100px", label: "stops up to", cell: (x) => (x.stops_on ? shortDate(x.stops_on) : "—") },
          ]} />
        )}
        <p className="ins-note">“Up to”: site stock is not in the data, so a late or missing supply stops the front no later than this.</p>
      </section>

      <section className="ins-sec">
        <SectionTitle>Requirement, fund and received by month</SectionTitle>
        <MonthTable months={d.months.filter((m) => m.requirement || m.fund || (m.received && (m.received.value ?? 0) > 0))} label="Requirement, fund and received" />
        <Facts items={[
          ["Bought against budget", <Fig f={p.actual} title="PO value on lines with a budget rate" sub={p.budget.value != null ? <>budget <Fig f={p.budget} title="Budget value" quiet /> · {p.budget_cover.text} of PO value has a rate</> : p.budget.note ?? undefined} />],
          ["Long-lead items", <Fig f={p.longlead} title="Look-ahead items ordered" sub={p.longlead_open.value ? <><Fig f={p.longlead_open} title="Not yet ordered" quiet /> not yet ordered</> : p.longlead.note ?? undefined} />],
        ]} />
      </section>

      <section className="ins-sec">
        <SectionTitle>Top materials by value</SectionTitle>
        {d.top_materials.length === 0 ? <Empty>No PO lines on this project.</Empty> : (
          <DataTable label="Top materials" rows={d.top_materials} rowKey={(x) => x.code} cols={[
            { id: "m", head: "Material", width: "minmax(180px,1fr)", cell: (x) => <TitleCell title={<Link to={`/insights/pricing/${encodeURIComponent(x.code)}`}>{x.description}</Link>} sub={<>{x.code} · <Link to={`/materials/${encodeURIComponent(x.code)}`}>record</Link></>} /> },
            { id: "q", head: "Quantity", width: "140px", end: true, label: "qty", cell: (x) => `${x.qty.toLocaleString("en-IN", { maximumFractionDigits: 2 })} ${x.uom}` },
            { id: "n", head: "PO lines", width: "80px", end: true, label: "lines", cell: (x) => x.lines },
            { id: "v", head: "Value", width: "110px", end: true, label: "value", cell: (x) => <Fig f={x.value} title={`${x.description}: PO value`} /> },
          ]} />
        )}
      </section>

      <section className="ins-sec">
        <SectionTitle>On Today</SectionTitle>
        {d.cases.length === 0 ? <Empty>No case on Today names this project.</Empty> : (
          <DataTable label="Today's cases" rows={d.cases} rowKey={(c) => c.key} cols={[
            { id: "t", head: "Case", width: "minmax(220px,1fr)", cell: (c) => <TitleCell title={<Link to={`/items/${encodeURIComponent(c.key)}`}>{c.title}</Link>} sub={`${c.owner}${c.shared ? " · shared with other projects" : ""}`} /> },
            { id: "w", head: "Waiting on", width: "120px", label: "waiting on", cell: (c) => <WhoDot who={c.waiting_on} /> },
            { id: "a", head: "Act by", width: "80px", label: "act by", cell: (c) => shortDate(c.act_by) },
            { id: "s", head: "Figure", width: "140px", end: true, label: "", cell: (c) => <Fig f={c.at_stake} title={c.title} sub={c.label} /> },
          ]} />
        )}
      </section>
    </div>
  );
}

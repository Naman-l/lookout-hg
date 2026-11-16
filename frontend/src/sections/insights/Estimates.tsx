// Estimates (MAPPING 10.4): per project and month, what the 3-month sheet asks against the fund sheet and against what MB51 received; bias against
// the project's own record, accuracy once a sheet month has passed, repeat over-askers, and sheet names no project resolves to.
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Disclose, SectionTitle, StateChip, Tile, Tiles } from "../../ds";
import { DataTable, TitleCell, type Col } from "../../ds/DataTable";
import { FilterBar, type FilterValue } from "../../ds/FilterBar";
import { monthShort, monthYear } from "../../ui/format";
import { insights, type EstimateRow, type EstimatesResponse } from "./api";
import { Frame } from "./Frame";
import { MonthTable } from "./Projects";
import { Empty, Fig, ReadFailed, Sources, useReadError, Vert } from "./ui";

const VERTS = ["roads", "railway", "bess", "solar", "td"];

function estimateCols(d: EstimatesResponse, open: string | null, toggle: (id: string) => void): Col<EstimateRow>[] {
  const months: Col<EstimateRow>[] = d.sheet_months.map((m) => ({
    id: m, head: monthYear(m), width: "170px", end: true, label: monthShort(m),
    cell: (r: EstimateRow) => {
      const x = r.months.find((y) => y.month === m);
      if (!x) return "—";
      return (
        <span className={`ins-rfr${x.over ? " over" : ""}`}>
          <Fig f={x.requirement} title={`${r.project_name}: requirement, ${monthYear(m)}`} sub={x.over ? "over its best month" : undefined} />
          <small>fund <Fig f={x.fund} title={`${r.project_name}: fund, ${monthYear(m)}`} quiet />{x.received ? <> · got <Fig f={x.received} title={`${r.project_name}: received, ${monthYear(m)}`} quiet /></> : null}</small>
        </span>
      );
    },
  }));
  return [
    { id: "p", head: "Project", width: "minmax(150px,1fr)", cell: (r) => (
      <span className="ins-proj">
        <TitleCell title={<Link to={`/insights/projects/${encodeURIComponent(r.project)}`}>{r.project_name}</Link>} sub={r.on_sheet ? `planner ${r.ask ?? "not on file"}` : "on no requirement sheet"} />
        <Disclose open={open === r.project} onClick={() => toggle(r.project)} className="ins-dis"><span className="ins-sr">{r.project_name}: </span>by month</Disclose>
      </span>) },
    ...months,
    { id: "u", head: "Usual · best month", width: "130px", end: true, label: "usual", hide: "narrow", cell: (r) => <Fig f={r.usual} title={`${r.project_name}: usual month received`} sub={r.peak ? <>best <Fig f={r.peak} title={`${r.project_name}: best month received`} quiet /></> : undefined} /> },
    { id: "b", head: "Bias", width: "110px", end: true, label: "bias", cell: (r) => <Fig f={r.bias} title={`${r.project_name}: requirement against the usual month`} sub={r.repeat ? "repeat over-ask" : r.over_months ? `${r.over_months} month over` : undefined} /> },
    { id: "a", head: "Accuracy", width: "100px", end: true, label: "accuracy", hide: "mid", cell: (r) => <Fig f={r.accuracy} title={`${r.project_name}: accuracy`} sub={r.accuracy?.note ? "no month closed" : undefined} /> },
  ];
}

/** /insights/estimates */
export function Estimates() {
  const r = useReadError(() => insights.estimates(), []);
  const [q, setQ] = useState("");
  const [f, setF] = useState<FilterValue>({ s: "sheet" });
  const [open, setOpen] = useState<string | null>(null);
  const d = r.data;
  const rows = useMemo(() => (d?.rows ?? []).filter((x) => (!f.v || x.vertical === f.v)
    && (!f.s || (f.s === "sheet" ? x.on_sheet : f.s === "over" ? x.repeat : f.s === "fund" ? x.fund_disagrees.length > 0 : !x.on_sheet))
    && (!q.trim() || x.project_name.toLowerCase().includes(q.trim().toLowerCase()))), [d, f, q]);
  return (
    <Sources>
      <Frame title="Estimates" meta={d ? <><span>sheets {monthYear(d.sheet_months[0])} – {monthYear(d.sheet_months[d.sheet_months.length - 1])}</span><span className="sep">·</span><span>against {monthYear(d.year_months[0])} – {monthYear(d.year_months[d.year_months.length - 1])} received</span></> : undefined}>
        {r.loading ? <div className="ins-sk" aria-busy="true" aria-label="Loading estimates"><i /><i /><i /><i /></div>
          : r.error || !d ? <ReadFailed e={r.error!} what="estimates" notFound={{ title: "Estimates", line: "No sheets on file." }} />
          : (
            <>
              <Tiles>
                <Tile figure={d.rows.filter((x) => x.on_sheet).length} label="projects on a requirement sheet" />
                <Tile figure={d.over_askers.length} label="repeat over-askers" tone={d.over_askers.length ? "caution" : undefined} />
                <Tile figure={d.rows.filter((x) => x.fund_disagrees.length).length} label="projects where fund and requirement disagree" />
                <Tile figure={d.unresolved.length} label="sheet names no project resolves to" tone={d.unresolved.length ? "unknown" : undefined} />
              </Tiles>
              <p className="ins-lead">Over-ask: {d.threshold}.</p>
              <FilterBar label="projects" search={q} onSearch={setQ} placeholder="Search projects" value={f} onChange={setF} filters={[
                { id: "v", label: "Vertical", options: VERTS.map((v) => ({ value: v, label: v === "td" ? "T&D" : v === "bess" ? "BESS" : v[0].toUpperCase() + v.slice(1), count: d.rows.filter((x) => x.vertical === v).length })) },
                { id: "s", label: "Show", options: [
                  { value: "sheet", label: "On a requirement sheet", count: d.rows.filter((x) => x.on_sheet).length },
                  { value: "over", label: "Repeat over-askers", count: d.over_askers.length },
                  { value: "fund", label: "Fund disagrees", count: d.rows.filter((x) => x.fund_disagrees.length).length },
                  { value: "off", label: "On no sheet", count: d.rows.filter((x) => !x.on_sheet).length },
                ] },
              ]} />
              <div className="ins-body">
                {rows.length === 0 ? <Empty>No project matches.</Empty> : (
                  <DataTable label="Requirement, fund and received" cols={estimateCols(d, open, (id) => setOpen(open === id ? null : id))} rows={rows} rowKey={(x) => x.project} two
                    active={(x) => open === x.project}
                    expand={(x) => (open === x.project ? (
                      <div className="ins-expand">
                        <div className="ins-expand-h"><Vert id={x.vertical} /><b>{x.project_name}</b>{x.fund_disagrees.length > 0 && <StateChip tone="caution">fund disagrees in {x.fund_disagrees.length} {x.fund_disagrees.length === 1 ? "head-month" : "head-months"}</StateChip>}</div>
                        <MonthTable months={x.months.filter((m) => m.requirement || m.fund || (m.received && (m.received.value ?? 0) > 0))} label={`${x.project_name} by month`} />
                      </div>
                    ) : null)} />
                )}
              </div>

              {d.over_askers.length > 0 && (
                <section className="ins-sec">
                  <SectionTitle>Repeat over-askers</SectionTitle>
                  <ul className="ins-unk">
                    {d.rows.filter((x) => x.repeat).map((x) => (
                      <li key={x.project}>
                        <p><Link to={`/insights/projects/${encodeURIComponent(x.project)}`}>{x.project_name}</Link> asks above its best month in {x.over_months} of {d.sheet_months.length} sheet months (best month <Fig f={x.peak} title={`${x.project_name}: best month`} quiet />; usual <Fig f={x.usual} title={`${x.project_name}: usual month`} quiet />; bias <Fig f={x.bias} title={`${x.project_name}: bias`} quiet />).</p>
                        <p className="ins-ask"><StateChip tone="unknown">unknown</StateChip> Site stock and the work planned are not in the data. Ask {x.ask ?? "the project's planner"}, who builds its requirement.</p>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              <section className="ins-sec">
                <SectionTitle>Names no project resolves to</SectionTitle>
                {d.unresolved.length === 0 ? <Empty>Every name on the sheets resolves to a project.</Empty> : (
                  <DataTable label="Unresolved names" rows={d.unresolved} rowKey={(u) => `${u.source}:${u.name}`} cols={[
                    { id: "n", head: "Name as printed", width: "minmax(160px,1fr)", cell: (u) => <TitleCell title={`“${u.name}”`} sub={u.source === "fund" ? "fund sheets" : u.source.replace(/_/g, " ")} /> },
                    { id: "a", head: "Carries", width: "120px", end: true, label: "carries", cell: (u) => <Fig f={u.amount} title={`Fund lines under “${u.name}”`} /> },
                    { id: "w", head: "Who can say", width: "160px", label: "ask", cell: (u) => (u.ask ? <Link to={`/insights/team/${encodeURIComponent(u.ask)}`}>{u.ask_name}</Link> : "the sheet's owner") },
                  ]} />
                )}
                <p className="ins-note">A name is linked to a project only by a person's answer, never by likeness. Until someone answers, its money sits outside every project above.</p>
              </section>
              <ul className="ins-notes">{d.notes.map((x) => <li key={x}>{x}</li>)}</ul>
            </>
          )}
      </Frame>
    </Sources>
  );
}

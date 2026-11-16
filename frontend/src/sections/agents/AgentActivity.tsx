import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { useResource } from "../../api/useResource";
import { DataTable, TitleCell, type Col } from "../../ds/DataTable";
import { LoadError } from "../../ds/LoadError";
import type { Run } from "../../api/types";
import { longDate } from "../../ui/format";
import "./agents.css";

const MODE = (r: Run) => (r.recorded ? "recording (mocked)" : "drafted by code");

/** Agent activity: every run, newest first: what it was on, how it was made, whether it passed its checks, its Reviewer grade, what it drafted. */
export function AgentActivity() {
  const r = useResource(api.runs, [], true);
  const cols: Col<Run>[] = [
    { id: "what", head: "Run", width: "minmax(0,1fr)", cell: (x) => <TitleCell title={x.title ?? x.item_key} sub={`${x.workflow} · ${MODE(x)}`} /> },
    { id: "when", head: "Started", width: "140px", cell: (x) => `${longDate(x.started_at)} ${x.started_at.slice(11, 16)}` },
    { id: "status", head: "Status", width: "110px", cell: (x) => (x.status === "ok" ? "passed" : x.status === "did_not_pass" ? "checks failed" : x.status) },
    { id: "checks", head: "Checks", width: "90px", end: true, cell: (x) => x.checks ?? "—" },
    { id: "grade", head: "Reviewer", width: "80px", end: true, cell: (x) => (x.grade != null ? String(x.grade) : "—") },
    { id: "drafts", head: "Drafts", width: "64px", end: true, cell: (x) => String(x.drafts ?? 0) },
    { id: "time", head: "Time", width: "64px", end: true, cell: (x) => (x.wall_ms != null ? `${(x.wall_ms / 1000).toFixed(1)} s` : "—") },
  ];
  return (
    <div className="uth">
      <h1>Agent activity</h1>
      <p className="uth-mode">Runs drafted by code (no model is connected here) and replays of the two mocked recordings. <Link to="/hood">Under the hood ›</Link></p>
      {r.error ? <LoadError what="the runs" /> : <DataTable label="Runs" cols={cols} rows={r.data ?? []} rowKey={(x) => x.run_id} to={(x) => `/activity/${x.run_id}`} />}
    </div>
  );
}

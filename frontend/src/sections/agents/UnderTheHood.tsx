import { Fragment, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { useResource } from "../../api/useResource";
import { LoadError } from "../../ds/LoadError";
import { invalidate } from "../../api/useResource";
import type { AgentRow, ActionItem, RunDetail, RunEvent } from "../../api/types";
import { StageStrip } from "../../components/domain/StageStrip";
import { caseShort, day } from "../records/model";
import "./agents.css";

/** The four steps of every case (F94), the words the case page uses, and what each step is for. */
const STEPS = [
  { key: "overview", name: "Overview", caption: "what happened, from which source" },
  { key: "analysis", name: "Analysis", caption: "the data, what matters, the links" },
  { key: "decision", name: "Decision", caption: "the options, one recommended" },
  { key: "approval", name: "Approval", caption: "the action, ready for the buyer to approve" },
] as const;
const CHECKS = [
  { key: "lookups", name: "Lookups", caption: "tools · code", text: "Every figure comes back from a lookup with an id. An agent can call only its own tools." },
  { key: "verifier", name: "Verifier", caption: "code", text: "Numbers, dates, counts, names, places and owners must match a lookup, or the run does not pass. A stray figure in the prose is marked unchecked." },
  { key: "reviewer", name: "Reviewer", caption: "model · grade sheet", text: "5 checks on every answer, plus 1 per kind. “Commits the company to nothing” sends it back once." },
  { key: "owner", name: "Owner signs", caption: <Link to="/approvals">Approvals</Link>, text: "Only the case owner approves, bound to the exact text. A run sends nothing." },
];

/** An agent's mark by shape: a filled square for Lookout (the orchestrator), an outline square for a specialist. */
export const Mark = ({ role }: { role: string }) => <i className={`ag-mark ${role === "orchestrator" ? "lead" : "spec"}`} aria-hidden />;

/** "claude-sonnet-5-5" -> "Sonnet 5.5". */
const modelName = (m?: string | null) => { const x = (m ?? "").match(/(opus|sonnet|haiku|fable)-(\d+)-(\d+)/i); return x ? `${x[1][0].toUpperCase()}${x[1].slice(1)} ${x[2]}.${x[3]}` : m ?? ""; };

type Row = { id: string; agent: AgentRow; stage: string; works: string; tools: string[]; recorded: boolean };

/** Under the hood (FINAL 08 A): how Lookout works a case and who does each step, how every figure is checked, the evals as measured, and the data. */
export function UnderTheHood() {
  const ag = useResource(api.agents);
  const ev = useResource(() => api.evalsSummary().catch(() => null));
  const counts = useResource(() => api.counts());
  const items = useResource(() => api.actionItems().catch(() => [] as ActionItem[]));
  const runs = useResource(() => api.runs().catch(() => []));
  const last7 = useResource(() => Promise.all((runs.data ?? []).slice(0, 7).map((r) => api.run(r.run_id ?? "").catch(() => null))), [runs.data]);
  const [open, setOpen] = useState<string | null>(null);
  const [lit, setLit] = useState<string | null>(null);
  const d = ag.data;
  const agents = d?.agents ?? [];
  const specialists = agents.filter((a) => a.role === "specialist").length;

  // One row per agent and stage it serves; Lookout's two stages carry their own words and tools.
  const rows: Row[] = useMemo(() => agents.flatMap((a) => a.stages.filter((s) => s !== "data").map((s, i) => {
    const own = a.by_stage?.[s];
    return { id: `${a.name}:${s}`, agent: a, stage: s, works: own?.works_on ?? a.works_on, tools: own?.tools ?? a.tools, recorded: i === 0 };
  })), [agents]);
  const steward = agents.find((a) => a.stages.includes("data"));

  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") { document.getElementById(`ag-${open}`)?.focus(); setOpen(null); } };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open]);

  const totals = useMemo(() => {
    const runs = (last7.data ?? []).filter(Boolean) as RunDetail[];
    let read = 0, checked = 0, drafts = 0, rewritten = 0, refused = 0;
    for (const r of runs) {
      const evs = (r.events ?? []) as RunEvent[];
      const v = [...evs].reverse().find((e) => e.type === "verifier.result")?.payload as { numbers_checked?: number; numbers_from_tools?: number } | undefined;
      read += v?.numbers_from_tools ?? 0; checked += v?.numbers_checked ?? 0;
      drafts += evs.filter((e) => e.type === "action.staged").length;
      for (const e of evs) {
        const p = e.payload as { gate?: string; tool?: string } | undefined;
        if (e.type !== "tool.called" || p?.gate !== "denied") continue;
        if (p.tool === "StructuredOutput") rewritten += 1; else refused += 1;
      }
    }
    return { n: runs.length, read, checked, drafts, rewritten, refused };
  }, [last7.data]);

  const tools = (t: string[]) => <span className="ag-tools">{t.slice(0, 3).map((x) => <code key={x}>{x}</code>)}{t.length > 3 && <em>+{t.length - 3}</em>}</span>;
  const recorded = (a: AgentRow) => (
    <span className="ag-rec">
      {a.runs ? <>{a.runs} {a.runs === 1 ? "run" : "runs"}</> : "—"}
      {a.name === "buyers_clerk" ? <small>{a.drafts} drafts · {a.questions} questions</small> : a.role === "specialist" && a.lookups ? <small>{a.lookups} lookups</small> : null}
    </span>
  );
  const agentRow = (r: Row) => {
    const isOpen = open === r.id;
    return (
      <Fragment key={r.id}>
        <div className={`ag-row ag-hit${lit === r.stage ? " lit" : ""}${isOpen ? " open" : ""}`} role="row">
          <span role="cell" className="ag-name">
            <button type="button" id={`ag-${r.id}`} className="ag-stretch" aria-expanded={isOpen} aria-controls={`ag-${r.id}-w`} onClick={() => setOpen(isOpen ? null : r.id)}>
              <Mark role={r.agent.role} />{r.agent.label}
            </button>
            {r.agent.role === "orchestrator" && <small>Orchestrator</small>}
          </span>
          <span role="cell" className="ag-works">{r.works}</span>
          <span role="cell">{tools(r.tools)}</span>
          <span role="cell" className="ag-n">{r.recorded ? recorded(r.agent) : null}</span>
        </div>
        {isOpen && <LatestWork id={`ag-${r.id}-w`} agent={r.agent} tools={r.tools} items={items.data ?? []} />}
      </Fragment>
    );
  };

  return (
    <div className="ag pg-fix">
      <div className="ag-title">
        <h1>Under the hood</h1>
        <p>{d ? <>1 orchestrator · {specialists} specialists · <Link to="/activity">{d.recorded_runs} recorded runs</Link> · ${d.recorded_cost_usd.toFixed(2)} recorded</> : " "}</p>
      </div>

      <div className="pg-body">
      <section className="ag-sec" aria-labelledby="ag-how">
        <div className="ag-h"><h2 id="ag-how">How Lookout works a case</h2><span>The same four steps as every case page</span></div>
        <StageStrip label="The four steps of a case" onHover={setLit} stops={STEPS.map((s) => ({
          key: s.key, name: s.name, caption: s.caption,
          children: <span className="ag-who">{agents.filter((a) => a.stages.includes(s.key)).map((a, i, all) => <span key={a.name}><Mark role={a.role} />{a.label}{i < all.length - 1 && " ·"}</span>)}</span>,
        }))} />
        {ag.loading && !d ? <div className="ag-sk" aria-hidden><i /><i /><i /></div> : ag.error ? <LoadError what="the agents" retry={invalidate} /> : (
          <div className="ag-table" role="table" aria-label="Agents">
            <div className="ag-row ag-hd" role="row"><span role="columnheader">Agent</span><span role="columnheader">Works on</span><span role="columnheader">Tools</span><span role="columnheader" className="ag-n">Recorded</span></div>
            {STEPS.map((s) => (
              <Fragment key={s.key}>
                <div className={`ag-group${lit === s.key ? " lit" : ""}`} role="row"><span role="rowheader">{s.name}</span></div>
                {rows.filter((r) => r.stage === s.key).map(agentRow)}
              </Fragment>
            ))}
          </div>
        )}
        {d && <p className="ag-foot">In a run the draft is prepared before Lookout decides, so it is ready when the buyer chooses. {d.earlier_prompt} of the {d.recorded_runs} recordings were made on an earlier prompt.</p>}
      </section>

      <section className="ag-sec" aria-labelledby="ag-check">
        <div className="ag-h"><h2 id="ag-check">How every figure is checked</h2><span>Before anything reaches a buyer</span></div>
        <StageStrip label="The checks on every answer" stops={CHECKS.map((c) => ({ key: c.key, name: c.name, caption: c.caption, children: <span className="ag-cap">{c.text}</span> }))} />
        {totals.n > 0 && (
          <p className="ag-tot">Last {totals.n} runs: <b>{totals.read} of {totals.checked}</b> figures in the answers matched a lookup · <b>{totals.drafts}</b> {totals.drafts === 1 ? "draft" : "drafts"} prepared for approval · <b>{totals.rewritten}</b> {totals.rewritten === 1 ? "answer" : "answers"} rewritten to fit the format · <b>{totals.refused}</b> {totals.refused === 1 ? "lookup" : "lookups"} refused over the per-case limit</p>
        )}
      </section>

      {ev.data && (
        <section className="ag-sec" aria-labelledby="ag-evals">
          <div className="ag-h"><h2 id="ag-evals">Evals</h2><span>{day(ev.data.date)} · {modelName(ev.data.model)} · round {ev.data.round} · {ev.data.trials} trials · answer sheets written from the raw files</span></div>
          <div className="ag-ev" role="table" aria-label="Evals">
            {(ev.data.rows ?? []).map((r) => (
              <div key={r.label} className="ag-evr" role="row"><span role="cell"><b>{r.label}</b>{r.sub && <small>{r.sub}</small>}</span><span role="cell" className="ag-v">{r.value}</span></div>
            ))}
            <p className="ag-evn">Every miss is in the report with its cause. <a href="/api/evals/report" target="_blank" rel="noreferrer">Full report →</a></p>
          </div>
        </section>
      )}

      <section className="ag-sec" aria-labelledby="ag-data">
        <div className="ag-h"><h2 id="ag-data">Data</h2><span>Outside the case</span></div>
        {steward && <div className="ag-table" role="table" aria-label="Data steward">{agentRow({ id: `${steward.name}:data`, agent: steward, stage: "data", works: steward.works_on, tools: steward.tools, recorded: true })}</div>}
        <div className="ag-links">
          <Link to="/data"><b>Data issues</b><span>{counts.data?.data_issues != null ? `${counts.data.data_issues} found in the files` : "found in the files"}</span></Link>
          <Link to="/data/import"><b>Import a file</b><span>map a supplier or ERP file</span></Link>
        </div>
      </section>
      </div>
    </div>
  );
}

/** An agent's latest recorded work, unfolded under its row: each lookup and what it returned, and a link to the whole run. */
function LatestWork({ id, agent, tools, items }: { id: string; agent: AgentRow; tools: string[]; items: ActionItem[] }) {
  const run = useResource(() => (agent.latest_run_id ? api.run(agent.latest_run_id) : Promise.resolve(null)), [agent.latest_run_id]);
  const r = run.data;
  const evs = ((r?.events ?? []) as RunEvent[]).filter((e) => e.agent === agent.name);
  const results = evs.filter((e) => e.type === "tool.result" && tools.includes(String((e.payload as { tool?: string } | undefined)?.tool)));
  const read = (e: RunEvent) => ((e.payload as { numbers?: unknown[] } | undefined)?.numbers ?? []).length;
  const item = items.find((i) => i.key === r?.item_key);
  const what = r?.title ?? (item ? caseShort(item.title) : r?.item_key ?? "");
  return (
    <div className="ag-work" id={id} role="row">
      {!agent.latest_run_id ? <span className="ag-none">No recorded run yet</span> : run.loading && !r ? <span className="ag-sk1" aria-hidden /> : !r ? <span className="ag-none">The run could not be loaded.</span> : (
        <>
          <p className="ag-wh">Latest work · {what} · recorded {day((r.recorded_at ?? r.started_at ?? "").slice(0, 10))} · {evs.filter((e) => e.type === "tool.called" && tools.includes(String((e.payload as { tool?: string } | undefined)?.tool))).length} lookups · {results.reduce((a, e) => a + read(e), 0)} figures read</p>
          {results.length === 0 ? <p className="ag-none">No lookups in this run.</p> : (
            <ul>{results.map((e) => <li key={e.seq}><code>{String((e.payload as { tool?: string }).tool)}</code><span>{e.summary}</span><em>{read(e)} read</em></li>)}</ul>
          )}
          <p className="ag-all">All tools: {tools.join(" · ")}</p>
          <Link to={`/activity/${encodeURIComponent(r.run_id ?? "")}`}>Open the run in Agent activity →</Link>
        </>
      )}
    </div>
  );
}

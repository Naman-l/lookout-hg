import { useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../../api/client";
import { useResource } from "../../api/useResource";
import { LoadError } from "../../ds/LoadError";
import { invalidate } from "../../api/useResource";
import type { ActionItem, Run, RunDetail } from "../../api/types";
import { day } from "../records/model";
import { buildTrace } from "./trace";
import { useAgentLabels } from "./labels";
import "./agents.css";

const TABS = { all: "All", drafts: "Drafts", rewritten: "Rewritten to fit", failed: "Figures failed", reviewer: "Reviewer not met" } as const;
type Tab = keyof typeof TABS;
const money = (n: number) => `$${n.toFixed(2)}`;
const median = (xs: number[]) => { if (!xs.length) return null; const s = [...xs].sort((a, b) => a - b); const m = Math.floor(s.length / 2); return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
/** The Today tab a case sits under (FINAL 02's kinds). */
const kindOf = (i: ActionItem) => (i.key.startsWith("risk:") ? "Supplier risk" : i.group === "trust" ? "Trust" : i.group === "deadline" ? "Deadlines" : i.group === "tariff" ? "Import duty" : i.group === "unknown" ? "Unknowns" : "Disruption");

type Line = { run: Run; title: string; sub: string; outcome: string; figures?: string; reviewer?: string; drafts: number; rewrites: number; failed: boolean; short: boolean; cost: number; replays: number };

/** Agent activity (FINAL 08 B): what each run did, its outcome in words, and what was checked; a row opens the run. */
export function AgentActivity() {
  const runs = useResource(api.runs);
  const items = useResource(() => api.actionItems().catch(() => [] as ActionItem[]));
  const details = useResource(() => Promise.all((runs.data ?? []).map((r) => api.run(r.run_id ?? "").catch(() => null))), [runs.data]);
  const label = useAgentLabels();
  const [params, setParams] = useSearchParams();
  const tab = ((params.get("tab") as Tab | null) && (params.get("tab") as Tab) in TABS ? params.get("tab") : "all") as Tab;

  const lines: Line[] = useMemo(() => (runs.data ?? []).map((r, k) => {
    const d = (details.data ?? [])[k] as RunDetail | null | undefined;
    const t = d ? buildTrace(d.events ?? []) : null;
    const item = (items.data ?? []).find((i) => i.key === r.item_key);
    const ask = (r.item_key ?? "").startsWith("ask:");
    const contacts = [...new Set((t?.staged ?? []).map((s) => s.contact).filter(Boolean))] as string[];
    // A run that only logged questions for the buyers says so ("Logged a question for <name>" -> Notes to 4 buyers).
    const notes = [...new Set(((d?.events ?? []) as { type: string; summary: string; payload?: { tool?: string } }[]).filter((e) => e.type === "tool.result" && e.payload?.tool === "log_buyer_question").map((e) => e.summary.match(/for ([A-Z][a-z]+)/)?.[1]).filter(Boolean))] as string[];
    const failed = r.verifier_passed === false || (r.status !== "ok" && r.status !== "running");
    const outcome = r.status === "running" ? `Working · ${t?.groups[t.groups.length - 1]?.name ?? "Overview"}`
      : failed ? "Did not pass" : contacts.length === 1 ? `Draft to ${contacts[0]}` : contacts.length > 1 ? `Drafts to ${contacts.join(", ")}` : (t?.staged.length ?? 0) > 0 ? "Draft prepared"
      : notes.length ? `Notes to ${notes.length === 1 ? notes[0] : `${notes.length} buyers`}` : "Answered";
    return {
      run: r, outcome, failed, drafts: t?.staged.length ?? 0, rewrites: t?.rewrites ?? 0, replays: 1,
      short: !!r.checks_total && (r.checks_passed ?? 0) < r.checks_total,
      title: (ask ? r.title ?? "A question to Lookout" : item?.title ?? r.title ?? r.item_key ?? "").replace(/\s*\(on time[^)]*\)/, ""),
      sub: ask ? "Ask" : item ? kindOf(item) : (r.item_key ?? "").split(":")[0],
      figures: t?.checked ? `${t.checked.from} of ${t.checked.of}` : undefined,
      reviewer: r.checks_total ? `${r.checks_passed ?? 0} of ${r.checks_total}` : undefined,
      cost: r.recorded ? Number(r.original_cost_usd ?? 0) : Number(r.cost_usd ?? 0),
    };
  }).reduce<Line[]>((acc, l) => {
    // The same recording replayed again is one row, said once ("replayed 3 times"), never three identical rows.
    const same = acc.find((x) => x.run.recorded && l.run.recorded && x.run.item_key === l.run.item_key && x.run.recorded_at === l.run.recorded_at && x.run.duration_ms === l.run.duration_ms);
    if (same) same.replays += 1; else acc.push(l);
    return acc;
  }, []), [runs.data, details.data, items.data]);

  const of = (k: Tab) => lines.filter((l) => k === "all" || (k === "drafts" ? l.drafts > 0 : k === "rewritten" ? l.rewrites > 0 : k === "reviewer" ? l.short : l.failed));
  const shown = of(tab);
  const recorded = lines.length > 0 && lines.every((l) => l.run.recorded);
  const read = lines.reduce((a, l) => a + Number(l.figures?.split(" of ")[0] ?? 0), 0), checked = lines.reduce((a, l) => a + Number(l.figures?.split(" of ")[1] ?? 0), 0);
  const secs = median(lines.map((l) => (l.run.duration_ms ?? 0) / 1000).filter(Boolean));
  const cost = lines.reduce((a, l) => a + l.cost, 0);
  const firstRecorded = lines.map((l) => l.run.recorded_at).filter(Boolean).sort()[0];

  return (
    <div className="ag act pg-fix">
      <div className="ag-title"><h1>Agent activity</h1></div>
      {runs.loading && !runs.data ? <div className="ag-sk" aria-hidden><i /><i /><i /></div>
        : runs.error ? <LoadError what="agent activity" retry={invalidate} />
        : lines.length === 0 ? <p className="ag-none" style={{ marginTop: 16 }}>No agent runs yet</p> : (
          <>
            <div className="act-stats">
              <div><b>{lines.length}</b><span>runs</span></div>
              <div><b>{details.data ? `${read} of ${checked}` : "…"}</b><span>figures checked</span></div>
              <div><b>{details.data ? lines.reduce((a, l) => a + l.drafts, 0) : "…"}</b><span>drafts prepared</span></div>
              <div><b>{secs != null ? `${Math.round(secs)} s` : "—"}</b><span>median time</span></div>
              <div><b>{money(cost)}</b><span>{recorded ? "recorded cost · replayed at $0" : "cost"}</span></div>
            </div>
            <div className="td-seg act-tabs" role="tablist" aria-label="Runs">
              {(Object.keys(TABS) as Tab[]).map((k) => (
                <button key={k} type="button" role="tab" aria-selected={tab === k} className={tab === k ? "on" : undefined} onClick={() => setParams(k === "all" ? {} : { tab: k }, { replace: true })}>
                  {TABS[k]} <em>{details.data || k === "all" || k === "failed" || k === "reviewer" ? of(k).length : ""}</em>
                </button>
              ))}
            </div>
            <div className="pg-body act-body">
            {shown.length === 0 ? <p className="ag-none">No run here.</p> : (
              <div className="act-table" role="table" aria-label="Agent runs">
                <div className="act-row act-hd" role="row">
                  {["Case or question", "Agents", "Outcome", "Figures", "Reviewer", "Lookups", "Time", "Cost"].map((h, i) => <span key={h} role="columnheader" className={i >= 2 ? "n" : undefined}>{h}</span>)}
                </div>
                {shown.map((l) => (
                  <div key={l.run.run_id} className="act-row ag-hit" role="row">
                    <span role="cell" className="act-case"><Link className="ag-stretch act-link" to={`/activity/${encodeURIComponent(l.run.run_id ?? "")}`}>{l.title}</Link><small>{l.sub}{l.replays > 1 ? ` · replayed ${l.replays} times` : ""}</small></span>
                    <span role="cell" className="act-q">{(l.run.specialists ?? []).map((s) => label(s.agent, s.label)).join(" · ")}</span>
                    <span role="cell" className="n">{l.outcome}</span>
                    <span role="cell" className="n">{l.figures ?? "—"}</span>
                    <span role="cell" className="n">{l.reviewer ?? "—"}</span>
                    <span role="cell" className="n act-q">{l.run.tool_calls ?? 0}</span>
                    <span role="cell" className="n act-q">{l.run.duration_ms != null ? `${Math.round(l.run.duration_ms / 1000)} s` : ""}</span>
                    <span role="cell" className="n act-q">{money(l.cost)}</span>
                  </div>
                ))}
              </div>
            )}
            {recorded && <p className="ag-foot">Recorded {firstRecorded ? day(firstRecorded.slice(0, 10)) : ""} on an earlier prompt and replayed without a key. Figures = the answer's figures that matched a lookup; Reviewer = checks passed, as recorded.</p>}
            </div>
          </>
        )}
    </div>
  );
}

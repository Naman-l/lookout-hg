import { Fragment, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { useResource } from "../../api/useResource";
import { invalidate } from "../../api/useResource";
import { useMe } from "../../api/useMe";
import type { ActionItem, DataIssue } from "../../api/types";
import { Handling } from "../../components/domain";
import { LoadError } from "../../ds/LoadError";
import { Expander } from "../../ui/Expander";
import "../today.css";
import "./data.css";

const NEEDS = new Set(["flag", "leave"]);
/** "Oct 13, 15:40" */
export const builtAt = (iso: string) => new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });
const n = (x: number) => x.toLocaleString("en-US");

/** The case an issue is about: every PO line and part id its example names is among one case's refs or the lines its amount was computed from. */
export function caseFor(issue: DataIssue, items: ActionItem[], patterns: string[]): ActionItem | null {
  const ids = patterns.flatMap((p) => (issue.example ?? "").match(new RegExp(p, "g")) ?? []);
  if (!ids.length) return null;
  return items.find((i) => {
    const inputs = (i.at_stake as { provenance?: { inputs?: { id?: string | null }[] } } | null)?.provenance?.inputs ?? [];
    const have = new Set([...(i.refs ?? []).map((r) => r.id), ...inputs.map((r) => r.id ?? "")]);
    return ids.every((x) => have.has(x));
  }) ?? null;
}

/** Data (FINAL 09 §1): what the load found in the company's files, the issues that need a person first, and how the data is rebuilt. */
export function DataPage() {
  const { me } = useMe();
  const issues = useResource(api.dataIssues);
  const stamp = useResource(() => api.stamp().catch(() => null));
  const steps = useResource(() => api.steps().catch(() => []));
  const health = useResource(api.health);
  const items = useResource(() => api.actionItems().catch(() => [] as ActionItem[]));
  const [who, setWho] = useState<"mine" | "all">("mine");
  const [tab, setTab] = useState<"needs" | "handled">("needs");
  const [q, setQ] = useState("");
  const [file, setFile] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const all = issues.data ?? [];
  const loaded = !!issues.data;
  const scoped = all.filter((x) => who === "all" || x.owner === me);
  const inTab = (t: "needs" | "handled") => scoped.filter((x) => NEEDS.has(x.handling ?? "") === (t === "needs"));
  const matched = inTab(tab).filter((x) => !q.trim() || `${x.issue} ${x.file} ${x.owner} ${x.consequence}`.toLowerCase().includes(q.trim().toLowerCase()));
  const files = Array.from(new Set(inTab(tab).map((x) => x.file ?? ""))).sort();
  const rows = matched.filter((x) => !file || x.file === file).sort((a, b) => (b.count ?? 0) - (a.count ?? 0));
  const patterns = useMemo(() => { const p = (health.data as { id_patterns?: Record<string, string> } | undefined)?.id_patterns ?? {}; return [p.po_line, p.part].filter(Boolean) as string[]; }, [health.data]);
  const needsCount = (w: "mine" | "all") => all.filter((x) => NEEDS.has(x.handling ?? "") && (w === "all" || x.owner === me)).length;
  const st = stamp.data;
  const asOf = health.data ? new Date(`${health.data.as_of}T00:00:00Z`).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" }).replace(",", "") : "";      // "Fri Sep 25"
  // Rows a step wrote: its rows out beyond the most any earlier step had written.
  const stepRows = (steps.data ?? []).map((s, i, a) => Math.max(0, s.rows_out - Math.max(0, ...a.slice(0, i).map((p) => p.rows_out))));

  return (
    <div className="dp pg-fix">
      <div className="dp-title">
        <h1>Data</h1>
        <div className="dp-right">
          <Link className="dp-import" to="/data/import">Import a file</Link>
          <div className="td-seg" role="group" aria-label="Whose issues">
            {(["mine", "all"] as const).map((w) => (
              <button key={w} type="button" aria-pressed={who === w} className={who === w ? "on" : undefined} disabled={w === "mine" && !me} onClick={() => setWho(w)}>
                {w === "mine" ? "Yours" : "Everyone"} <em>{loaded ? needsCount(w) : ""}</em>
              </button>
            ))}
          </div>
        </div>
      </div>
      {st && (
        <div className="dp-cap">
          <p>{st.gate_failed > 0 ? <span className="dp-bad">{st.gate_failed} of {st.gate_checks} load checks failed</span> : `${st.gate_checks - st.gate_failed} of ${st.gate_checks} load checks passed`} · loaded {n(st.counts.po_lines ?? 0)} PO lines, {n(st.counts.parts ?? 0)} parts, {n(st.counts.supplier_identities ?? 0)} suppliers, {n(st.counts.messages ?? 0)} messages · rebuilt {builtAt(st.built_at)} from the raw files</p>
          <p>Not in the data: {st.counts.stock_counts === 0 ? "stock on hand (no count given yet) and " : ""}anything after {asOf}. That is why shortfalls read "up to".</p>
        </div>
      )}
      {(steps.data ?? []).length > 0 && (
        <Expander title="How the data is rebuilt" hint={`${steps.data!.length} steps${st ? ` · recipe ${st.recipe_hash.slice(0, 8)}` : ""}`}>
          <div className="dp-steps" role="table" aria-label="How the data is rebuilt">
            <div className="dp-sr dp-sh" role="row"><span role="columnheader">Step</span><span role="columnheader">What it does</span><span role="columnheader" className="n">Rows written</span><span role="columnheader" className="n">Issues found</span></div>
            {steps.data!.map((s, i) => (
              <div key={s.seq} className="dp-sr" role="row"><span role="cell" className="n" title={s.step}>{i + 1}</span><span role="cell">{s.title}</span><span role="cell" className="n">{stepRows[i] ? n(stepRows[i]) : "—"}</span><span role="cell" className="n">{s.issues || "—"}</span></div>
            ))}
          </div>
        </Expander>
      )}
      <div className="td-tabs dp-tabs" role="group" aria-label="Issues">
        {(["needs", "handled"] as const).map((t) => (
          <button key={t} type="button" aria-pressed={tab === t} className={tab === t ? "on" : undefined} onClick={() => { setTab(t); setFile(""); }}>
            {t === "needs" ? "Needs a decision" : "Handled by Lookout"} <em>{loaded ? inTab(t).length : ""}</em>
          </button>
        ))}
      </div>
      <div className="td-filters">
        <input className="td-f td-q" type="search" placeholder="Search issues" aria-label="Search issues" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => { if (e.key === "Escape") setQ(""); }} />
        {files.length > 1 && (
          <select className="td-f" aria-label="Show one file" value={file} onChange={(e) => setFile(e.target.value)}>
            <option value="">All files</option>
            {files.map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
        )}
      </div>
      {issues.loading && !issues.data ? <div className="dp-sk" aria-hidden><i /><i /><i /><i /></div>
        : issues.error ? <LoadError what="data issues" retry={invalidate} />
        : inTab(tab).length === 0 ? <p className="dp-empty">{who === "mine" && tab === "needs" ? "Nothing in the data waits on you." : "Nothing here."}</p>
        : rows.length === 0 ? <p className="dp-empty">No issues match.</p> : (
          <div className="dp-t pg-body" role="table" aria-label="Data issues">
            <div className="dp-r dp-h" role="row"><span role="columnheader">What was found</span><span role="columnheader">File</span><span role="columnheader" className="n">Rows</span><span role="columnheader">What was done</span><span role="columnheader">Who decides</span></div>
            {rows.map((x) => {
              const isOpen = open === x.key, c = caseFor(x, items.data ?? [], patterns);
              return (
                <Fragment key={x.key}>
                  <div className={`dp-r dp-hit${isOpen ? " open" : ""}`} role="row">
                    <span role="cell" className="dp-what">
                      <button type="button" className="dp-stretch" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : x.key ?? null)}>{x.issue}</button>
                      <small>{x.consequence}</small>
                    </span>
                    <span role="cell" className="dp-file">{x.file}</span>
                    <span role="cell" className="n">{n(x.count ?? 0)}</span>
                    <span role="cell" className="dp-how"><Handling how={x.handling ?? ""} rule={x.rule} />{c && <Link className="dp-today" to={`/items/${encodeURIComponent(c.key)}`} title={c.title}>On Today</Link>}</span>
                    <span role="cell" className="dp-who">{x.owner}</span>
                  </div>
                  {isOpen && (
                    <dl className="dp-x">
                      <dt>Rule</dt><dd>{x.rule}</dd>
                      <dt>Consequence</dt><dd>{x.consequence}</dd>
                      <dt>Example</dt><dd>{x.example}</dd>
                      <dt>Step</dt><dd>{x.step}</dd>
                    </dl>
                  )}
                </Fragment>
              );
            })}
          </div>
        )}
    </div>
  );
}

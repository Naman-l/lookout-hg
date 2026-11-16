import { Fragment, useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { invalidate, useResource } from "../api/useResource";
import type { Action, ItemDetail, MessageDetail, Route, RunDetail, Unknown } from "../api/types";
import { useMe } from "../api/useMe";
import { useAskContext, useAskState } from "../shell/AskContext";
import { NotFound, RightPanel } from "../ds";
import { VERTICALS, VerticalIcon } from "../components/domain";
import { owners } from "../components/domain/caseStatus";
import { baseOf, enIn, inr, longDate, monthShort, qty, shortDate } from "../ui/format";
import { DraftView } from "./case/Draft";
import { Mail } from "./case/Mail";
import { LadderStrip } from "./case/LadderStrip";
import "./case-page.css";
import "./case/case.css";

const TAB: Record<string, string> = { requirement: "Requirement", after_po: "After PO", price: "Price", payments: "Payments", vendor_risk: "Vendor risk", trust: "Trust", unknown: "Unknowns" };
const STEPS = ["Overview", "Analysis", "Decision", "Approval", "Sent", "Response"] as const;
const RECORDED = ["Overview", "Analysis", "Decision", "Approval", "Recorded"] as const;
const HELD = ["Overview", "Analysis", "Controls", "Done"] as const;
type Step = (typeof STEPS)[number] | "Recorded" | "Controls" | "Done";

const who = (n?: string | null) => (n ?? "").split(" ")[0];
const isOut = (a: Action) => a.type === "supplier_request" || a.type === "internal_note";

/** The case page: what came in, what the records show, the routes to choose from, the draft to sign, what was sent and what came back. */
export function Item() {
  const { id = "" } = useParams();
  const key = decodeURIComponent(id);
  const { me } = useMe();
  const r = useResource(() => api.item(key, me), [key, me], true);
  const acts = useResource(() => api.actionsFor(key).catch(() => [] as Action[]), [key], true);
  const all = useResource(() => api.actions().catch(() => [] as Action[]), [key], true);
  useAskContext(r.data ? { type: "item", id: key, label: (r.data.title.startsWith("Held: ") ? r.data.title.slice(6) : r.data.title).split(": ")[0] } : null);
  if (r.error) return <NotFound title="No such case" line={`Nothing on Today has the key ${key}.`} />;
  if (!r.data) return <div className="cp-head"><span className="skel" style={{ width: 420 }} /></div>;
  const mine = [...(acts.data ?? []), ...(all.data ?? []).filter((a) => (a.change as { asks?: string[] } | null)?.asks?.includes(key) && a.item_key !== key)];
  return <CaseView i={r.data} drafts={mine} me={me} />;
}

function CaseView({ i, drafts, me }: { i: ItemDetail; drafts: Action[]; me: string | null }) {
  const held = i.tab === "trust";
  const ownerList = owners(i);
  const isOwner = !!me && ownerList.includes(me);
  const out = drafts.filter((a) => a.type !== "note" || ["record", "erp_update", "note"].includes(String((a.change as { kind?: string } | null)?.kind)));
  const live = out.filter((a) => a.state !== "rejected" && (a.change as { kind?: string } | null)?.kind !== "choice" && (a.change as { kind?: string } | null)?.kind !== "control");
  const recordedOnly = live.length > 0 && live.every((a) => a.type === "note");
  const steps: readonly Step[] = held ? HELD : recordedOnly ? RECORDED : STEPS;
  const doneControls = (i.held?.done ?? []).length;
  const stageStep: Step = held ? (doneControls >= (i.held?.controls ?? []).length && doneControls > 0 ? "Done" : "Controls")
    : i.stage?.key === "answered" ? "Response" : i.stage?.key === "sent" ? "Sent" : i.stage?.key === "approved" ? (recordedOnly ? "Recorded" : "Sent")
    : ["drafted", "signed"].includes(i.stage?.key ?? "") ? "Approval" : i.stage?.key === "decision_ready" ? "Decision" : "Analysis";
  const [step, setStep] = useState<Step>(stageStep);
  useEffect(() => setStep(stageStep), [i.key, stageStep]);
  const at = steps.indexOf(stageStep);
  return (
    <div className="cp">
      <Header i={i} steps={steps} step={step} reached={at} onStep={setStep} mine={isOwner} />
      <div className="cp-cols">
        <div className="cp-stack">
          {step === "Overview" && <Overview i={i} />}
          {step === "Analysis" && <Analysis i={i} me={me} />}
          {step === "Decision" && <Decision i={i} me={me} mine={isOwner} onDone={() => { invalidate(); setStep("Approval"); }} />}
          {step === "Approval" && <Approval i={i} drafts={live} me={me} onBack={() => setStep("Decision")} />}
          {(step === "Sent" || step === "Recorded") && <Sent i={i} drafts={live} />}
          {step === "Response" && <Response i={i} drafts={live} me={me} mine={isOwner} />}
          {step === "Controls" && <Controls i={i} me={me} mine={isOwner} />}
          {step === "Done" && <Controls i={i} me={me} mine={false} />}
        </div>
        <Rail i={i} drafts={live} />
      </div>
    </div>
  );
}

function Header({ i, steps, step, reached, onStep, mine }: { i: ItemDetail; steps: readonly Step[]; step: Step; reached: number; onStep: (s: Step) => void; mine: boolean }) {
  const v = baseOf(i.at_stake);
  const months = [...new Set((i.site_impact ?? []).map((s) => s.month))].sort().slice(0, 2);
  const lines = (i.po_lines ?? []).length + (i.pr_lines ?? []).length;
  const vendor = i.vendor?.name;
  return (
    <div className="cp-head">
      <p className="cp-crumb"><Link to="/">Today</Link> › {TAB[i.tab] ?? i.tab}</p>
      <h1 title={i.title}>{i.title}</h1>
      <div className="cs-imp">
        <span className="vt">{VERTICALS.filter((x) => i.verticals.includes(x.id)).map((x) => <VerticalIcon key={x.id} id={x.id} title={x.name} />)}</span>
        {months.map((m) => <span key={m}>{monthShort(m)}: {(i.site_impact ?? []).filter((s) => s.month === m).slice(0, 2).map((s) => `${s.project.label} ${s.front}`).join(" · ")}</span>)}
        {months.length > 0 && <span className="uo">(up to: site stock is not in the data)</span>}
        {v == null && i.at_stake && "owner" in i.at_stake && <span title={i.at_stake.question}><b>₹ unknown</b> {i.at_stake.what}</span>}
        {v != null && <span title={i.at_stake_rule}><b>{inr(v)}</b> {i.at_stake_label}{lines ? ` on ${lines} ${(i.pr_lines ?? []).length && !(i.po_lines ?? []).length ? "PR" : "PO"} line${lines === 1 ? "" : "s"}` : ""}</span>}
        {i.team_total && <span className="uo">of {inr(baseOf(i.team_total))} for the team</span>}
        {i.act_by && <span>Act by <b>{longDate(i.act_by)}</b>{i.days_left != null ? ` (${i.days_left < 0 ? `${-i.days_left} days late` : i.days_left === 0 ? "today" : `${i.days_left} days`})` : ""}</span>}
        {vendor && <span>{vendor}</span>}
        <span>Owner {owners(i).map(who).join(" · ")}</span>
        <span>Waiting on <b>{i.waiting_on}</b></span>
      </div>
      <ol className="cp-track" aria-label="Steps">
        <span className="fill" style={{ width: `${(Math.max(0, reached) / (steps.length - 1)) * 100}%` }} aria-hidden />
        {steps.map((s, n) => (
          <li key={s} className={`${n < reached ? "done" : ""}${s === step ? " cur" : ""}${s === step && mine ? " mine" : ""}`} style={{ left: `${(n / (steps.length - 1)) * 100}%` }}
            aria-current={s === step ? "step" : undefined}>
            {n <= Math.max(reached, 2) || s === "Decision" ? <button type="button" onClick={() => onStep(s)}><i /><b>{s}</b></button> : <span><i /><b>{s}</b></span>}
          </li>
        ))}
      </ol>
    </div>
  );
}

function Card({ title, by, children }: { title: string; by?: ReactNode; children: ReactNode }) {
  return <section className="cp-card"><div className="cp-ch"><b>{title}</b>{by && <span className="cp-cs">{by}</span>}</div>{children}</section>;
}
function Sec({ title, by, children }: { title: string; by?: ReactNode; children: ReactNode }) {
  return <div className="cp-sec"><div className="st"><h3>{title}</h3>{by && <span className="by">{by}</span>}</div>{children}</div>;
}

/** Overview: the source as it came in. The messages, the SAP rows (PR, PO lines with their export row), the sheet cells. No interpretation. */
function Overview({ i }: { i: ItemDetail }) {
  const msgs = useResource(() => Promise.all((i.messages ?? []).slice(0, 4).map((m) => api.thread(m.id).catch(() => null))), [i.key]);
  return (
    <Card title="Overview" by="the records as they came in">
      {(msgs.data ?? []).filter(Boolean).map((m) => <Sec key={(m as MessageDetail).summary.ref.id} title="Message"><Mail m={m as MessageDetail} /></Sec>)}
      {(i.pr_lines ?? []).length > 0 && (
        <Sec title="PR lines (ME5A)" by={`${(i.pr_lines ?? []).length}`}>
          <table className="cp-t"><thead><tr><th>PR line</th><th>Material</th><th className="n">Qty</th><th>Project</th><th>Raised</th><th>Needed by</th><th>Status</th></tr></thead>
            <tbody>{(i.pr_lines ?? []).slice(0, 40).map((l) => <tr key={l.ref.id}><td><Link to={`/prs/${l.pr}`}>{l.ref.id}</Link></td><td>{l.text}</td><td className="n">{qty(l.qty, l.uom)}</td>
              <td>{l.project?.label ?? <span className="none">no project</span>}</td><td>{shortDate(l.created)}</td><td>{shortDate(l.needed_by)}</td><td>{l.status}{l.flags.length ? <small>{l.flags.join("; ")}</small> : null}</td></tr>)}</tbody></table>
        </Sec>
      )}
      {(i.po_lines ?? []).length > 0 && (
        <Sec title="PO lines (ME2N, netted with MB51)" by={`${(i.po_lines ?? []).length}`}>
          <table className="cp-t"><thead><tr><th>PO line</th><th>Item</th><th className="n">Open</th><th className="n">Open ₹</th><th>Due</th><th>Vendor's date</th></tr></thead>
            <tbody>{(i.po_lines ?? []).slice(0, 40).map((l) => <tr key={l.ref.id}><td><Link to={`/pos/${l.po}`}>{l.ref.id}</Link><small>{l.doc_type === "Work order" ? "WO" : ""}</small></td><td>{l.text}</td>
              <td className="n">{qty(l.open_qty, l.uom)}</td><td className="n">{inr(l.open_value.amount)}</td><td>{shortDate(l.delivery_date)}</td>
              <td>{(l.revised ?? []).length ? (l.revised ?? []).map((x) => shortDate(x.date)).join(", ") : <span className="none">—</span>}</td></tr>)}</tbody></table>
        </Sec>
      )}
      {(i.sheet_cells ?? []).length > 0 && (
        <Sec title="Sheet cells (fund vs requirement)">
          <table className="cp-t"><thead><tr><th>Column</th><th>Head</th><th className="n">Fund sheet</th><th className="n">Requirement</th></tr></thead>
            <tbody>{(i.sheet_cells ?? []).map((c) => { const x = c as { check: string; column: string; head: string; fund: number; requirement?: number | null };
              return <tr key={x.check}><td>{x.column}</td><td>{x.head}</td><td className="n">{inr(x.fund)}</td><td className="n">{x.requirement != null ? inr(x.requirement) : <span className="none">none</span>}</td></tr>; })}</tbody></table>
        </Sec>
      )}
      {!(i.messages ?? []).length && !(i.pr_lines ?? []).length && !(i.po_lines ?? []).length && !(i.sheet_cells ?? []).length && <p className="cp-none">The case rests on the records in Analysis.</p>}
    </Card>
  );
}

function UnknownTable({ rows }: { rows: Unknown[] }) {
  if (!rows.length) return null;
  return (
    <Sec title="What we don't know">
      <table className="cp-t"><thead><tr><th>Question</th><th>Who can say</th><th>Why it matters</th></tr></thead>
        <tbody>{rows.slice(0, 20).map((u, n) => <tr key={n}><td>{u.question}</td><td>{u.owner}</td><td>{u.why_it_blocks}</td></tr>)}</tbody></table>
    </Sec>
  );
}

/** Lookout's run on the case: a run replayed from a recording, or drafted by code with no model, each labelled as what it is; its steps, its checks. */
function RunBlock({ i, me }: { i: ItemDetail; me: string | null }) {
  const [runId, setRunId] = useState<string | null>((i.latest_run as { run_id?: string } | null)?.run_id ?? null);
  const [err, setErr] = useState("");
  const [tick, setTick] = useState(0);
  const run = useResource(() => (runId ? api.run(runId).catch(() => null) : Promise.resolve(null)), [runId, tick], true);
  useEffect(() => {
    if (run.data?.status !== "running") return;
    const t = setTimeout(() => setTick((n) => n + 1), 900);
    return () => clearTimeout(t);
  }, [run.data, tick]);
  useEffect(() => { if (run.data && run.data.status !== "running") invalidate(); }, [run.data?.status]);      // eslint-disable-line react-hooks/exhaustive-deps
  const start = async () => {
    setErr("");
    try { const r = await api.startRun(i.key, me ?? ""); setRunId(r.run_id); } catch (e) { setErr((e as Error).message.includes("404") ? "The agent layer is not running on this server." : "The run could not start."); }
  };
  const d: RunDetail | null | undefined = run.data;
  const rec = d?.recommendation;
  return (
    <Sec title="Lookout's reading" by={d ? `${d.mode === "recorded" ? "replayed from a recording (mocked; no model ran)" : d.mode === "code" ? "drafted by code, no model" : d.model ?? ""}` : undefined}>
      {!d && <p className="cp-line">The case was found and figured by code. <button type="button" className="b9" onClick={start}>Work this case with Lookout</button>{err && <span className="df-err"> {err}</span>}</p>}
      {d && d.status === "running" && <ol className="cs-run">{(d.events ?? []).filter((e) => ["step.text", "child.started", "tool.called"].includes(e.type)).map((e) => <li key={`${e.run_id}${e.seq}`}><span className="ag">{e.agent_label}</span>{e.summary}</li>)}<li>…</li></ol>}
      {d && d.status !== "running" && rec && (
        <>
          {rec.finding && <p className="cp-line"><b>{rec.finding}</b></p>}
          {rec.recommended && <p className="cp-line">Recommended: <b>{rec.recommended.kind.replace(/_/g, " ")}</b>{rec.recommended.reason ? ` · ${rec.recommended.reason}` : ""}</p>}
          <p className="cp-line">{d.verifier ? `${d.verifier.checked - d.verifier.failures.length} of ${d.verifier.checked} checks passed` : ""}{d.review ? ` · Reviewer ${d.review.grade}` : ""} · <Link to={`/activity/${d.run_id}`}>How we got here</Link></p>
        </>
      )}
    </Sec>
  );
}

/** Analysis: what the records show (code's facts, each over the record it rests on), the requirement against supply by month, the ladder, the CS, and what
 * nobody knows yet with who could say. */
function Analysis({ i, me }: { i: ItemDetail; me: string | null }) {
  const s = i.supply;
  return (
    <Card title="Analysis" by="computed from the records">
      {i.finding && <p className="cp-line"><b>{i.finding}</b></p>}
      {i.held && <p className="cp-line">Imitates <b>{i.held.imitates ?? "—"}</b>. {i.held.flags.join("; ")}.</p>}
      {(i.findings ?? []).length > 0 && (
        <Sec title="What the records show">
          <div className="cp-fg">{(i.findings ?? []).map((f) => <Fragment key={f.key}><div className="f">{f.fact}</div><div className="m">{f.meaning}</div></Fragment>)}</div>
        </Sec>
      )}
      {!held(i) && <RunBlock i={i} me={me} />}
      {s && (s.months ?? []).some((m) => m.required != null || m.on_order || m.received) && (
        <Sec title={`Requirement against supply · ${s.project_name}`} by={s.note}>
          <table className="cp-t cs-mo"><thead><tr><th>Month</th><th className="n">Required</th><th className="n">On order</th><th className="n">Received</th><th className="n">Gap (up to)</th></tr></thead>
            <tbody>{s.months.map((m) => <tr key={m.month}><td>{monthShort(m.month)} {m.month.slice(0, 4)}</td><td className="n">{m.required != null ? qty(m.required, s.uom) : "—"}</td>
              <td className="n">{qty(m.on_order)}{m.late_into ? <small>{enIn(m.late_into)} moved in late</small> : null}</td><td className="n">{qty(m.received)}</td>
              <td className={`n${m.gap ? " gap" : ""}`}>{m.gap != null ? qty(m.gap) : "—"}</td></tr>)}</tbody></table>
        </Sec>
      )}
      {i.ladder && <Sec title="From PR to payment" by="each wait attributed by rule"><LadderStrip ladder={i.ladder} /></Sec>}
      {i.cs && (
        <Sec title={`Comparative statement ${i.cs.cs}`} by={`${i.cs.quotes_in} of ${i.cs.vendors_asked} quoted · ${i.cs.status ?? ""}`}>
          <table className="cp-t"><thead><tr><th>Vendor</th><th className="n">Rate</th><th>Valid to</th><th>Remarks</th></tr></thead>
            <tbody>{i.cs.quotes.map((q) => <tr key={q.ref.id}><td>{q.vendor_name}{q.l1 ? <small>L1</small> : null}</td><td className="n">{q.rate ? inr(q.rate.amount) : "—"}</td><td>{shortDate(q.validity)}</td><td>{q.remarks ?? ""}</td></tr>)}</tbody></table>
          <p className="cs-why">Last PO rate {i.cs.last_po_rate ? inr(i.cs.last_po_rate.amount) : "not on file"} · budget {i.cs.budget_rate ? inr(i.cs.budget_rate.amount) : "not on file"}</p>
        </Sec>
      )}
      <UnknownTable rows={i.unknowns ?? []} />
    </Card>
  );
}
const held = (i: ItemDetail) => i.tab === "trust";

/** Decision: the routes of this kind of case, as a code table, with figures from the records. Nothing is preselected; the owner chooses; the draft follows. */
function Decision({ i, me, mine, onDone }: { i: ItemDetail; me: string | null; mine: boolean; onDone: () => void }) {
  const routes = useResource(() => api.routes(i.key, me), [i.key, me]);
  const { openWith } = useAskState();
  const [pick, setPick] = useState<string | null>(null);
  const [also, setAlso] = useState<Set<string>>(new Set());
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const rec = (i.recommendation as { recommended?: { kind: string; reason?: string } } | null)?.recommended;
  const rs = routes.data ?? [];
  const chosen = rs.find((r) => r.kind === pick);
  useEffect(() => { setAlso(new Set(rs.filter((r) => r.also_start).map((r) => r.kind))); }, [routes.data]);      // eslint-disable-line react-hooks/exhaustive-deps
  const go = async () => {
    if (!chosen || !me) return;
    setBusy(true); setErr("");
    try {
      await api.choose(i.key, chosen.kind, me, reason);
      for (const k of also) if (k !== chosen.kind) { const r = rs.find((x) => x.kind === k); if (r && r.leads_to !== "record") await api.choose(i.key, k, me, ""); }
      onDone();
    } catch (e) { setErr(e instanceof ApiError ? e.detail || e.message : (e as Error).message); } finally { setBusy(false); }
  };
  const to = (r: Route) => r.leads_to === "record" ? "On record" : r.leads_to === "note" ? (r.label.includes("SAP") ? "To enter in SAP" : "A note") : r.to.length ? r.to.map((t) => t.name ? `${t.name}, ${t.role.replace(" (contact on file)", "")}` : t.role).join("; ") + (r.leads_to === "request" ? " (contact on file)" : "") : "no contact on file";
  const footer = chosen ? (chosen.leads_to === "request" ? `Continue drafts the letter${chosen.to.length > 1 ? "s" : ""} to ${chosen.to.map((t) => t.name ?? t.role).join(", ")}; nothing goes out until you sign` + (chosen.countersign ? ` and ${who(chosen.countersign)} countersigns` : "")
    : chosen.leads_to === "internal_note" ? `Continue drafts the note to ${chosen.to.map((t) => t.name).join(", ")}; it is sent (simulated) when you sign` + (chosen.countersign ? ` and ${who(chosen.countersign)} countersigns` : "")
    : chosen.leads_to === "record" ? "Continue records your decision with its reason, for your signature" : "Continue stages the note for your signature; nothing is sent") + "." : "Choose a route.";
  return (
    <Card title="Decision" by={mine ? "yours to choose" : `${owners(i).map(who).join(" · ")} chooses`}>
      {routes.loading && !routes.data ? <span className="skel" style={{ width: 320 }} /> : rs.length === 0 ? <p className="cp-none">No routes for this kind of case.</p> : (
        <table className="cp-t cs-rt">
          <thead><tr><th>Route</th><th>What it changes</th><th>Earliest help</th><th className="n">Cost</th><th>Goes to</th></tr></thead>
          <tbody>
            {rs.map((r) => (
              <tr key={r.kind} className={pick === r.kind ? "on" : undefined}>
                <td><label><input type="radio" name="route" disabled={!mine} checked={pick === r.kind} onChange={() => setPick(r.kind)} />
                  <span><span className="rk">{r.label}</span>{r.commits && <span className="ss" title={r.doa_line ?? ""}>ⓢ</span>}{rec?.kind === r.kind && <span className="rec">Recommended</span>}
                    {r.also_start && <small><br />Also start: {r.also_why}</small>}</span></label></td>
                <td>{r.changes}</td>
                <td>{r.earliest ? shortDate(r.earliest) : "—"}<small>{r.earliest_basis}</small></td>
                <td className="n">{r.cost ? inr(r.cost.amount) : "—"}<small>{r.cost_basis}</small></td>
                <td>{to(r)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {rec?.reason && <p className="cs-why">Lookout recommends <b>{rec.kind.replace(/_/g, " ")}</b>: {rec.reason} (advice; the choice is yours).</p>}
      {chosen?.commits && <p className="cs-why">ⓢ {chosen.doa_line}</p>}
      {chosen?.leads_to === "record" && <textarea className="df-reason" rows={2} placeholder="The reason, on record" value={reason} onChange={(e) => setReason(e.target.value)} />}
      {rs.some((r) => r.also_start) && mine && (
        <div className="cs-ctl">{rs.filter((r) => r.also_start).map((r) => (
          <label key={r.kind}><input type="checkbox" checked={also.has(r.kind)} onChange={(e) => { const n = new Set(also); if (e.target.checked) n.add(r.kind); else n.delete(r.kind); setAlso(n); }} />
            Also start: {r.label}<small>{r.also_why}</small></label>))}</div>
      )}
      {err && <p className="df-err" role="alert">{err}</p>}
      <div className="cp-foot">
        <span className="pp">{mine ? footer : `Only ${owners(i).join(" and ")} can choose.`}</span>
        <button type="button" className="b9" onClick={() => openWith(`For "${i.title}": is there another option? `)}>Ask for another option</button>
        {mine && <button type="button" className="b9 dark" disabled={!chosen || busy || (chosen.leads_to === "record" && !reason.trim())} onClick={go}>Continue</button>}
      </div>
    </Card>
  );
}

/** Approval: the drafts for the chosen route, exact text, with the DoA line; the owner signs (or edits, or rejects); above the threshold the Head countersigns. */
function Approval({ i, drafts, me, onBack }: { i: ItemDetail; drafts: Action[]; me: string | null; onBack: () => void }) {
  const waiting = drafts.filter((a) => a.state === "proposed" || a.state === "signed");
  const rest = drafts.filter((a) => !waiting.includes(a));
  return (
    <Card title="Approval" by={i.doa?.line}>
      {waiting.length === 0 && <p className="cp-none">Nothing is waiting for a signature. <button type="button" className="cp-link" onClick={onBack}>Choose a route</button></p>}
      {waiting.map((a) => <Sec key={a.action_id} title={a.subject ?? "Draft"}><DraftView a={a} me={me} /></Sec>)}
      {rest.length > 0 && <Sec title="Earlier on this case">{rest.map((a) => <DraftView key={a.action_id} a={a} me={me} compact />)}</Sec>}
    </Card>
  );
}

/** Sent: what went out (simulated) and to whom; a decision on record shows as recorded. */
function Sent({ i, drafts }: { i: ItemDetail; drafts: Action[] }) {
  const sent = drafts.filter((a) => a.state === "executed");
  return (
    <Card title={sent.every((a) => a.type === "note") ? "Recorded" : "Sent"} by={i.stage?.next_act}>
      {sent.length === 0 && <p className="cp-none">Nothing has gone out yet.</p>}
      {sent.map((a) => <Sec key={a.action_id} title={isOut(a) ? `To ${a.recipient_name ?? a.recipient} (simulated)` : "On record"} by={a.confirmed_at ? longDate(a.confirmed_at) : undefined}><DraftView a={a} me={null} compact /></Sec>)}
    </Card>
  );
}

/** Response: what came back, and what it changes per line; the change to make in SAP is offered as a note for the owner's signature. */
function Response({ i, drafts, me, mine }: { i: ItemDetail; drafts: Action[]; me: string | null; mine: boolean }) {
  const to = new Set(drafts.filter((a) => a.state === "executed" && a.recipient).map((a) => (a.recipient ?? "").toLowerCase()));
  const msgs = useResource(() => api.messages().then((m) => Promise.all(m.filter((x) => to.has((x.from_email ?? "").toLowerCase()) && x.simulated).map((x) => api.thread(x.ref.id)))).catch(() => [] as MessageDetail[]),
    [i.key, [...to].join(",")]);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState("");
  const moves = (msgs.data ?? []).flatMap((m) => m.moves ?? []).filter((x) => x.ref.type === "po_line");
  const stage = async () => {
    if (!me) return;
    setBusy(true);
    try {
      await api.stage(i.key, { kind: "erp_update", staged_by: me, text: "PO delivery dates as the vendor's reply confirms, to change in SAP.", option_kind: "reply_dates" });
      setDone("Staged for your signature in Approvals."); invalidate();
    } catch (e) { setDone(e instanceof ApiError ? e.detail : (e as Error).message); } finally { setBusy(false); }
  };
  return (
    <Card title="Response" by={i.stage?.next_act}>
      {(msgs.data ?? []).map((m) => <Sec key={m.summary.ref.id} title="Reply"><Mail m={m} /></Sec>)}
      {moves.length > 0 && (
        <Sec title="What it changes">
          <table className="cp-t"><thead><tr><th>Line</th><th>Was</th><th>Now</th><th className="n">Qty</th></tr></thead>
            <tbody>{moves.map((x, n) => <tr key={n}><td>{x.label}</td><td>{shortDate(x.was)}</td><td>{shortDate(x.now)}</td><td className="n">{x.qty != null ? enIn(x.qty) : ""}</td></tr>)}</tbody></table>
          {mine && <div className="cp-foot"><span className="pp">The SAP delivery dates are not changed by Lookout: stage the change as a note to enter.</span><button type="button" className="b9 dark" disabled={busy} onClick={stage}>Stage the SAP change</button></div>}
          {done && <p className="cs-why">{done}</p>}
        </Sec>
      )}
      {!(msgs.data ?? []).length && <p className="cp-none">No reply yet.</p>}
    </Card>
  );
}

/** A held message: the controls a person records (who, when). Nothing is drafted, paid or ordered from it. */
function Controls({ i, me, mine }: { i: ItemDetail; me: string | null; mine: boolean }) {
  const h = i.held;
  const [err, setErr] = useState("");
  if (!h) return null;
  const done = new Map((h.done ?? []).map((d) => [String((d as { control?: string }).control), d as { by?: string; at?: string }]));
  const tick = async (c: string) => { if (!me) return; setErr(""); try { await api.recordControl(i.key, c, me); invalidate(); } catch (e) { setErr(e instanceof ApiError ? e.detail : (e as Error).message); } };
  return (
    <Card title={done.size >= h.controls.length ? "Done" : "Controls"} by={h.claimed ? `${inr(h.claimed.amount, true)} claimed · ₹0 paid` : undefined}>
      <p className="cp-line">From <b>{h.sender}</b>{h.imitates ? <> · imitates <b>{h.imitates}</b></> : null}</p>
      <div className="cs-ctl">
        {h.controls.map((c) => { const d = done.get(c); return (
          <label key={c}><input type="checkbox" checked={!!d} disabled={!!d || !mine} onChange={() => tick(c)} />{c}{d && <small>{who(d.by)} · {d.at ? longDate(d.at) : ""}</small>}</label>); })}
      </div>
      {!mine && <p className="cs-why">Only {owners(i).join(" and ")} can record the controls.</p>}
      {err && <p className="df-err">{err}</p>}
    </Card>
  );
}

/** The rail: deadlines, the vendor and the project on file, cases that share a record, what is folded under this case, and the history. */
function Rail({ i, drafts }: { i: ItemDetail; drafts: Action[] }) {
  const v = i.vendor, p = i.project;
  const signed = useMemo(() => drafts.filter((a) => a.state !== "proposed"), [drafts]);
  return (
    <RightPanel label="About this case" className="cp-rail">
      <RightPanel.Section title="Deadlines">{(i.deadlines ?? []).length ? (i.deadlines ?? []).map((d, n) => (
        <div key={n} className={`dd${n === 0 ? " nx" : ""}`} title={d.source}><b>{shortDate(d.date)}</b><span>{d.what}</span><small>{d.days_left < 0 ? `${-d.days_left} d ago` : `${d.days_left} d`}</small></div>)) : null}</RightPanel.Section>
      {v && (
        <RightPanel.Section title="Vendor">
          <Link className="nm" to={`/vendors/${v.ref.id}`}>{v.name}</Link>
          <div className="s">{v.codes.join(" · ")}{v.gstin ? ` · GSTIN ${v.gstin}` : ""}</div>
          <div className="s">{v.on_time}{v.avg_days_late ? ` · late ones avg ${v.avg_days_late} d` : ""}</div>
          {v.streak_line && <div className="s">{v.streak_line}</div>}
          {v.terms.length > 0 && <div className="s">{v.terms.join("; ")}</div>}
          <div className="s">{v.msme ? `MSME${v.msme_due_45 ? ` · ${v.msme_due_45} invoice(s) due within 45 days` : ""}` : "Not MSME"} · {v.library.length ? `library: ${v.library.join(", ")}` : "not in the library"}</div>
          {v.contact && <div className="s">Contact on file: {v.contact}</div>}
        </RightPanel.Section>
      )}
      {p && (
        <RightPanel.Section title="Project">
          <Link className="nm" to={`/insights/projects/${p.ref.id}`}>{p.ref.label}</Link>
          <div className="s">{p.vertical} · {p.stage}{p.plants.length ? ` · plant ${p.plants.join(", ")}` : " · no SAP plant yet"}</div>
          <div className="s">Head {p.head ?? "—"} · Planner {p.planner ?? "—"}</div>
          {p.median_pr_po_days != null && <div className="s">PR → PO median {p.median_pr_po_days} days</div>}
        </RightPanel.Section>
      )}
      {(i.dated ?? []).length > 0 && <RightPanel.Section title="Folded under this case">{(i.dated ?? []).map((d) => <Link key={d.key} className="ln" to={`/items/${encodeURIComponent(d.key)}`}>{d.act_by ? `${shortDate(d.act_by)} · ` : ""}{d.title}</Link>)}</RightPanel.Section>}
      {(i.linked ?? []).length > 0 && <RightPanel.Section title="Linked cases">{(i.linked ?? []).map((l) => <Link key={l.key} className="ln" to={`/items/${encodeURIComponent(l.key)}`} title={l.why}>{l.title}<span className="s"> · {l.why}</span></Link>)}</RightPanel.Section>}
      {((i.decisions ?? []).length > 0 || signed.length > 0) && <RightPanel.Section title="History">{(i.decisions ?? []).map((d) => <div key={d.action_id + d.at} className="s">{shortDate(d.at)} · {d.text}</div>)}</RightPanel.Section>}
      <RightPanel.Section><div className="links">{(i.messages ?? []).length > 0 && <Link to={`/inbox/${encodeURIComponent((i.messages ?? [])[0].id)}`}>Messages ({(i.messages ?? []).length})</Link>}<Link to="/approvals">Approvals</Link></div></RightPanel.Section>
    </RightPanel>
  );
}

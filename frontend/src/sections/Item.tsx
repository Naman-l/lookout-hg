import { MessageCircle } from "lucide-react";
import { Fragment, useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useAskContext } from "../shell/AskContext";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useResource } from "../api/useResource";
import { isMoney, isUnknown, type Action, type ItemDetail, type MessageSummary, type RunDetail, type TimePhased, type Trust, type Value as V } from "../api/types";
import { describeAction } from "../ui/actionText";
import { useSupplierNames } from "../api/useSupplierNames";
import { SEVERITY_LABEL } from "../ui/labels";
import { EntityChip } from "../domain-ui/EntityChip";
import { PoLineList } from "../domain-ui/PoLineList";
import { UnknownValue } from "../domain-ui/Unknown";
import { Value } from "../domain-ui/Value";
import { Expander } from "../ui/Expander";
import { Table } from "../ui/Table";
import { Assumptions, CheckStrip, RunTrace } from "../domain-ui/Agent";
import { RunLine, RunPanel } from "../organism/RunPanel";
import { Button, Disclose, NotFound, Notice, PageHeader, Row, Section, StateChip, Tile, Tiles, type SectionDef } from "../ds";
import { humanize, shortDate, signersOf } from "../ui/format";
import { PAST_DUE } from "../ui/copy";
import { StageHeld, StageRail, type StepFact } from "../domain-ui/StageTracker";
import { ResultCard, type ResultData } from "../domain-ui/ResultCard";
import { FireOptions } from "./FireOptions";
import { useNamed } from "../ui/useNamed";
import { ShareBar, dutyNumbers } from "./ShareBar";
import { useMe } from "../api/useMe";
import { useRun } from "../organism/useRun";
import { StatusLine } from "../ds/StatusLine";
import { buildRun } from "../organism/runModel";
import { ApiError } from "../api/client";
import { invalidate } from "../api/useResource";
import { Part, People, ProblemKind, Supplier, Tip, kindOfGroup } from "../components/domain";
import { CaseView } from "./CasePage";

const TRUST: Record<Trust, { label: string; cls: string }> = {
  on_file: { label: "on file", cls: "s-ok" }, new_sender: { label: "new sender", cls: "t-plain" }, suspicious: { label: "suspicious", cls: "t-trust" },
};

/** After a run ends, look again every two seconds for up to a minute while its answer and the Reviewer's grade are stored. */
const SETTLE_TICKS = 30;

export function Item() {
  const { id = "" } = useParams();
  const key = decodeURIComponent(id);
  const [ver, setVer] = useState(0);
  const [started, setStarted] = useState<string | null>(null);
  const [lastRun, setLastRun] = useState<string | null>(null);
  const { me } = useMe();
  const r = useResource(() => api.item(key, me), [key, ver, me], true);      // the viewer's slice of a team case (BUYER #1)
  useAskContext(r.data ? { type: "item", id: key, label: humanize(r.data.title.split(":")[0]) } : null);      // the chip reads "About: <case>", the title up to its colon
  const actions = useResource(() => api.actionsFor(key).then((a) => a.filter((x) => x.item_key === key)).catch(() => [] as Action[]), [key, ver], true);
  const runs = useResource(() => api.runs().catch(() => []), [key]);
  const runId = lastRun ?? r.data?.latest_run?.run_id ?? runs.data?.find((x) => x.item_key === key)?.run_id;
  const [tick, setTick] = useState(0);
  const run = useResource(() => (runId ? api.run(runId).catch(() => null) : Promise.resolve(null)), [runId, tick, ver], true);
  // When the steps end, the run we hold is the one fetched while it was going: it must not pull the page back onto the steps. Only a newer look can.
  const seen = useRef(run.data); seen.current = run.data;
  const stale = useRef<unknown>(null);
  const finish = useCallback(() => { stale.current = seen.current; setVer((n) => n + 1); setStarted(null); }, []);
  // A run that is still going is shown live, whatever got us here (a reload, a second click, a stream that dropped): the start button never shows over it.
  useEffect(() => {
    const d = run.data;
    if (!started && d?.status === "running" && d !== stale.current) setStarted(d.run_id ?? runId ?? null);
  }, [run.data, started, runId]);
  // While a run is on screen, look at it every two seconds too: when it is over, the page moves on to its answer even if the live stream never said so.
  useEffect(() => {
    if (!started) return;
    const d = run.data;
    if (d && d.run_id === started && d.status !== "running") { finish(); return; }
    const t = setTimeout(() => setTick((n) => n + 1), 2000);
    return () => clearTimeout(t);
  }, [started, run.data, finish]);
  // A run ends a moment before its answer and its Reviewer grade are stored: look again, a few times, then stop. The page never settles on the old item while a result is on its way.
  const graded = !!run.data?.recommendation?.grade;
  useEffect(() => {
    const d = run.data;
    if (!d || tick >= SETTLE_TICKS) return;
    const settling = !d.recommendation && d.status !== "failed" && d.status !== "did_not_pass";
    const grading = !!d.recommendation && !graded && !d.recorded && (Number(d.cost_usd) > 0 || Number(d.original_cost_usd) > 0);
    if (!settling && !grading) return;
    const t = setTimeout(() => { setTick((n) => n + 1); invalidate(); }, 2000);
    return () => clearTimeout(t);
  }, [run.data, graded, tick]);
  // Looking again after a run keeps the page on screen: only the very first load is a skeleton.
  if (r.loading && !r.data) return <><h1><span className="skel" style={{ width: 420 }} /></h1></>;
  if (r.error || !r.data) return <NotFound title="Case not found" line={`No case has the key ${key}.`} />;
  const i = r.data;
  const withRun = { ...i, recommendation: (lastRun ? run.data?.recommendation ?? i.recommendation : i.recommendation ?? run.data?.recommendation) ?? null } as ItemDetail;
  // Only a model's answer is graded; a held message or a code-answered run ($0) never gets a Reviewer, so it is never waited for.
  const reviewable = i.group !== "trust" && (Number(run.data?.cost_usd) > 0 || Number(run.data?.original_cost_usd) > 0);
  const settling = !started && !!run.data && !(lastRun ? run.data.recommendation : withRun.recommendation) && run.data.status !== "failed" && run.data.status !== "did_not_pass" && tick < SETTLE_TICKS;
  void reviewable; void settling;      // used by the r7 page (ItemView), kept until FINAL 07 is signed off
  return <CaseHost i={withRun} actions={actions.data ?? []} run={run.data ?? null} runId={runId ?? null} started={started} onStarted={(id) => { setStarted(id); setLastRun(id); }} onSeeResult={(id) => { setLastRun(id); setVer((n) => n + 1); }} />;
  // the r7 page, kept until FINAL 07 is signed off
  // return <ItemView i={i} withRun={withRun} actions={actions.data ?? []} run={run.data ?? null} runId={runId ?? null} started={started} settling={settling} loadingRuns={(runs.loading && !runs.data) || (!!runId && run.loading && !run.data)} checking={reviewable && !settling && !started && tick < SETTLE_TICKS && ((!!run.data?.recommendation && !graded && !run.data.recorded) || (!!i.latest_run && i.latest_run.status !== "running" && (i.latest_run as { reviewer_score?: number | null }).reviewer_score == null && !graded))} onStarted={(id) => { setStarted(id); setLastRun(id); }} onFinished={finish} onSeeResult={(id) => { setLastRun(id); setVer((n) => n + 1); }} />;
}

/** FINAL 07: the case page, with the Review button wired to the agent run. */
function CaseHost({ i, actions, run, runId, started, onStarted, onSeeResult }: { i: ItemDetail; actions: Action[]; run: RunDetail | null; runId: string | null; started: string | null; onStarted: (id: string) => void; onSeeResult: (id: string) => void }) {
  const { start, busy, err, note } = useStartRun(i.key, onStarted, onSeeResult);
  return <>{note}<CaseView key={i.key} i={i} actions={actions} run={run} runId={runId} started={started} onStart={() => start()} onRunLive={() => start(true)} busy={busy} startErr={err} /></>;
}

/** One section at a time: a segmented control on a desktop, a short list of rows that open sheets on a phone. */
export function ItemView({ i, withRun, actions, run, runId, started, settling, loadingRuns, checking, onStarted, onFinished, onSeeResult }: { checking: boolean; settling: boolean; loadingRuns: boolean; onSeeResult: (id: string) => void; i: ItemDetail; withRun: ItemDetail; actions: Action[]; run: RunDetail | null; runId: string | null; started: string | null; onStarted: (id: string) => void; onFinished: () => void }) {
  const [params, setParams] = useSearchParams();
  const rec = withRun.recommendation;
  const lines = i.po_lines ?? [], msgs = i.messages ?? [];
  const evidenceBlocks = [!!rec, i.group === "tariff" && dutyNumbers(i).length > 0, !!i.time_phased, msgs.length > 0].filter(Boolean).length;
  const options = i.group === "disruption" ? <FireOptions itemKey={i.key} month={i.robots_short?.[0] ? new Date(`${i.robots_short[0].month}-01T00:00:00Z`).toLocaleString("en-US", { month: "long", timeZone: "UTC" }) : undefined} /> : null;
  const stageNode = (i.group as string) === "trust" ? <StageHeld>nothing can be sent from this message</StageHeld> : null;
  const { me } = useMe();
  const owners = (i.owner ?? "").split(" · ").map((n) => n.trim()).filter(Boolean);
  const stageRail = (i.group as string) !== "trust" && i.stage ? <div className="rail-stage"><StageRail stage={i.stage} facts={stepFacts(run, actions)} waitingOn={owners.length > 0 && !owners.includes(me ?? "") ? owners.map((n) => n.split(" ")[0]).join(", ") : undefined} /></div> : null;
  const dec = useDecision({ i: withRun, actions, run, started, settling, loadingRuns, runId, onStarted, onFinished, onSeeResult, onDetails: () => setParams({ s: "trace" }, { replace: true }), options });
  const sections: SectionDef[] = [
    { id: "rec", label: "Recommendation", render: () => <>{dec.main}{(evidenceBlocks > 0 || i.group === "tariff") && <div className="ev">{i.group === "tariff" && <ShareBar item={i} />}<Evidence i={withRun} /></div>}</> },
    ...(lines.length > 0 ? [{ id: "lines", label: "Lines", count: lines.length, render: () => { const one = (f: (l: (typeof lines)[number]) => string) => new Set(lines.map(f)).size === 1; const same = one((l) => l.supplier.id) && one((l) => l.buyer ?? ""); return <PoLineList lines={lines} showSupplier={!same} showBuyer={!same} />; } }] : []),
    ...(run ? [{ id: "trace", label: "How we got here", render: () => <RunTrace run={run} runId={runId} /> }] : []),
  ];
  const want = params.get("s") ?? "rec";
  const current = sections.find((x) => x.id === want)?.id ?? "rec";
  const open = (id: string) => setParams(id === "rec" ? {} : { s: id }, { replace: true });
  return (
    <div className="item">
      <PageHeader
        back={{ to: "/", label: "Today" }}
        actions={<Button variant="quiet" onClick={() => document.querySelector<HTMLInputElement>(".composer input")?.focus()}><MessageCircle size={16} strokeWidth={1.5} aria-hidden />Ask about this</Button>}
        title={humanize(i.title)}
        meta={<><ProblemKind kind={kindOfGroup(i.group, i.key)} />{SEVERITY_LABEL[i.severity] && <span className={`dm-chip sev-${i.severity}`}>{SEVERITY_LABEL[i.severity]}</span>}<MetaRefs i={i} />{stageNode}<People names={(i.owner ?? "").split(" · ").map((n) => n.trim()).filter(Boolean)} /></>}
      />
      <div className="tpl-rail item-grid">
        <div className="item-main"><Section sections={sections} current={current} onSelect={open} /></div>
        <aside className="rail" aria-label="Where this stands">
          {checking && <StatusLine text="Reviewer: checking…" />}
          {stageRail}
          {dec.decide && <div className="rail-pin">{dec.decide}</div>}
          <div className="rail-scroll">{dec.rail}</div>
        </aside>
      </div>
    </div>
  );
}

export function NumbersSection({ i }: { i: ItemDetail }) {
  const nums = i.numbers ?? [];
  return (
    <>
      <dl className="kv">
        {nums.map((n) => (<Fragment key={n.id}><dt>{humanize(n.label)}</dt><dd><Value value={n.value as V} /></dd></Fragment>))}
      </dl>
      {(i.unknowns ?? []).length > 0 && <h4 className="oqh">Open questions</h4>}
      <ul className="oq">
        {(i.unknowns ?? []).map((u) => <li key={u.what}><span>{humanize(u.question)}</span><span>{u.owner}</span></li>)}
      </ul>
    </>
  );
}

/** The meta line names who and what: the supplier, the build, and every part the item names (the first three, then "+N" that opens the rest, never silently cut). */
function MetaRefs({ i }: { i: ItemDetail }) {
  const refs = i.refs ?? [];
  const parts = refs.filter((r) => r.type === "part");
  const suppliers = refs.filter((r) => r.type === "supplier");
  return (
    <>
      {suppliers.length <= 2 ? suppliers.map((r) => <Supplier key={r.id} id={r.id} name={r.label} />) : <Tip tip={suppliers.map((r) => r.label ?? r.id).join(", ")}><span className="dm-chip">{suppliers.length} suppliers</span></Tip>}
      {refs.filter((r) => r.type === "product").map((r) => <EntityChip key={r.type + r.id} r={r} />)}
      {parts.length === 1 && <Part id={parts[0].id} name={parts[0].label} />}
      {parts.length > 1 && <Tip tip={parts.map((r) => r.label ?? r.id).join(", ")}><span className="dm-chip">{parts.length} parts</span></Tip>}
    </>
  );
}

/** The one place to act: what to do next and by when, with its buttons. Dates count from the data date (the header says so). */
function ActionBand({ i, children }: { i: ItemDetail; children?: ReactNode }) {
  const named = useNamed();
  const due = i.group === "trust" ? "now" : i.act_by ? `Act by ${shortDate(i.act_by)}${i.days_left != null ? ` · ${i.days_left === 0 ? "that day" : i.days_left === 1 ? "in 1 day" : `in ${i.days_left} days`}` : ""}` : "";
  return (
    <div className="ds-act">
      <div className="what">
        <b>{i.next_action ? <>Next: {named(i.next_action)}</> : "Next"}</b>
        {(due || i.owner) && <small>{[due, i.owner].filter(Boolean).join(" · ")}</small>}
      </div>
      {children}
    </div>
  );
}

/** The agent's answer, opened to its first few sentences: the rest (often the options again, in prose) is one click away. */
function Finding({ text }: { text?: string }) {
  const named = useNamed();
  const [all, setAll] = useState(false);
  const full = named(text ?? "");
  const cut = full.search(/\bWays? through\b/i);
  const head = cut > 40 ? full.slice(0, cut).trim() : full;
  const sentences = head.split(/(?<=[.!?])\s+/);
  const short = sentences.slice(0, 3).join(" ");
  const more = short.length < full.length - 1;
  return (
    <>
      <p className="ds-decision">{all || !more ? full : short}</p>
      {more && <Disclose open={all} onClick={() => setAll(!all)} className="read-more">{all ? "Show less" : "Read the agent’s full answer"}</Disclose>}
    </>
  );
}

function useStartRun(key: string, onStarted: (id: string) => void, onSeeResult: (id: string) => void) {
  const { me } = useMe();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [existing, setExisting] = useState<{ id: string; at: string } | null>(null);
  const start = (asked?: unknown) => {      // a click handler passes its event; only an explicit true runs live
    const live = asked === true;
    setBusy(true); setErr(null); setExisting(null);
    api.startRun(key, me ?? "", live).then(async (r) => {
      if (r.existing && !live) {
        // The agent has already worked this item: say so, with when, and offer its result; never a silent click.
        const run = await api.run(r.run_id).catch(() => null);
        const at = run?.started_at ? new Date(run.started_at).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false }) : "";
        if (run && run.status !== "running") { setExisting({ id: r.run_id, at }); setBusy(false); return; }
      }
      onStarted(r.run_id); setBusy(false);
    }, () => { setBusy(false); setErr("The agent could not start. Try again."); });
  };
  const note = existing ? <Notice>The agent already worked this item{existing.at ? ` at ${existing.at}` : ""}. <button type="button" className="linkbtn" onClick={() => { onSeeResult(existing.id); setExisting(null); }}>See the result</button></Notice> : null;
  return { start, busy, err, note };
}

/** The decision, split in two: the main column holds what the agent concluded and the ways through; the rail holds the numbers, the one next act, what waits for you, and how the agent got there. */
function useDecision({ i, actions, run, started, settling, loadingRuns, runId, onStarted, onFinished, onSeeResult, onDetails, options }: { onDetails: () => void; onSeeResult: (id: string) => void; i: ItemDetail; actions: Action[]; run: RunDetail | null; started: string | null; settling: boolean; loadingRuns: boolean; runId: string | null; onStarted: (id: string) => void; onFinished: () => void; options?: ReactNode; stage?: ReactNode }): { main: ReactNode; decide: ReactNode; rail: ReactNode } {
  const nameOf = useSupplierNames();
  const rec = i.recommendation;
  const { start, busy, err, note: existingNote } = useStartRun(i.key, onStarted, onSeeResult);
  const { me: signer } = useMe();
  const [signing, setSigning] = useState(false);
  const [signErr, setSignErr] = useState<string | null>(null);
  /** The numbers, on every kind of item: the same Tiles, fed from the item's own numbers. */
  const tiles = i.group === "tariff" && i.at_stake && !("owner" in i.at_stake) ? <TariffTiles i={i} />
    : i.group === "disruption" && isMoney(i.at_stake as V) ? <DisruptionTiles i={i} /> : <KeyTiles i={i} />;
  // While a run goes, the answer from before shrinks to one muted line (or, when there was none, the item's finding stays): nothing above the run changes height.
  const prevAt = i.recommendation && i.latest_run?.started_at ? new Date(i.latest_run.started_at).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false }) : "";
  const prev = i.recommendation ? <p className="run-prev">{prevAt ? `Previous answer from ${prevAt}` : "Previous answer"}</p> : <p className="ds-decision">{humanize(i.finding)}</p>;
  if (started) {
    return { main: <><LiveLine runId={started} />{prev}<RunPanel runId={started} onDone={onFinished} /></>, decide: null, rail: null };
  }
  if (!rec && i.group === "trust") {
    const msg = (i.refs ?? []).find((r) => r.type === "message");
    return { main: <Finding text={i.finding} />, decide: <ActionBand i={i}>{msg && <Button variant="primary" to={`/inbox/${encodeURIComponent(msg.id)}`}>Open the message</Button>}</ActionBand>, rail: null };
  }
  if (settling && runId) {
    // The run is over but its answer is not stored yet: the steps stay where they were, with one line saying what is left; never a blank page or the start button.
    return { main: <><StatusLine text="Writing up the answer…" />{prev}<RunPanel runId={runId} onDone={() => {}} /></>, decide: null, rail: null };
  }
  if (!rec) {
    return {
      main: <><Finding text={i.finding} />{options}</>,
      decide: (
        <ActionBand i={i}>
          <Button variant="primary" disabled={busy || loadingRuns} onClick={start}>{busy ? "Starting…" : "Work this with the agent"}</Button>
          {i.latest_run && <Link to={`/activity/${encodeURIComponent(i.latest_run.run_id)}`}>See the last run</Link>}
        </ActionBand>
      ),
      rail: (
        <>
          {err && <Notice tone="risk">{err}</Notice>}
          {existingNote}
          {tiles}
        </>
      ),
    };
  }
  const waitingAction = actions.find((a) => a.state === "proposed");
  // The run may have added to a request that belongs to another item: the stage names it, and it is reviewed from Approvals.
  const stageAct = i.stage?.key === "drafted" && !waitingAction ? i.stage.action ?? null : null;
  // A run that did not pass its check says so in words: nothing on screen may look verified when it is not.
  const didNotPass = run?.status === "did_not_pass";
  const failReason = run?.verifier?.reasons?.[0] ?? run?.verifier?.failures?.[0];
  // A single waiting draft that is yours, with every check passed, can be approved from here: the same call, still hash- and owner-checked on the server. The queue stays in Approvals.
  const inPlace = !!waitingAction && actions.filter((a) => a.state === "proposed").length === 1 && !!signer && signersOf(waitingAction as { owner?: string | null }, i.owner).split(" · ").map((n) => n.trim()).includes(signer) && (waitingAction.unverified_checks ?? []).length === 0 && !didNotPass;
  // The run's structured answer (finding, points with their entities, the next step) is the result card; what it staged to approve is listed beneath it.
  const asked = rec as unknown as { points?: ResultData["points"]; next_step?: ResultData["next_step"] };
  const staged = actions.filter((a) => !run?.run_id || a.run_id === run.run_id || !a.run_id);
  const result: ResultData | undefined = (run as unknown as { result?: ResultData } | null)?.result
    ?? ((asked.points?.length || asked.next_step) ? {
      finding: rec.finding,
      points: (asked.points ?? []).slice(0, 4),
      next_step: asked.next_step ?? null,
      done: staged.map((a) => ({ action_id: a.action_id, label: describeAction(a, nameOf).title, stage: a.state === "proposed" ? "drafted" : a.state === "executed" ? "sent" : a.state === "approved" ? "approved" : null })),
    } : undefined);
  return {
    main: (
      <>
        {run && <RunOutcome run={run} drafts={staged.filter((a) => a.type !== "note").map((a) => a.target?.label ?? (a.target ? nameOf(a.target.id) : "") ?? "").filter(Boolean)} notes={staged.filter((a) => a.type === "note").length} drafted={staged.filter((a) => a.type !== "note").length} added={stageAct ? stageAct.label ?? "" : null} now={i.stage?.label ?? null} asks={[...new Set((i.unknowns ?? []).map((u) => String(u.owner ?? "").split(" ")[0]).filter(Boolean))]} />}
        {result ? <ResultCard data={options ? { ...result, points: result.points?.filter((p) => !/^ways through$/i.test(p.label)) } : result} runId={run?.run_id ?? undefined} /> : <Finding text={rec.finding} />}
        {options}
      </>
    ),
    decide: (
      <ActionBand i={i}>
          {waitingAction
            ? (inPlace
              ? <><Button variant="primary" disabled={signing} onClick={() => { setSigning(true); setSignErr(null); api.approve(waitingAction.action_id, waitingAction.payload_hash, signer ?? "").then(() => { setSigning(false); onFinished(); }, (e: unknown) => { setSigning(false); const d = e instanceof ApiError && e.detail ? e.detail : ""; setSignErr(d ? d.charAt(0).toUpperCase() + d.slice(1) : "This draft could not be approved here. Open it to review."); invalidate(); }); }}>Approve and send as {(signer ?? "").split(" ")[0]} (simulated)</Button><Button variant="quiet" to={`/approvals/${waitingAction.action_id}`}>Review the draft</Button><Button variant="quiet" disabled={busy} onClick={start}>Ask the agent again</Button></>
              : <><Button variant="primary" to={`/approvals/${waitingAction.action_id}`}>Review and approve the request</Button><Button variant="quiet" disabled={busy} onClick={start}>Ask the agent again</Button></>)
            : stageAct
              ? <><Button variant="primary" to={`/approvals/${encodeURIComponent(stageAct.id)}`}>Review and approve the request</Button><Button variant="quiet" disabled={busy} onClick={start}>Ask the agent again</Button></>
              : <Button disabled={busy} onClick={start}>Ask the agent again</Button>}
      </ActionBand>
    ),
    rail: (
      <>
        {signErr && <Notice tone="risk">{signErr}</Notice>}
        {didNotPass && <Notice tone="risk">This answer did not pass its check{failReason ? `: ${humanize(failReason)}` : ""}. Check the figures before you rely on it.</Notice>}
        {existingNote}
        {tiles}
        {(i.dated ?? []).length > 0 && <div><h4 className="oqh">Dates in this problem</h4>
          {(i.dated ?? []).map((d) => <Row key={d.key} to={`/items/${encodeURIComponent(d.key)}`} title={d.title} sub={d.act_by ? `${shortDate(d.act_by)}${d.days_left != null ? ` · ${d.days_left === 0 ? "today" : d.days_left === 1 ? "in 1 day" : `in ${d.days_left} days`}` : ""}` : undefined} />)}</div>}
        {actions.length > 0 && !(actions.length === 1 && actions[0].state === "proposed") && <div><h4 className="oqh">Waiting for you</h4>
          {actions.map((d) => {
            const w = describeAction(d, nameOf);
            const proposed = d.state === "proposed";
            return <Row key={d.action_id} to={proposed ? `/approvals/${d.action_id}` : undefined} title={w.title} sub={w.rest ? short(w.rest) : undefined} figure={<StateChip tone={proposed ? "caution" : d.state === "rejected" ? "unknown" : "positive"}>{actionState(d)}</StateChip>} />;
          })}</div>}
        {run?.events?.length ? <RunLine run={run} onDetails={onDetails} /> : <CheckStrip run={run} />}
      </>
    ),
  };
}

const actionState = (a: Action) =>
  a.state === "proposed" ? "Awaiting approval" : a.state === "executed" ? (a.type === "note" ? "Logged" : "Sent (simulated)") : a.state === "rejected" ? "Rejected" : "Approved";

function Evidence({ i }: { i: ItemDetail }) {
  const rec = i.recommendation;
  const msgs = i.messages ?? [];
  const short = i.time_phased?.buckets.filter((b) => b.short).map((b) => shortDate(b.month + "-01").split(" ")[0]).join(", ");
  return (
    <>
      {rec && (
        <Expander title="Why" hint="assumptions · what would change it"><Assumptions rec={rec} /></Expander>
      )}
      {i.group === "tariff" && dutyNumbers(i).length > 0 && (
        <Expander title="Exposure by part" hint={`${dutyNumbers(i).length} parts, largest first`}>
          <Table rows={dutyNumbers(i)} rowKey={(n) => n.id ?? ""} empty="No parts on the list." cols={[
            { head: "Part", cell: (n) => { const id = (n.id ?? "").split(":")[1]; return <><span className="pn">{id}</span><span className="grey"> {(n.label ?? "").replace(id, "").trim()}</span></>; } },
            { head: "New duty, net", num: true, cell: (n) => <Value value={n.value as V} tag={false} /> },
          ]} />
        </Expander>
      )}
      {i.time_phased && (
        <Expander title="Month by month" hint={`${i.time_phased.part.id} · short ${short}`}>
          <TimePhasedTable tp={i.time_phased} supplier={(i.refs ?? []).find((r) => r.type === "supplier")?.label ?? null} />
        </Expander>
      )}
      {msgs.length > 0 && (
        <Expander title={`${msgs.length} ${msgs.length === 1 ? "message" : "messages"}`} hint={msgs.some((m) => m.trust === "suspicious") ? `${msgs.filter((m) => m.trust === "suspicious").length} suspicious, held` : undefined}>
          <MessageList messages={msgs} />
        </Expander>
      )}
    </>
  );
}

function MessageList({ messages }: { messages: MessageSummary[] }) {
  return (
    <div className="lines">
      {messages.map((m) => (
        <div className="ln" key={m.ref.id}>
          <span className="muted">{shortDate(m.date)}</span>
          <Link to={`/inbox/${encodeURIComponent(m.ref.id)}`}>{m.from}: {humanize(m.summary)}</Link>
          <span className={`badge ${TRUST[m.trust].cls}`}>{TRUST[m.trust].label}</span>
        </div>
      ))}
    </div>
  );
}

function TimePhasedTable({ tp, supplier }: { tp: TimePhased; supplier: string | null }) {
  const mon = (m: string) => shortDate(m + "-01").split(" ")[0];
  const [all, setAll] = useState(false);
  // The months that matter: those up to the last short one and the next two; the rest of the year is one toggle away.
  const lastShort = tp.buckets.reduce((n, b, k) => (b.short ? k : n), -1);
  const buckets = all || lastShort < 0 ? tp.buckets : tp.buckets.slice(0, Math.min(tp.buckets.length, lastShort + 3));
  const hidden = tp.buckets.length - buckets.length;
  return (
    <div>
    <div className="tablewrap">
      <table className="tp">
        <thead><tr><th /><th className="num">Past due</th>{buckets.map((b) => <th key={b.month} className="num">{mon(b.month)}</th>)}</tr></thead>
        <tbody>
          <tr><td>Requirements</td><td className="num">—</td>{buckets.map((b) => <td key={b.month} className="num"><Value value={b.requirements} tag={false} /></td>)}</tr>
          <tr><td>Scheduled receipts</td><td className="num"><Value value={tp.past_due_receipts} tag={false} /></td>{buckets.map((b) => <td key={b.month} className="num"><Value value={b.scheduled_receipts} tag={false} /></td>)}</tr>
          {(Number(tp.past_due_receipts.value) > 0 || tp.buckets.some((b) => Number(b.under_disruption.value) > 0)) && (
            <tr><td>&nbsp;&nbsp;{tp.disrupted ? "under force majeure" : "under the notice"}</td><td className="num short">{whole(tp.past_due_receipts.value)}</td>{buckets.map((b) => <td key={b.month} className={`num ${Number(b.under_disruption.value) ? "short" : ""}`}>{whole(b.under_disruption.value)}</td>)}</tr>
          )}
          <tr><td>On hand</td><td colSpan={buckets.length + 1}><UnknownValue u={tp.on_hand as never} /></td></tr>
          <tr><td><b>{supplier ? `Short if ${supplier} ships nothing` : "Short if the supplier ships nothing"}</b></td><td className="num">—</td>{buckets.map((b) => <td key={b.month} className={`num ${b.short ? "cellshort" : ""}`}>{b.short ? whole(b.short.value) : "—"}</td>)}</tr>
        </tbody>
      </table>
    </div>
    {(hidden > 0 || all) && <Disclose open={all} onClick={() => setAll(!all)}>{all ? "Fewer months" : `All ${tp.buckets.length} months`}</Disclose>}
    </div>
  );
}

const isUnknownValue = (v: object): boolean => "owner" in v;
/** Counts are whole numbers: a quantity the API sends as 222.0 is 222. */
const whole = (v: string | number): string => { const n = Number(v); return Number.isFinite(n) && Number.isInteger(n) ? String(n) : String(v); };

/** At most four numbers up front: the first of each kind (shortage, stuck, requirement, ...), so the rest stay under All numbers. */
function keyNumbers(i: ItemDetail) {
  const seen = new Set<string>();
  const out: NonNullable<ItemDetail["numbers"]> = [];
  if (i.group === "tariff") {
    if (i.at_stake && !isUnknownValue(i.at_stake)) out.push({ id: "net", label: "New duty, net", value: i.at_stake });
    if (i.at_stake_gross) out.push({ id: "gross", label: "Gross, if every line slips past Nov 1", value: i.at_stake_gross });
    seen.add("duty_net"); seen.add("net"); seen.add("gross");
  }
  for (const n of i.numbers ?? []) {
    if (n.value == null || isUnknownValue(n.value)) continue;
    const kind = (n.id ?? "").split(":")[0];
    if (seen.has(kind) || (i.group === "tariff" && /gross/.test(n.id ?? ""))) continue;
    seen.add(kind); out.push(n);
    if (out.length === 4) break;
  }
  return out;
}

/** The duty in the parts it is owed in: certain, owed only if open orders ship late, and the second tranche; each says what it means. Gross is a quiet footnote, never a headline. */
function TariffTiles({ i }: { i: ItemDetail }) {
  const num = (p: string) => (i.numbers ?? []).find((n) => (n.id ?? "").startsWith(p));
  const cond = num("duty_conditional:"), t2 = num("duty_net:tranche2"), gross = num("duty_gross:tranche1");
  const rule = (n?: { value?: unknown }) => { const v = n?.value as V | undefined; return v && !isUnknown(v) ? (v.provenance?.rule ?? "") : ""; };
  return (
    <>
      <Tiles>
        <Tile figure={<Value value={i.at_stake as V} tag={false} />} label="Owed: new duty on China-origin parts entering after the duty date" />
        {cond && <Tile tone="critical" figure={<Value value={cond.value as V} tag={false} />} label="More only if open orders ship late: ask suppliers for ship dates" />}
        {t2 && <Tile figure={<Value value={t2.value as V} tag={false} />} label={humanize(t2.label)} />}
      </Tiles>
      <p className="ds-note">{rule(cond) ? `${humanize(rule(cond))} ` : ""}{gross && isMoney(gross.value as V) ? <>If every open line slipped past the date the total would be <Value value={gross.value as V} tag={false} />.</> : null}</p>
    </>
  );
}

/** A supply disruption in three figures that each mean something else: the money under the notice, the robots it stops, and how many of its lines were already late. */
function DisruptionTiles({ i }: { i: ItemDetail }) {
  const lines = i.po_lines ?? [];
  const inScope = i.lines_in_scope ?? lines.length;
  const late = i.lines_already_late ?? lines.filter((l) => l.days_past_due > 0).length;
  const short = i.robots_short ?? [];
  const monthName = (m: string) => new Date(`${m}-01T00:00:00Z`).toLocaleString("en-US", { month: "long", timeZone: "UTC" });
  const months = [...new Set(short.map((s) => s.month))].sort();      // a shortage is counted in its own month: never summed across months
  return (
    <Tiles>
      <Tile figure={<Value value={i.at_stake as V} tag={false} />} label={i.key.startsWith("risk:") ? `open on the ${inScope} lines with ${i.refs?.find((r) => r.type === "supplier")?.label ?? "the supplier"}` : i.key.startsWith("incident:") ? `open on the ${inScope} lines moved or late` : `open on the ${inScope} lines under the notice`} />
      {months.map((m) => <Tile key={m} tone="critical" figure={<>{short.filter((s) => s.month === m).sort((a, b) => b.robots - a.robots).map((s) => `${s.robots} ${(s.product.label ?? s.product.id).split(" ")[0]}`).join(" + ")} <span className="uom">robots</span></>} label={`short in ${monthName(m)}, before stock on hand`} />)}
      {inScope > 0 && <Tile figure={<>{late} <span className="uom">of {inScope}</span></>} label={`lines already ${PAST_DUE}`} />}
    </Tiles>
  );
}

/** The three figures that matter, as tiles under the decision. The shortage carries a risk dot. */
function KeyTiles({ i }: { i: ItemDetail }) {
  const k = keyNumbers(i).slice(0, 3);
  if (k.length === 0) return null;
  return (
    <Tiles>
      {k.map((n) => <Tile key={n.label} tone={/short/i.test(n.label ?? "") ? "critical" : undefined} figure={<Value value={n.value as V} tag={false} monthOnly={/month/i.test(n.label ?? "")} />} label={humanize(n.label)} />)}
    </Tiles>
  );
}


/** What the page knows of each earlier step. The API names the current stage only, so a time or a name appears only where a run, a draft or a decision records it. */
function stepFacts(run: RunDetail | null, actions: Action[]): Partial<Record<"found" | "worked" | "decision_ready" | "drafted" | "approved" | "sent" | "answered", StepFact>> {
  const f: Partial<Record<"found" | "worked" | "decision_ready" | "drafted" | "approved" | "sent" | "answered", StepFact>> = {};
  if (run?.started_at) { f.worked = { at: run.started_at, by: "Lookout", text: "The agent worked this item." }; f.decision_ready = { at: run.started_at, by: "Lookout", text: "The options were laid out." }; }
  const done = actions.find((a) => a.decided_at && a.state !== "proposed");
  const draft = actions.find((a) => a.proposed_at);
  if (draft) f.drafted = { at: draft.proposed_at, by: "Buyer's clerk", text: "A draft was prepared for its owner.", to: `/approvals/${draft.action_id}` };
  if (done?.decided_at) { f.approved = { at: done.decided_at, by: done.decided_by ?? undefined, text: "Signed by a person." }; if (done.state === "executed") f.sent = { at: done.decided_at, by: "Outbox (simulated)", text: "Left for the supplier (simulated)." }; }
  return f;
}

/** A line of parts or ids is a count and a few names, not a wall: the first words, then how many more. */
function short(t: string): string {
  const max = 80;
  if (t.length <= max) return t;
  const cut = t.slice(0, max).replace(/[,;(\s][^,;(]*$/, "");
  return `${cut}…`;
}

/** What the run achieved, in one or two plain lines from the data: how long, what it drafted or who it needs answers from, where the item stands now, and its checks. */
function RunOutcome({ run, drafts, drafted, notes, added, now, asks }: { run: RunDetail; drafts: string[]; drafted: number; notes: number; added: string | null; now: string | null; asks: string[] }) {
  const r = run as unknown as { checks_passed?: number | null; checks_total?: number | null; reviewer_score?: number | null };
  const took = run.duration_ms ? `Worked in ${Math.round(run.duration_ms / 1000)} s` : "";
  const did = [
    drafted > 0 ? `drafted ${drafted} ${drafted === 1 ? "request" : "requests"}${drafts.length ? ` to ${drafts.slice(0, 3).join(", ")}${drafts.length > 3 ? ` and ${drafts.length - 3} more` : ""}` : ""}` : "",
    notes > 0 ? `logged ${notes} ${notes === 1 ? "question" : "questions"}${asks.length ? ` for ${asks.join(", ")}` : ""}` : "",
    added != null && drafted === 0 ? `added to the waiting request${added ? ` to ${added}` : ""}` : "",
  ].filter(Boolean).join(" · ") || "no draft";
  const checks = [r.checks_total ? `${r.checks_passed ?? 0} of ${r.checks_total} checks passed` : "", r.reviewer_score != null ? `Reviewer ${r.reviewer_score}` : ""].filter(Boolean).join(" · ");
  if (run.status === "failed" || run.status === "did_not_pass") return null;
  return <p className="run-outcome" role="status">{[took, did, now ? `now: ${now}` : "", checks].filter(Boolean).join(" · ")}</p>;
}

/** While the agent works, the top of the main column says what it is doing now: the phase when it is past its last lookup, else the latest step. */
export function LiveLine({ runId }: { runId: string }) {
  const { run, events } = useRun(runId);
  const v = buildRun(events, run?.run_id ?? runId);
  const lines = v.rows.flatMap((r) => (r.kind === "line" ? [r.line] : r.d.lines)).filter((l) => l.status !== "denied");
  const now = lines[lines.length - 1];
  // After the last lookup the trace's own notes (a rewrite to fit the format) mean nothing to a buyer: say what is happening instead.
  const said = now ? humanize(now.text) : "Starting";
  const plain = /rewritten .*to fit the format/i.test(said) ? "Writing up the answer…" : /numbers checked against the data/i.test(said) ? "Checking every number against the data…" : said;
  return <StatusLine text={v.phase ?? plain} />;
}

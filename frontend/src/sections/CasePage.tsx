import { Fragment, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useResource, invalidate } from "../api/useResource";
import type { Action, ItemDetail, RunDetail } from "../api/types";
import { useMe } from "../api/useMe";
import { useAskState } from "../shell/AskContext";
import { RobotIcon, useRobots } from "../components/domain";
import { usePartNames } from "../api/usePartNames";
import { asksOf, replyBy } from "../domain-ui/DraftBlock";
import { DraftFlow } from "./ApprovalsPage";
import { WhatChanges } from "../domain-ui/WhatChanges";
import { RightPanel } from "../ds";
import { AskForChanges } from "./AskForChanges";
import { LandedCostTable } from "../components/domain/LandedCostTable";
import { LiveLine } from "./Item";
import { CaseAskSlot } from "./CaseAsk";
import { Check } from "lucide-react";
import type { MessageDetail } from "../api/types";
import { longDate } from "../ui/format";
import { MailBody } from "./inbox/MailBody";
import "./inbox/inbox.css";
import "./case-page.css";

/** The case page (FINAL 07, r12 on the r7 base, F94-F99): a header with the step track, one card per step, and a plain rail.
 * Steps: Overview · Analysis · Decision · Approval · Sent · Response (a held message: Held · Done). Every figure is code; the agent's
 * words are only its recommended reason, its why per option and its points. Nothing on the page invents a figure or a date. */

const STEPS = ["Overview", "Analysis", "Decision", "Approval", "Sent", "Response"] as const;
const RECORDED = ["Overview", "Analysis", "Decision", "Approval", "Recorded"] as const;
const HELD = ["Overview", "Analysis", "Controls", "Done"] as const;      // a held message (Khalid 2026-10-14): what came in, why it is held, the controls, done
type Step = (typeof STEPS)[number] | (typeof HELD)[number] | "Recorded";

const day = (iso?: string | null) => (iso && /^\d{4}-\d{2}-\d{2}/.test(iso) ? new Date(`${iso.slice(0, 10)}T00:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" }) : "");
const monthName = (ym?: string | null) => (ym ? new Date(`${ym}-01T00:00:00Z`).toLocaleDateString("en-US", { month: "short", timeZone: "UTC" }) : "");
const money = (v?: string | number | null) => { if (v == null || v === "") return ""; const x = Number(v); return x >= 1e6 ? `$${(x / 1e6).toFixed(2)}M` : x >= 1e4 ? `$${Math.round(x / 1e3)}K` : x >= 1e3 ? `$${(x / 1e3).toFixed(1)}K` : `$${x.toLocaleString("en-US", { maximumFractionDigits: 2 })}`; };
const usdOf = (m: unknown) => (m && typeof m === "object" && "usd" in m ? (m as { usd?: string | null }).usd ?? null : null);
const first = (n?: string | null) => (n ?? "").split(" ")[0];
const qty = (v?: string | null) => (v ? Number(v).toLocaleString("en-US") : "—");

type Kind = { kind: string; label: string; leads_to: string; to: string; button: string; changes?: string | null; also_start?: boolean | null; also_why?: string | null };
type Fire = { kind: string; label: string; earliest?: { date: string } | null; earliest_basis?: string | null; cost_delta?: unknown; duty_effect?: unknown; decided_by?: { what?: string } | null };
type Opt = { raised?: boolean; kind: string; title: string; short: string; change: string; time: string; basis: string; cost: string; next: string; leads: string; why: string; alsoWhy: string };
type Rec = { recommended?: { kind: string; reason: string } | null; options?: { kind: string; why: string }[]; points?: { label: string; text: string }[] } | null;

const NEXT: Record<string, string> = { request: "Email", note: "Note", record: "Record", order: "Order", po_change: "PO change" };

/** The options for this case: the code table's kinds, the fire's computed fields where they exist, and Lookout's why per kind. */
function useOptions(i: ItemDetail): Opt[] {
  const { me } = useMe();
  const q = me ? `?owner=${encodeURIComponent(me)}` : "";      // the viewer's own routes and figures (her quote, her share), never the team total (certification 15)
  const kinds = useResource(() => fetch(`/api/action-items/${encodeURIComponent(i.key)}/option-kinds${q}`).then((r) => (r.ok ? r.json() : [])).catch(() => []) as Promise<Kind[]>, [i.key, q]);
  const fire = useResource(() => (i.group !== "trust" ? fetch(`/api/action-items/${encodeURIComponent(i.key)}/options${q}`).then((r) => (r.ok ? r.json() : [])).catch(() => []) : Promise.resolve([])) as Promise<Fire[]>, [i.key, q]);      // every kind's computed routes (AGENT-F f274c4e); a trust case has none
  const rec = i.recommendation as Rec;
  return useMemo(() => {
    const why = new Map((rec?.options ?? []).map((o) => [o.kind, o.why]));
    const f = new Map((fire.data ?? []).map((o) => [o.kind, o]));
    const out = (kinds.data ?? []).map((k): Opt => {
      const x = f.get(k.kind);
      const y = x as (typeof x & { covers?: string | null; cost?: unknown; cost_basis?: string | null }) | undefined;
      const cost = usdOf(y?.cost) ?? usdOf(x?.cost_delta), duty = usdOf(x?.duty_effect);
      const costBasis = (y?.cost_basis ?? "").replace(/\s*\[[^\]]*\]/g, "").trim();      // the route's own words for its figure, the cited ids left off
      return {
        kind: k.kind, title: k.label, short: k.label,      // Continue names the row exactly as the row reads (UX 07 #3)
        change: y?.covers ?? k.changes ?? "",      // code's "what it changes" only (the agent's per-route why is never filled: dropped, WORK-F 11:25)
        time: x?.earliest?.date ? day(x.earliest.date) : "", basis: x?.earliest_basis ?? "",
        cost: cost ? `${Number(cost) < 0 ? `saves ${money(-Number(cost))}` : money(cost)}${costBasis && costBasis !== "not in the records" ? ` · ${costBasis}` : ""}` : duty ? `up to ${money(duty)} duty if it lands late` : "",
        next: `${NEXT[k.leads_to] ?? "Note"}${k.to ? ` → ${k.to}` : ""}`, leads: k.leads_to, why: why.get(k.kind) ?? "", alsoWhy: k.also_start ? k.also_why ?? "" : "",
      };
    });
    const top = rec?.recommended?.kind;      // the recommended one first; the rest in the code table's order (Rule B)
    return top ? [...out.filter((o) => o.kind === top), ...out.filter((o) => o.kind !== top)] : out;
  }, [kinds.data, fire.data, rec]);
}

/** Which step the case is on: from the run, the ledger and the buyer's choice (kept for this tab until a choice ledger lands). */
function stepOf(i: ItemDetail, started: string | null, chosen: string | null, drafts: Action[], trustDone = false, again = false, routes = 0): Step {
  if (i.group === "trust") return trustDone ? "Done" : "Controls";
  if (again) return chosen ? "Approval" : "Decision";      // R1: after a reply that leaves the case short, the buyer decides the next way through
  const k = i.stage?.key;      // the stage is the ledger's word for the case: a note logged by the morning run is not an approval (LOOKOUT #72, UX S6)
  void drafts;
  if (k === "answered") return "Response";
  if (k === "approved" && i.stage?.label === "Recorded") return "Recorded";      // a note or decision signed on the case: nothing was sent
  if (k === "sent" || k === "approved") return "Sent";
  if (started) return "Analysis";
  if (!i.recommendation) return chosen ? "Approval" : routes > 0 ? "Decision" : "Overview";      // the buyer decides; the routes are code's, so a case with no run still reaches Decision (its Analysis offers the run)
  return chosen ? "Approval" : "Decision";
}

export function CaseView({ i, actions, run, runId, started, onStart, onRunLive, busy, startErr }: {
  i: ItemDetail; actions: Action[]; run: RunDetail | null; runId: string | null; started: string | null; onStart: () => void; onRunLive?: () => void; busy: boolean; startErr?: string | null;
}) {
  const live = useResource(api.health).data?.agent_live === true;      // "Run live" only where a model is connected (hybrid: recorded cases replay unless asked)
  const { me } = useMe();
  const ask = useAskState();
  const boot = useResource(api.health).data?.boot ?? "";
  const waitingDraft = actions.find((a) => a.action_id === i.stage?.action?.id && a.state === "proposed") ?? actions.find((a) => a.state === "proposed");      // the draft the stage names first (IMPL-F 4892a7a)
  // The choice is kept only for this case, this server run and this draft: a demo reset (a restart) or a changed draft drops it, and another case never sees it.
  const store = `lookout.chosen.${i.key}.${boot}`;      // the choice lasts for this case and this server run; a draft the choice itself creates must not drop it (the ledger records it too: chosen_route)
  const [params] = useSearchParams();
  const fromAsk = params.get("draft");      // "Prepared: email to … · Review →" in the Ask panel opens this case at its Approval card with that draft
  const [chosen, setChosen] = useState<string | null>(fromAsk ? `draft:${fromAsk}` : null);
  useEffect(() => { if (fromAsk) { setChosen(`draft:${fromAsk}`); return; } if (!boot) return; try { setChosen(sessionStorage.getItem(store)); } catch { /* none kept */ } }, [fromAsk, store, boot]);
  const choose = (k: string | null) => { setChosen(k); try { if (k) sessionStorage.setItem(store, k); else sessionStorage.removeItem(store); } catch { /* the choice lasts for this view */ } };
  const drafts = actions;      // this case's own drafts (B4)
  const options = useOptions(i);
  // A case the agent already drafted for opens at Approval on the route the draft serves (Khalid 2026-10-14): the draft's own option kind, else the request route it was written for.
  const recKind = (i.recommendation as Rec)?.recommended?.kind;
  // A draft made in Ask on this case (Khalid 14:30): waiting, serving no route, and made by a run other than the case's own (or a turn of this Ask thread). It is her own option, not a route's draft.
  const caseRun = (i.latest_run as { run_id?: string } | null)?.run_id ?? null;
  const threadRuns = new Set(ask.thread.map((t) => t.runId));
  const askMade = (a: Action) => { const x = a as Action & { change?: { option_kind?: string } | null; chosen_route?: string | null; run_id?: string | null };
    return a.state === "proposed" && !x.change?.option_kind && !x.chosen_route && !!x.run_id && (threadRuns.has(x.run_id) || x.run_id !== caseRun); };
  // (a) an Ask-made draft to a route's own recipient is that route's draft: an email by the route's supplier, a note by the route's addressee
  const toOf = (o: Opt) => o.next.replace(/^[^→]*→\s*/, "");
  const askRoute = (a: Action): string | null => {
    const sup = a.target?.label ?? "", to = ((a.change ?? {}) as { to?: string | null }).to ?? "";
    const local = (a.recipient ?? "").split("@")[0].toLowerCase();
    const isContact = (o: Opt) => { const name = toOf(o).replace(/\s*\(.*\)\s*$/, "").toLowerCase().split(/\s+/).filter(Boolean); return name.length > 0 && name.every((w) => local.includes(w)); };      // the route's contact on file is the email's addressee
    const m = a.type === "supplier_request" ? options.filter((o) => o.leads === "request" && (isContact(o) || (!!sup && toOf(o).includes(sup)))) : options.filter((o) => o.leads === "note" && !!to && toOf(o) === to);
    return (m.find((o) => o.kind === recKind) ?? m[0])?.kind ?? null;
  };
  const askMap: Record<string, string> = Object.fromEntries(actions.filter(askMade).map((a) => [a.action_id, askRoute(a)]).filter(([, k]) => k) as [string, string][]);
  const yourOptions: Opt[] = actions.filter((a) => askMade(a) && !askMap[a.action_id]).map((a) => { const c = (a.change ?? {}) as { to?: string | null };
    return { kind: `draft:${a.action_id}`, title: "Your option, worked out with Lookout", short: a.subject ?? "your option", change: (a.body ?? "").split("\n").map((l) => l.trim()).find((l) => l && !/,$/.test(l)) ?? a.subject ?? "",      // its first line that says something (a greeting is skipped)
      time: "", basis: "", cost: "", next: a.type === "supplier_request" ? `Email → ${a.recipient ?? a.target?.label ?? ""}` : `Note → ${c.to ?? "the case"}`, leads: "draft", why: "", alsoWhy: "", subject: a.subject ?? "" } as Opt; });
  // Khalid 14:45: the routes are arranged by the discussion. A route is raised when a supplier or part the Ask answers named (their entities) is in its words, or an Ask draft went to its contact.
  const askHere = ask.context?.type === "item" && ask.context.id === i.key ? ask.thread : [];
  const askRuns = useResource(() => Promise.all(askHere.map((t) => api.run(t.runId).catch(() => null))), [askHere.map((t) => t.runId).join(",")]);
  const named = new Set<string>();
  for (const r of askRuns.data ?? []) { const rc = (r?.recommendation ?? null) as { answer_entities?: { type?: string; ref?: string; label?: string | null; text?: string }[] | null; recommendation_entities?: { type?: string; ref?: string; label?: string | null; text?: string }[] | null } | null;
    for (const e of [...(rc?.answer_entities ?? []), ...(rc?.recommendation_entities ?? [])]) if (e.type === "supplier" || e.type === "part") [e.ref, e.text, e.label].forEach((x) => x && x.length > 2 && named.add(x)); }
  const said = (askRuns.data ?? []).map((r) => { const rc = (r?.recommendation ?? null) as { finding?: string | null; points?: unknown[] | null } | null; return `${rc?.finding ?? ""} ${JSON.stringify(rc?.points ?? [])}`; }).join(" ").toLowerCase();      // what Lookout said in the discussion
  const COMMON = new Set(["before", "request", "supplier", "normal", "quantity", "accept", "revised", "delayed", "builds", "prepayment"]);
  const spoken = (o: Opt) => !!said && o.title.toLowerCase().split(/[^a-z-]+/).some((w) => w.length >= 6 && !COMMON.has(w) && said.includes(w));      // the route's own distinctive word ("cutoff", "freight", "Motion") in the answer
  const askMapped = new Set(Object.values(askMap));
  const raisedBy = (o: Opt) => askMapped.has(o.kind) || spoken(o) || [...named].some((n) => `${o.title} ${o.next} ${o.change}`.includes(n));
  const arranged: Opt[] = askHere.length || askMapped.size ? [...options.filter(raisedBy).map((o) => ({ ...o, raised: true })), ...options.filter((o) => !raisedBy(o))] : options;      // no discussion: the table exactly as code orders it
  const routeOf = (d?: Action) => (d && askMade(d) ? null : d ? (d as Action & { change?: { option_kind?: string } | null }).change?.option_kind ?? (d.type === "supplier_request" ? (options.find((o) => o.kind === recKind && o.leads === "request") ?? options.find((o) => o.leads === "request"))?.kind : undefined) ?? null : null);
  const drafted = waitingDraft ? routeOf(waitingDraft) : null;
  const sentRoute = routeOf(actions.find((a) => a.type === "supplier_request" && (a.state === "executed" || a.state === "approved")));      // after signing, the route is the one the sent email served
  // "Also start": routes the buyer starts beside the chosen one; each becomes its own draft or note for her signature. Kept for this tab, like the choice.
  const alsoKey = `lookout.also.${i.key}.${boot}`;
  const [also, setAlsoList] = useState<string[]>([]);
  useEffect(() => { try { setAlsoList(JSON.parse(sessionStorage.getItem(alsoKey) ?? "[]")); } catch { /* none */ } }, [alsoKey]);
  const [alsoErr, setAlsoErr] = useState<string | null>(null);
  // A team roll-up (more than one owner) opened by one of them: when the viewer's own list holds a case of the same group on the same supplier or part, that is their part (AI-UI-SYNC 11:58); Continue waits there.
  const yours = useResource(() => ((i.owner ?? "").includes(" · ") && me ? api.actionItems(me).catch(() => []) : Promise.resolve([])), [i.key, me]);
  const team = useResource(() => ((i.owner ?? "").includes(" · ") ? api.actionItems().catch(() => []) : Promise.resolve([])), [i.key]);
  // a slice of THIS case: a per-owner key (never on the team list) of the same group, naming only records this case names, in the kinds of record this case names
  const kindsNamed = new Set((i.refs ?? []).map((r) => r.type).filter((t) => ["supplier", "part", "po_line"].includes(t)));
  const refIds = new Set((i.refs ?? []).filter((r) => kindsNamed.has(r.type)).map((r) => r.id));
  const teamKeys = new Set((team.data ?? []).map((x) => x.key));
  const slice = (yours.data ?? []).find((x) => { const own = (x.refs ?? []).filter((r) => kindsNamed.has(r.type)); return x.key !== i.key && !teamKeys.has(x.key) && x.group === i.group && own.length > 0 && own.every((r) => refIds.has(r.id)); });
  // Khalid 11:35: when the buyer picks a route, the agent drafts what it needs. One function: AGENT-F's choose endpoint returns the prepared draft or a new one;
  // until it is served (404/405) the page falls back to the drafts already on the case, matched to this route only.
  const [routeDraft, setRouteDraft] = useState<string | null>(null);
  // One function for every choice (Khalid 11:35, FINAL-SPEC §2): AGENT-F's choose records it and returns the route's draft (prepared, drafted, amended or covered).
  // Until it is served (404/405) the page falls back to the case's own drafts, for that route only; once it answers, there is no fallback.
  const [alsoIds, setAlsoIds] = useState<Record<string, string>>({});
  const callChoose = async (k: string, reason?: string) => {
    const r = await fetch(`/api/action-items/${encodeURIComponent(i.key)}/routes/${encodeURIComponent(k)}/choose`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ by: me, ...(reason ? { reason } : {}) }) });
    if (r.status === 404 || r.status === 405) throw new Error("Choosing a route is not served by this build");
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? "Could not prepare it");
    const a = (await r.json().catch(() => null)) as { action_id?: string } | null;
    invalidate();
    return a?.action_id ?? null;
  };
  const chooseRoute = (k: string) => {
    setAlsoErr(null);
    if (k.startsWith("draft:")) { setReopened(false); choose(k); return; }      // her own option is already a draft: no choose call
    if (options.find((o) => o.kind === k)?.leads === "record") { setRouteDraft(null); choose(k); return; }      // a decision needs the buyer's reason: Approval asks for it, then chooses with it
    callChoose(k).then((id) => { setRouteDraft(id); setReopened(false); choose(k); }).catch((e: Error) => setAlsoErr(e.message));
  };
  const setAlso = (k: string, on: boolean) => {
    const next = on ? [...new Set([...also, k])] : also.filter((x) => x !== k); setAlsoList(next); try { sessionStorage.setItem(alsoKey, JSON.stringify(next)); } catch { /* this view */ }
    const o = options.find((x) => x.kind === k);      // Khalid 11:08 #1 (I-2): a ticked route is chosen too, so its own draft is made for its own signature
    if (!on || !o || !me || !(o.leads === "note" || o.leads === "request" || (o.leads === "record" && o.alsoWhy))) return;
    setAlsoErr(null);
    callChoose(k, o.leads === "record" ? o.alsoWhy : undefined).then((id) => { if (id) setAlsoIds((m) => ({ ...m, [k]: id })); }).catch((e: Error) => setAlsoErr(e.message));
  };

  type Ch = Action & { chosen?: boolean | null; chosen_route?: string | null; chosen_at?: string | null };
  const ledgerChosen = (actions as Ch[]).filter((a) => a.chosen && a.chosen_route && a.state === "proposed" && !also.includes(a.chosen_route));      // a route ticked as Also start is not her pick      // STATE #1: the choice lives in the ledger, so a reload or a return keeps it
  const ledgerPick = (ledgerChosen.find((a) => a.chosen_route === recKind) ?? ledgerChosen.slice().sort((a, b) => (b.chosen_at ?? "").localeCompare(a.chosen_at ?? ""))[0])?.chosen_route ?? null;
  const [reopened, setReopened] = useState(false);
  const [lastPick, setLastPick] = useState<string | null>(null);      // her pick, kept for "← Decision"      // "← Decision" shows the routes again, her pick selected, until she continues
  const [again, setAgain] = useState(false);
  const picked = again ? chosen : chosen ?? (reopened ? null : ledgerPick) ?? sentRoute;      // a drafted case opens at Decision with its draft's route tagged (Khalid 10:33, BUYER-F); the buyer reviews it from there
  const heldMsg = useResource(() => (i.group === "trust" && (i.messages ?? [])[0] ? api.thread((i.messages ?? [])[0].ref.id).catch(() => null) : Promise.resolve(null)), [i.key]);
  const held = useTicks(i, actions, i.group === "trust" && heldMsg.data ? controlsFor((heldMsg.data as { summary?: { trust_flags?: string[] } }).summary?.trust_flags ?? []) : []);
  const step = stepOf(i, started, picked, drafts, held.all, again, options.length);
  const steps: readonly Step[] = i.group === "trust" ? HELD : step === "Recorded" ? RECORDED : STEPS;
  const at = steps.indexOf(step);
  // r5: one step on screen at a time. It is the case's own step unless the buyer opened a done step from the step line ("Back to …" returns).
  const [view, setView] = useState<Step>(step);
  useEffect(() => { setView(step); window.scrollTo({ top: 0 }); }, [step]);
  const reading: Step = steps.includes(view) && steps.indexOf(view) <= at ? view : step;
  const mine = !!me && (i.owner ?? "").split(" · ").includes(me);
  const state = step === "Controls" ? "Held" : started ? "Lookout working…" : (mine && (step === "Response" || !["Sent", "Recorded"].includes(step))) ? "On you" : "";
  const top = useRef<HTMLDivElement>(null);
  const hd = useRef<HTMLElement>(null);
  useEffect(() => {      // the rail sticks under the header: the header's own height, measured
    const h = hd.current; if (!h || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => top.current?.style.setProperty("--cp-hd", `${h.offsetHeight}px`)); ro.observe(h); return () => ro.disconnect();
  }, []);
  const go = (s: Step) => { setView(s); window.scrollTo({ top: 0 }); };
  const chosenTitle = options.find((o) => o.kind === picked)?.short;

  const head = (
    <header className="cp-head" ref={hd}>
      <div className="cp-crumb"><Link to="/">Today</Link> › {kindOf(i)}</div>
      <h1 title={i.title}>{i.title}</h1>
      <Stakes i={i} />
      <nav className="cp-steps" aria-label="Steps">
        {steps.map((s, n) => {
          const done = n < at, cur = n === at;
          return <Fragment key={s}>{n > 0 && <i className="ln" aria-hidden />}
            <button type="button" disabled={n > at} aria-current={s === reading ? "step" : undefined} className={`${done ? "done" : ""}${cur ? " cur" : ""}${s === reading ? " on" : ""}`} onClick={() => go(s)}>
              <span className="nb">{done ? <Check size={12} strokeWidth={3} aria-hidden /> : n + 1}</span>{s}{done && s === "Decision" && chosenTitle && <span className="sub"> · {chosenTitle}</span>}
            </button></Fragment>;
        })}
      </nav>
    </header>
  );

  const body = (s: Step, readOnly: boolean): ReactNode => {
    switch (s) {
      case "Overview": return <Overview i={i} drafts={drafts} />;
      case "Analysis": return i.group === "trust" ? <HeldWhy i={i} /> : started && !readOnly ? <Sec title="Lookout working"><LiveLine runId={started} /></Sec> : <Analysis i={i} run={run} onRun={onStart} busy={busy} />;
      case "Decision": return <Decision i={i} options={[...arranged, ...yourOptions]} askMap={askMap} drafts={drafts} mine={mine} readOnly={readOnly} chosen={picked ?? (reopened ? lastPick ?? ledgerPick : null)} drafted={drafted} also={also} alsoIds={alsoIds} onAlso={setAlso} onContinue={chooseRoute} slice={slice ? { key: slice.key, title: slice.title } : null} live={live} onAsk={() => ask.openWith("Another way through this case: ")} />;
      case "Approval": return <Approval i={i} drafts={drafts} options={options} chosen={picked} mine={mine} live={live} also={also} alsoIds={alsoIds} recommended={recKind ?? null} routeDraft={routeDraft} onBack={() => { setLastPick(picked); choose(null); setReopened(true); go("Decision"); }} onOpen={(k) => choose(k)} onAsk={(t) => ask.openWith(t)} />;
      case "Sent": return <Sent i={i} drafts={drafts} options={options} chosen={picked} />;
      case "Response": return <Response i={i} drafts={drafts} mine={mine} onAgain={() => { choose(null); setAgain(true); }} />;
      case "Controls": return <Controls i={i} held={held} readOnly={readOnly} />;
      case "Done": return <p className="cp-line"><b>{held.controls.length} of {held.controls.length} controls on record</b>{usdOf(i.at_stake) ? ` · ${money(usdOf(i.at_stake))} claimed · $0 paid` : ""}</p>;
      case "Recorded": return <p className="cp-line">{i.stage?.next_act}</p>;
      default: return null;
    }
  };
  const current = reading === step;
  return (
    <div className="cp" ref={top}>
      {head}
      <div className={`cp-cols${ask.open ? " ask-open" : ""}`}>      {/* the Ask panel takes the rail's place (UX ask-panel.md) */}
        <div className="cp-stack">
          <section key={reading} id={`step-${reading}`} className="cp-card" aria-label={reading}>
            <div className="cp-ch"><h2>{reading}</h2><span className="cp-chr">{current && state && <span className={`cp-cs${state === "On you" ? " on" : state === "Held" ? " red" : ""}`}>{state}</span>}<button type="button" className="cp-link" title={`Ask Lookout about the ${reading} of this case`} onClick={() => ask.openWith(`On the ${reading} of this case: `)}>Ask about {reading.toLowerCase()}</button></span></div>
            {reading === "Decision" && current && ask.thread.length > 0 && ask.context?.type === "item" && ask.context.id === i.key && <Discussion runId={ask.thread[ask.thread.length - 1].runId} onShow={() => ask.setOpen(true)} />}
            {(reading === "Decision" || reading === "Approval") && alsoErr && <p className="cp-line h" role="alert">{alsoErr}</p>}
            {body(reading, !current)}
            {current && reading === "Overview" && i.group !== "trust" && <div className="cp-foot">{startErr ? <span className="pp red" role="alert">{startErr}</span> : <span className="pp">Not reviewed yet</span>}<button type="button" className="b9 dark" disabled={busy} onClick={onStart}>Review</button></div>}
            {current && startErr && reading !== "Overview" && <p className="cp-line h" role="alert">{startErr}</p>}
            {!current && <div className="cp-foot end"><button type="button" className="b9 dark" onClick={() => go(step)}>Back to {step} →</button></div>}
          </section>
        </div>
        {ask.open ? <CaseAskSlot about={reading} /> : <Rail i={i} run={run} runId={runId} drafts={drafts} onRunLive={live && onRunLive && i.group !== "trust" ? onRunLive : undefined} busy={busy || !!started} />}
      </div>
    </div>
  );
}

/** The latest Ask answer on this case, one line above the routes: the options are presented with the discussion (Khalid 14:30). */
function Discussion({ runId, onShow }: { runId: string; onShow: () => void }) {
  const r = useResource(() => api.run(runId).catch(() => null), [runId]);
  const f = ((r.data?.recommendation ?? null) as { finding?: string | null } | null)?.finding ?? "";
  const line = f.split(/(?<=[.!?])\s/)[0];
  if (!line) return null;
  return <p className="cp-line cp-disc"><span className="cp-lbl">From your discussion</span> {line} · <button type="button" className="cp-link" onClick={onShow}>Show</button></p>;
}

/** The header's one line of stakes (r5): robots short per month (first two months, "up to" when stock is not on file), the money and lines, act by, the supplier, the owner. Never repeated below. */
function Stakes({ i }: { i: ItemDetail }) {
  const robots = useRobots();
  const { me } = useMe();
  const rs = i.robots_short ?? [];
  const months = [...new Set(rs.map((r) => r.month))].sort();      // every month the case is short (certification 15: a case short in three months)
  const lit = robots.filter((r) => rs.some((x) => x.product.id === r.id) || (i.robots ?? []).some((x) => x.id === r.id));
  const noStock = (i.unknowns ?? []).some((u) => /stock/i.test(u.what ?? ""));
  const sup = (i.refs ?? []).find((r) => r.type === "supplier");
    const exp = usdOf(i.at_stake);
  const parts: ReactNode[] = [];
  if (months.length) parts.push(<span key="r" className="sk-r">{lit.map((r) => <span key={r.id} className={`cp-ri r-${(r.slot % 3) + 1}`} title={r.name}><RobotIcon slot={r.slot} /></span>)}<span className="lb">Short</span>
    {months.map((m) => <span key={m} className="mo">{monthName(m)} {robots.map((r) => ({ r, n: rs.filter((x) => x.month === m && x.product.id === r.id).reduce((a, x) => a + x.robots, 0) })).filter((x) => x.n > 0).map((x, k) => <span key={x.r.id}>{k > 0 && " · "}<b>{x.n}</b> {first(x.r.name)}</span>)}</span>)}
    {noStock && <span className="q">(up to: stock on hand is not in the data)</span>}</span>);
  const figs = months.length ? [] : stakeFigures(i, me);
  parts.push(...figs.map(([l, t]) => <span key={l}><small>{l}</small> <b>{t}</b></span>));
  if (exp && (months.length || !figs.some(([, t]) => t === money(exp) || t.includes(`of ${money(exp)}`)))) parts.push(i.group === "trust" ? <span key="e"><b>{money(exp)}</b> claimed · <b>$0</b> paid</span> : <span key="e"><b>{money(exp)}</b>{i.lines_in_scope ? ` on ${i.lines_in_scope} PO lines` : ""}</span>);
  if (i.act_by) parts.push(<span key="a">Act by <b>{day(i.act_by)}</b></span>);
  const sups = (i.refs ?? []).filter((r) => r.type === "supplier");
  if (sups.length > 1) parts.push(<span key="s" title={sups.map((x) => nameOf(i, x)).join(", ")}>{sups.length} suppliers</span>);
  else if (sup) parts.push(<Link key="s" to={`/suppliers/${encodeURIComponent(sup.id)}`} title={sup.label ?? ""}>{nameOf(i, sup)}</Link>);
  if (i.owner) parts.push(<span key="o">Owner: {i.owner}</span>);
  return <div className="cp-meta">{parts.map((p, n) => <Fragment key={n}>{n > 0 && <i className="dot">·</i>}{p}</Fragment>)}</div>;
}

/** The case's kind in the buyer's words, from its key (the group is the list's grouping, not the kind). */
function kindOf(i: ItemDetail): string {
  const k = i.key;
  if (i.group === "trust") return "Trust";
  if (k.startsWith("risk:")) return "Supplier risk";
  if (k.startsWith("tariff:")) return "Import duty";
  if (k === "deadline:chase") return "Past due";
  if (k.startsWith("deadline:")) return "Deadline";
  if (k.startsWith("unknown:")) return "Unknowns";
  if (k.startsWith("incident:")) return "Incident";
  if (k.startsWith("consignment:")) return "Consignment";
  return "Disruption";
}

/** Where the case came from (atlas: four source kinds). Overview shows that source as received; nothing on it is the agent's reading. */
type Shape = "message" | "records" | "notice" | "gap" | "none";
function shapeOf(i: ItemDetail): Shape {      // from the data, never the case key: the detector's group, then the kind of message the case carries
  if (i.group === "tariff") return "notice";
  if (i.group === "unknown") return "gap";
  if (i.group === "trust") return "message";
  if (eventMessage(i)) return "message";      // a supplier wrote: a notice, a slip, a closure, a price change
  return (i.po_lines ?? []).length || (i.messages ?? []).length ? "records" : "none";      // else the case is a pattern in the records (lines, history, a quote on file)
}
const kindOfMsg = (m: { kind?: string | null }) => m.kind ?? "";
/** The message the case was made from: the one its lines name as their cause, else the first that is not a quote (a quote is a record on file, not an event). */
function eventMessage(i: ItemDetail) {
  const ms = (i.messages ?? []) as (NonNullable<ItemDetail["messages"]>[number] & { kind?: string | null })[];
  const cause = new Set(((i.po_lines ?? []) as { disrupted_by?: { id?: string } | null }[]).map((l) => l.disrupted_by?.id).filter(Boolean));
  return ms.find((m) => cause.has(m.ref.id)) ?? ms.find((m) => kindOfMsg(m) !== "quote");
}
type Line = NonNullable<ItemDetail["po_lines"]>[number] & { promise_date?: string | null; revised_date?: string | null; days_past_due?: number | null; qty?: { value?: string } | null; disrupted_by?: { id?: string } | null };
const linesOf = (i: ItemDetail) => ((i.po_lines ?? []) as Line[]).slice().sort((a, b) => (a.promise_date ?? "9").localeCompare(b.promise_date ?? "9"));
function Overview({ i, drafts }: { i: ItemDetail; drafts: Action[] }) {
  const asked = useAsked(i, drafts);
  const shape = shapeOf(i);
  if (shape === "message") { const m = eventMessage(i) ?? (i.messages ?? [])[0]; return <>{m && <AsReceived id={m.ref.id} />}<LinesTable i={i} asked={asked} title={`The ${linesOf(i).length} PO lines it names, on file`} /></>; }
  if (shape === "records") return <Records i={i} asked={asked} />;
  if (shape === "notice") return <Notice i={i} />;
  if (shape === "gap") return <Gap i={i} asked={asked} />;
  return <Situation i={i} />;
}

/** A message as received: its headers (the sender checked against the contact on file), then the body exactly as written, its tables kept, the lines the case rests on marked. */
function AsReceived({ id, folded }: { id: string; folded?: boolean }) {
  const d = useResource(() => api.thread(id).catch(() => null), [id]);
  const [open, setOpen] = useState(!folded);
  const t = d.data as (MessageDetail & { from_email?: string | null }) | null;
  if (!t) return <div className="cp-msg"><span className="skel" style={{ width: 320 }} /></div>;
  const flags = t.summary.trust_flags ?? [];
  const from = t.from_email ?? (t.summary as { from_email?: string | null }).from_email ?? "";
  const rows: [string, ReactNode, string?][] = [
    ["From", <><b>{t.summary.from}</b>{from ? ` <${from}>` : ""}{t.summary.company && t.summary.company !== "not on file" ? ` · ${t.summary.company}` : ""}{t.summary.trust === "on_file" && <span className="ok"> ✓ the contact on file</span>}</>, flags.includes("sender_domain_lookalike") ? "red" : undefined],
    ["Reply-to", t.reply_to, flags.some((f) => f.startsWith("reply_to")) ? "red" : undefined],
    ["To", t.to], ["Date", longDate(t.summary.date)], ["Subject", <b key="s">{t.subject}</b>],
  ];
  return (
    <div className="cp-msg">
      <dl className="cp-hdrs">{rows.filter(([, v]) => v).map(([k, v, tone]) => <div key={k}><dt>{k}</dt><dd data-tone={tone}>{v}</dd></div>)}</dl>
      {open ? <MailBody body={t.body ?? ""} highlights={[...(t.highlights ?? []), ...(flags.includes("bank_detail_change") ? (t.body ?? "").split("\n").filter((l) => /^\s*(Beneficiary|Bank|Account|IBAN|SWIFT)\b/i.test(l)).map((l) => l.trim()) : [])]} entities={t.entities} suspect={t.summary.trust !== "on_file"} />
        : <button type="button" className="cp-link" onClick={() => setOpen(true)}>The message, as received ›</button>}
    </div>
  );
}

/** Which draft asks about each PO line or part (AI-UI-SYNC M11, M14): read from the drafts' own entities (the case's drafts and the ones its run lists as done), so a multi-row case never claims a row nobody asked about. */
function useAsked(i: ItemDetail, drafts: Action[]) {
  const done = (((i.recommendation as { done?: { action_id?: string | null }[] } | null)?.done) ?? []).map((d) => d.action_id ?? "").filter((id) => id && !drafts.some((a) => a.action_id === id));
  const more = useResource(() => Promise.all(done.map((id) => api.action(id).catch(() => null))), [done.join(",")]);
  return useMemo(() => {
    const m = new Map<string, Action[]>();
    const all = [...drafts, ...((more.data ?? []).filter(Boolean) as Action[])].filter((a) => a.type === "supplier_request" && a.state !== "rejected");
    for (const a of all) {
      const ents = [...((a as { body_entities?: { type: string; ref: string }[] }).body_entities ?? []), ...((a as { subject_entities?: { type: string; ref: string }[] }).subject_entities ?? [])];
      for (const e of ents) if (e.type === "po_line" || e.type === "part") { const l = m.get(e.ref) ?? []; if (!l.includes(a)) l.push(a); m.set(e.ref, l); }
    }
    return { any: all.length > 0, of: (id: string) => m.get(id) ?? [] };
  }, [drafts, more.data]);
}
function AskedCell({ asked, id }: { asked: ReturnType<typeof useAsked>; id: string }) {
  const a = asked.of(id);
  return <td>{a.length ? a.map((x, n) => <Fragment key={x.action_id}>{n > 0 && ", "}<Link to={`/approvals/${x.action_id}`}>{x.target?.label ?? x.recipient}</Link></Fragment>) : <span className="no">not asked</span>}</td>;
}

/** The case's open PO lines as the records hold them: PO line · Part · Open qty · Promised · how late. Worst first is the promise order; 4 rows, then the rest in place. */
function LinesTable({ i, title, asked }: { i: ItemDetail; title: string; asked?: ReturnType<typeof useAsked> }) {
  const names = usePartNames();
  const [all, setAll] = useState(false);
  const lines = linesOf(i);
  if (!lines.length) return null;
  const shown = all ? lines : lines.slice(0, 4);
  return (
    <Sec title={title}>
      <table className="cp-t"><thead><tr><th>PO line</th><th>Part</th><th className="n">Open qty, EA</th><th>Promised</th><th />{asked?.any && <th>Asked in</th>}</tr></thead>
        <tbody>{shown.map((l) => <tr key={l.ref.id}><td><Link to={`/orders?q=${encodeURIComponent(l.ref.id)}`}>{l.ref.id}</Link></td><td>{l.part.id} {partName(i, l.part.id, names)}</td><td className="n">{qty(l.qty?.value)}</td>
          <td>{day(l.revised_date ?? l.promise_date)}</td><td className="late">{l.days_past_due ? `${l.days_past_due} d late` : ""}</td>{asked?.any && <AskedCell asked={asked} id={l.ref.id} />}</tr>)}</tbody></table>
      {lines.length > 4 && <button type="button" className="cp-link more" onClick={() => setAll(!all)}>{all ? "Show fewer" : `+ ${lines.length - 4} more lines`}</button>}
    </Sec>
  );
}
const cap = (s?: string | null) => (s ? s.replace(/^\w/, (c) => c.toUpperCase()) : "");
/** A part as the case names it (its ref label keeps the item master's case: "Motor, BLDC"), else the part list's name. */
const partName = (i: ItemDetail, id: string, names: (p: string) => string | null | undefined) => (i.refs ?? []).find((r) => r.type === "part" && r.id === id)?.label?.trim() || cap(names(id));

/** A pattern in the records: the quote on file (folded to its headers), the open lines, and the part's closed lines newest first (promised vs received, from the PO file). */
function Records({ i, asked }: { i: ItemDetail; asked: ReturnType<typeof useAsked> }) {
  const quote = (i.messages ?? []).find((m) => (m as { kind?: string | null }).kind === "quote") ?? (i.messages ?? [])[0];
  const part = ((i.numbers ?? []) as Num[]).find((n) => n.id.startsWith("risk_need:"))?.id.slice(10);
  const sup = (i.refs ?? []).find((r) => r.type === "supplier");
  const news = useResource(async () => {      // the supplier's news on file, as published
    const d = sup ? await api.supplier(sup.id).catch(() => null) : null;
    const ids = ((d as { news?: { id: string }[] } | null)?.news ?? []).map((n) => n.id);
    return (await Promise.all(ids.map((id) => fetch(`/api/sources/news/${encodeURIComponent(id)}`).then((r) => (r.ok ? r.json() : null)).catch(() => null)))).filter(Boolean) as Source[];
  }, [sup?.id]);
  return <>{quote && <AsReceived id={quote.ref.id} folded />}{(news.data ?? []).map((x) => <SourceView key={x.id} src={x} />)}<LinesTable i={i} asked={asked} title="Open lines, on file" />{part && <ClosedLines part={part} />}</>;
}
function ClosedLines({ part }: { part: string }) {
  const names = usePartNames();
  const [all, setAll] = useState(false);
  const d = useResource(async () => {
    const p = await api.partDetail(part).catch(() => null);
    const ids = ((p as { lead_time_actual?: { lines?: { id: string }[] } | null } | null)?.lead_time_actual?.lines ?? []).map((l) => l.id);
    const rows = await Promise.all(ids.map((id) => api.order(id).catch(() => null)));
    return rows.filter(Boolean).map((o) => { const r = (o as { raw?: Record<string, string> }).raw ?? {}; return { id: id(o), qty: r.qty_received ?? r.qty, promised: r.promised_date, received: r.received_date }; })
      .filter((r) => r.received).sort((a, b) => (b.received ?? "").localeCompare(a.received ?? ""));
    function id(o: unknown) { return (o as { po_line: { id: string } }).po_line.id; }
  }, [part]);
  const rows = d.data ?? [];
  if (!rows.length) return null;
  const shown = all ? rows : rows.slice(0, 4);
  const late = (r: { promised?: string; received?: string }) => (r.promised && r.received ? Math.round((Date.parse(r.received) - Date.parse(r.promised)) / 864e5) : 0);
  return (
    <Sec title={`Closed lines for ${part}, newest first`}>
      <table className="cp-t"><thead><tr><th>PO line</th><th>Part</th><th className="n">Qty, EA</th><th>Promised</th><th>Received</th><th /></tr></thead>
        <tbody>{shown.map((r) => <tr key={r.id}><td>{r.id}</td><td>{part} {cap(names(part))}</td><td className="n">{qty(r.qty)}</td><td>{day(r.promised)}</td><td>{day(r.received)}</td><td className="late">{late(r) > 0 ? `${late(r)} d late` : ""}</td></tr>)}</tbody></table>
      {rows.length > 4 && <button type="button" className="cp-link more" onClick={() => setAll(!all)}>{all ? "Show fewer" : `+ ${rows.length - 4} more`}</button>}
    </Sec>
  );
}

/** A regulatory notice: the parts it names, as the part file holds them (HTS, origin, buyer) with the open lines on each. */
function Notice({ i }: { i: ItemDetail }) {
  const src = useResource(() => getSources("?type=notice"), []);
  const ids = (i.refs ?? []).filter((r) => r.type === "part").map((r) => r.id);
  const d = useResource(() => Promise.all(ids.map((p) => api.partDetail(p).catch(() => null))), [ids.join(",")]);
  const lines = linesOf(i);
  const rows = (d.data ?? []).map((p, n) => ({ p, n })).filter(({ p }) => p).map(({ p, n }) => { const x = p as unknown as { raw?: Record<string, string>; buyer?: string | null }; return { id: ids[n], name: x.raw?.description ?? "", hts: x.raw?.hts_code ?? "", coo: x.raw?.country_of_origin ?? "", buyer: x.buyer ?? "", open: lines.filter((l) => l.part.id === ids[n]).length }; });
  return (<>
    {(src.data ?? []).slice(0, 1).map((x) => <SourceView key={x.id} src={x} />)}
    <Sec title="Your parts it names, on file">
      <table className="cp-t"><thead><tr><th>Part</th><th>HTS</th><th>Origin</th><th>Buyer</th><th className="n">Open lines</th></tr></thead>
        <tbody>{rows.map((r) => <tr key={r.id}><td>{r.id} <small>{r.name}</small></td><td>{r.hts || <span className="none">not on file</span>}</td><td>{r.coo || <span className="none">not on file</span>}</td><td>{r.buyer}</td><td className="n">{r.open || ""}</td></tr>)}</tbody></table>
    </Sec></>
  );
}

type Source = { type: string; id: string; kind: string; date: string; title: string; summary?: string | null; publisher?: string | null; url?: string | null; text?: string | null };
const getSources = (q: string) => fetch(`/api/sources${q}`).then((r) => (r.ok ? r.json() : [])).catch(() => []) as Promise<Source[]>;

/** An outside source as received (a notice, a news item): its header, then its text. A notice's markdown is set as it was written: headings, paragraphs, lists and its tables as tables. */
function SourceView({ src }: { src: Source }) {
  return (
    <div className="cp-msg">
      <dl className="cp-hdrs">{([["From", src.publisher ?? ""], ["Date", longDate(src.date)], ["Title", <b key="t">{src.title}</b>]] as [string, ReactNode][]).filter(([, v]) => v).map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
      <div className="ml cp-md">{md(src.text ?? src.summary ?? "")}</div>
    </div>
  );
}
/** A small markdown reader for a source's text: a leading note in quotes (the file's own preface) is left out; # headings, - lists, | tables |, **bold**. */
function md(text: string): ReactNode[] {
  const lines = text.replace(/^(?:>.*\n)+\s*/, "").split("\n");
  const out: ReactNode[] = [];
  const inline = (t: string) => t.split(/(\*\*[^*]+\*\*)/).map((x, n) => (x.startsWith("**") ? <b key={n}>{x.slice(2, -2)}</b> : x));
  for (let n = 0; n < lines.length; ) {
    const l = lines[n];
    if (!l.trim()) { n++; continue; }
    if (l.startsWith("|")) {
      const rows: string[][] = [];
      while (n < lines.length && lines[n].startsWith("|")) { const c = lines[n].split("|").slice(1, -1).map((x) => x.trim()); if (!c.every((x) => /^:?-+:?$/.test(x))) rows.push(c); n++; }
      out.push(<table key={n} className="cp-t"><thead><tr>{rows[0].map((h, k) => <th key={k}>{inline(h)}</th>)}</tr></thead><tbody>{rows.slice(1).map((r, k) => <tr key={k}>{r.map((x, j) => <td key={j}>{inline(x)}</td>)}</tr>)}</tbody></table>);
      continue;
    }
    if (/^#{1,6} /.test(l)) { out.push(<h4 key={n} className="cp-mdh">{inline(l.replace(/^#+ /, ""))}</h4>); n++; continue; }
    if (/^\s*([-*]|\d+\.) /.test(l)) {
      const items: string[] = [];
      while (n < lines.length && /^\s*([-*]|\d+\.) /.test(lines[n])) { items.push(lines[n].replace(/^\s*([-*]|\d+\.) /, "")); n++; }
      out.push(<ul key={n} className="ml-p">{items.map((x, k) => <li key={k}>{inline(x)}</li>)}</ul>);
      continue;
    }
    const para: string[] = [];
    while (n < lines.length && lines[n].trim() && !/^(#|\||\s*([-*]|\d+\.) )/.test(lines[n])) { para.push(lines[n]); n++; }
    out.push(<p key={n} className="ml-p">{inline(para.join(" "))}</p>);
  }
  return out;
}

/** A gap in the records: each row with the missing field shown as missing, and who can supply it. */
function Gap({ i, asked }: { i: ItemDetail; asked: ReturnType<typeof useAsked> }) {
  const names = usePartNames();
  const us = (i.unknowns ?? []) as { what: string; question?: string | null; owner?: string | null; refs?: { type: string; id: string }[] | null }[];
  return (
    <Sec title="The records, as they stand">
      <table className="cp-t"><thead><tr><th>Record</th><th>Missing</th><th>Who can fill it</th>{asked.any && <th>Asked in</th>}</tr></thead>
        <tbody>{us.map((u, n) => { const r = (u.refs ?? [])[0]; return <tr key={n}><td>{r ? <>{r.id} <small>{r.type === "part" ? cap(names(r.id)) : ""}</small></> : "—"}</td><td><span className="none">{u.what}: not on file</span></td><td title={u.question ?? ""}>{u.owner ?? ""}</td>{asked.any && (r ? <AskedCell asked={asked} id={r.id} /> : <td />)}</tr>; })}</tbody></table>
    </Sec>
  );
}

/** Analysis (r5): the agent's computed tables, then at most two of its facts. The disruption's parts table: stuck at the supplier, the month's need and shortfall per part, and the second source the findings name. */
function Analysis({ i, run, onRun, busy }: { i: ItemDetail; run: RunDetail | null; onRun?: () => void; busy?: boolean }) {
  const nums = (i.numbers ?? []) as Num[];
  const hasParts = nums.some((n) => n.id.startsWith("stuck_qty:"));
  const shape = shapeOf(i);
  const tabled = hasParts || nums.some((n) => /^(duty_net|risk_need|duty_if_china_net):/.test(n.id));      // a case with a computed table of its own
  const ran = !!i.recommendation;
  return <>
    <Reading i={i} />
    {ran && <Found i={i} max={4} />}
    {ran && <AgentNotes i={i} />}
    {!ran && i.group !== "trust" && onRun && <div className="cp-foot"><span className="pp">The agent has not analysed this case yet; the records below are code's</span><button type="button" className="b9 dark" disabled={busy} onClick={onRun}>Run analysis</button></div>}
    {hasParts && <PartsTable i={i} />}<Evidence i={i} run={run} noLines={shape === "message" || shape === "records"} noMonths={hasParts} />{!tabled && <Figures i={i} />}
  </>;
}
/** The agent's analysis (Khalid: "at the analysis step, the agent should be doing the analysis"): its reading of the case, checked by the verifier, then what it does not know,
 * what would change its call and the assumption it rests on; all from the run's recommendation, never invented. A reading whose checks failed is not shown. */
type RecA = { finding?: string | null; grade?: { checks_passed?: number; checks_total?: number; failed_checks?: unknown[] } | null; open_questions?: { what?: string; question?: string | null; owner?: string | null; why_it_blocks?: string | null }[] | null;
  would_change?: string[] | null; assumptions?: string[] | null } | null;
function Reading({ i }: { i: ItemDetail }) {
  const robots = useRobots();
  const r = i.recommendation as RecA & { unchecked?: unknown[] | null };
  const g = r?.grade;
  if (!r?.finding || (r.unchecked ?? []).length > 0) return null;      // the verifier (figures against the tools) is the truth gate; the Reviewer's grade is quality, shown beside it
  // A count of robots in the reading must be one of the case's own shortfalls (robots_short): a planned count read as a shortfall is not shown (AI-UI-SYNC Analysis check).
  const names = robots.map((x) => first(x.name)).filter(Boolean).join("|");
  const short = new Set((i.robots_short ?? []).map((x) => x.robots));
  const counts = [...r.finding.matchAll(new RegExp(`(\\d[\\d,]*)\\s+(?:${names ? `${names}|` : ""}robots?)\\b`, "gi"))].map((m) => Number(m[1].replace(/,/g, "")));
  if (counts.some((n) => !short.has(n))) return null;
  const notMet = ((g?.failed_checks ?? []) as ({ name?: string } | string)[]).map((x) => (typeof x === "string" ? x : x.name ?? "")).filter(Boolean);
  return <p className="cp-reading"><span className="lbl">Lookout's reading{g?.checks_total ? ` · ${g.checks_passed} of ${g.checks_total} checks` : ""}{notMet.length ? ` · not met: ${notMet.join("; ")}` : ""}</span>{r.finding}</p>;
}
function AgentNotes({ i }: { i: ItemDetail }) {
  const r = i.recommendation as RecA;
  const qs = r?.open_questions ?? [], wc = r?.would_change ?? [], as = r?.assumptions ?? [];
  return (
    <>
      {qs.length > 0 && <Sec title="What we don't know" by="the agent's open questions"><table className="cp-t cp-fig"><thead><tr><th>Question</th><th>Who</th><th>Why it matters</th></tr></thead>
        <tbody>{qs.map((q, n) => <tr key={n}><td>{q.question ?? q.what}</td><td>{q.owner ?? ""}</td><td>{q.why_it_blocks ?? ""}</td></tr>)}</tbody></table></Sec>}
      {wc.length > 0 && <Sec title="Would change the call"><ul className="cp-ul">{wc.map((x, n) => <li key={n}>{x}</li>)}</ul></Sec>}
      {as.length > 0 && <p className="cp-line q">{as.join(" ")}</p>}
    </>
  );
}

/** Any case without a computed table of its own: the detector's finding as code wrote it, then each figure with its own label (any new kind of case shows its numbers this way). */
function Figures({ i }: { i: ItemDetail }) {
  const mine = new Set((i.po_lines ?? []).map((l) => l.ref.id));
  const pat = (useResource(api.health).data as { id_patterns?: { po_line?: string } } | undefined)?.id_patterns?.po_line;      // the company's own PO-line id shape, from the API
  const lineOf = (n: Num) => (pat ? new RegExp(pat).exec(n.id)?.[0] : undefined);      // a figure about one PO line (its id carries it)
  const others = ((i.numbers ?? []) as Num[]).some((n) => { const l = lineOf(n); return !!l && mine.size > 0 && !mine.has(l); });
  const rows = ((i.numbers ?? []) as Num[]).filter((n) => !n.id.startsWith("tile:") && n.value && (!lineOf(n) || !mine.size || mine.has(lineOf(n)!))).map((n) => {
    const v = n.value!;
    const text = v.usd != null ? money(v.usd) : v.date ? day(v.date) : v.value != null ? `${Number(v.value).toLocaleString("en-US")}${v.uom && v.uom !== "EA" ? ` ${v.uom}` : v.uom === "EA" ? " EA" : ""}` : "";
    return { id: n.id, label: n.label, text };
  }).filter((r) => r.text);
  return (
    <>
      {i.finding && <p className="cp-line">{i.finding}</p>}
      {rows.length > 0 && <Sec title="Figures" by={others ? "totals are for all buyers; lines are yours" : undefined}><table className="cp-t cp-fig"><tbody>{rows.slice(0, 8).map((r) => <tr key={r.id}><td>{r.label}</td><td className="n">{r.text}</td></tr>)}</tbody></table></Sec>}
    </>
  );
}

function PartsTable({ i }: { i: ItemDetail }) {
  const names = usePartNames();
  const robots = useRobots();
  const f = useResource(() => fetch(`/api/action-items/${encodeURIComponent(i.key)}/findings`).then((r) => (r.ok ? r.json() : [])).catch(() => []) as Promise<{ key: string; fact: string }[]>, [i.key]);
  const nums = (i.numbers ?? []) as Num[];
  const val = (id: string) => { const v = nums.find((n) => n.id === id)?.value?.value; return v != null ? Number(v) : null; };
  const month = (i.robots_short ?? []).map((r) => r.month).sort()[0];
  const sup = (i.refs ?? []).find((r) => r.type === "supplier");
  const pat = (useResource(api.health).data as { id_patterns?: { part?: string } } | undefined)?.id_patterns?.part;
  const second = new Map<string, string>();      // from the findings by their key, the parts each names matched by the company's own part-id shape (API id_patterns)
  for (const x of f.data ?? []) {
    const ps = pat ? x.fact.match(new RegExp(pat, "g")) ?? [] : [];
    if (x.key === "alt_on_file") ps.forEach((p) => second.set(p, "supplied before on a PO"));
    if (x.key === "alt_quote_coverage") ps.slice(0, 1).forEach((p) => second.set(p, "a quote on file"));
    if (x.key === "no_alt_quote") ps.forEach((p) => second.has(p) || second.set(p, "none"));
  }
  const rows = nums.filter((n) => n.id.startsWith("stuck_qty:")).map((n) => n.id.slice(10)).map((p) => ({
    p, robot: robots.find((r) => (i.robots_short ?? []).some((x) => x.product.id === r.id && x.short_parts.some((s) => s.id === p))),
    stuck: val(`stuck_qty:${p}`), need: val(`requirement:${p}:${month}`), short: val(`shortage:${p}:${month}:short`),
  })).sort((a, b) => (b.short ?? 0) - (a.short ?? 0));
  return (
    <Sec title={`Parts stuck at ${sup ? nameOf(i, sup) : "the supplier"}`}>
      <table className="cp-t"><thead><tr><th>Part</th><th>Robot</th><th className="n">Stuck, EA</th><th className="n">{monthName(month)} need</th><th className="n">{monthName(month)} short</th><th>Second source</th></tr></thead>
        <tbody>{rows.map((r) => <tr key={r.p}><td>{r.p} {partName(i, r.p, names)}</td><td>{r.robot?.name ?? ""}</td><td className="n">{r.stuck != null ? r.stuck.toLocaleString("en-US") : ""}</td><td className="n">{r.need != null ? r.need.toLocaleString("en-US") : ""}</td><td className="n">{r.short != null ? r.short.toLocaleString("en-US") : ""}</td><td className={second.get(r.p) === "none" || !second.get(r.p) ? "none" : ""}>{second.get(r.p) ?? "none on file"}</td></tr>)}</tbody></table>
    </Sec>
  );
}

function Sec({ title, by, children }: { title: string; by?: string; children: ReactNode }) {
  return <section className="cp-sec"><div className="st"><h3>{title}</h3>{by && <span className="by">{by}</span>}</div>{children}</section>;
}

function Situation({ i }: { i: ItemDetail }) {
  const rows: [string, string][] = [["Act by", day(i.act_by)], ["Lines", i.lines_in_scope ? `${i.lines_in_scope} open PO lines${i.lines_already_late ? ` · ${i.lines_already_late} past due` : ""}` : ""], ["Next", i.next_action ?? ""]];
  return <Sec title="Situation"><dl className="cp-kv">{rows.filter(([, v]) => v).map(([k, v]) => <Fragment key={k}><dt>{k}</dt><dd>{v}</dd></Fragment>)}</dl></Sec>;
}

type Num = { id: string; label: string; value?: { usd?: string | null; value?: string | null; uom?: string | null; date?: string } | null };
const SHORT: [RegExp, string][] = [[/^tile:owed$/, "Owed"], [/^tile:if_late$/, "If late"], [/^tile:if_china$/, "If China"], [/^tile:count$/, "Count"], [/^tile:lines_late$/, "Lines late"],
  [/^tile:prepayment$/, "Prepayment"], [/^risk_need:/, "Need"], [/^chase:count$/, "Lines"]];
/** The case's own figures for the Impact line, all code (numbers with a tile id), with short labels; the act-by date lives in the meta. */
function impactFigures(i: ItemDetail): [string, string][] {
  const out: [string, string][] = [];
  for (const n of (i.numbers ?? []) as Num[]) {
    let label = SHORT.find(([re]) => re.test(n.id))?.[1];
    if (label === "Count") label = /order/i.test(n.label) ? "Orders" : /line/i.test(n.label) ? "Lines" : "Parts";      // the count says what it counts
    if (!label || !n.value) continue;
    const v = n.value;
    const text = v.usd != null ? `${n.id === "tile:if_late" || n.id === "tile:if_china" ? "+" : ""}${money(v.usd)}` : v.value != null ? (v.uom === "%" ? `${Number(v.value)}%` : n.id.startsWith("risk_need") ? `${Number(v.value).toLocaleString("en-US")} a month` : `${Number(v.value).toLocaleString("en-US")}`) : "";
    const own = n.id === "chase:count" && i.po_lines?.length ? String(i.po_lines.length) : null;      // the viewer's own lines on a team case, not the team count
    if (own ?? text) out.push([label, own ?? text]);
  }
  return out;
}

/** The case's figures for the header (no robots short): the viewer's share first on a team case (K-482), a viewer's own count on a slice (QA-2), each figure once (F105). */
function stakeFigures(i: ItemDetail, me: string | null | undefined): [string, string][] {
  const share = ((i.numbers ?? []) as Num[]).find((n) => n.id === `duty_share:${first(me)}`);
  const owed = usdOf(i.at_stake);
  let figs = impactFigures(i);
  if (share?.value?.usd && owed) figs = [[`Your share`, `${money(share.value.usd)} of ${money(owed)} (${Math.round((Number(share.value.usd) / Number(owed)) * 100)}%)`], ...figs.filter(([l]) => l !== "Owed")];
  const mineCount = /^(\d+)\b/.exec(i.title)?.[1];
  if (mineCount && !(i.owner ?? "").includes(" · ")) figs = figs.map(([l, t]) => (["Orders", "Parts", "Lines"].includes(l) ? [l, mineCount] : [l, t]));
  return figs;
}

/** What Lookout found (contract v2, UX C1): at most 4 rows, each the meaning (13/500) then the code fact on one line (ellipsis, full on hover); never the run's prose points.
 * The run's picks lead in its order; without them, code's list. An all-time on-time figure drops when a late streak is among the facts (the rail shows the streak). */
function Found({ i, max = 4 }: { i: ItemDetail; max?: number }) {
  const f = useResource(() => fetch(`/api/action-items/${encodeURIComponent(i.key)}/findings`).then((r) => (r.ok ? r.json() : [])).catch(() => []) as Promise<{ key: string; fact: string; template_meaning?: string | null }[]>, [i.key]);
  const said = new Map((((i.recommendation as { case_findings?: { key: string; meaning: string }[] } | null)?.case_findings) ?? []).map((x) => [x.key, x.meaning]));
  let rows = (f.data ?? []).map((x) => ({ key: x.key, fact: x.fact, meaning: said.get(x.key) ?? x.template_meaning ?? "" }));
  if (said.size) rows = [...said.keys()].map((k) => rows.find((x) => x.key === k)).filter((x): x is (typeof rows)[number] => !!x);
  if (rows.some((x) => /in a row|receipts late/i.test(x.fact))) rows = rows.filter((x) => !/on time on \d+%/i.test(x.fact));
  rows = rows.slice(0, max);
  if (!rows.length) return null;
  return <Sec title={said.size ? "Lookout's findings" : "Findings from the records"} by={said.size ? "each: the agent's meaning, then the record it rests on" : "code's findings and their standard meaning"}><div className="cp-fd">{rows.map((p) => <div key={p.key} className="r"><b>{p.meaning || p.fact}</b>{p.meaning && <span title={p.fact}>{p.fact}</span>}</div>)}</div></Sec>;
}

/** Every route a draft serves: its own option kind, the route chosen for it, and the routes a shared email covers (chosen_routes). */
const routesOf = (a: Action) => { const x = a as Action & { change?: { option_kind?: string } | null; chosen_route?: string | null; chosen_routes?: string[] | null };
  return new Set([x.change?.option_kind, x.chosen_route, ...(x.chosen_routes ?? [])].filter(Boolean) as string[]); };

function Decision({ i, options, askMap = {}, drafts, mine, readOnly, chosen, onContinue, onAsk, live, drafted, also, alsoIds = {}, onAlso, slice }: { i: ItemDetail; options: Opt[]; askMap?: Record<string, string>; drafts: Action[]; mine: boolean; readOnly: boolean; chosen: string | null; onContinue: (k: string) => void; onAsk: () => void; live: boolean; drafted?: string | null; also: string[]; alsoIds?: Record<string, string>; onAlso: (k: string, on: boolean) => void; slice?: { key: string; title: string } | null }) {
  const rec = i.recommendation as Rec;
  const recKind = rec?.recommended?.kind ?? null;
  const [sel, setSel] = useState<string | null>(chosen ?? null);      // Khalid 11:35: the buyer drives the decision; nothing is preselected (Recommended is advice only)      // with no recommendation nothing is preselected: the buyer picks
  const list = useRef<HTMLDivElement>(null);
  const pick = options.find((o) => o.kind === sel);
  const draft = drafts.find((a) => a.state === "proposed" && a.type === "supplier_request" && pick?.leads === "request" && (!drafted || pick.kind === drafted));
  const key = (e: KeyboardEvent<HTMLDivElement>) => {
    const n = Math.max(0, options.findIndex((o) => o.kind === sel));
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const to = options[Math.max(0, Math.min(options.length - 1, n + (e.key === "ArrowDown" ? 1 : -1)))];
      setSel(to.kind); (list.current?.querySelector(`[data-k="${to.kind}"]`) as HTMLElement | null)?.focus();
    } else if (e.key === "Enter" && pick && mine && !readOnly) { e.preventDefault(); onContinue(pick.kind); }
  };
  const waiting = drafts.filter((a) => a.state === "proposed");
  const hasTime = options.some((o) => o.time), hasCost = options.some((o) => o.cost);      // a column the code never fills for this case is left out
  return (
    <>
      {!readOnly && !slice && !mine && (i.owner ?? "").includes(" · ") && <p className="cp-line cp-slice">Not yours: {i.owner} own these lines</p>}
      {!readOnly && slice && <p className="cp-line cp-slice">Your part of this is <Link to={`/items/${encodeURIComponent(slice.key)}`}>{slice.title}</Link> ›</p>}
      {options.length === 0 && (() => { const n = (i.recommendation as { next_step?: { who?: string; what?: string; by?: string } | null } | null)?.next_step; return n?.what ? <p className="cp-line"><span className="cp-lbl">The agent's next step</span> {n.what}{n.who ? ` · ${n.who}` : ""}{n.by ? ` · by ${n.by}` : ""}</p> : null; })()}
      {options.length === 0 && <AgentNotes i={i} />}
      {options.length === 0 ? (waiting.length ? <div className="cp-prep">{waiting.map((a) => <Link key={a.action_id} className="cp-prow" to={`/approvals/${a.action_id}`}><b>Ask {a.target?.label ?? a.recipient} (drafted by the agent)</b><span> · Review →</span></Link>)}</div> : <p className="cp-none">No route is built for this kind of case yet{(i.recommendation as { next_step?: unknown } | null) ? "" : "; nothing to send"}.</p>) : (
        <div className="cp-og" style={{ gridTemplateColumns: `20px minmax(0,1.4fr) minmax(0,1fr)${hasTime ? " minmax(0,1fr)" : ""}${hasCost ? " minmax(0,.8fr)" : ""} minmax(0,.9fr)` }} role="radiogroup" aria-label="Routes" ref={list} onKeyDown={key}>
          <div className="oh" aria-hidden><span /><span>Route</span><span>What it changes</span>{hasTime && <span>Earliest help</span>}{hasCost && <span>Cost</span>}<span>Goes to</span></div>
          {options.map((o) => (
            <div key={o.kind} data-k={o.kind} role="radio" aria-checked={o.kind === sel} tabIndex={o.kind === sel || (!sel && o === options[0]) ? 0 : -1} className={`o${o.kind === sel ? " on" : ""}`}
              onClick={() => !readOnly && setSel(o.kind)} onKeyDown={(e) => { if (e.key === " ") { e.preventDefault(); setSel(o.kind); } }}>
              <span className="dot" aria-hidden />
              <span className="rt"><b>{o.title}</b>{o.raised && <span className="sug">raised in your discussion</span>}{o.kind === recKind && <span className="rec"><em>Recommended</em>{rec?.recommended?.reason ? ` ${rec.recommended.reason}` : ""}</span>}{(() => { const st = drafts.find((a) => (routesOf(a).has(o.kind) || askMap[a.action_id] === o.kind) && a.state === "proposed" && o.kind !== sel); const sent = !st && drafts.find((a) => routesOf(a).has(o.kind) && (a.state === "executed" || a.state === "approved") && a.type === "supplier_request"); if (sent) return <Link className="also" to={`/approvals/${sent.action_id}`} onClick={(e) => e.stopPropagation()}>Sent ✓ · email to {sent.target?.label ?? sent.recipient} ›</Link>; if (!st && alsoIds[o.kind] && o.kind !== sel) return <Link className="also" to={`/approvals/${alsoIds[o.kind]}`} onClick={(e) => e.stopPropagation()}>Started ✓ · covered by a draft waiting for your signature ›</Link>; return st ? <Link className="also" to={`/approvals/${st.action_id}`} onClick={(e) => e.stopPropagation()}>Started ✓ · {st.type === "note" ? "note" : `email to ${o.next.replace(/^[^→]*→\s*/, "") || st.recipient}`} · waiting for your signature{askMap[st.action_id] ? " · prepared with Lookout" : ""} ›</Link> : null; })()}{o.kind !== sel && (o.leads === "request" || o.leads === "note" || (o.leads === "record" && !!o.alsoWhy)) && !drafts.some((a) => (routesOf(a).has(o.kind) || askMap[a.action_id] === o.kind) && a.state === "proposed") && !alsoIds[o.kind] && <label className="also" onClick={(e) => e.stopPropagation()}><input type="checkbox" disabled={readOnly || !mine} checked={also.includes(o.kind)} onChange={(e) => onAlso(o.kind, e.target.checked)} /> Also start</label>}{(sel ? o.kind !== sel : o.kind !== recKind) && o.alsoWhy && !alsoIds[o.kind] && !drafts.some((a) => (routesOf(a).has(o.kind) || askMap[a.action_id] === o.kind) && a.state === "proposed") && <span className="sug">suggested: {o.alsoWhy}</span>}</span>
              <span className="cv">{o.change || <span className="none">not stated</span>}</span>
              {hasTime && <span>{o.time || <span className="none">{o.leads === "draft" ? "—" : "not known"}</span>}{o.time && o.basis && <small>{o.basis}</small>}</span>}
              {hasCost && <span>{o.cost || <span className="none">{o.leads === "draft" ? "—" : "not known"}</span>}</span>}
              <span className="gt">{o.next}</span>
            </div>
          ))}
        </div>
      )}
      {!readOnly && !pick && options.length > 0 && <div className="cp-foot"><span className="pp">Pick an option</span><button type="button" className="b9" disabled={!live} title={live ? "Work out another option in Ask; it can prepare the email" : "Live only: the agent is not connected"} onClick={onAsk}>Ask for another option</button><button type="button" className="b9 dark" disabled>Continue →</button></div>}
      {!readOnly && pick && (
        <div className="cp-foot">
          <span className="pp">{(() => { const to = pick.next.replace(/^[^→]*→\s*/, ""); const what = pick.leads === "draft" ? `your option "${pick.short}" (${pick.next.replace(/ → /, " to ")})` : pick.leads === "request" ? `an email to ${to}` : pick.leads === "note" ? `a note to ${to}` : "a decision on record"; const sug = options.filter((o) => o.kind !== pick.kind && o.alsoWhy && !also.includes(o.kind));
            return <><b>Continue:</b> {what} for your signature{draft && pick.leads === "request" && replyBy(draft.body ?? "") ? ` · asks ${asksOf(draft.body ?? "")} by ${replyBy(draft.body ?? "")}` : ""}{sug.length ? <> · also suggested: {sug.map((o) => `${o.title} (${o.alsoWhy})`).join("; ")}</> : null}</>; })()}</span>
          <button type="button" className="b9" disabled={!live} title={live ? "Work out another option in Ask; it can prepare the email" : "Live only: the agent is not connected"} onClick={onAsk}>Ask for another option</button>
          <button type="button" className="b9 dark" disabled={!mine || !!slice} title={slice ? "Your part of this case is decided on its own page" : mine ? `Continue with ${pick.short}` : `${first(i.owner)} decides`} onClick={() => onContinue(pick.kind)}><span className="lb">Continue with {pick.short}</span>&nbsp;→</button>
        </div>
      )}
    </>
  );
}

function Approval({ i, drafts, options, chosen, mine, live, onBack, onAsk, also = [], alsoIds = {}, recommended, onOpen, routeDraft }: { i: ItemDetail; drafts: Action[]; options: Opt[]; chosen: string | null; mine: boolean; live: boolean; onBack: () => void; onAsk: (text: string) => void; also?: string[]; alsoIds?: Record<string, string>; recommended?: string | null; onOpen?: (k: string) => void; routeDraft?: string | null }) {
  const fetched = useResource(() => (routeDraft && !drafts.some((a) => a.action_id === routeDraft) ? api.action(routeDraft).catch(() => null) : Promise.resolve(null)), [routeDraft]);      // I-1: a covering draft can belong to another case
  const fromAsk = chosen?.startsWith("draft:") ? chosen.slice(6) : null;
  const opt = options.find((o) => o.kind === chosen);
  const staged = (a: Action) => ((a as Action & { change?: { option_kind?: string } | null }).change?.option_kind ?? null);
  const draft = fromAsk ? drafts.find((a) => a.action_id === fromAsk)
    : routeDraft ? drafts.find((a) => a.action_id === routeDraft) ?? (fetched.data as Action | null) ?? undefined      // exactly the draft the choose call returned (AI-UI-SYNC P1, I-1)
    : opt ? drafts.find((a) => a.state === "proposed" && (a as Action & { chosen_route?: string | null }).chosen_route === opt.kind)
      ?? drafts.find((a) => (a.state === "proposed" || a.state === "approved" || a.state === "executed") && staged(a) === opt.kind) : undefined;      // the ledger's draft for this chosen route, else this route's own staged draft
  const liveOnly = live ? undefined : "Live only: the agent is not connected";
  return (
    <>
      <p className="cp-chosen"><button type="button" className="cp-link" onClick={onBack}>← Decision</button>{!draft && <> · Chosen: <b>{fromAsk ? "your option, worked out with Lookout" : opt?.title ?? chosen}</b></>}</p>
      {!draft && opt && <dl className="cp-kv cp-signs"><dt>Route</dt><dd>{`${opt.title}${opt.kind === recommended ? " (Lookout's recommendation, your choice)" : " (your choice)"}`}</dd></dl>}
      {draft && (draft.change as unknown as { how?: string } | null)?.how === "covered" && <p className="cp-line">Already asked in <Link to={`/approvals/${draft.action_id}`}>{draft.subject ?? draft.action_id}</Link> · this route is covered by that email</p>}
      {draft && <SignsToo i={i} draft={draft} route={fromAsk ? "your option, worked out with Lookout" : opt ? `${opt.title}${opt.kind === recommended ? " (Lookout's recommendation, your choice)" : " (your choice)"}` : ""} />}
      {also.length > 0 && <AlsoStarted i={i} kinds={also} ids={alsoIds} options={options} drafts={drafts} onOpen={onOpen} onPrepare={live ? (t) => onAsk(`Prepare the ${t} for this case`) : undefined} />}
      {draft ? <>
        <DraftFlow id={draft.action_id} mine={mine} owner={(draft as Action & { owner?: string | null }).owner ?? i.owner ?? ""} item={i} onLearned={() => invalidate()} inCase onDecided={() => invalidate()} />
        {draft.state === "proposed" && draft.type === "supplier_request" && (live ? <AskForChanges action={draft} onAmended={() => invalidate()} /> : <p className="cp-askc"><button type="button" className="cp-link" disabled title={liveOnly}>Ask for changes…</button></p>)}
      </> : opt && opt.leads !== "request" ? <StageOption i={i} opt={opt} mine={mine} />
        : <div className="cp-foot"><span className="pp">{opt ? `${opt.next}: not prepared yet` : "Choose an option first"}</span>
          {opt && <button type="button" className="b9 dark" disabled={!live} title={liveOnly} onClick={() => onAsk(`Prepare the ${opt.title} for this case`)}>Prepare it with Ask</button>}</div>}
    </>
  );
}

/** What signing this draft also signs (r6, BUYER 11): the route, the rights the email keeps (its own sentence, quoted, else "not stated"), and the money on the case. */
function SignsToo({ i, draft, route }: { i: ItemDetail; draft: Action; route: string }) {
  const body = (draft.body ?? "").replace(/\s+/g, " ");
  const rights = body.split(/(?<=[.!?])\s+/).find((x) => /\b(rights?|waive[sd]?|without prejudice)\b/i.test(x));
  const exp = usdOf(i.at_stake);
  const request = draft.type === "supplier_request";
  const rows: [string, ReactNode][] = [
    ["Route", route],
    ["Rights", rights ? <>keeps them: <q>{rights.trim()}</q></> : <span className="none">not stated in the email</span>],
    ["$", [exp ? `${money(exp)} open${i.lines_in_scope ? ` on ${i.lines_in_scope} lines` : ""}` : "", request ? "no new money (a request)" : ""].filter(Boolean).join(" · ")],
  ];
  return <dl className="cp-kv cp-signs">{rows.filter(([, v]) => v).map(([k, v]) => <Fragment key={k}><dt>{k}</dt><dd>{v}</dd></Fragment>)}</dl>;
}

/** The routes started beside the chosen one: each with its own draft's state, or what it still needs (a note is staged here; an email is prepared by the agent). */
function AlsoStarted({ i, kinds, ids = {}, options, drafts, onOpen, onPrepare }: { i: ItemDetail; kinds: string[]; ids?: Record<string, string>; options: Opt[]; drafts: Action[]; onOpen?: (k: string) => void; onPrepare?: (title: string) => void }) {
  const staged = (a: Action) => (a as Action & { change?: { option_kind?: string } | null }).change?.option_kind;
  return (
    <div className="cp-also"><span className="lbl">Also started</span>
      {kinds.map((k) => { const o = options.find((x) => x.kind === k); if (!o) return null; const d = drafts.find((a) => (ids[k] ? a.action_id === ids[k] : staged(a) === k)) ?? (ids[k] ? ({ action_id: ids[k], state: "proposed" } as Action) : undefined);
        return <span key={k} className="r"><b>{o.title}</b> · {o.next}{d ? <> · <Link to={`/approvals/${d.action_id}`}>{d.state === "proposed" ? "waiting for your signature" : d.state} ›</Link></> : <> · not drafted yet{o.leads === "note" ? onOpen && <> · <button type="button" className="cp-link" onClick={() => onOpen(k)}>write the note ›</button></> : <> · <button type="button" className="cp-link" disabled={!onPrepare} title={onPrepare ? "The agent prepares the email in Ask" : "Live only: the agent is not connected"} onClick={() => onPrepare?.(o.title)}>prepare the email ›</button></>}</>}</span>; })}
      <span className="q">{i.owner ? `each signed by ${first(i.owner)} on its own` : ""}</span>
    </div>
  );
}

/** The note a route stages, in the words StageOption pre-fills: the route, what it changes, the PO lines it is about. */
const noteText = (i: ItemDetail, opt: Opt) => {
  // M7: the lines a figure of the case rests on (its provenance inputs, all PO lines: e.g. duty owed on lines that cannot ship in time) are settled lines.
  // A decision on record names those; a note names the case's other lines. With no such figure, both name every line.
  const all = [...new Set([...(i.po_lines ?? []).map((l) => l.ref.id), ...(i.refs ?? []).filter((r) => r.type === "po_line").map((r) => r.id)])];
  const fixed = [...new Set(((i.numbers ?? []) as { value?: { provenance?: { inputs?: { type: string; id: string }[] } } | null }[]).flatMap((n) => { const ins = n.value?.provenance?.inputs ?? []; return ins.length && ins.every((x) => x.type === "po_line") ? ins.map((x) => x.id) : []; }))];
  const lines = !fixed.length ? all : opt.leads === "record" ? fixed : all.filter((l) => !fixed.includes(l));
  return `${opt.title}${opt.change ? `: ${opt.change}` : ""}${lines.length ? `.\nPO lines: ${lines.slice(0, 8).join(", ")}${lines.length > 8 ? ` and ${lines.length - 8} more` : ""}.` : ""}`; };

/** A note or a decision for an option (P7): the text prefilled from the option, the buyer edits it, and it is staged for their own signature. Nothing is sent. */
function StageOption({ i, opt, mine }: { i: ItemDetail; opt: Opt; mine: boolean }) {
  const { me } = useMe();
  const record = opt.leads === "record";
  const [text, setText] = useState(noteText(i, opt));      // the note names what it is about (QA-2 #3)
  const [reason, setReason] = useState(opt.change || "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const to = opt.next.replace(/^[^→]*→\s*/, "");
  if (!mine) return <p className="cp-line">With {first(i.owner)}: only the owner stages this.</p>;
  const stage = () => {
    setBusy(true); setErr(null);
    const viaActions = () => fetch(`/api/action-items/${encodeURIComponent(i.key)}/actions`, { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ kind: record ? "record" : "note", staged_by: me, text, to: record ? "" : to, reason: record ? reason : "", option_kind: opt.kind }) });
    // a decision goes through the route's choose with its reason, so the choice is in the ledger (FINAL-SPEC §2); a build without choose stages it as before
    (record ? fetch(`/api/action-items/${encodeURIComponent(i.key)}/routes/${encodeURIComponent(opt.kind)}/choose`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ by: me, reason }) })
      .then((r) => (r.status === 404 || r.status === 405 ? viaActions() : r)) : viaActions())
      .then(async (r) => { if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? "Could not stage it"); invalidate(); })
      .catch((e: Error) => setErr(e.message)).finally(() => setBusy(false));
  };
  return (
    <div className="cp-stage">
      <label><span>{record ? "Decision" : `Note to ${to}`}</span><textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} /></label>
      {record && <label><span>Reason</span><input value={reason} onChange={(e) => setReason(e.target.value)} /></label>}
      {err && <p className="cp-line h" role="alert">{err}</p>}
      <div className="cp-foot"><span className="pp">Staged for your signature · nothing is sent</span><button type="button" className="b9 dark" disabled={busy || !text.trim() || (record && !reason.trim())} onClick={stage}>Stage for my signature</button></div>
    </div>
  );
}

function Sent({ i, drafts, options, chosen }: { i: ItemDetail; drafts: Action[]; options: Opt[]; chosen: string | null }) {
  const a = drafts.find((x) => x.type === "supplier_request" && (x.state === "executed" || x.state === "approved"));
  const due = replyBy(a?.body ?? "");
  const opt = options.find((o) => o.kind === chosen);
  const asOf = useResource(api.health).data?.as_of;
  const to = /^Waiting on ([^;.]+)/.exec(i.next_action ?? "")?.[1];
  return (
    <>
      <p className="cp-line"><b>{opt ? opt.title : "Request"}</b> · sent {day(asOf)}{to ? ` to ${to}` : ""}{due ? ` · response due ${due}` : ""} (simulated)</p>
      {drafts.filter((x) => x !== a && x.type === "supplier_request").length > 0 && <div className="cp-also"><span className="lbl">The case's other drafts</span>{drafts.filter((x) => x !== a && x.type === "supplier_request").map((x) => <span key={x.action_id} className="r"><b>{x.target?.label ?? x.recipient}</b> · <Link to={`/approvals/${x.action_id}`}>{x.state === "proposed" ? "waiting for a signature" : x.state} ›</Link></span>)}</div>}
      <div className="cp-foot"><span className="pp">{due ? `No action until ${due}` : i.stage?.next_act ?? "No action until the reply"}</span>{a && <Link className="b9" to={`/approvals/${a.action_id}`}>The sent email</Link>}</div>
    </>
  );
}

/** The reply (F110): what changed since you asked, re-measured on read. One line (the new date and whether the case is still short), the change table, what is left to decide. */
function Response({ i, drafts, mine, onAgain }: { i: ItemDetail; drafts: Action[]; mine: boolean; onAgain?: () => void }) {
  type M = NonNullable<ItemDetail["messages"]>[number] & { changes?: Parameters<typeof WhatChanges>[0]["changes"] };
  const m = (i.messages ?? [])[0] as M | undefined;
  const robots = useRobots();
  const { me } = useMe();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!m) return <p className="cp-line">{i.next_action}</p>;
  // Khalid 11:08 #2: the reply's new dates become a PO update for the owner to sign, entered in the ERP by a person (Lookout writes no orders). The backend kind erp_update exists.
  const dated = (m.changes ?? []).filter((c) => c.ref.type === "po_line" && typeof c.after === "string" && /^\d{4}-\d{2}-\d{2}/.test(c.after));
  const erp = drafts.find((a) => (a.change as unknown as { kind?: string } | null)?.kind === "erp_update" && a.state !== "rejected");
  const stageErp = () => {
    setBusy(true); setErr(null);
    fetch(`/api/action-items/${encodeURIComponent(i.key)}/actions`, { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ kind: "erp_update", staged_by: me, text: `Update the promise date of ${dated.length} PO line${dated.length === 1 ? "" : "s"} from the reply (${m.ref.label}). Enter in the ERP.`,
        lines: dated.map((c) => ({ po_line: c.ref.id, was: c.before ?? null, now: c.after })) }) })
      .then(async (r) => { if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? "Could not draft it"); invalidate(); })
      .catch((e: Error) => setErr(e.message)).finally(() => setBusy(false));
  };
  const lines = (m.changes ?? []).filter((c) => c.ref.type === "po_line" && c.after);
  const latest = lines.map((c) => c.after as string).sort().pop();
  const rs = i.robots_short ?? [];
  const m1 = rs.map((x) => x.month).sort()[0];
  const short = robots.map((r) => ({ r, n: rs.filter((x) => x.month === m1 && x.product.id === r.id).reduce((a, x) => a + x.robots, 0) })).filter((x) => x.n > 0);
  return (
    <>
      <p className="cp-line"><b>{latest ? `Revised to ${day(latest)}` : m.ref.label}</b>{short.length ? ` · still short in ${[...new Set(rs.map((x) => x.month))].sort().slice(0, 2).map((mo) => `${monthName(mo)} (${robots.map((r) => ({ r, n: rs.filter((x) => x.month === mo && x.product.id === r.id).reduce((a, x) => a + x.robots, 0) })).filter((x) => x.n > 0).map((x) => `${x.n} ${x.r.key}`).join(" · ")})`).join(", ")}` : " · no robot short any more"}</p>
      {lines.length > 0 && <WhatChanges changes={m.changes ?? []} caption="What changed since you asked" wasLabel="Confirmed" nowLabel="Now" qtyLabel="Open qty" delta limit={4} />}
      {err && <p className="cp-line h" role="alert">{err}</p>}
      <div className="cp-foot"><span className="pp">{erp ? <>PO date update for {dated.length} lines · <Link to={`/approvals/${erp.action_id}`}>{erp.state === "proposed" ? "waiting for your signature" : erp.state} ›</Link> · enter in the ERP</> : short.length ? "Left to decide: the next way through for what is still short" : "Left to do: update the PO lines from the reply"}</span>
        <Link className={`b9${dated.length && !erp ? "" : " dark"}`} to={`/inbox/${encodeURIComponent(m.ref.id)}`}>Read the reply →</Link>
        {short.length > 0 && onAgain && <button type="button" className="b9" disabled={!mine} onClick={onAgain}>Decide the next way →</button>}
        {dated.length > 0 && !erp && <button type="button" className="b9 dark" disabled={!mine || busy} title={mine ? "A note with the new date per line, for your signature; you enter it in the ERP" : `${first(i.owner)} signs`} onClick={stageErp}>Draft the PO date update →</button>}</div>
    </>
  );
}

const HELD_ACTIONS = ["Do not reply to the sender: call the contact on file, on the number on file", "Keep paying the real account only: the real invoices stay payable",
  "Tell Accounts Payable not to change the vendor master", "Report the look-alike domain to IT security"];
/** The controls a held message needs, from its own trust flags (one per flag family; the wording of the first four is what recorded ticks key on). */
function controlsFor(flags: string[]): string[] {
  const out = [HELD_ACTIONS[0]];
  if (flags.includes("bank_detail_change")) out.push(HELD_ACTIONS[1], HELD_ACTIONS[2]);
  if (flags.includes("sender_domain_lookalike")) out.push(HELD_ACTIONS[3]);
  if (flags.includes("instruction_in_message")) out.push("Report the message to IT security: it carries an instruction aimed at AI");
  if (flags.some((f) => ["price_far_above_history", "supplier_on_hold", "advance_payment_demand"].includes(f))) out.push("Do not order from this message: buy only from a supplier on file, at a checked price");
  return out;
}

/** The four controls on a held message, each recorded on the case with who did it and when (IMPL-F 4a6d567: an executed note, append-only), read back from the case's actions. */
function useTicks(i: ItemDetail, actions: Action[], controls: string[]) {
  const { me } = useMe();
  const [err, setErr] = useState("");
  const ticks: Record<string, string> = Object.fromEntries(actions.filter((a) => a.type === "note" && (a.change as unknown as { kind?: string } | null)?.kind === "control" && a.decided_at)
    .map((a) => [(a.change as unknown as { control: string }).control, `${(a.decided_by ?? "").split(" ")[0]} · ${new Date(a.decided_at as string).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false })}`]));
  const tick = (t: string) => { if (!me) return; setErr(""); api.recordControl(i.key, t, me).then(() => invalidate()).catch((e) => setErr(e instanceof Error ? e.message : "Not recorded")); };
  return { ticks, tick, err, me, controls, all: i.group === "trust" && controls.length > 0 && controls.every((t) => ticks[t]) };
}

/** Why it is held (BUYER R2b, F105): Held · claimed · $0 paid, and each indicator with its evidence, read by code from the message (no model). */
function HeldWhy({ i }: { i: ItemDetail }) {
  const m = (i.messages ?? [])[0];
  const d = useResource(() => (m ? api.thread(m.ref.id).catch(() => null) : Promise.resolve(null)), [m?.ref.id]);
  const x = d.data as { summary?: { trust_flags?: string[]; from_email?: string | null }; reply_to?: string | null; imitates?: string | null; body?: string } | null;
  const flags = x?.summary?.trust_flags ?? [];
  const from = x?.summary?.from_email ?? "";
  const place = /^\s*Bank:[^\n]*,\s*([A-Z][\w ]+?)\s*$/m.exec(x?.body ?? "")?.[1];
  const rows: [string, string][] = [
    ...(flags.includes("sender_domain_lookalike") ? [["Look-alike domain", `${from.split("@")[1] ?? from}${x?.imitates ? ` imitates ${x.imitates}` : ""}`] as [string, string]] : []),
    ...(flags.includes("reply_to_freemail") ? [["Replies go to a free mailbox", x?.reply_to ?? ""] as [string, string]] : []),
    ...(flags.includes("bank_detail_change") ? [["New bank details", place ? `an account in ${place}` : "a new account"] as [string, string]] : []),
    ...(flags.includes("urgency") ? [["Pressure", "asks for action today"] as [string, string]] : []),
  ];
  return (
    <>
      <p className="cp-line"><b className="h">Held</b>{usdOf(i.at_stake) ? ` · ${money(usdOf(i.at_stake))} claimed · $0 paid` : ""}</p>
      {rows.length > 0 && <Sec title="Indicators"><table className="cp-t"><thead><tr><th>Indicator</th><th>Evidence</th></tr></thead><tbody>{rows.map(([k, v]) => <tr key={k}><td>{k}</td><td>{v}</td></tr>)}</tbody></table></Sec>}
    </>
  );
}

function Controls({ held, readOnly }: { i: ItemDetail; held: ReturnType<typeof useTicks>; readOnly: boolean }) {
  return <>{held.controls.map((t) => <label key={t} className="cp-ck"><input type="checkbox" checked={!!held.ticks[t]} disabled={readOnly || !!held.ticks[t] || !held.me} onChange={(e) => e.target.checked && held.tick(t)} /> {t}{held.ticks[t] && <small>✓ done · {held.ticks[t]}</small>}</label>)}{held.err && <p className="apr-err" role="alert">{held.err}</p>}</>;
}

/** The Analysis card (F95, trimmed by F105): only the tables that decide this case, each figure once (the supplier record and the checks are in the rail).
 * Disruptions: shortfall by month + the PO lines. Duty: the landed-cost table for the largest part + one line for the next. Supplier risk: the quote check + its lines. Tables open at 4 rows. */
function Evidence({ i, noLines, noMonths }: { i: ItemDetail; run: RunDetail | null; noLines?: boolean; noMonths?: boolean }) {
  const robots = useRobots();
  const names = usePartNames();
  const [allLines, setAllLines] = useState(false);
  const rs = i.robots_short ?? [];
  const months = [...new Set(rs.map((r) => r.month))].sort();
  const lines = i.po_lines ?? [];
  const shown = allLines ? lines : lines.slice(0, 4);
  const nums = (i.numbers ?? []) as Num[];
  const mineParts = new Set((i.po_lines ?? []).map((l) => l.part.id));      // the viewer's own lines (the API slices them by viewer)
  const duty = nums.filter((n) => n.id.startsWith("duty_net:")).sort((a, b) => Number(mineParts.has(b.id.slice(9))) - Number(mineParts.has(a.id.slice(9))) || Number(b.value?.usd ?? 0) - Number(a.value?.usd ?? 0)).map((n) => n.id.slice(9));
  const quoted = nums.find((n) => n.id.startsWith("risk_need:"))?.id.slice(10);
  const late = lines.filter((l) => (l as { days_past_due?: number | null }).days_past_due).length;
  return (
    <>
      {duty[0] && <Sec title="Landed cost with the duty" by={`${duty[0]} · ${names(duty[0]) ?? ""}`}><LandedCostTable part={duty[0]} variant="duty" also={duty.slice(1, 2)} /></Sec>}
      {quoted && <Sec title="Quote check" by={`${quoted} · ${names(quoted) ?? ""}`}><LandedCostTable part={quoted} variant="quote" /></Sec>}
      {(() => { const rows = nums.filter((n) => n.id.startsWith("duty_if_china_net:")).sort((a, b) => Number(b.value?.usd ?? 0) - Number(a.value?.usd ?? 0)); return rows.length > 0 && <Sec title="Duty if China, by part">
        <table className="cp-t"><thead><tr><th>Part</th><th className="n">Duty if China</th></tr></thead><tbody>{rows.slice(0, 4).map((n) => { const p = n.id.slice(18); return <tr key={p}><td>{names(p) ?? p} <small>{p}</small></td><td className="n">{money(n.value?.usd)}</td></tr>; })}</tbody></table>
        {rows.length > 4 && <span className="cp-line q">+{rows.length - 4} more</span>}</Sec>; })()}
      {months.length > 0 && !(noMonths && months.length <= 2) && <Sec title="Shortfall by month">
        <table className="cp-t"><thead><tr><th>Robot</th>{months.map((m) => <th key={m}>{monthName(m)}</th>)}</tr></thead>
          <tbody>{robots.filter((r) => rs.some((x) => x.product.id === r.id)).map((r) => <tr key={r.id}><td><span className={`cp-ri r-${(r.slot % 3) + 1}`}><RobotIcon slot={r.slot} /></span> {r.key}</td>{months.map((m) => { const n = rs.filter((x) => x.month === m && x.product.id === r.id).reduce((a, x) => a + x.robots, 0); return <td key={m}>{n ? `up to ${n}` : "—"}</td>; })}</tr>)}</tbody></table>
      </Sec>}
      {lines.length > 0 && !noLines && <Sec title="PO lines" by={`${lines.length} lines${late ? ` · ${late} past due` : ""}`}>
        <table className="cp-t"><thead><tr><th>PO line</th><th>Part</th><th className="n">Open qty</th><th>Confirmed</th><th /></tr></thead>
          <tbody>{shown.map((l) => { const x = l as typeof l & { promise_date?: string | { date?: string } | null; revised_date?: string | { date?: string } | null; days_past_due?: number | null; qty?: { value?: string } }; const dt = (v: unknown) => (typeof v === "string" ? v : (v as { date?: string } | null)?.date ?? null); return <tr key={l.ref.id}><td><Link to={`/orders?q=${encodeURIComponent(l.ref.id)}`}>{l.ref.id}</Link></td><td>{names(l.part.id) ?? l.part.id} <small>{l.part.id}</small></td><td className="n">{qty(x.qty?.value)}</td><td>{day(dt(x.revised_date) ?? dt(x.promise_date))}</td><td>{x.days_past_due ? `${x.days_past_due} d past due` : ""}</td></tr>; })}</tbody></table>
        {lines.length > 4 && <button type="button" className="cp-link" onClick={() => setAllLines(!allLines)}>{allLines ? "Show fewer" : `+${lines.length - 4} ›`}</button>}
      </Sec>}
    </>
  );
}

/** A dated row in the buyer's short words: the supplier's name and the part after a colon dropped ("<Supplier> promised revised dates by <date>: chase…" → "Promised revised dates by <date>"). */
function eventWords(title: string, supplier?: string | null) {
  let t = title.split(":")[0];
  const short = (supplier ?? "").split(" ")[0];
  if (short && t.startsWith(short)) t = t.slice(short.length).replace(/^['’]s\b/, "").trim();
  return t.replace(/^\w/, (c) => c.toUpperCase());
}
const consequence = (x: { at_stake?: { what?: string } | null }) => { const w = (x.at_stake?.what ?? "").replace(/^the /, ""); return w.length <= 18 ? w : ""; };      // a short word on the right, or nothing

/** The one honest limit, on the two cases where it matters (BUYER interview-stress §2): what the buyer takes elsewhere. */
function outside(i: ItemDetail): string | null {
  if (i.group === "tariff") return "FTZ, drawback and classification strategy: your customs broker";
  if (i.key.startsWith("risk:") && /insolven/i.test(i.title)) return "Insolvency protections (retention of title, set-off): your legal counsel";
  return null;
}

/** A supplier as the buyer says it ('Acme'), the legal name on hover (UX SL-7). */
const nameOf = (i: ItemDetail, r: { id: string; label?: string | null }) => i.short_names?.[r.id] ?? r.label ?? r.id;

/** The simple rail (r6/r7): Deadlines · Supplier · Linked cases · Checks · links. No findings and no buttons. */
function Rail({ i, run, runId, drafts, onRunLive, busy }: { i: ItemDetail; run: RunDetail | null; runId: string | null; drafts: Action[]; onRunLive?: () => void; busy?: boolean }) {
  const sup = (i.refs ?? []).find((r) => r.type === "supplier");
  const s = useResource(() => (sup ? api.supplier(sup.id).catch(() => null) : Promise.resolve(null)), [sup?.id]);
  const d = s.data as { delivery?: { n: number; on_time: number; on_time_pct: number; avg_days_late: number } | null; terms?: string | null; incoterms?: string | null; contact?: { name?: string | null } | null } | null;
  const dated = ((i as { dated?: { key: string; title: string; act_by: string; at_stake?: { what?: string } | null }[] }).dated ?? []).slice().sort((a, b) => a.act_by.localeCompare(b.act_by));
  const linked = (i as { linked?: { key: string; title: string; why: string }[] }).linked ?? [];
  const msgs = (i.messages ?? []).length;
  const real = drafts.filter((a) => !(a.type === "note" && a.state === "executed" && ((a.change as unknown as { how?: string } | null)?.how || (a.change as unknown as { kind?: string } | null)?.kind === "control")));      // a choice or a done control on the ledger is not a draft
  return (
    <RightPanel label="About this case" className="cp-rail">
      <RightPanel.Section title="Deadlines">{dated.length > 0 && dated.slice(0, 5).map((x, n) => <Link key={x.key} to={`/items/${encodeURIComponent(x.key)}`} className={`dd${n === 0 ? " nx" : ""}`}><b>{day(x.act_by)}</b><span title={x.title}>{eventWords(x.title, sup && nameOf(i, sup))}</span><small>{consequence(x)}</small></Link>)}</RightPanel.Section>
      <RightPanel.Section title="Supplier">{sup && i.group !== "trust" && <><Link className="nm" to={`/suppliers/${encodeURIComponent(sup.id)}`} title={sup.label ?? ""}>{nameOf(i, sup)}</Link>
        {d?.delivery && <div className="s">{(d.delivery as { streak?: { line?: string } | null }).streak?.line?.replace(/\s*\([^)]*\)\s*$/, "") ?? `OTD ${Math.round(d.delivery.on_time_pct * 100)}% (${d.delivery.on_time}/${d.delivery.n}) · avg ${Math.round(d.delivery.avg_days_late)} d late`}</div>}
        {(d?.terms || d?.contact?.name) && <div className="s">{[d?.terms, d?.incoterms, d?.contact?.name ? `${d.contact.name} (on file)` : ""].filter(Boolean).join(" · ")}</div>}</>}</RightPanel.Section>
      <RightPanel.Section title="Linked cases">{linked.length > 0 && linked.slice(0, 3).map((l) => <Link key={l.key} className="ln" to={`/items/${encodeURIComponent(l.key)}`}>{l.title.split(":")[0]} · {l.why.replace(/:.*$/, "").replace(/^the /, "")} ›</Link>)}</RightPanel.Section>
      <RightPanel.Section title="Checks">{run && <div className="s">{run.checks_total ? `${run.checks_passed} of ${run.checks_total} checks passed` : "No checks recorded"}{onRunLive && <> · <button type="button" className="cp-link" disabled={busy} title="Work this case again with the live agent; the saved run is kept" onClick={onRunLive}>Run live</button></>}</div>}</RightPanel.Section>
      <RightPanel.Section title="Outside Lookout">{outside(i) && <div className="s">{outside(i)}</div>}</RightPanel.Section>
      <RightPanel.Section className="links">{(msgs > 0 || real.length > 0 || runId) && <div className="links">{msgs > 0 && <Link to={`/inbox?case=${encodeURIComponent(i.key)}`}>Messages {msgs} ›</Link>}{real.length > 0 && <Link to={`/approvals/${real[0].action_id}`}>Drafts {real.length} ›</Link>}{runId && <Link to={`/activity/${encodeURIComponent(runId)}`}>History ›</Link>}</div>}</RightPanel.Section>
    </RightPanel>
  );
}

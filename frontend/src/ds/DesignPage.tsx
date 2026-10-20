import { useState } from "react";
import { Bell } from "lucide-react";
import { Button, EmptyState, Field, Ladder, Notice, PageHeader, Row, RowGroup, Section, SegmentedControl, SideNav, Skeleton, StateChip, StateDot, TabBar, Tile, Tiles, type SectionDef, type State } from "./index";
import { useResource } from "../api/useResource";
import { api } from "../api/client";
import { BuildRef, PartRef, PoLineRef, SupplierRef } from "../domain-ui/Records";
import { DateDue, MethodBadge, Money, Quantity, UnknownValue } from "../domain-ui/Values";
import { StageCompact, STEPS, HELD, ASKING } from "../domain-ui/StageTracker";
import { ResultCard } from "./../domain-ui/ResultCard";
import { ReadinessSummary, ShortageFigure, SupplierEvent, TariffExposure, TrustFlag } from "../domain-ui/Concepts";
import { Assumptions, CheckStrip, DecisionHistory, Recommendation, RunTrace } from "../domain-ui/Agent";
import { Draft } from "../domain-ui/Draft";
import { useMe } from "../api/useMe";
import type { Money as M, Quantity as Q, Unknown } from "../api/types";
import * as DM from "../components/domain";

const ROLES: [string, string][] = [["surface", "Page"], ["raised", "Tiles, trough"], ["hover", "Hover"], ["line", "Hairlines"], ["ink", "Text"], ["ink-2", "Secondary text"], ["ink-3", "Meta, labels"], ["ink-4", "Placeholder, off"], ["accent", "Links, focus"], ["fill", "The primary button"], ["badge", "Count badge"],
  ["critical", "Risk ink"], ["critical-bg", "Risk surface"], ["caution", "Late, waiting"], ["caution-bg", "Late surface"], ["positive", "Done well"], ["positive-bg", "Done surface"], ["unknown", "Unknown ink"], ["unknown-bg", "Unknown surface"]];
const STATES: [State, string][] = [["done", "Shown by the records"], ["expected", "Expected"], ["late", "Late"], ["disrupted", "Disrupted"], ["unknown", "Unknown: ask"], ["na", "Not applicable"], ["high", "High"], ["med", "Medium"], ["low", "Low"]];
const TYPE: [string, string][] = [["t-title", "Page title, figures"], ["t-lead", "The decision, phone body"], ["t-body", "Everything else"], ["t-small", "Meta, second lines, table heads"], ["t-caption", "Legends, tab labels, chips"]];
const SPACE = ["s1", "s2", "s3", "s4", "s5", "s6", "s7"];
const RADII = ["r-xs", "r-sm", "r-md", "r-lg", "r-sheet", "r-pill"];

const SAMPLE = "Sam Cho at Acme sent PT-1001 on PO-26-00001/20: 1,200 EA, $396K, due Oct 1 (6 to 8 weeks).";
const span = (what: string, type: string, extra: object = {}) => ({ start: SAMPLE.indexOf(what), end: SAMPLE.indexOf(what) + what.length, type, ...extra });
const SAMPLE_ENTITIES = [span("Sam Cho", "person"), span("Acme", "supplier", { ref: "SP-1", trust: "on_file" }), span("PT-1001", "part", { ref: "PT-1001", label: "Drive motor" }), span("PO-26-00001/20", "po_line", { ref: "PO-26-00001/20" }), span("1,200 EA", "quantity"), span("$396K", "money"), span("Oct 1", "date", { ref: "2026-10-01" }), span("6 to 8 weeks", "duration")];

/** The design system as a page, built from the real components: for Khalid and the reviewer, and a visual-regression page for the scroll and keyboard checks. */
export function DesignPage() {
  const { me, people } = useMe();
  const [seg, setSeg] = useState("a");
  const [sec, setSec] = useState("rec");
  // The demo records are the first item the API lists, its first part and supplier: nothing here names a company.
  const demo = useResource(async () => {
    const items = await api.actionItems();
    const first = items.find((x) => (x.refs ?? []).some((r) => r.type === "part")) ?? items[0];
    const part = (first?.refs ?? []).find((r) => r.type === "part") ?? null;
    const supplier = (first?.refs ?? []).find((r) => r.type === "supplier") ?? null;
    const tariffKey = items.find((x) => x.group === "tariff")?.key ?? first?.key;
    return { first, part, supplier, tariffKey };
  }, []);
  const partId = demo.data?.part?.id;
  const ladder = useResource(() => (partId ? api.phases(partId).catch(() => null) : Promise.resolve(null)), [partId]);
  const live = useResource(async () => {
    const d = demo.data;
    if (!d?.first || !d.part) return null;
    const [part, builds, item, runs, actions] = await Promise.all([api.partDetail(d.part.id), api.builds(), api.item(d.first.key), api.runs(), api.actions("proposed")]);
    const run = runs.find((r) => r.item_key === d.first.key);
    const detail = run?.run_id ? await api.run(run.run_id) : null;
    const tariff = await api.item(d.tariffKey ?? d.first.key);
    return { part, builds, item, detail, action: actions[0] ?? null, tariff };
  }, [demo.data?.first?.key]);
  const sections: SectionDef[] = [
    { id: "rec", label: "Recommendation", render: () => <p style={{ margin: 0 }}>The decision lives here; the rest is a click away.</p> },
    { id: "evidence", label: "Evidence", count: 3, render: () => <p style={{ margin: 0 }}>Why, month by month, messages.</p> },
    { id: "lines", label: "Lines", count: 10, render: () => <p style={{ margin: 0 }}>Ten PO lines, each with its stages.</p> },
  ];
  return (
    <div className="ds-page">
      <PageHeader title="Lookout design system" meta="Tokens by role, then every component in its states. Phone and desktop share each one." />

      <h2>Stage tracker · result card</h2>
      <div className="ds-demo-row">
        <StageCompact state={{ stage: { key: "drafted", label: "Draft waiting", step: 4, of: 7, next_act: "Approve the draft", waiting_on: "you" } }} />
        <StageCompact state={{ stage: { key: "approved", label: "Approved", step: 5, of: 7, next_act: "Wait for the reply", waiting_on: null } }} />
        <StageCompact state={{ kind: "held" }} />
        <StageCompact state={{ kind: "asking" }} />
      </div>
      <ResultCard data={{ finding: "Two of ten lines will not arrive in time.", points: [{ label: "Why", text: "The supplier's revised dates are after the build." }, { label: "Cost", text: "$4,200 more if air freight is used." }], done: [{ action_id: "A-demo", label: "Request to the supplier", stage: "drafted" }], next_step: { who: "The buyer", what: "Approve the request", by: "Oct 10" }, open_questions: [{ what: "stock on hand", question: "How many of AB-10001 are on the shelf?", owner: "Planning" }], checks: ["8 of 8 numbers match the data"] }} />
      <h2>Stage legend</h2>
      <div className="ds-legend">{[...STEPS, { key: "held", ...HELD }, { key: "asking", ...ASKING }].map((x) => <div key={x.name}><x.Icon size={16} strokeWidth={1.5} aria-hidden /><b>{x.name}</b><small>{x.meaning}</small></div>)}</div>
      <h2>Colour roles</h2>
      <div className="ds-sws">{ROLES.map(([n, d]) => <div key={n}><i style={{ background: `var(--${n})` }} /><b>--{n}</b><span>{d}</span></div>)}</div>

      <h2>States</h2>
      <div className="ds-cell"><div>{STATES.map(([s, d]) => <span key={s} style={{ display: "inline-flex", gap: "var(--s2)", alignItems: "center", minWidth: 190 }}><StateDot state={s} />{d}</span>)}</div></div>

      <h2>Type</h2>
      {TYPE.map(([n, u]) => <div className="ds-spec" key={n}><code>--{n}</code><span style={{ fontSize: `var(--${n})` }}>A supplier's force majeure leaves 10 open PO lines stuck</span><small className="muted" style={{ marginLeft: "auto" }}>{u}</small></div>)}

      <h2>Space and radii</h2>
      <div className="ds-cell"><div>{SPACE.map((s) => <span key={s} style={{ fontSize: "var(--t-small)" }}><i style={{ display: "block", height: 16, width: `var(--${s})`, background: "var(--ink-4)", marginBottom: 4 }} />--{s}</span>)}</div></div>
      <div className="ds-cell"><div>{RADII.map((r) => <span key={r} style={{ fontSize: "var(--t-small)" }}><i style={{ display: "block", width: 64, height: 44, background: "var(--raised)", boxShadow: "inset 0 0 0 1px var(--ink-4)", borderRadius: `var(--${r})`, marginBottom: 4 }} />--{r}</span>)}</div></div>

      <h2>Button</h2>
      <div className="ds-cell"><div><Button variant="primary">Review and approve the request</Button><Button>Ask the agent again</Button><Button variant="quiet">Reject with reason…</Button><Button disabled>Disabled</Button></div></div>

      <h2>StateChip</h2>
      <div className="ds-cell"><div><StateChip tone="critical"><StateDot state="disrupted" />2 force majeure</StateChip><StateChip tone="caution">3 late on the supplier's latest date</StateChip><StateChip tone="unknown">80 unknown</StateChip><StateChip tone="positive">Sent (simulated)</StateChip><StateChip>35 covered</StateChip></div></div>

      <h2>Tile</h2>
      <Tiles><Tile tone="critical" figure="364 EA" label="short in October, before stock on hand" /><Tile figure="1,140 EA" label="open on 3 PO lines · stuck: force majeure" /><Tile tone="unknown" figure="80" label="no open order: unknown without stock data" /><Tile tone="caution" figure="3" label="late on the supplier's latest date" /></Tiles>

      <h2>Row</h2>
      <RowGroup>Supply disruption</RowGroup>
      <Row state="high" to="/design" title="Supplier fire: two robot builds short of drive motors from October" sub="Ask the supplier for revised dates and an allocation before the October builds" figure="364 EA" note="Oct 10" />
      <Row state="unknown" title="5 parts: country of origin unknown ($123K if China)" sub="Ask the supplier for a certificate of origin" figure="unknown" note="Oct 15" />
      <Row state="med" title="19 lines past due with no word from the supplier: $504K open" sub="Chase the five largest first" figure="$504K" />

      <h2>SegmentedControl · Section</h2>
      <div className="ds-cell"><SegmentedControl items={[{ id: "a", label: "Recommendation" }, { id: "b", label: "Evidence", count: 3 }, { id: "c", label: "Lines", count: 10 }, { id: "d", label: "Numbers", count: 17 }]} value={seg} onChange={setSeg} /></div>
      <Section sections={sections} current={sec} onSelect={setSec} />

      <h2>Notice · EmptyState · Skeleton · Field</h2>
      <div className="ds-cell" style={{ display: "grid", gap: "var(--s3)", maxWidth: 560 }}>
        <Notice>No stock count is loaded: parts with no open order are unknown, not covered.</Notice>
        <Notice>Offline: showing what was last read. Approving needs a connection.</Notice>
        <Notice tone="risk">This message looks suspicious. Nothing can be approved from it.</Notice>
        <EmptyState>Nothing needs you right now.</EmptyState>
        <Skeleton width={240} />
        <Field placeholder="Ask Lookout" aria-label="Ask Lookout" />
        <Field kind="textarea" rows={3} placeholder={"PART=QUANTITY, one per line"} aria-label="Counts" />
        <Field kind="select" aria-label="Buyer" defaultValue=""><option value="">All buyers</option>{people.map((x) => <option key={x.name}>{x.name}</option>)}</Field>
      </div>

      <h2>SideNav · TabBar</h2>
      <div className="ds-cell" style={{ display: "grid", gap: "var(--s4)", maxWidth: 420 }}>
        <SideNav items={[{ to: "/", label: "Action list", count: 12, hot: true, end: true, icon: <Bell size={16} strokeWidth={1.5} /> }, { to: "/inbox", label: "Inbox", count: 15 }, { to: "/approvals", label: "Approvals", count: 2, hot: true }]} />
        <TabBar items={[{ to: "/", label: "Today", end: true }, { to: "/approvals", label: "Approvals", count: 2, hot: true }, { to: "/inbox", label: "Inbox" }, { to: "/more", label: "More" }]} isOn={(to) => to === "/design" || to === "/"} />
      </div>

      <h2>Ladder</h2>
      {ladder.data ? <Ladder ladder={ladder.data} /> : <Skeleton width={320} />}

      <h2>Domain components</h2>
      <p className="ds-note">One component per kind of thing. Colour means one thing: red is blocked or at risk, amber needs you or is near, green is done or verified; each also carries an icon or a word.</p>
      <div className="dm-showcase">
        <div><small>Part (the product tells two same-named parts apart; a long name truncates)</small><div className="ds-line">
          <DM.Part id="PT-1001" name="Drive motor" product="Alpha" /><DM.Part id="PT-1002" name="Drive motor" product="Beta" />
          <DM.Part id="PT-1003" name="Motor, brushless DC, 48 V 400 W, 86 mm frame, hall sensors, encoder, wheel drive" /></div></div>
        <div><small>Supplier (country code, then whether we have it on file)</small><div className="ds-line">
          <DM.Supplier id="SUP-1" name="Example Motors Ltd." country="CN" trust="on_file" /><DM.Supplier id="SUP-2" name="Example Bearings GmbH" country="DE" trust="new" /><DM.Supplier id="SUP-3" name="Examp1e Motors Ltd." country="CN" trust="lookalike" /></div></div>
        <div><small>PO line (the real number) and a compact table, collapsed after 3</small>
          <div className="ds-line"><DM.PoLine id="PO-26-00001 / 10" qty="1200" uom="EA" date="2026-10-10" /></div>
          <DM.PoLineTable rows={[10, 20, 30, 40, 50].map((n) => ({ id: `PO-26-00001 / ${n}`, part: { id: "PT-1001", name: "Drive motor", product: "Alpha" }, qty: 100 + n, uom: "EA", was: "Oct 1", now: "Nov 17" }))} /></div>
        <div><small>Person, a shared first name, and the count chip at four or more</small><div className="ds-line">
          <DM.People names={["Ana Lee", "Sam Cho"]} /><DM.People names={["Ana Lee", "Ana Kim"]} /><DM.People names={["A One", "B Two", "C Three", "D Four"]} noun="buyers" /></div></div>
        <div><small>Money (under $10K whole dollars, then K and M; exact cents only on a quote price)</small><div className="ds-line">
          <DM.Money value={{ amount: "8009", currency: "USD" }} /><DM.Money value={{ amount: "396000", currency: "USD" }} /><DM.Money value={{ amount: "1539053.57", currency: "USD" }} /><DM.Money value={{ amount: "188.9875", currency: "USD" }} exact /><DM.Money value={{ amount: "504000", currency: "USD" }} risk /></div></div>
        <div><small>Date (counted from the data date; amber within 7 days; red once past)</small><div className="ds-line">
          <DM.DateDue date="2026-10-10" asOf="2026-09-25" /><DM.DateDue date="2026-10-01" asOf="2026-09-25" /><DM.DateDue date="2026-09-23" asOf="2026-09-25" /></div></div>
        <div><small>Stage</small><div className="ds-line">
          {(["found", "worked", "decision_ready", "drafted", "approved", "sent", "answered", "asking", "held"] as DM.StageKey[]).map((k) => <DM.Stage key={k} stage={k} waitingOn={k === "drafted" ? "you" : undefined} />)}</div></div>
        <div><small>Trust, a sentence per reason</small><DM.TrustBadges flags={["sender_domain_lookalike", "bank_detail_change"]} /><DM.TrustBadges flags={[]} onFile /></div>
        <div><small>Problem kind (meaning on hover or focus), and the legend Today carries</small><div className="ds-line">
          {(Object.keys(DM.KINDS) as DM.Kind[]).map((k) => <DM.ProblemKind key={k} kind={k} />)}</div><DM.ProblemLegend /></div>
        <div><small>Text with its entities: figures bold, dates and durations as chips, one idea per line, the rest behind Read in full</small>
          <DM.EntityLines asOf="2026-09-25" limit={2} text="Pay $187,420 for 1,200 EA by Oct 1. Restart takes 6 to 8 weeks. The supplier is Examp1e Motors. Nothing else is known." entities={[{ start: 4, end: 12, type: "money" }, { start: 17, end: 25, type: "quantity" }, { start: 29, end: 34, type: "date", ref: "2026-10-01" }, { start: 55, end: 67, type: "duration" }]} />
          <DM.Points points={[{ label: "What changed", text: "Ten lines cannot ship." }, { label: "What to do", text: "Ask for revised dates." }]} /></div>
        <div><small>Entity markers: one per kind of thing, the same on every screen</small>
          <dl className="dm-legend-grid">{DM.MARKERS.map((x) => <div key={x.type}><dt>{x.name}</dt><dd>{x.marker}</dd></div>)}</dl>
          <DM.EntityText asOf="2026-09-25" text={SAMPLE} entities={SAMPLE_ENTITIES} /></div>
        <div><small>Terms carry their meaning</small><div className="ds-line"><DM.Term k="bom" /><DM.Term k="hts" /><DM.Term k="incoterm" /><DM.Term k="fm" /></div></div>
      </div>

      <h2>Meaning layer: records</h2>
      <div className="ds-cell"><div style={{ display: "grid", gap: "var(--s2)" }}>
        {demo.data?.part && <PartRef id={demo.data.part.id} name={demo.data.part.label} />}
        {demo.data?.part && <PartRef id={demo.data.part.id} />}
        {demo.data?.supplier && <SupplierRef r={demo.data.supplier} />}
        {demo.data?.supplier && <SupplierRef r={demo.data.supplier} status="unvetted" />}
        {live.data?.item.po_lines?.[0] && <PoLineRef id={live.data.item.po_lines[0].ref.id ?? ""} />}
        {live.data?.builds[0] && <BuildRef product={live.data.builds[0].product.label ?? live.data.builds[0].product.id} month={live.data.builds[0].month} />}
      </div></div>

      <h2>Meaning layer: values</h2>
      <div className="ds-cell"><div>
        {live.data?.part.exposure?.net && <Money value={live.data.part.exposure.net as M} />}
        {live.data?.part.shortage && <Quantity value={live.data.part.shortage.short as Q} upTo />}
        <DateDue date="2026-10-10" daysLeft={15} />
        <DateDue date="2026-09-23" daysLeft={-2} />
        <UnknownValue u={{ what: "origin", why_it_blocks: "", owner: me ?? "a buyer", question: "Where are these made?", refs: [] } as Unknown} />
        <MethodBadge method="inferred" /><MethodBadge method="flagged" />
      </div></div>

      <h2>Meaning layer: concepts</h2>
      {live.data?.builds[0] && <ReadinessSummary counts={live.data.builds[0].counts ?? {}} />}
      <div className="ds-cell" style={{ marginTop: "var(--s4)" }}>
        {live.data?.part.shortage && <Tiles><ShortageFigure short={live.data.part.shortage.short as Q} month={live.data.part.shortage.month} /></Tiles>}
        {live.data?.tariff.at_stake && !("owner" in live.data.tariff.at_stake) && <TariffExposure net={live.data.tariff.at_stake as M} gross={live.data.tariff.at_stake_gross as M} />}
        <div style={{ display: "grid", gap: "var(--s3)", maxWidth: 560 }}>
          <TrustFlag flags={["a look-alike domain", "new bank details"]} />
          <span><SupplierEvent kind="force_majeure" messageId="2026-01-01_example_notice">10 open lines</SupplierEvent></span>
        </div>
      </div>

      <h2>Meaning layer: the agent</h2>
      {live.data?.item.recommendation && <Recommendation rec={live.data.item.recommendation}><Assumptions rec={live.data.item.recommendation} /></Recommendation>}
      <CheckStrip run={live.data?.detail ?? null} />
      {live.data?.detail && <RunTrace run={live.data.detail} runId={live.data.detail.run_id ?? null} />}
      {live.data?.action && <Draft action={live.data.action} />}
      <DecisionHistory decisions={(live.data?.item as { decisions?: { text: string }[] } | undefined)?.decisions} />
    </div>
  );
}

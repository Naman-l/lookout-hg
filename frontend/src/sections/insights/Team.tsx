// Team (PLAN 13, MAPPING 10.1): one row per member the viewer may see, grouped and ordered as the SCM organogram draws the team. The Head of SCM
// sees everyone, a lead their own team, anyone else their own page. Nothing is ranked and no column sorts; no counts of emails, hours or logins.
import { Link, useParams } from "react-router-dom";
import { useMe } from "../../api/useMe";
import { Button, Notice, SectionTitle, Tile, Tiles } from "../../ds";
import { DataTable, TitleCell, type Col } from "../../ds/DataTable";
import { useAskContext } from "../../shell/AskContext";
import { longDate, shortDate } from "../../ui/format";
import { insights, type MemberPage, type MemberSummary } from "./api";
import { Bar, Empty, Facts, Fig, FUNCTIONS, ReadFailed, Sources, useReadError, Vert, WhoDot } from "./ui";
import { Frame } from "./Frame";

/** A team's heading: its lead (the head's own row is headed "Head of SCM") and what the team buys, as the organogram words it. */
function GroupHead({ name, note }: { name: string; note?: string | null }) {
  return (
    <div className="ins-group ins-group-org">
      <span>{name}</span>
      {note && <small>{note.replace(/\s*\n\s*/g, " ")}</small>}
    </div>
  );
}

/** What the organogram says of a member: designation, whom they report to, their desk and their work. */
function OrgFacts({ m }: { m: MemberSummary }) {
  const work = m.responsibilities ?? m.portfolio;
  return (
    <Facts items={[
      ["Designation", m.designation ? <span title={m.designation_full ?? undefined}>{m.designation}{m.designation_full ? <small className="ins-sub"> {m.designation_full}</small> : null}</span> : "—"],
      ["Reports to", m.reports_to && m.reports_to_name ? <Link to={`/insights/team/${encodeURIComponent(m.reports_to)}`}>{m.reports_to_name}</Link> : (m.reports_to_name ?? "—")],
      ...(m.category ? [["Desk", m.category] as [string, string]] : []),
      ["Work", work ? <span className="ins-work">{work}</span> : "—"],
    ]} />
  );
}

const tat = (m: MemberSummary) =>
  m.turnaround.length === 0 ? <span className="ins-fig none">—</span> : (
    <span className="ins-stack">
      {m.turnaround.map((t) => (
        <span key={t.vertical} className="ins-tat"><Vert id={t.vertical} short /><Fig f={t.mine} title={`${m.name}: PR → PO, ${t.name}`} /><small>vertical <Fig f={t.vertical_median} title={`${t.name}: PR → PO, every buyer`} quiet /></small></span>
      ))}
    </span>
  );

const lines = (n: number) => `${n.toLocaleString("en-IN")} ${n === 1 ? "line" : "lines"}`;

function teamCols(): Col<MemberSummary>[] {
  return [
    { id: "who", head: "Member", width: "minmax(170px,1fr)", cell: (m) => <TitleCell title={<Link to={`/insights/team/${encodeURIComponent(m.id)}`}>{m.name}</Link>} sub={m.role} tip={`${m.name} · ${m.designation_full ?? m.designation ?? ""} · ${m.responsibilities ?? m.role}`} /> },
    { id: "open", head: "Open PRs", width: "100px", end: true, label: "Open PRs", cell: (m) => <Fig f={m.open_prs} title={`${m.name}: open PR lines`} sub={m.oldest_open.value != null ? <>oldest <Fig f={m.oldest_open} title="Oldest open PR line" quiet /></> : undefined} /> },
    { id: "po", head: "POs · 30 / 90 days", width: "140px", end: true, label: "POs, 30 days", cell: (m) => <Fig f={m.pos_30_value} title={`${m.name}: POs in 30 days`} sub={<><Fig f={m.pos_30} title="POs released in 30 days" quiet /> · 90 days <Fig f={m.pos_90_value} title={`${m.name}: POs in 90 days`} quiet /></>} /> },
    { id: "tat", head: "PR → PO median", width: "150px", label: "PR → PO", cell: tat },
    { id: "save", head: "vs last price · budget", width: "140px", end: true, label: "vs last price", cell: (m) => <Fig f={m.saving_last} title={`${m.name}: against the previous rate`} sub={<>{m.saving_last.value != null ? `${lines(m.saving_last.refs.length)} · ` : ""}budget <Fig f={m.saving_budget} title={`${m.name}: against budget`} quiet /></>} /> },
    { id: "gone", head: "Cancelled PRs", width: "100px", end: true, label: "Cancelled", hide: "mid", cell: (m) => <Fig f={m.cancelled} title={`${m.name}: PR lines later cancelled`} sub={<><Fig f={m.cancelled_quotes} title="Quotes on cancelled lines" quiet /> in</>} /> },
    { id: "held", head: "A line waited on", width: "120px", end: true, label: "A line waited on", cell: (m) => <Fig f={m.waited_others_line} title={`${m.name}: days a line waited on other functions`} sub={<>on others · SCM <Fig f={m.waited_scm_line} title="Days a line waited on SCM" quiet /></>} /> },
    { id: "cases", head: "Today", width: "90px", end: true, label: "Today", hide: "narrow", cell: (m) => <Fig f={m.workload.cases} title={`${m.name}: Today's cases`} sub={<><Fig f={m.workload.cases_on_you} title="Cases whose move is SCM's" quiet /> on them</>} /> },
  ];
}

/** /insights/team */
export function Team() {
  const { me, choose, ready } = useMe();
  const r = useReadError(() => (me ? insights.team(me) : Promise.reject(new Error("no viewer"))), [me]);
  return (
    <Sources>
      <Frame title="Team" meta={r.data ? <><span>{r.data.period}</span><span className="sep">·</span><span>by {r.data.order}, never by a figure</span></> : undefined}>
        {!me ? (ready ? <Notice><span>Team pages are shown to the member, the Head of SCM and the GM. Say who you are to see yours.</span><Button onClick={() => choose(true)}>Choose who you are</Button></Notice> : null)
          : r.loading ? <TeamSkeleton />
          : r.error ? <ReadFailed e={r.error} what="the Team page" notFound={{ title: "Team", line: "No Team page here." }} />
          : r.data ? <TeamBody d={r.data} /> : null}
      </Frame>
    </Sources>
  );
}

const TeamSkeleton = () => <div className="ins-sk" aria-busy="true" aria-label="Loading the team"><i /><i /><i /><i /></div>;

function TeamBody({ d }: { d: NonNullable<Awaited<ReturnType<typeof insights.team>>> }) {
  if (d.scope === "none") return <Notice>{d.note}</Notice>;
  if (d.scope === "self" && d.members[0]) return (<><Notice>{d.note}</Notice><SelfCard m={d.members[0]} /></>);
  const cols = teamCols();
  const groups = [...new Set(d.members.map((m) => m.group))].map((g) => ({ g, rows: d.members.filter((m) => m.group === g) }));
  return (
    <>
      <p className="ins-lead">{d.note}</p>
      <div className="ins-body">
        {groups.map(({ g, rows }, n) => (
          <section key={g} className="ins-sec">
            <GroupHead name={rows[0].group_name} note={rows[0].group_note} />
            <DataTable label={`Team: ${rows[0].group_name}`} cols={cols} rows={rows} rowKey={(m) => m.id} header={n === 0} two />
          </section>
        ))}
      </div>
      <p className="ins-foot">Teams as the <Link to="/org">organisation chart</Link> draws them. Days held add up the PR-to-payment ladder: each wait is attributed to whoever held the step (SCM, Projects, Vendor, QA, Finance, Management). Lookout counts no emails, hours or logins.</p>
    </>
  );
}

function SelfCard({ m }: { m: MemberSummary }) {
  return (
    <article className="ins-card">
      <header><div><b>{m.name}</b><small>{m.role}{m.groups.length ? ` · ${m.groups.join(", ")}` : ""}</small></div><Button to={`/insights/team/${encodeURIComponent(m.id)}`}>Open your page</Button></header>
      <OrgFacts m={m} />
      <Facts items={[
        ["Open PR lines", <Fig f={m.open_prs} title="Your open PR lines" sub={m.oldest_open.value != null ? <>oldest {m.oldest_open.text}</> : undefined} />],
        ["POs in 30 days", <Fig f={m.pos_30_value} title="POs released in 30 days" sub={m.pos_30.text} />],
        ["POs in 90 days", <Fig f={m.pos_90_value} title="POs released in 90 days" sub={m.pos_90.text} />],
        ["PR → PO median", tat(m)],
        ["Against the last price", <Fig f={m.saving_last} title="Against the previous rate" sub={m.saving_last.note ?? undefined} />],
        ["Against budget", <Fig f={m.saving_budget} title="Against the budget rate" sub={m.saving_budget.note ?? undefined} />],
        ["PR lines later cancelled", <Fig f={m.cancelled} title="PR lines later cancelled" sub={`${m.cancelled_quotes.text} received on them`} />],
        ["A line waited on others", <Fig f={m.waited_others_line} title="Days a line waited on other functions" sub={`SCM ${m.waited_scm_line.text} · ${m.waited_others.text} in all`} />],
        ["Today's cases", <Fig f={m.workload.cases} title="Today's cases" sub={`${m.workload.cases_on_you.text} on you`} />],
      ]} />
    </article>
  );
}

/** /insights/team/:person */
export function TeamPerson() {
  const { person = "" } = useParams();
  const { me, choose, ready } = useMe();
  const r = useReadError(() => (me ? insights.member(person, me) : Promise.reject(new Error("no viewer"))), [person, me]);
  useAskContext(r.data ? { type: "person", id: r.data.id, label: r.data.name } : null);
  const d = r.data;
  return (
    <Sources>
      <Frame back={{ to: "/insights/team", label: "Team" }} title={d?.name ?? "Team"}
        meta={d ? <><span>{d.designation ?? d.role}</span>{d.reports_to_name && <><span className="sep">·</span><span>reports to {d.reports_to_name}</span></>}<span className="sep">·</span><span>{d.groups.join(", ") || "no purchasing group"}</span>{d.verticals.length > 0 && <><span className="sep">·</span><span className="ins-vs">{d.verticals.map((v) => <Vert key={v} id={v} />)}</span></>}<span className="sep">·</span><span>{d.period}</span></> : undefined}
        actions={d ? <Button to={`/brief/${encodeURIComponent(d.id)}`}>Daily brief</Button> : undefined}>
        {!me ? (ready ? <Notice><span>Say who you are: a Team page is shown to the member, the Head of SCM and the GM.</span><Button onClick={() => choose(true)}>Choose who you are</Button></Notice> : null)
          : r.loading ? <TeamSkeleton />
          : r.error ? <ReadFailed e={r.error} what="this Team page" notFound={{ title: "No such member", line: `Nobody called “${person}” is on the SCM team.` }} />
          : d ? <MemberBody d={d} /> : null}
      </Frame>
    </Sources>
  );
}

function MemberBody({ d }: { d: MemberPage }) {
  const maxDays = Math.max(1, ...d.waits.map((w) => w.days.value ?? 0));
  const maxTat = Math.max(1, ...d.turnaround.flatMap((t) => [t.mine.value ?? 0, t.vertical_median.value ?? 0]));
  return (
    <div className="ins-body">
      {d.viewer_note && <Notice>{d.viewer_note}</Notice>}
      <section className="ins-sec">
        <SectionTitle>On the organogram</SectionTitle>
        <OrgFacts m={d} />
        <p className="ins-note">{d.role}. From HG's SCM organogram; see where {d.name.split(" ")[0]} sits on the <Link to="/org">organisation chart</Link>.</p>
      </section>
      <Tiles>
        <Tile figure={<Fig f={d.open_prs} title="Open PR lines" />} label={d.oldest_open.value != null ? `open PR lines · oldest ${d.oldest_open.text}` : "open PR lines"} />
        <Tile figure={<Fig f={d.pos_30_value} title="POs in 30 days" />} label={`${d.pos_30.text} in 30 days`} />
        <Tile figure={<Fig f={d.pos_90_value} title="POs in 90 days" />} label={`${d.pos_90.text} in 90 days`} />
        <Tile figure={<Fig f={d.workload.cases} title="Today's cases" />} label={`on Today · ${d.workload.cases_on_you.text} on you`} />
      </Tiles>

      <section className="ins-sec">
        <SectionTitle>Open PRs and their age</SectionTitle>
        <div className="ins-buckets">
          {d.ageing.map((b) => <div key={b.label}><Fig f={b.lines} title={b.label} /><small>{b.label}</small></div>)}
        </div>
        {d.oldest.length === 0 ? <Empty>No open PR lines on {d.groups.join(", ") || "this member's groups"}.</Empty> : (
          <DataTable label="Oldest open PR lines" rows={d.oldest} rowKey={(x) => x.ref} cols={[
            { id: "pr", head: "PR line", width: "minmax(200px,1fr)", cell: (x) => <TitleCell title={<Link to={`/prs/${x.pr}`}>{x.text || `PR ${x.pr}`}</Link>} sub={`PR ${x.pr} / ${x.item}${x.project_name ? ` · ${x.project_name}` : ""}`} /> },
            { id: "since", head: "Since", width: "100px", label: "since", cell: (x) => shortDate(x.since) },
            { id: "age", head: "Age", width: "80px", end: true, label: "age", cell: (x) => `${x.age_days} days` },
            { id: "rfq", head: "RFQ · quotes", width: "120px", label: "RFQ", hide: "narrow", cell: (x) => (x.rfq_sent ? `${shortDate(x.rfq_sent)} · ${x.quotes_in}` : "not sent") },
            { id: "now", head: "Waiting for", width: "190px", label: "waiting for", cell: (x) => (x.waiting_on ? <span className="ins-inline">{x.rung} · <WhoDot who={x.waiting_on} /></span> : "—") },
          ]} />
        )}
      </section>

      <section className="ins-sec">
        <SectionTitle>PR → PO turnaround, against your vertical</SectionTitle>
        {d.turnaround.length === 0 ? <Empty>No PR line on this member's groups was converted to a PO in the period.</Empty> : (
          <div className="ins-cmp">
            {d.turnaround.map((t) => (
              <div key={t.vertical} className="ins-cmp-r">
                <span className="ins-cmp-l"><Vert id={t.vertical} /></span>
                <span className="ins-cmp-b"><Bar value={t.mine.value ?? 0} max={maxTat} tone="accent" /><Bar value={t.vertical_median.value ?? 0} max={maxTat} tone="muted" /></span>
                <span className="ins-cmp-f"><Fig f={t.mine} title={`PR → PO on ${t.name}: yours`} sub="yours" /><Fig f={t.vertical_median} title={`PR → PO on ${t.name}: every buyer`} sub="vertical" quiet /></span>
              </div>
            ))}
            <p className="ins-note">Median days from PR release to PO; a PR keyed in the day of its PO measures nothing and is left out. Set only against the vertical's own median.</p>
          </div>
        )}
      </section>

      <section className="ins-sec">
        <SectionTitle>Savings</SectionTitle>
        <div className="ins-two">
          {([["Against the last price", d.saving_last_detail, "the previous PO rate for the material at the plant"], ["Against budget", d.saving_budget_detail, "the project's budget rate"]] as const).map(([t, s, what]) => (
            <div key={t} className="ins-box">
              <h3>{t}</h3>
              <b className="ins-big"><Fig f={s.net} title={t} /></b>
              <p className="ins-note">{s.lines ? `${s.net.note}, of ${s.of_lines.toLocaleString("en-IN")} PO lines. Positive: bought below ${what}.` : `No PO line has ${what === "the project's budget rate" ? "a budget rate" : "a previous rate"} to compare with.`}</p>
              {s.lines > 0 && <Facts items={[["Below it", <Fig f={s.below} title={`${t}: below`} sub={s.below.note ?? undefined} />], ["Above it", <Fig f={s.above} title={`${t}: above`} sub={s.above.note ?? undefined} />]]} />}
            </div>
          ))}
        </div>
      </section>

      <section className="ins-sec">
        <SectionTitle>Effort on PRs later cancelled</SectionTitle>
        <Facts items={[
          ["PR lines deleted or short-closed", <Fig f={d.cancelled_detail.lines} title="Cancelled PR lines" sub={`${d.cancelled_detail.prs} PRs`} />],
          ["An RFQ went out on", <Fig f={d.cancelled_detail.rfq_lines} title="Cancelled lines with an RFQ" />],
          ["Enquiries behind them", <Fig f={d.cancelled_detail.enquiries} title="Enquiries (CS)" />],
          ["Vendors asked", <Fig f={d.cancelled_detail.vendors_asked} title="Vendors asked to quote" />],
          ["Quotes received", <Fig f={d.cancelled_detail.quotes} title="Quotes on cancelled lines" />],
        ]} />
      </section>

      <section className="ins-sec">
        <SectionTitle>Days items waited, by function</SectionTitle>
        <div className="ins-waits" role="table" aria-label="Days held by function">
          <div className="ins-wr ins-wh" role="row"><span role="columnheader">Held by</span><span role="columnheader" aria-hidden /><span role="columnheader" className="n">Days</span><span role="columnheader" className="n">Lines</span><span role="columnheader" className="n">Per line</span><span role="columnheader" className="n">On it now</span></div>
          {FUNCTIONS.map((fn) => d.waits.find((w) => w.function === fn)).filter(Boolean).map((w) => (
            <div key={w!.function} className="ins-wr" role="row">
              <span role="cell"><WhoDot who={w!.function} /></span>
              <span role="cell" className="ins-wb"><Bar value={w!.days.value ?? 0} max={maxDays} tone={w!.function === "SCM" ? "accent" : "muted"} /></span>
              <span role="cell" className="n" data-label="days"><Fig f={w!.days} title={`Days held by ${w!.function}`} /></span>
              <span role="cell" className="n" data-label="lines">{w!.lines.toLocaleString("en-IN")}</span>
              <span role="cell" className="n" data-label="per line"><Fig f={w!.per_line} title={`Days per line held by ${w!.function}`} quiet /></span>
              <span role="cell" className="n" data-label="now"><Fig f={w!.now} title={`Lines whose move is ${w!.function}'s`} quiet /></span>
            </div>
          ))}
        </div>
        <p className="ins-note">The ladder attributes every gap between two steps to whoever held it (release: Projects; RFQ, CS and PO: SCM; quotes and delivery: the vendor; inspection: QA; payment: Finance; a CS above the DoA threshold: Management). This is where purchases waited, not a measure of anyone's hours.</p>
      </section>

      <section className="ins-sec">
        <SectionTitle>Workload</SectionTitle>
        <Facts items={[
          ["Open PR lines", <Fig f={d.workload.open_pr_lines} title="Open PR lines" />],
          ["Open PO lines", <Fig f={d.workload.open_po_lines} title="Open PO lines" sub={<Fig f={d.workload.open_po_value} title="Open value" quiet />} />],
          ["Today's cases", <Fig f={d.workload.cases} title="Today's cases" sub={<><Fig f={d.workload.cases_on_you} title="Cases on them" quiet /> whose move is SCM's</>} />],
        ]} />
      </section>
      <p className="ins-foot">As of {longDate(d.as_of)}. No ranking, and no counts of emails, hours or logins.</p>
    </div>
  );
}


import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useResource } from "../api/useResource";
import { useMe } from "../api/useMe";
import type { Action, ActionItem, BuildReadiness, PoLine, ReadyPart } from "../api/types";
import { RobotIcon, useRobots, type Robot } from "../components/domain";
import { NotFound } from "../ds";
import { useAskContext } from "../shell/AskContext";
import { shortDate } from "../ui/format";
import { caseShort, isRollup } from "../ui/cases";
import { first, owners, statusOf, type Status } from "./Today";
import { myChosenCases, myDraftCases } from "../components/domain/caseStatus";
import { actBy } from "../components/domain/caseStatus";
import "./build.css";

/** A robot's build page (Robots r3): can we build this robot's plan? One answer sentence and a three-month strip, the cases that put robots short,
 * then every problem part of the build, worst first, with its status, case and buyer. Everything else is one link away. */

const AT_RISK = new Set(["after_build", "undated", "past_due", "disrupted"]);
const MON = (m: string) => new Date(`${m}-01T00:00:00Z`).toLocaleString("en-US", { month: "short", timeZone: "UTC" });
const MONTH = (m: string) => new Date(`${m}-01T00:00:00Z`).toLocaleString("en-US", { month: "long", timeZone: "UTC" });
const nextMonth = (m: string, n: number) => { const [y, mo] = m.split("-").map(Number); const d = new Date(Date.UTC(y, mo - 1 + n, 1)); return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`; };
const daysBetween = (a: string, b: string) => Math.round((Date.parse(b) - Date.parse(a)) / 864e5);
const range = (xs: string[]) => { const s = [...xs].sort(); return s.length === 0 ? "" : s[0] === s[s.length - 1] ? shortDate(s[0]) : `${shortDate(s[0])} – ${shortDate(s[s.length - 1])}`; };
const span = (ns: number[]) => { const lo = Math.min(...ns), hi = Math.max(...ns); return lo === hi ? `${lo} day${lo === 1 ? "" : "s"}` : `${lo}–${hi} days`; };
/** "Motor, BLDC, 48 V …" -> "Motor": the part as a buyer names it on a card; later names start lower case unless they are an acronym. */
const partWord = (label: string | null | undefined, later: boolean) => {
  let w = (label ?? "").split(",")[0].trim();
  if (/^[A-Z]{5,}$/.test(w)) w = w[0] + w.slice(1).toLowerCase();      // a shouted record ("MOTOR") reads as a word; short acronyms (PCBA) stay
  return later && /^[A-Z][a-z]/.test(w) ? w[0].toLowerCase() + w.slice(1) : w; };
/** "<Robot name> tote-handling AMR, final assembly" -> "Tote-handling AMR": the description without the name and the assembly word. */
const descriptor = (desc: string | undefined, name: string) => { const d = (desc ?? "").replace(name, "").replace(/,\s*final assembly$/i, "").trim(); return d ? d[0].toUpperCase() + d.slice(1) : ""; };

type Short = { item: ActionItem; robots: number };

/** "Motor, BLDC, 48 V 400 W, 86 mm frame" -> "Motor, BLDC": the name a buyer says; a shouted record ("PCBA, I/O EXPANSION") reads in sentence case, acronyms stay. */
const ACRONYMS = new Set(["PCBA", "BLDC"]);
const partTitle = (label: string | null | undefined) => {
  const name = (label ?? "").split(", ").slice(0, 2).join(", ");
  if (name !== name.toUpperCase()) return name;
  return name.replace(/[A-Za-z]{4,}/g, (w, at: number) => (ACRONYMS.has(w) ? w : at === 0 ? w[0] + w.slice(1).toLowerCase() : w.toLowerCase()));
};

/** "Drive module assembly, <robot>" -> "Drive module"; "CHASSIS ASSEMBLY, <ROBOT>" -> "Chassis": the module a planner kits, as a caption under a part. */
const moduleName = (label: string | null | undefined) => {
  const l = (label ?? "").trim();
  if (/,\s*final assembly$/i.test(l)) return "Final assembly";
  let w = l.split(",")[0].replace(/\s*\(common\)$/i, "").replace(/\s+(assembly|module)$/i, "").trim();
  if (w === w.toUpperCase()) w = w[0] + w.slice(1).toLowerCase();
  return w;
};

export function Build() {
  const { product = "", month = "" } = useParams();
  const { me } = useMe();
  const robots = useRobots();
  const robot: Robot | undefined = robots.find((r) => r.id === product);
  const ready = useResource(() => api.readiness(product, month), [product, month]);
  // The card's next two months read their own readiness (a month with no build planned reads "—").
  const ready2 = useResource(() => api.readiness(product, nextMonth(month, 1)).catch(() => null), [product, month]);
  const ready3 = useResource(() => api.readiness(product, nextMonth(month, 2)).catch(() => null), [product, month]);
  const items = useResource(() => api.actionItems(), []);
  const forecast = useResource(() => api.forecast(), []);
  const orders = useResource(() => api.orders().catch(() => [] as PoLine[]), []);
  const acts = useResource(() => api.actions().catch(() => [] as Action[]), []);
  const health = useResource(api.health, []);
  const self = useResource(() => api.partDetail(product).catch(() => null), [product]);
  const d: BuildReadiness | null = ready.data ?? null;
  const name = robot?.name ?? d?.product.label ?? product;
  const shortName = name.split(" ")[0];
  useAskContext(name ? { type: "product", id: product, label: name } : null);

  const draftOwner = useMemo(() => new Map((acts.data ?? []).map((a) => [a.action_id, (a as Action & { owner?: string | null }).owner ?? ""])), [acts.data]);
  const boot = useResource(api.health).data?.boot ?? "";
  const asOf = health.data?.as_of ?? null;
  const myDrafts = useMemo(() => myDraftCases(acts.data, me), [acts.data, me]);
  const myChosen = useMemo(() => myChosenCases(acts.data, me), [acts.data, me]);
  const status = (i: ActionItem): Status => statusOf(i, me, draftOwner, boot, myDrafts, myChosen);
  const all = items.data ?? [];
  const byKey = new Map(all.map((i) => [i.key, i]));

  // Robots short of this robot, per month, per case (each case's own count; the month's shortfall is the worst one, never a sum).
  const shortIn = (m: string): Short[] => all.flatMap((i) => (i.robots_short ?? []).filter((r) => r.product.id === product && r.month === m).map((r) => ({ item: i, robots: r.robots })))
    .sort((a, b) => b.robots - a.robots || a.item.key.localeCompare(b.item.key));
  const worst = (m: string) => Math.max(0, ...shortIn(m).map((s) => s.robots));

  // The parts of this build, once each (a part can sit in two sub-assemblies).
  const parts = useMemo(() => {
    const seen = new Map<string, ReadyPart>();
    for (const g of d?.groups ?? []) for (const p of g.parts ?? []) if (!seen.has(p.part.id)) seen.set(p.part.id, p);
    return [...seen.values()];
  }, [d]);
  const moduleOf = useMemo(() => {
    const m = new Map<string, string>();
    for (const g of d?.groups ?? []) for (const p of g.parts ?? []) if (!m.has(p.part.id)) m.set(p.part.id, moduleName(g.assembly.label));
    return m;
  }, [d]);
  const late = parts.filter((p) => AT_RISK.has(p.state));
  const noOrder = parts.filter((p) => p.state === "no_order");
  const promise = useMemo(() => new Map((orders.data ?? []).map((l) => [l.ref.id, l])), [orders.data]);
  const counted = (key: string) => (byKey.get(key)?.robots_short ?? []).some((r) => r.product.id === product && shownOf(r.month));
  const shownOf = (m: string) => [0, 1, 2].some((n) => nextMonth(month, n) === m);

  // The months: this build and the next two (past the last open order nothing is computed, and a blank would read as fine).
  const plan = (forecast.data ?? []).find((f) => f.product === name)?.months ?? [];
  const months = [0, 1, 2].map((n) => nextMonth(month, n)).map((m) => ({ m, planned: plan.find((x) => x.month === m)?.units })).filter((x) => x.planned != null) as { m: string; planned: number }[];

  // The month the page is about: this build, or (when it is clear) the first shown month that is short (UX/BUYER review).
  const shownMonths = months.map((x) => x.m);
  const focus = worst(month) > 0 ? month : shownMonths.find((m) => worst(m) > 0) ?? month;
  // What stands in the way: the cases that count this robot short in a shown month, then the cases holding one of its problem parts (team lists last).
  // A case that only names this robot (a supplier risk with no part of this build in trouble) is left to "+ N more on Today" (BUYER r2 review).
  const holding = new Set(late.flatMap((p) => p.cases ?? []));
  const rank = (i: ActionItem) => {
    const mine = (i.robots_short ?? []).filter((r) => r.product.id === product);
    if (mine.some((r) => r.month === focus)) return 0;
    if (mine.some((r) => shownMonths.includes(r.month))) return 1;
    if (i.key.startsWith("risk:") && (holding.has(i.key) || (i.robots ?? []).some((r) => r.id === product))) return 2;
    if (!holding.has(i.key)) return 9;
    return isRollup(i.key) ? 4 : 3;
  };
  const related = all.filter((i) => rank(i) < 9).sort((a, b) => rank(a) - rank(b) || (a.act_by ?? "9999").localeCompare(b.act_by ?? "9999"));
  const cases = related.filter((i) => rank(i) !== 2 || holding.has(i.key));
  const elsewhere = related.length - Math.min(4, cases.length);

  // The case a part sits in: one that counts robots short here first, then a named cause before a team list.
  const caseOf = (p: ReadyPart): ActionItem | null => {
    const cs = (p.cases ?? []).map((k) => byKey.get(k)).filter((i): i is ActionItem => !!i);
    return cs.sort((a, b) => Number(counted(b.key)) - Number(counted(a.key)) || Number(isRollup(a.key)) - Number(isRollup(b.key)))[0] ?? null;
  };
  const buyerOf = (p: ReadyPart) => [...new Set((p.po_lines ?? []).map((l) => promise.get(l)?.buyer).filter((b): b is string => !!b).map(first))].join(" · ");
  const daysLate = (p: ReadyPart) => (p.arrives && asOf ? daysBetween(p.arrives, asOf) : 0);
  const rankOf = (p: ReadyPart) => (p.state === "disrupted" ? 0 : p.state === "past_due" ? 1 : p.state === "undated" ? 2 : 3);
  // Worst first: force majeure, past due (most days first), no promise date, then the late parts with no case before those with one (latest date first).
  const rows = late.map((p) => ({ p, cs: caseOf(p) })).sort((a, b) => rankOf(a.p) - rankOf(b.p)
    || (rankOf(a.p) === 1 ? daysLate(b.p) - daysLate(a.p) : 0)
    || (rankOf(a.p) === 3 ? Number(!!a.cs) - Number(!!b.cs) : 0)
    || (b.p.arrives ?? "").localeCompare(a.p.arrives ?? ""));
  const noCase = rows.filter((r) => !r.cs).map((r) => r.p);

  // The card stays put; the cases and parts scroll below it, from the top for each robot and month (Khalid: fixed headers, section scrolls).
  const bodyRef = useRef<HTMLDivElement>(null);
  useEffect(() => { if (bodyRef.current) bodyRef.current.scrollTop = 0; }, [product, month]);
  if (ready.error) return <NotFound title="Build not found" line={`No build of ${product} is planned for ${month}.`} />;
  const loading = !d || !items.data || !forecast.data;
  const units = d?.units ?? 0;
  const bought = Object.entries(d?.counts ?? {}).filter(([k]) => k !== "in_house").reduce((a, [, v]) => a + (v as number), 0);
  const tone = robot ? (robot.slot % 3) + 1 : 1;
  const style = { "--sel": `var(--robot-${tone})` } as CSSProperties;

  // Clear to build: the latest promised date among the parts that land after the month.
  const lastLand = [...parts.filter((p) => p.state === "after_build" && p.arrives).map((p) => p.arrives as string)].sort().pop();

  return (
    <div className="rbp">
      <section className={`rbq t${tone}`} style={style} aria-busy={loading}>
        <div className="rbp-id">
          {robot && <RobotIcon slot={robot.slot} size={20} />}
          <h1>{name}</h1>
          <span className="rbp-desc">{self.data ? [descriptor(self.data.part.description, name), product].filter(Boolean).join(" · ") : product}</span>
        </div>
        <table className="rbq-t">
          <thead>
            <tr><th scope="col">Next 3 months · {name}</th>{months.map(({ m }) => <th scope="col" key={m}>{MON(m)} {m.slice(0, 4)}{m === month && <small>this month</small>}</th>)}</tr>
          </thead>
          {loading ? <tbody><tr><th scope="row"><span className="skel" style={{ width: 120 }} /></th>{months.map(({ m }) => <td key={m}><span className="skel" style={{ width: 48 }} /></td>)}</tr></tbody> : (
            <tbody>
              <tr><th scope="row">Planned builds <small>robots</small></th>{months.map(({ m, planned }) => <td key={m}>{planned}</td>)}</tr>
              <tr><th scope="row">Short, up to <small>robots</small></th>{months.map(({ m }) => <td key={m} className={worst(m) ? "neg" : "z"}>{worst(m) || "—"}</td>)}</tr>
              <tr><th scope="row">Buildable after the cases <small>robots</small></th>{months.map(({ m, planned }) => <td key={m}>{Math.max(0, planned - worst(m))}</td>)}</tr>
              <tr><th scope="row">Limited by</th>{months.map(({ m }) => {
                const drv = [...new Map(shortIn(m).map((x) => [x.item.key, x.item])).values()];
                return <td key={m} className="by">{drv.length ? drv.map((i, k) => <span key={i.key}>{k > 0 && " · "}<Link to={`/items/${encodeURIComponent(i.key)}`}>{caseShort(i)}</Link></span>) : "—"}</td>;
              })}</tr>
              <tr><th scope="row">Parts late or undated <small>parts</small></th>{months.map(({ m }, k) => {
                const c = [d, ready2.data, ready3.data][k]?.counts;
                const late = c ? (c.past_due ?? 0) + (c.disrupted ?? 0) + (c.after_build ?? 0) + (c.undated ?? 0) : null;
                return <td key={m}>{late ?? "—"}{k === 0 && lastLand && <small>clear ≥ {shortDate(lastLand)}</small>}</td>;
              })}</tr>
            </tbody>
          )}
        </table>
        {d && !d.stock_counted && <p className="rbq-n">No open order: {d.counts.no_order ?? 0} parts · stock on hand not on file, so short is an upper bound</p>}
      </section>

      <div className="rbp-body" ref={bodyRef}>
      <section className="rbp-s">
        <h2>What stands in the way</h2>
        {loading ? [0, 1, 2].map((k) => <div className="rbp-row ghost" key={k}><span className="skel" style={{ width: "70%" }} /></div>) :
          cases.length === 0 ? <p className="rbp-none">No case holds a part of this build.</p> : (
            <div className="rbp-tbl">
              <div className="rbp-row hd"><span>Case</span><span>Robots short</span><span>Act by</span><span style={{ textAlign: "right" }}>Status</span></div>
              {cases.slice(0, 4).map((i) => <CaseRow key={i.key} i={i} st={status(i)} product={product} months={shownMonths} parts={parts} asOf={asOf} lines={promise} robotKey={robot?.key ?? ""} />)}
            </div>
          )}
        {!loading && elsewhere > 0 && <p className="rbp-more"><Link to={`/?r=${robot?.key ?? ""}`}>+ {elsewhere} more on Today</Link></p>}
      </section>

      <section className="rbp-s">
        <h2>{MONTH(month)}’s problem parts
          <small>{late.length} of {bought} bought part{bought === 1 ? "" : "s"}{noCase.length ? ` · ${noCase.length} with no case${range(noCase.map((p) => p.arrives).filter(Boolean) as string[]) ? `, landing ${range(noCase.map((p) => p.arrives).filter(Boolean) as string[])}` : ""}` : ""}</small>
          <Link to={`/parts/bom/${encodeURIComponent(product)}`}>Bill of materials →</Link>
        </h2>
        {loading ? <div className="rbp-row ghost"><span className="skel" style={{ width: "60%" }} /></div> : rows.length === 0 ? <p className="rbp-none">No bought part of this build is late, past due or under a force-majeure notice.</p> : (
          <table className="rbp-pt">
            <thead><tr><th>Part · module</th><th>Status</th><th>Case</th><th>Buyer</th></tr></thead>
            <tbody>
              {rows.map(({ p, cs }) => (
                <tr key={p.part.id}>
                  <td><Link className="nm" to={`/parts/${encodeURIComponent(p.part.id)}`}>{partTitle(p.part.label)}</Link><small>{p.part.id}</small><span className="md">{moduleOf.get(p.part.id)}</span></td>
                  <td>{p.state === "disrupted" ? <><span className="fm">force majeure</span> · no date</>
                    : p.state === "past_due" ? <><span className="pd">{daysLate(p)} d past due</span> · no new date</>
                    : p.state === "undated" ? <span className="pd">no promise date</span>
                    : <>lands {p.arrives ? shortDate(p.arrives) : "no date"} · after {MONTH(month)}</>}</td>
                  <td>{cs ? caseShort(cs) : <span className="nc">no case</span>}</td>
                  <td>{buyerOf(p) || "Unassigned"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {!loading && (noOrder.length > 0 || noCase.length > 0) && <StockCheck noOrder={noOrder} late={noCase} name={name} units={units} month={month} buyerOf={buyerOf} stockOnFile={!!d?.stock_counted} />}
      </section>

      <p className="rbp-foot">More on the {shortName}: <Link to={`/suppliers?r=${robot?.key ?? ""}`}>Its suppliers</Link> · <Link to={`/orders?r=${robot?.key ?? ""}`}>Its open orders</Link> · <Link to="/forecast">Forecast</Link></p>
      </div>
    </div>
  );
}

function CaseRow({ i, st, product, months, parts, asOf, lines, robotKey }: { i: ActionItem; st: Status; product: string; months: string[]; parts: ReadyPart[]; asOf: string | null; lines: Map<string, PoLine>; robotKey: string }) {
  const counts = (i.robots_short ?? []).filter((r) => r.product.id === product && months.includes(r.month)).sort((a, b) => a.month.localeCompare(b.month)).map((r) => `${MON(r.month)} ${r.robots}`);
  const held = parts.filter((p) => (p.cases ?? []).includes(i.key) && AT_RISK.has(p.state));
  const words = [...new Set(held.map((p) => partWord(p.part.label, false)))].map((w, k) => (k ? partWord(w, true) : w));
  const when: string[] = [];
  if (held.some((p) => p.state === "disrupted")) when.push("force majeure · no date");
  const lands = held.filter((p) => p.state === "after_build" && p.arrives).map((p) => p.arrives as string);
  if (lands.length) when.push(`lands ${range(lands)}`);
  if (held.some((p) => p.state === "undated")) when.push("no date");
  const pd = held.filter((p) => p.state === "past_due" && p.arrives && asOf).map((p) => daysBetween(p.arrives as string, asOf as string));
  // A case that counts no robots short here says how late its parts are in the "robots short" column instead.
  const late = pd.length ? `${counts.length ? "" : `${words.length === 1 ? words[0].toLowerCase() : "parts"} `}late ${counts.length ? span(pd) : span(pd).replace(/ days?$/, " d")}` : "";
  if (late && counts.length) when.push(late);
  // A team list says only its share on this robot: the lines that feed it (BUYER review).
  const feed = isRollup(i.key) ? held.flatMap((p) => p.po_lines ?? []).map((l) => lines.get(l)).filter((l): l is PoLine => !!l && (i.key !== "deadline:chase" || (l.days_past_due ?? 0) > 0)) : [];
  const who = isRollup(i.key) && feed.length ? [...new Set(feed.map((l) => first(l.buyer)))] : owners(i).map(first);
  const share = isRollup(i.key) && feed.length ? `${feed.length} line${feed.length === 1 ? "" : "s"} feed ${robotKey}` : "";
  const sub = [share, words.join(", "), ...when].filter(Boolean).join(" · ");
  const owner = who[0] && !st.word.includes(who[0]) ? who.join(" · ") : "";
  const act = actBy(i, asOf);
  return (
    <Link className="rbp-row" to={`/items/${encodeURIComponent(i.key)}`}>
      <div>
        <div className="rbp-t">{i.title}</div>
        {sub && <div className="rbp-sub">{sub}</div>}
      </div>
      <span className={`rbp-sh${counts.length ? "" : " z"}`}>{counts.length ? counts.join(" · ") : late ? `${late} · not counted` : "none counted"}</span>
      <span className={`rbp-by${act && asOf && act < asOf ? " past" : ""}`}>{act ? shortDate(act) : ""}</span>
      <span className={`rbp-w k-${st.tone}`} title={st.full}>{st.word}{owner && <small>{owner}</small>}</span>
    </Link>
  );
}

/** The stock check: what is on hand of the parts with no open order and of those landing late with no case behind them. It is copied for the
 * stockroom to answer; the app has no call that stages a note to a free recipient, so nothing is staged and the button says what it does. */
function StockCheck({ noOrder, late, name, units, month, buyerOf, stockOnFile }: { noOrder: ReadyPart[]; late: ReadyPart[]; name: string; units: number; month: string; buyerOf: (p: ReadyPart) => string; stockOnFile: boolean }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number>();
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const need = (p: ReadyPart) => `needed in ${MON(month)} ${Number(p.need.value).toLocaleString("en-US")} ${p.need.uom}`;
  const copy = async () => {
    const text = [`Stock check for the stockroom: what is on hand for the ${MONTH(month)} build of ${units} ${name}?`,
      noOrder.length ? `No open order (${noOrder.length}):\n${noOrder.map((p) => `  ${p.part.id} · ${partTitle(p.part.label)} · ${need(p)}`).join("\n")}` : "",
      late.length ? `Landing late, no case (${late.length}):\n${late.map((p) => `  ${p.part.id} · ${partTitle(p.part.label)} · ${need(p)} · promised ${p.arrives ? shortDate(p.arrives) : "no date"} · ${p.supplier?.label ?? "no supplier"} · ${(p.po_lines ?? []).join(", ") || "no PO line"} · buyer ${buyerOf(p) || "unassigned"}`).join("\n")}` : ""]
      .filter(Boolean).join("\n\n");
    try { await navigator.clipboard.writeText(text); } catch { /* clipboard refused: the toast still says what was meant */ }
    setCopied(true);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setCopied(false), 2000);
  };
  const lead = [noOrder.length ? `${noOrder.length} with no order` : "", late.length ? `${late.length} landing late` : ""].filter(Boolean).join(" + ");
  return (
    <div className="rbp-ask">
      <span><b>{lead}</b>{stockOnFile ? "" : " · stock on hand is not on file"}</span>
      <button type="button" className="ds-btn b9" onClick={copy}>Copy the stock check for the stockroom</button>
      <div className={`rbp-toast${copied ? " on" : ""}`} role="status" aria-live="polite">{copied ? "Copied" : ""}</div>
    </div>
  );
}

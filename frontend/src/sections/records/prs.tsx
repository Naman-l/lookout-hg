// PRs (MAPPING 8.6, 8.10, 8.11): ME5A lines with status, age or turnaround, the CS behind each and the plain-word flags; one PR with each line's ladder.
import { useMemo, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client";
import { useAskContext } from "../../shell/AskContext";
import { invalidate, useResource } from "../../api/useResource";
import { useMe } from "../../api/useMe";
import type { Ladder, PrLine } from "../../api/types";
import { Disclose, EmptyState, PageHeader, Tile, Tiles } from "../../ds";
import { DataTable, TitleCell, type Col } from "../../ds/DataTable";
import { FilterBar, type FilterDef } from "../../ds/FilterBar";
import { LoadError } from "../../ds/LoadError";
import { VERTICALS } from "../../components/domain/Vertical";
import { baseOf, enIn, qty } from "../../ui/format";
import { LadderView, ladderLine } from "./Ladder";
import { Block, Flags, ListTitle, LoadingRows, PageState, ProjectPicker, RecordsTabs, RefLink, WhoSwitch, day, days, lineTo, plural, projectMatches, rs, useAsOf, useMore, useProjects, useUrl } from "./shared";

const STATUS: Record<string, string> = { open: "Open", converted: "Converted to a PO", deleted: "Deleted", closed: "Closed" };

/** Where a PR line stands, in a word and a line under it: how long it has waited, or how long it took to become a PO. */
export function PrStatus({ l }: { l: PrLine }) {
  if (l.status === "open") {
    const step = l.quotes_in ? `${plural(l.quotes_in, "quote")} in` : l.rfq_sent ? `RFQ out ${day(l.rfq_sent)}` : l.released ? "released" : "not released";
    return <span>Open<small>{l.age_days != null ? `${days(l.age_days)} · ` : ""}{step}</small></span>;
  }
  if (l.status === "converted") {
    return <span>PO {l.po_date ? day(l.po_date) : ""}<small>{l.turnaround_days != null ? `in ${days(l.turnaround_days)}` : l.flags.some((f) => /day of its PO/.test(f)) ? "keyed in the PO's day" : "turnaround not measured"}</small></span>;
  }
  return <span>{STATUS[l.status] ?? l.status}{l.changed_on && <small>{day(l.changed_on)}</small>}</span>;
}

/** A line's second row: its id, then any plain-word flag it carries ("PO with no PR"), so a flag shows at every width. */
export const LineSub = ({ id, flags }: { id: ReactNode; flags: string[] }) => <>{id}{flags.map((f) => <span key={f} className="rc-flag"> · {f}</span>)}</>;

/** PR lines as a table: line (with its flags), project, quantity and value, buyer, raised and released, needed by, status. */
export function PrTable({ rows, label, to = true, project = true }: { rows: PrLine[]; label: string; to?: boolean; project?: boolean }) {
  const { shown, more } = useMore(rows, 150, `${rows.length}|${rows[0]?.ref.id}`);
  const cols: Col<PrLine>[] = [
    { id: "l", head: "PR line", width: "minmax(0,1fr)", cell: (l) => <TitleCell title={l.text || l.material?.label || l.ref.id} tip={[l.text, ...l.flags].join("\n")} sub={<LineSub id={`PR ${l.ref.id}${l.cs ? ` · ${l.cs}` : ""}`} flags={l.flags} />} /> },
    ...(project ? [{ id: "p", head: "Project", width: "120px", label: "Project", cell: (l: PrLine) => l.project?.label ?? <span className="rc-warn">no project</span> }] : []),
    { id: "q", head: "Quantity", width: "120px", end: true, label: "Qty", cell: (l) => <span>{qty(l.qty, l.uom)}<small title={l.value ? "PR quantity × the last PO rate for the material at the plant (a PR has no price)" : "No PO rate on file for this material"}>{l.value ? rs(l.value) : "no rate"}</small></span> },
    { id: "b", head: "Buyer", width: "128px", hide: "mid", label: "Buyer", cell: (l) => <span>{l.buyer ?? <span className="none">—</span>}<small>{l.purch_group}</small></span> },
    { id: "r", head: "Raised", width: "112px", label: "Raised", cell: (l) => <span>{day(l.created)}<small>{l.released ? `released ${day(l.released)}` : "not released"}</small></span> },
    { id: "n", head: "Needed by", width: "96px", label: "Needed by", cell: (l) => day(l.needed_by) },
    { id: "s", head: "Status", width: "136px", label: "Status", cell: (l) => <PrStatus l={l} /> },
  ];
  return <><DataTable label={label} rows={shown} rowKey={(l) => l.ref.id} cols={cols} to={to ? (l) => lineTo("pr", l.ref.id) : undefined} two />{more}</>;
}

/** Yours or everyone's, defaulting to yours when the viewer has lines in the list. */
export function useWho(u: ReturnType<typeof useUrl>, me: string | null, has: boolean) {
  const raw = u.get("who");
  const who: "mine" | "all" = raw === "mine" || raw === "all" ? raw : me && has ? "mine" : "all";
  return { who, setWho: (w: "mine" | "all") => u.set({ who: w }) };
}

/** PRs: every ME5A line, open ones first by how long they have waited. */
export function Prs() {
  useAsOf();
  const { me } = useMe();
  const r = useResource(() => api.prs());
  const pj = useProjects();
  const u = useUrl();
  const all = r.data ?? [];
  const mine = useMemo(() => all.filter((l) => me && l.buyer === me), [all, me]);
  const { who, setWho } = useWho(u, me, mine.length > 0);
  const base = who === "mine" ? mine : all;
  const st = u.get("status") ?? "open";
  const f = { status: st === "any" ? undefined : st, flag: u.get("flag"), vertical: u.get("vertical"), buyer: who === "all" ? u.get("buyer") : undefined };
  const project = u.get("project");
  const q = (u.get("q") ?? "").trim().toLowerCase();
  const vert = (l: PrLine) => pj.byId.get(l.project?.id ?? "")?.vertical;
  const count = (pred: (l: PrLine) => boolean) => base.filter(pred).length;
  const flags = [...new Set(all.flatMap((l) => l.flags))].sort();
  const buyers = [...new Set(all.map((l) => l.buyer).filter(Boolean) as string[])].sort();
  const filters: FilterDef[] = [
    { id: "status", label: "Status", options: Object.entries(STATUS).map(([value, label]) => ({ value, label, count: count((l) => l.status === value) })) },
    { id: "flag", label: "Flag", options: flags.map((x) => ({ value: x, label: x, count: count((l) => l.flags.includes(x)) })) },
    { id: "vertical", label: "Vertical", options: VERTICALS.map((v) => ({ value: v.id, label: v.name, count: count((l) => vert(l) === v.id) })).filter((o) => o.count) },
    ...(who === "all" ? [{ id: "buyer", label: "Buyer", options: buyers.map((b) => ({ value: b, label: b, count: count((l) => l.buyer === b) })) }] : []),
  ];
  const rows = base.filter((l) =>
    (!f.status || l.status === f.status) && (!f.flag || l.flags.includes(f.flag)) && (!f.vertical || vert(l) === f.vertical) && (!f.buyer || l.buyer === f.buyer)
    && (!project || l.project?.id === project)
    && (!q || `${l.ref.id} ${l.text} ${l.material?.id ?? ""} ${l.project?.label ?? ""} ${l.requisitioner ?? ""} ${l.cs ?? ""} ${l.plant} ${l.po_line?.id ?? ""}`.toLowerCase().includes(q) || projectMatches(pj.byId.get(l.project?.id ?? ""), q)));
  const sorted = [...rows].sort((a, b) => (a.status === "open" && b.status === "open" ? (b.age_days ?? 0) - (a.age_days ?? 0) : a.status === "open" ? -1 : b.status === "open" ? 1 : b.created.localeCompare(a.created)));
  const valued = rows.filter((l) => l.value);
  const sum = valued.reduce((s, l) => s + (baseOf(l.value) ?? 0), 0);
  return (
    <div className="rc pg-fix">
      <RecordsTabs />
      <ListTitle title="PRs" sub="Purchase requisition lines from SAP (ME5A). A PR has no price: its value is the quantity at the last PO rate for the material at that plant."
        right={<WhoSwitch me={me} value={who} onChange={setWho} mine={r.data ? mine.length : undefined} all={r.data ? all.length : undefined} />} />
      <div className="rc-bar">
        <FilterBar label="PR lines" search={u.get("q") ?? ""} onSearch={(s) => u.set({ q: s })} placeholder="PR, material, project, CS" filters={filters}
          value={f} onChange={(v) => u.set({ status: v.status ?? "any", flag: v.flag, vertical: v.vertical, buyer: v.buyer })} />
        <ProjectPicker projects={pj.list} value={project} onChange={(id) => u.set({ project: id })} />
      </div>
      {r.data && (
        <p className="rc-count" role="status">
          {enIn(rows.length)} {rows.length === 1 ? "line" : "lines"}{f.status === "open" ? ", longest waiting first" : ""}
          {valued.length > 0 && <> · {rs(sum)} at the last PO rate{valued.length < rows.length ? ` (${enIn(rows.length - valued.length)} with no rate)` : ""}</>}
          {who === "mine" && me && <> · {me}'s purchasing group</>}
        </p>
      )}
      <div className="pg-body">
        {r.loading && !r.data ? <LoadingRows /> : r.error ? <LoadError what="PR lines" retry={invalidate} />
          : rows.length === 0 ? <EmptyState>{who === "mine" && !mine.length ? "No PR lines on your purchasing group. Everyone shows the rest." : "No PR line matches."}</EmptyState>
          : <PrTable rows={sorted} label="PR lines" />}
      </div>
    </div>
  );
}

/** Each line's ladder: one line saying where it stands; opened, the fourteen rungs. A PR or PO of up to three lines shows them all open. */
export function LineLadders({ items }: { items: { key: string; title: ReactNode; sub?: ReactNode; ladder?: Ladder }[] }) {
  const [open, setOpen] = useState<Set<string>>(() => new Set(items.length <= 3 ? items.map((i) => i.key) : items.slice(0, 1).map((i) => i.key)));
  const flip = (k: string) => setOpen((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  return (
    <div className="rc-ladders">
      {items.map((i) => (
        <div key={i.key} className="rc-ladder">
          <div className="rc-ladder-h">
            <span className="rc-ladder-t"><b>{i.title}</b>{i.sub && <small>{i.sub}</small>}</span>
            {i.ladder && !open.has(i.key) && <span className="rc-ladder-s">{ladderLine(i.ladder)}</span>}
            {i.ladder && <Disclose open={open.has(i.key)} onClick={() => flip(i.key)}>{open.has(i.key) ? "Hide steps" : "All 14 steps"}</Disclose>}
          </div>
          {!i.ladder ? <p className="rc-note">No ladder on file for this line.</p> : open.has(i.key) && <LadderView ladder={i.ladder} />}
        </div>
      ))}
    </div>
  );
}

/** One PR: its lines and, for each, the PR-to-payment ladder with whose move every wait was. */
export function PrPage() {
  const { no = "" } = useParams();
  useAsOf();
  const r = useResource(() => api.pr(no), [no]);
  useAskContext(r.data ? { type: "pr", id: no, label: `PR ${no}` } : null);
  if (!r.data) return <PageState what={`PR ${no}`} error={r.error} kind="PR" />;
  const d = r.data;
  const first = d.lines[0];
  const ladderOf = (l: PrLine) => d.ladders.find((x) => x.pr_line?.id === l.ref.id || x.subject.id === l.ref.id);
  const projects = [...new Map(d.lines.filter((l) => l.project).map((l) => [l.project!.id, l.project!])).values()];
  const open = d.lines.filter((l) => l.status === "open");
  const value = d.lines.reduce((s, l) => s + (baseOf(l.value) ?? 0), 0);
  const waits = d.ladders.map((l) => l.waiting_on).filter(Boolean) as string[];
  const waitOn = [...new Set(waits)];
  return (
    <div className="rc rc-page">
      <RecordsTabs />
      <PageHeader flow back={{ to: "/prs", label: "PRs" }} title={`PR ${d.pr}`}
        meta={<>
          {projects.length ? projects.map((p, k) => <span key={p.id}>{k > 0 && ", "}<RefLink r={p} id={false} /></span>) : <span className="rc-warn">no project</span>}
          <span className="sep">·</span><span>plant {first.plant}</span>
          {first.buyer && <><span className="sep">·</span><span>{first.buyer} ({first.purch_group})</span></>}
          {first.requisitioner && <><span className="sep">·</span><span>raised by {first.requisitioner}</span></>}
          <span className="sep">·</span><span>{day(first.created)}{first.released ? `, released ${day(first.released)}` : ", not released"}</span>
        </>} />
      <Tiles>
        <Tile figure={enIn(d.lines.length)} label={`${d.lines.length === 1 ? "line" : "lines"} · ${open.length} open`} />
        <Tile figure={value ? rs(value) : "—"} label="at the last PO rate" />
        <Tile figure={waitOn.length ? waitOn.join(", ") : "—"} label={waitOn.length ? "whose move it is now" : "nobody's move on file"} tone={waitOn.length ? "caution" : undefined} />
        <Tile figure={day(first.needed_by)} label="needed by" />
      </Tiles>
      <Block title="Lines" count={d.lines.length}>
        <DataTable label="PR lines" rows={d.lines} rowKey={(l) => l.ref.id} two cols={[
          { id: "l", head: "Line", width: "minmax(0,1fr)", cell: (l) => <TitleCell title={l.material ? <RefLink r={l.material} id={false}>{l.text || l.material.label}</RefLink> : l.text} sub={`${l.ref.id}${l.material ? ` · ${l.material.id}` : ""}${l.cs ? ` · ${l.cs}` : ""}`} /> },
          { id: "q", head: "Quantity", width: "120px", end: true, label: "Qty", cell: (l) => <span>{qty(l.qty, l.uom)}<small>{l.value ? rs(l.value) : "no rate"}</small></span> },
          { id: "n", head: "Needed by", width: "96px", label: "Needed by", cell: (l) => day(l.needed_by) },
          { id: "s", head: "Status", width: "140px", label: "Status", cell: (l) => <PrStatus l={l} /> },
          { id: "po", head: "PO", width: "130px", label: "PO", cell: (l) => (l.po_line ? <Link to={lineTo("po", l.po_line.id)}>{l.po_line.id}</Link> : <span className="none">—</span>) },
          { id: "f", head: "Flags", width: "170px", hide: "narrow", label: "Flags", cell: (l) => <Flags flags={l.flags} /> },
        ]} />
      </Block>
      <Block title="PR to payment" note="Each step's date and the row it is read from; the time before each step is attributed to whoever held it. A step the records cannot show is marked, never guessed.">
        <LineLadders items={d.lines.map((l) => ({ key: l.ref.id, title: l.text || l.ref.id, sub: `line ${l.item} · ${qty(l.qty, l.uom)}`, ladder: ladderOf(l) }))} />
      </Block>
    </div>
  );
}

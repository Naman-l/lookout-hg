// Organisation: the SCM organogram, who reports to whom and what each person does, as the sheet draws it and with the edits people made here.
// One chart, two views: a tree laid out like the sheet (the head, then a column per lead, their people under the desk labels) and a list. Anyone
// reads it; a member of the team changes it, and every change is kept with who made it, so it can be undone back to the sheet.
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMe } from "../../api/useMe";
import { invalidate, useResource } from "../../api/useResource";
import { Button, Disclose, EmptyState, Field, FieldLabel, Notice, PageHeader, SegmentedControl, Sheet, StateChip } from "../../ds";
import { DataTable, TitleCell, type Col } from "../../ds/DataTable";
import { FilterBar, type FilterValue } from "../../ds/FilterBar";
import { LoadError } from "../../ds/LoadError";
import { useMedia } from "../../ui/useMedia";
import { first } from "../../ui/format";
import { org, OrgError, type OrgChart, type OrgFields, type OrgNode } from "./api";
import "./org.css";

/** The chart as lookups: each box, its people in the sheet's order, and the lead (under the head) whose team it is on. */
type Index = { by: Map<string, OrgNode>; kids: Map<string, OrgNode[]>; head: OrgNode | null; leads: OrgNode[]; team: (id: string) => OrgNode | null; order: OrgNode[]; under: (id: string) => Set<string> };

function indexOf(c: OrgChart): Index {
  const by = new Map(c.people.map((p) => [p.id, p]));
  const kids = new Map<string, OrgNode[]>();
  for (const p of c.people) if (p.reports_to) kids.set(p.reports_to, [...(kids.get(p.reports_to) ?? []), p]);
  for (const xs of kids.values()) xs.sort((a, b) => a.position - b.position);
  const head = c.head ? by.get(c.head) ?? null : null;
  const leads = head ? kids.get(head.id) ?? [] : [];
  const team = (id: string) => {
    let p = by.get(id);
    while (p && p.reports_to && p.reports_to !== head?.id) p = by.get(p.reports_to);
    return p ?? null;
  };
  const order: OrgNode[] = [];
  const walk = (p: OrgNode) => { order.push(p); (kids.get(p.id) ?? []).forEach(walk); };
  if (head) walk(head);
  const under = (id: string) => { const out = new Set<string>(); const go = (x: string) => (kids.get(x) ?? []).forEach((k) => { out.add(k.id); go(k.id); }); go(id); return out; };
  return { by, kids, head, leads, team, order, under };
}

const nameOf = (p: OrgNode | null | undefined) => (p ? p.name ?? "To be filled" : "—");
/** The designation in full, when the glossary says more than the short form does (not just its spacing). */
const fullOf = (p: OrgNode) => (p.designation_full && p.designation_full.replace(/\s/g, "") !== p.designation.replace(/\s/g, "") ? p.designation_full : null);
const postOf = (p: OrgNode) => [p.designation, p.portfolio].filter(Boolean).join(" - ");
/** "21 Oct, 17:59" */
const when = (iso: string) => new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
/** The sheet's people under a lead, by the desk label the sheet writes beside them, in the order it draws them. */
function byDesk(xs: OrgNode[]): { desk: string | null; people: OrgNode[] }[] {
  const out: { desk: string | null; people: OrgNode[] }[] = [];
  for (const p of xs) {
    const last = out[out.length - 1];
    if (last && last.desk === p.category) last.people.push(p);
    else out.push({ desk: p.category, people: [p] });
  }
  return out;
}

type Editing = { mode: "change"; id: string } | { mode: "add"; under: string };

/** /org */
export function OrgPage() {
  const { me, choose, ready } = useMe();
  const [params, setParams] = useSearchParams();
  const view = params.get("view") === "list" ? "list" : "tree";
  const r = useResource(org.chart, [], true);
  const [chart, setChart] = useState<OrgChart | null>(null);
  useEffect(() => { if (r.data) setChart(r.data); }, [r.data]);
  const [editing, setEditing] = useState<Editing | null>(null);
  const ix = useMemo(() => (chart ? indexOf(chart) : null), [chart]);
  const live = chart ? chart.edits.filter((e) => !e.undone).length : 0;
  const file = chart?.source_file.split("/").pop() ?? "";

  return (
    <div className="org">
      <PageHeader title="Organisation"
        actions={ix?.head ? <Button onClick={() => setEditing({ mode: "add", under: ix.head!.id })}>Add a person</Button> : undefined}
        meta={chart ? <>
          <span>{chart.named} people</span><span className="sep">·</span><span>{chart.open_posts} open {chart.open_posts === 1 ? "post" : "posts"}</span>
          <span className="sep">·</span><span>as the sheet {file} draws it</span>
          {live > 0 && <><span className="sep">·</span><span>{live} {live === 1 ? "change" : "changes"} made here</span></>}
        </> : undefined} />
      {r.error && !chart ? <LoadError what="the organisation chart" retry={invalidate} busy={r.loading} />
        : !chart || !ix ? <div className="org-sk" aria-busy="true" aria-label="Loading the chart"><i /><i /><i /></div>
        : (
          <>
            <p className="org-lead">{chart.note}{chart.total_on_sheet != null && chart.total_on_sheet !== chart.named ? ` The sheet's own total is ${chart.total_on_sheet}.` : ""}</p>
            {ready && !me && <Notice><span>Anyone can read the chart. To change it, say who you are: every change is kept with your name.</span><Button onClick={() => choose(true)}>Choose who you are</Button></Notice>}
            <div className="org-bar">
              <SegmentedControl label="View" items={[{ id: "tree", label: "Tree" }, { id: "list", label: "List" }]} value={view}
                onChange={(v) => setParams(v === "list" ? { view: "list" } : {}, { replace: true })} />
            </div>
            <Changes chart={chart} me={me} onChart={setChart} />
            {view === "tree" ? <Tree ix={ix} open={(id) => setEditing({ mode: "change", id })} /> : <List ix={ix} open={(id) => setEditing({ mode: "change", id })} />}
            {editing && <Editor key={editing.mode === "add" ? `add:${editing.under}` : editing.id} editing={editing} ix={ix} me={me} choose={() => choose(true)}
              onChart={setChart} onClose={() => setEditing(null)} onAdd={(under) => setEditing({ mode: "add", under })} />}
          </>
        )}
    </div>
  );
}

// ------------------------------------------------------------------------------------------------------------------------------- tree
function Tree({ ix, open }: { ix: Index; open: (id: string) => void }) {
  const phone = useMedia("(max-width: 760px)");
  if (!ix.head) return <EmptyState>The sheet names nobody at the head of the chart.</EmptyState>;
  return (
    <div className="org-tree">
      <div className="org-top"><Card p={ix.head} open={open} top /></div>
      <div className="org-cols">
        {ix.leads.map((l) => <Column key={l.id} lead={l} ix={ix} open={open} phone={phone} />)}
      </div>
    </div>
  );
}

function Column({ lead, ix, open, phone }: { lead: OrgNode; ix: Index; open: (id: string) => void; phone: boolean }) {
  const [shown, setShown] = useState(false);
  const team = [...ix.under(lead.id)].map((id) => ix.by.get(id)!);
  const posts = team.filter((p) => p.vacancy).length;
  const count = `${team.length - posts} ${team.length - posts === 1 ? "person" : "people"}${posts ? ` · ${posts} open ${posts === 1 ? "post" : "posts"}` : ""}`;
  const people = ix.kids.get(lead.id) ?? [];
  return (
    <section className="org-col" aria-label={`${nameOf(lead)}'s team`}>
      <Card p={lead} open={open} lead />
      {people.length === 0 ? <p className="org-none">No team on the sheet</p>
        : phone ? <Disclose open={shown} onClick={() => setShown(!shown)} className="org-more">{count}</Disclose>
        : <p className="org-count">{count}</p>}
      {people.length > 0 && (!phone || shown) && byDesk(people).map((g, n) => (
        <div key={`${g.desk ?? ""}${n}`} className="org-desk">
          {g.desk && <h3 className="org-cat">{g.desk}</h3>}
          {g.people.map((p) => <Branch key={p.id} p={p} ix={ix} open={open} />)}
        </div>
      ))}
    </section>
  );
}

/** A box and, indented under it, anyone who reports to it, to any depth. */
function Branch({ p, ix, open }: { p: OrgNode; ix: Index; open: (id: string) => void }) {
  const kids = ix.kids.get(p.id) ?? [];
  return (
    <>
      <Card p={p} open={open} />
      {kids.length > 0 && <div className="org-sub">{kids.map((k) => <Branch key={k.id} p={k} ix={ix} open={open} />)}</div>}
    </>
  );
}

function Card({ p, open, lead, top }: { p: OrgNode; open: (id: string) => void; lead?: boolean; top?: boolean }) {
  const text = lead ? p.portfolio ?? p.responsibilities : p.vacancy ? p.responsibilities : p.responsibilities ?? (top ? fullOf(p) : null);
  return (
    <button type="button" className={`org-card${p.vacancy ? " post" : ""}${lead ? " lead" : ""}${top ? " top" : ""}`} onClick={() => open(p.id)}
      aria-label={`${p.vacancy ? `Open post: ${postOf(p)}` : `${p.name}, ${p.designation}`}. Open to read or change.`}>
      <span className="org-name">{p.vacancy ? "To be filled" : p.name}</span>
      <span className="org-desig" title={fullOf(p) ?? undefined}>{p.vacancy ? postOf(p) : p.designation}</span>
      {text && <span className="org-text">{text}</span>}
      {(p.edited.length > 0 || p.source === "added") && <span className="org-marks"><StateChip>{p.source === "added" ? "added here" : "edited"}</StateChip></span>}
    </button>
  );
}

// ------------------------------------------------------------------------------------------------------------------------------- list
function List({ ix, open }: { ix: Index; open: (id: string) => void }) {
  const [q, setQ] = useState("");
  const [f, setF] = useState<FilterValue>({});
  const rows = ix.order.filter((p) => {
    if (f.team && ix.team(p.id)?.id !== f.team) return false;
    const t = q.trim().toLowerCase();
    return !t || [p.name, p.designation, p.designation_full, p.category, p.portfolio, p.responsibilities, p.role, ...p.purchasing_groups].some((x) => (x ?? "").toLowerCase().includes(t));
  });
  const teams = ix.leads.map((l) => ({ value: l.id, label: nameOf(l), count: ix.order.filter((p) => ix.team(p.id)?.id === l.id).length }));
  const cols: Col<OrgNode>[] = [
    { id: "who", head: "Person", width: "minmax(200px,1fr)", cell: (p) => <TitleCell title={p.vacancy ? "To be filled" : p.name} sub={p.vacancy ? postOf(p) : p.designation} tip={fullOf(p) ?? undefined} /> },
    { id: "to", head: "Reports to", width: "150px", label: "Reports to", cell: (p) => (p.reports_to ? nameOf(ix.by.get(p.reports_to)) : "—") },
    { id: "team", head: "Team", width: "140px", label: "Team", hide: "narrow", cell: (p) => (p.id === ix.head?.id ? "Head of SCM" : nameOf(ix.team(p.id))) },
    { id: "desk", head: "Desk", width: "170px", label: "Desk", hide: "mid", cell: (p) => <span className="org-clamp">{p.category ?? (p.reports_to === ix.head?.id ? "Leads the team" : "—")}</span> },
    { id: "work", head: "Responsibilities", width: "260px", label: "Work", cell: (p) => <span className="org-clamp" title={p.responsibilities ?? p.portfolio ?? undefined}>{p.responsibilities ?? p.portfolio ?? "—"}</span> },
    { id: "sap", head: "SAP groups", width: "90px", label: "SAP groups", hide: "narrow", cell: (p) => p.purchasing_groups.join(", ") || "—" },
  ];
  return (
    <div className="org-list">
      <FilterBar label="the organisation chart" search={q} onSearch={setQ} placeholder="Search names, desks, work" value={f} onChange={setF}
        filters={[{ id: "team", label: "Team", options: teams }]} />
      {rows.length === 0 ? <EmptyState>Nobody on the chart matches.</EmptyState>
        : <DataTable label="The organisation chart" cols={cols} rows={rows} rowKey={(p) => p.id} onClick={(p) => open(p.id)} two />}
    </div>
  );
}

// ------------------------------------------------------------------------------------------------------------------------------- changes
function Changes({ chart, me, onChart }: { chart: OrgChart; me: string | null; onChart: (c: OrgChart) => void }) {
  const [shown, setShown] = useState(false);
  const [sure, setSure] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (chart.edits.length === 0) return null;
  const live = chart.edits.filter((e) => !e.undone).length;
  const run = async (p: () => Promise<OrgChart>) => {
    setBusy(true); setErr(null);
    try { onChart(await p()); setSure(false); } catch (e) { setErr(e instanceof OrgError ? e.detail : "The change could not be made."); } finally { setBusy(false); }
  };
  return (
    <section className="org-changes">
      <Disclose open={shown} onClick={() => setShown(!shown)}>Changes made here <em>{live}</em></Disclose>
      {shown && (
        <div className="org-log">
          <ol>
            {chart.edits.map((e) => (
              <li key={e.id} className={e.undone ? "undone" : ""}>
                <span>{e.summary}</span>
                <small>{e.by} · {when(e.at)}{e.undone ? " · undone" : !e.applied ? " · not applied: the sheet no longer has this box" : ""}</small>
              </li>
            ))}
          </ol>
          {live > 0 && (
            <div className="org-log-act">
              {!me && <span className="org-hint">Say who you are to undo.</span>}
              <Button disabled={!me || busy} onClick={() => run(() => org.undo(me!))}>Undo last change</Button>
              {sure ? (
                <span className="org-sure">
                  <span>Undo all {live} {live === 1 ? "change" : "changes"}? They stay listed here.</span>
                  <Button variant="primary" disabled={!me || busy} onClick={() => run(() => org.reset(me!))}>Back to the sheet</Button>
                  <Button variant="quiet" onClick={() => setSure(false)}>Keep them</Button>
                </span>
              ) : <Button variant="quiet" disabled={!me || busy} onClick={() => setSure(true)}>Back to the sheet</Button>}
            </div>
          )}
          {err && <Notice tone="risk">{err}</Notice>}
        </div>
      )}
    </section>
  );
}

// ------------------------------------------------------------------------------------------------------------------------------- editor
type Form = { name: string; designation: string; reports_to: string; category: string; portfolio: string; responsibilities: string; vacancy: boolean };

function Editor({ editing, ix, me, choose, onChart, onClose, onAdd }: {
  editing: Editing; ix: Index; me: string | null; choose: () => void; onChart: (c: OrgChart) => void; onClose: () => void; onAdd: (under: string) => void;
}) {
  const node = editing.mode === "change" ? ix.by.get(editing.id) ?? null : null;
  const parent = editing.mode === "add" ? ix.by.get(editing.under) ?? null : null;
  const start: Form = node
    ? { name: node.name ?? "", designation: node.designation, reports_to: node.reports_to ?? "", category: node.category ?? "", portfolio: node.portfolio ?? "",
        responsibilities: node.responsibilities ?? "", vacancy: node.vacancy }
    : { name: "", designation: "", reports_to: parent?.id ?? "", category: parent && parent.reports_to && parent.reports_to !== ix.head?.id ? parent.category ?? "" : "",
        portfolio: "", responsibilities: "", vacancy: false };
  const [f, setF] = useState<Form>(start);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sure, setSure] = useState(false);
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setF((x) => ({ ...x, [k]: v }));
  const close = onClose;
  if (editing.mode === "change" && !node) return <Sheet title="Not on the chart" onClose={close}><EmptyState>This box is no longer on the chart.</EmptyState></Sheet>;

  const isHead = !!node && node.reports_to === null;
  const blocked = node ? ix.under(node.id) : new Set<string>();
  const choices = ix.order.filter((p) => p.id !== node?.id && !blocked.has(p.id));
  const leadOf = f.reports_to ? (f.reports_to === ix.head?.id ? null : ix.team(f.reports_to)) : null;
  const desks = [...new Set(ix.order.filter((p) => leadOf && ix.team(p.id)?.id === leadOf.id && p.category).map((p) => p.category!))];
  const showPortfolio = (f.reports_to === ix.head?.id && !f.vacancy) || f.vacancy || !!start.portfolio;
  const changed = (Object.keys(f) as (keyof Form)[]).filter((k) => (typeof f[k] === "string" ? (f[k] as string).trim() : f[k]) !== (typeof start[k] === "string" ? (start[k] as string).trim() : start[k]));
  const title = node ? (node.vacancy ? "Open post" : node.name ?? "") : `Add under ${nameOf(parent)}`;

  const write = async (p: () => Promise<OrgChart>, after?: () => void) => {
    setBusy(true); setErr(null);
    try { onChart(await p()); (after ?? close)(); } catch (e) { setErr(e instanceof OrgError ? e.detail : "The change could not be made."); } finally { setBusy(false); }
  };
  const save = (e: FormEvent) => {
    e.preventDefault();
    if (!me) return;
    const body: OrgFields = { by: me };
    const keys = editing.mode === "add" ? (Object.keys(f) as (keyof Form)[]).filter((k) => k === "vacancy" || (f[k] as string).trim()) : changed;
    for (const k of keys) (body as Record<string, unknown>)[k] = typeof f[k] === "string" ? (f[k] as string).trim() : f[k];
    if (f.vacancy) delete body.name;
    else if (node?.vacancy && !("name" in body)) body.name = f.name.trim();
    write(() => (editing.mode === "add" ? org.add(body) : org.change(node!.id, body)));
  };

  return (
    <div className="org-ed">
      <Sheet title={title} hint={node ? (node.src ? `Sheet ${node.src}` : "Added on this page") : undefined} onClose={close}>
        {!me && <Notice><span>Say who you are to change the chart.</span><Button onClick={choose}>Choose who you are</Button></Notice>}
        <form className="org-form" onSubmit={save}>
          {!isHead && (
            <label className="org-check"><input type="checkbox" checked={f.vacancy} onChange={(e) => set("vacancy", e.target.checked)} /><span>Open post (to be filled)</span></label>
          )}
          {!f.vacancy && <label className="org-f"><FieldLabel>Name</FieldLabel><Field value={f.name} onChange={(e) => set("name", e.target.value)} autoComplete="off" /></label>}
          <label className="org-f">
            <FieldLabel>Designation</FieldLabel>
            <Field value={f.designation} onChange={(e) => set("designation", e.target.value)} placeholder="AM, DM, Manager, GM - SCM" autoComplete="off" />
            {node && fullOf(node) && f.designation === node.designation && <small>{fullOf(node)}</small>}
          </label>
          {!isHead && (
            <label className="org-f">
              <FieldLabel>Reports to</FieldLabel>
              <Field kind="select" value={f.reports_to} onChange={(e) => set("reports_to", e.target.value)}>
                {!f.reports_to && <option value="">Choose…</option>}
                {choices.map((p) => <option key={p.id} value={p.id}>{p.vacancy ? `Open post: ${postOf(p)}` : `${p.name} · ${p.designation}`}</option>)}
              </Field>
            </label>
          )}
          {!isHead && (
            <label className="org-f">
              <FieldLabel>Desk</FieldLabel>
              <Field value={f.category} onChange={(e) => set("category", e.target.value)} list="org-desks" placeholder={desks[0] ?? "Aggregate, Logistics…"} autoComplete="off" />
              <datalist id="org-desks">{desks.map((d) => <option key={d} value={d} />)}</datalist>
            </label>
          )}
          {showPortfolio && (
            <label className="org-f">
              <FieldLabel>{f.vacancy ? "The post's desk" : "What the team buys"}</FieldLabel>
              <Field value={f.portfolio} onChange={(e) => set("portfolio", e.target.value)} autoComplete="off" />
            </label>
          )}
          <label className="org-f"><FieldLabel>Responsibilities</FieldLabel><Field kind="textarea" rows={5} value={f.responsibilities} onChange={(e) => set("responsibilities", e.target.value)} /></label>
          {err && <Notice tone="risk">{err}</Notice>}
          <div className="org-ed-act">
            <Button variant="primary" type="submit" disabled={!me || busy || (editing.mode === "change" && changed.length === 0)}>{editing.mode === "add" ? "Add to the chart" : "Save"}</Button>
            <Button variant="quiet" onClick={close}>Cancel</Button>
          </div>
        </form>
        {node && (
          <div className="org-ed-more">
            {node.member_id && (
              <div className="org-facts">
                {node.role && <p>{node.role}</p>}
                <p>{node.purchasing_groups.length ? `SAP purchasing groups ${node.purchasing_groups.join(", ")}` : "No SAP purchasing group of their own"}{node.email ? ` · ${node.email}` : ""}</p>
                <Link to={`/insights/team/${encodeURIComponent(node.member_id)}`}>Team page</Link>
              </div>
            )}
            <div className="org-ed-act">
              <Button disabled={busy} onClick={() => onAdd(node.id)}>Add someone under {node.vacancy ? "this post" : first(node.name)}</Button>
              {!isHead && !sure && <Button variant="quiet" disabled={busy} onClick={() => setSure(true)}>Remove from the chart</Button>}
            </div>
            {sure && (
              <div className="org-sure">
                <span>Take {node.vacancy ? "this open post" : node.name} off the chart? Anyone under them moves up to {nameOf(ix.by.get(node.reports_to ?? ""))}.</span>
                <Button variant="primary" disabled={!me || busy} onClick={() => write(() => org.remove(node.id, me!))}>Remove</Button>
                <Button variant="quiet" onClick={() => setSure(false)}>Keep</Button>
              </div>
            )}
          </div>
        )}
      </Sheet>
    </div>
  );
}

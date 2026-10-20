import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { api } from "../api/client";
import { DataTable, TitleCell, type Col } from "../ds/DataTable";
import { useResource } from "../api/useResource";
import type { FireOption, Unknown, Value as V } from "../api/types";
import { Value } from "../domain-ui/Value";
import { humanize, shortDate } from "../ui/format";

const ask = (u: Unknown) => `${humanize(u.what)} · ask ${u.owner}`;

/** The detail of one way through, opened from its row: what it needs, what it costs and the one thing that decides it. */
function OptionDetail({ o }: { o: FireOption }) {
  const needs = o.needs ?? [], unknowns = o.cost_unknowns ?? [];
  return (
    <dl className="opt-detail ds-rowx">
      <dt>When</dt><dd>{whenText(o)}{o.earliest_basis && <span className="muted"> · {humanize(o.earliest_basis)}</span>}</dd>
      <dt>Needs</dt><dd>{needs.length ? <ul>{needs.map((n) => <li key={n.what}>{humanize(n.what)}<span className="muted"> · {n.owner}</span></li>)}</ul> : "nothing outside the company"}</dd>
      <dt>Cost</dt><dd>{o.cost_delta ? <><Value value={o.cost_delta as V} tag={false} /> more than today{o.cost_basis && <span className="muted"> · {humanize(o.cost_basis)}</span>}</> : <span className="unk">{unknowns[0] ? humanize(unknowns[0].what) + " is not in the data" : "not in the data"}</span>}{o.duty_effect && <><br />Duty <Value value={o.duty_effect as V} tag={false} /> if it ships late</>}</dd>
      {o.products && o.products.length > 0 && <><dt>Builds</dt><dd>{o.products.map((p) => `${p.product.label ?? p.product.id}: ${p.robots} robots`).join(" · ")}</dd></>}
      <dt>Decides it</dt><dd className="unk">{ask(o.decided_by)}</dd>
    </dl>
  );
}

/** "Vinh Phuc Motor Technology Co., Ltd. for Motor, BLDC" as a short name over what it supplies. */
const LEGAL = /,?\s+(Co\.,?\s*Ltd\.?|Co\.|Ltd\.?|Inc\.?|LLC|GmbH|S\.A\.[^,]*|AG|JSC|Corp\.?)$/i;
const splitLabel = (label: string): [string, string | undefined] => {
  const n = label.indexOf(" for ");
  if (n < 0) return [label, undefined];
  return [label.slice(0, n).replace(LEGAL, ""), `for ${label.slice(n + 5)}`];
};

const whenText = (o: FireOption) => (o.earliest ? `from ${shortDate(o.earliest.date)}` : o.not_before ? `not before ${shortDate(o.not_before.date)}` : "no date in the data");

/** The fire's ways through, one line each: the option, its earliest date, its cost and who decides it; the detail opens from the row. Only a supplier's disruption has them. Never ranked. */
export function FireOptions({ itemKey, month }: { itemKey: string; month?: string }) {
  const r = useResource(() => api.options(itemKey).catch(() => [] as FireOption[]), [itemKey]);
  const [open, setOpen] = useState<string | null>(null);
  if (!r.data || r.data.length === 0) return null;
  const cols: Col<FireOption>[] = [
    { id: "o", head: "Way through", width: "minmax(180px,1fr)", cell: (o) => { const [t, sub] = splitLabel(humanize(o.label)); return <TitleCell title={t} sub={sub} tip={humanize(o.label)} />; } },
    { id: "when", head: "Earliest", width: "130px", hide: "narrow", label: "earliest", cell: (o) => whenText(o) },
    { id: "cost", head: "Cost", width: "110px", end: true, label: "cost", cell: (o) => (o.cost_delta ? <Value value={o.cost_delta as V} tag={false} /> : <span className="unk">not in the data</span>) },
    { id: "who", head: "Decided by", width: "110px", hide: "mid", phone: "hide", cell: (o) => o.decided_by.owner },
    { id: "more", head: "", width: "36px", cell: (o) => <span className="chev-cell" aria-hidden>{open === o.kind ? <ChevronDown size={18} strokeWidth={1.5} /> : <ChevronRight size={18} strokeWidth={1.5} />}</span> },
  ];
  return (
    <section className="opts-zone">
      <h4 className="oqh">{month ? `${month} options` : "Options"}</h4>
      <DataTable<FireOption> label="Ways through" cols={cols} rows={r.data} rowKey={(o) => o.kind} onClick={(o) => setOpen(open === o.kind ? null : o.kind)}
        expand={(o) => (open === o.kind ? <OptionDetail o={o} /> : null)} />
    </section>
  );
}

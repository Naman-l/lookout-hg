import type { ReactNode } from "react";
import { isUnknown, type BidColumn, type Value as V } from "../../api/types";
import { UnknownValue } from "../../domain-ui/Unknown";
import { Value } from "../../domain-ui/Value";
import { humanize, shortDate } from "../../ui/format";

const cell = (v: V | null | undefined): ReactNode => (v == null ? <span className="muted">—</span> : isUnknown(v) ? <UnknownValue u={v} /> : <Value value={v} tag={false} />);

/** The bid tab (unchanged from the part page before FINAL 06): suppliers as columns, landed cost per unit at a quantity. */
export function BidTable({ cols }: { cols: BidColumn[] }) {
  const rows: { head: string; strong?: boolean; render: (c: BidColumn) => ReactNode }[] = [
    { head: "Unit price", render: (c) => <>{cell(c.landed.offer.unit_price_usd as V)}<span className="unit">{c.landed.offer.price_basis === "per_1000" ? "from a per-1,000 price" : ""}</span></> },
    { head: "Incoterms", render: (c) => c.landed.offer.incoterm ?? <span className="muted">—</span> },
    { head: "Origin", render: (c) => c.landed.offer.origin ?? (c.landed.offer.origin_claim ? <span title={c.landed.offer.origin_claim}>Claimed: {c.landed.offer.origin_claim}</span> : <span className="muted">—</span>) },
    { head: "Duty", render: (c) => c.landed.duty_usd ? cell(c.landed.duty_usd as V) : c.landed.duty_status === "unknown_origin" ? <span className="unknown">origin not settled</span> : <span className="muted">none</span> },
    { head: "Tooling per unit", render: (c) => cell(c.landed.tooling_per_unit_usd as V | null) },
    { head: "Landed cost per unit", strong: true, render: (c) => <>{cell(c.landed.total_known_usd as V | null)}{c.landed.duty_status === "unknown_origin" && <span className="unit">before duty</span>}</> },
    { head: "If the origin is ruled China", render: (c) => c.landed.total_if_china_usd ? cell(c.landed.total_if_china_usd as V) : <span className="muted">—</span> },
    { head: "Minimum order", render: (c) => c.landed.offer.moq ?? <span className="muted">—</span> },
    { head: "Lead time", render: (c) => { const l = c.landed.offer.lead_time as { value?: string; condition?: string } | null | undefined; return l ? <>{l.value}{l.condition ? <span className="grey"> {l.condition}</span> : null}</> : <span className="muted">—</span>; } },
    { head: "Valid until", render: (c) => c.landed.offer.valid_until ? <>{shortDate(c.landed.offer.valid_until)}{c.landed.offer.days_left != null ? <span className="grey"> · {c.landed.offer.days_left} days</span> : null}</> : <span className="muted">—</span> },
    { head: "Payment", render: (c) => c.landed.offer.payment_terms ?? <span className="muted">—</span> },
  ];
  return (
    <div className="tablewrap">
      <table className="bid">
        <thead>
          <tr><th />{cols.map((c, n) => <th key={n} className="colhead"><span className="who">{humanize(c.label.replace(/^Current: /, ""))}</span><span className="muted">{c.is_current ? "Current order" : c.landed.offer.quote_no ?? ""}</span></th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r) => <tr key={r.head} className={r.strong ? "strong" : ""}><th scope="row">{r.head}</th>{cols.map((c, n) => <td key={n}>{r.render(c)}</td>)}</tr>)}
        </tbody>
      </table>
    </div>
  );
}

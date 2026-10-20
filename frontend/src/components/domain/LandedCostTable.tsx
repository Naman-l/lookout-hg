import { api } from "../../api/client";
import { useResource } from "../../api/useResource";
import type { BidColumn } from "../../api/types";
import { useState } from "react";
import { landedLine, landedTable, type Variant } from "./landedCost";

type Opts = { shortOf?: (id: string | null | undefined, name: string) => string; reviewed?: string; note?: string; order?: number };

/** The landed-cost table (F103): what a piece really costs from each offer, the last PO pinned first as "current", the cheapest landed bold, then one
 * line naming the point. `duty` for a new-duty case (Supplier · origin | Quoted | Duty | Landed | If ruled China | vs last PO + duty); `quote` for a
 * high quote (… | vs last paid | Surcharge / tooling | Duty | Landed | vs last landed | Terms). Negatives are never coloured. */
export function LandedCostTableView({ columns, variant, ...opts }: { columns: BidColumn[]; variant: Variant } & Opts) {
  const t = landedTable(columns, variant, opts);
  const [all, setAll] = useState(false);
  const grid = { gridTemplateColumns: `minmax(0,1.4fr) ${t.cols.map((c) => (c.key === "terms" ? "minmax(0,1.5fr)" : c.key === "landed" ? "minmax(0,1.3fr)" : "minmax(0,1fr)")).join(" ")}` };
  if (t.rows.filter((r) => !r.current).length === 0) return <p className="lc-empty">No other offers on file for this part.</p>;
  const rows = all ? t.rows : t.rows.slice(0, 4);      // at most four rows open (F105), then "+N"
  return (
    <div className="lc">
      <div className="lc-t" role="table" aria-label={variant === "duty" ? "Landed cost with the new duty" : "Quote check"}>
        <div className="lc-r lc-h" role="row" style={grid}><span role="columnheader">Offer</span>{t.cols.map((c) => <span key={c.key} role="columnheader" className={c.end ? "n" : undefined}>{c.head}</span>)}</div>
        {rows.map((r) => (
          <div key={r.key} className={`lc-r${r.current ? " cur" : ""}`} role="row" style={grid}>
            <span role="rowheader">{r.label}{r.current && <small> current</small>}</span>
            {t.cols.map((c) => { const x = r.cells[c.key]; return <span key={c.key} role="cell" title={x?.tip} className={`${c.end ? "n" : ""}${x?.bold ? " b" : ""}`}>{x?.text ?? "—"}{x?.note && <small> {x.note}</small>}</span>; })}
          </div>
        ))}
      </div>
      {t.rows.length > rows.length && <button type="button" className="lc-more" onClick={() => setAll(true)}>+{t.rows.length - rows.length} ›</button>}
      {t.line && <p className="lc-line">{t.line}</p>}
    </div>
  );
}

/** The same table read live for one part (GET /parts/{part}/compare). */
export function LandedCostTable({ part, variant, qty = 1000, tiers = variant === "quote" ? [100] : [], order = variant === "quote" ? 200 : undefined, also = [], ...opts }: { part: string; variant: Variant; qty?: number; tiers?: number[]; also?: string[] } & Opts) {
  // `order`: the quantity a quote is bought at (the bridge order, 160–240 pcs); its break is the bold row. The bid tab prices each offer at the break for one quantity; a quote also reads the smaller breaks a buyer might order (the 100-pc tier), one row each.
  const bid = useResource(() => Promise.all([qty, ...tiers].map((q) => api.compare(part, q))).then((all) => {
    const seen = new Set<string>();
    const cols = all.flatMap((b) => b.columns).filter((c) => { const k = `${c.is_current}|${c.landed.offer.offer_id ?? c.label}|${c.landed.offer.qty_break ?? ""}`; if (seen.has(k)) return false; seen.add(k); return true; });
    return { columns: cols };
  }), [part, qty, tiers.join(",")]);
  if (bid.loading && !bid.data) return <div className="lc-sk" aria-hidden><i /><i /><i /></div>;
  if (bid.error || !bid.data) return <p className="lc-empty">The offers for this part could not be loaded.</p>;
  return <><LandedCostTableView columns={bid.data.columns} variant={variant} order={order} {...opts} />{also.map((p) => <AlsoLine key={p} part={p} qty={qty} shortOf={opts.shortOf} />)}</>;
}

/** A further part of the same case as one line under the table (F105: one part block per case). */
function AlsoLine({ part, qty, shortOf }: { part: string; qty: number; shortOf?: Opts["shortOf"] }) {
  const bid = useResource(() => api.compare(part, qty).catch(() => null), [part, qty]);
  const line = bid.data ? landedLine(part, bid.data.columns, shortOf) : null;
  return line ? <p className="lc-line">{line}</p> : null;
}

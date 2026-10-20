import { useState } from "react";
import { TriangleAlert } from "lucide-react";
import { Part, Money } from "../../components/domain";
import { shortDate } from "../../ui/format";
import { usePartNames } from "../../api/usePartNames";
import type { OfferRow } from "./model";

/** Quoted prices as the supplier wrote them: exact to the cent, one row per quantity break, collapsed after `limit`. */
export function OfferTable({ rows, limit = 3 }: { rows: OfferRow[]; limit?: number }) {
  const partName = usePartNames();
  const [all, setAll] = useState(false);
  const shown = all ? rows : rows.slice(0, limit);
  const perK = rows.some((r) => r.basis === "per_1000"), breaks = rows.some((r) => r.breakQty), valid = rows.some((r) => r.validTo), sites = new Set(rows.map((r) => r.site).filter(Boolean)).size > 1;
  const notes = [...new Set(rows.map((r) => r.conditions).filter((c): c is string => !!c))];
  return (
    <div className="dm-tablewrap">
      <table className="dm-table">
        <caption className="dm-sr">Quoted prices</caption>
        <thead><tr><th scope="col">Part</th>{sites && <th scope="col" className="dm-opt">Made in</th>}{breaks && <th scope="col" className="dm-num">From qty</th>}{perK && <th scope="col" className="dm-num">Quoted</th>}<th scope="col" className="dm-num">Price each</th>{valid && <th scope="col" className="dm-opt">Valid to</th>}</tr></thead>
        <tbody>
          {shown.map((r, n) => (
            <tr key={`${r.partId}-${r.breakQty}-${n}`}>
              <td><Part id={r.partId} name={partName(r.partId)} /></td>
              {sites && <td className="dm-opt">{r.site ?? "—"}{r.availableFrom && <span className="dm-hint"> · from {shortDate(r.availableFrom)}</span>}</td>}
              {breaks && <td className="dm-num">{r.breakQty ? r.breakQty.toLocaleString("en-US") : "—"}</td>}
              {perK && <td className="dm-num">{r.basis === "per_1000" ? <><Money value={{ amount: r.amount, currency: r.currency }} exact /><span className="dm-hint"> per 1,000</span></> : "—"}</td>}
              <td className="dm-num"><Money value={r.basis === "per_1000" && r.unitUsd ? { amount: r.unitUsd, currency: "USD" } : { amount: r.amount, currency: r.currency }} exact /></td>
              {valid && <td className="dm-opt">{r.validTo ? shortDate(r.validTo) : "—"}</td>}
            </tr>
          ))}
        </tbody>
      </table>
      {notes.length > 0 && <ul className="ib-conds" aria-label="Conditions">{notes.map((c) => <li key={c}><TriangleAlert size={14} strokeWidth={1.75} aria-hidden /><span>{c}</span></li>)}</ul>}
      {rows.length > limit && <button type="button" className="dm-more" aria-expanded={all} onClick={() => setAll(!all)}>{all ? "Show fewer" : `Show ${rows.length - limit} more`}</button>}
    </div>
  );
}

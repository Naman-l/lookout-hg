import { useState } from "react";
import { Link } from "react-router-dom";
import { FileText } from "lucide-react";
import { Part } from "./Part";
import { shortDate } from "../../ui/format";

/** "PO-26-00001 / 10" -> "PO-26-00001/10": the real number, spaced the way the ERP prints it. */
export const poLineNumber = (id: string) => id.trim().replace(/\s*[/:]\s*/, "/");

export type PoLineIn = { id: string; part?: { id: string; name?: string | null; product?: string | null } | null; qty?: string | number | null; uom?: string | null; date?: string | null; was?: string | null; now?: string | null; note?: string | null };

const qtyText = (q?: string | number | null, uom?: string | null) => (q == null || q === "" ? "" : `${Number(q).toLocaleString("en-US")}${uom ? ` ${uom}` : ""}`);

/** One PO line: the real number, quantity and date. The chip opens the order. */
export function PoLine({ id, qty, uom, date, to = true }: { id: string; qty?: string | number | null; uom?: string | null; date?: string | null; to?: boolean }) {
  const n = poLineNumber(id);
  const rest = [qtyText(qty, uom), date ? shortDate(date) : ""].filter(Boolean);
  const inner = (
    <>
      <FileText size={14} strokeWidth={1.5} aria-hidden />
      <span className="dm-id dm-po">{n}</span>
      {rest.map((r) => <span key={r} className="dm-hint">· {r}</span>)}
    </>
  );
  return to
    ? <Link className="dm-chip" to={`/orders?q=${encodeURIComponent(n)}`} title={n} aria-label={`Order line ${n}${rest.length ? ", " + rest.join(", ") : ""}`}>{inner}</Link>
    : <span className="dm-chip" title={n}>{inner}</span>;
}

/** A list of PO lines as a compact table: line, part, then quantity and (if any row carries them) was and now. Collapsed after `limit` rows. */
export function PoLineTable({ rows, limit = 3, caption = "Order lines" }: { rows: PoLineIn[]; limit?: number; caption?: string }) {
  const [all, setAll] = useState(false);
  const shown = all ? rows : rows.slice(0, limit);
  const change = rows.some((r) => r.was != null || r.now != null);
  const qty = rows.some((r) => r.qty != null);
  const date = !change && rows.some((r) => r.date);
  const more = rows.length - limit;
  return (
    <div className="dm-tablewrap">
      <table className="dm-table">
        <caption className="dm-sr">{caption}</caption>
        <thead>
          <tr><th scope="col">Line</th><th scope="col">Part</th>{qty && <th scope="col" className="dm-num">Qty</th>}{date && <th scope="col">Date</th>}{change && <><th scope="col">Was</th><th scope="col">Now</th></>}</tr>
        </thead>
        <tbody>
          {shown.map((r) => (
            <tr key={r.id}>
              <td><Link className="dm-cell-link dm-id dm-po" to={`/orders?q=${encodeURIComponent(poLineNumber(r.id))}`}>{poLineNumber(r.id)}</Link></td>
              <td>{r.part ? <Part id={r.part.id} name={r.part.name} product={r.part.product} /> : <span className="dm-rel">—</span>}</td>
              {qty && <td className="dm-num">{qtyText(r.qty, r.uom)}</td>}
              {date && <td>{r.date ? shortDate(r.date) : "—"}</td>}
              {change && <><td className="dm-was">{r.was ?? "—"}</td><td className="dm-now">{r.now ?? "—"}</td></>}
            </tr>
          ))}
        </tbody>
      </table>
      {more > 0 && <button type="button" className="dm-more" aria-expanded={all} onClick={() => setAll(!all)}>{all ? "Show fewer" : `Show ${more} more`}</button>}
    </div>
  );
}

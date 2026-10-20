import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { usePartNames } from "../api/usePartNames";
import { RobotIcon, useRobots } from "../components/domain";
import "./what-changes.css";

/** What a message (or a supplier's reply) changes, line by line: the shared component of the Inbox, the case's Replied state and the slip case (FINAL 04 §5).
 * One sentence for what every line shares, then one row per delivery: PO line · part · robots · qty · the date before · the date now (ship date under it). */

export type Change = { ref: { type: string; id: string }; label: string; before?: string | null; after?: string | null; line?: string | null; qty?: number | null; ship?: string | null };

const day = (iso?: string | null) => (iso && /^\d{4}-\d{2}-\d{2}/.test(iso) ? new Date(`${iso.slice(0, 10)}T00:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" }) : null);
const robotsCache = new Map<string, Promise<string[]>>();
/** The robots (product ids) a part goes into, read once per part. */
export function usePartRobots(parts: string[]): Record<string, string[]> {
  const [map, setMap] = useState<Record<string, string[]>>({});
  const key = [...new Set(parts)].sort().join("|");
  useEffect(() => {
    let live = true;
    const ids = key ? key.split("|") : [];
    Promise.all(ids.map((p) => {
      if (!robotsCache.has(p)) robotsCache.set(p, api.whereUsed(p).then((rows) => [...new Set(rows.map((r) => r.product.id))], () => []));
      return robotsCache.get(p)!.then((r) => [p, r] as const);
    })).then((rows) => { if (live) setMap(Object.fromEntries(rows)); });
    return () => { live = false; };
  }, [key]);
  return map;
}

/** Three robot slots for one part: lit in the robot's colour when the part goes into it. */
export function PartRobots({ ids }: { ids: string[] }) {
  const robots = useRobots();
  return (
    <span className="wc-rb">
      {robots.map((r) => ids.includes(r.id)
        ? <i key={r.id} className={`on r-${(r.slot % 3) + 1}`} title={`${r.name} · uses this part`}><RobotIcon slot={r.slot} /></i>
        : <i key={r.id} title={`${r.name} · not affected`}><RobotIcon slot={r.slot} /></i>)}
    </span>
  );
}

export function WhatChanges({ changes, shared, terms, caption = "What it changes", wasLabel = "Promised", nowLabel = "Arrives", qtyLabel = "Qty", delta = false, limit = 12 }: {
  changes: Change[]; shared?: ReactNode; terms?: ReactNode; caption?: string; wasLabel?: string; nowLabel?: string; qtyLabel?: string; delta?: boolean; limit?: number;
}) {
  const names = usePartNames();
  const lines = changes.filter((c) => c.ref.type === "po_line");
  const offers = changes.filter((c) => c.ref.type === "part" && c.label.startsWith("Offer"));
  const partOf = (c: Change) => /\((HR-\d{5})\)/.exec(c.label)?.[1] ?? (c.ref.type === "part" ? c.ref.id : "");
  const robots = usePartRobots([...lines, ...offers].map(partOf).filter(Boolean));
  const [all, setAll] = useState(false);
  const count = new Map<string, number>();
  for (const c of lines) count.set(c.ref.id, (count.get(c.ref.id) ?? 0) + 1);
  const rows = all ? lines : lines.slice(0, limit);
  const hasNow = lines.some((c) => day(c.after) || day(c.ship));      // a column empty on every row is not drawn
  const robotsHead = <span className="wc-rl">{useRobots().map((r) => <span key={r.id}>{r.key}</span>)}</span>;
  const part = (p: string) => <><Link to={`/parts/${encodeURIComponent(p)}`} className="wc-pn">{names(p) ?? p}</Link><small>{p}</small></>;
  return (
    <section className="wc" aria-label={caption}>
      <div className="wc-cap">{caption}</div>
      {shared && <p className="wc-shared">{shared}</p>}
      {terms}
      {lines.length > 0 && (
        <table className="wc-t">
          <colgroup><col style={{ width: 132 }} /><col /><col style={{ width: 76 }} /><col style={{ width: 70 }} /><col style={{ width: 84 }} />{hasNow && <col style={{ width: 84 }} />}</colgroup>
          <thead><tr><th>PO line</th><th>Part</th><th>{robotsHead}</th><th className="n">{qtyLabel}</th><th className="n">{wasLabel}</th>{hasNow && <th className="n">{nowLabel}</th>}</tr></thead>
          <tbody>
            {rows.map((c, n) => {
              const p = partOf(c), after = day(c.after);
              const shift = c.before && c.after && after ? Math.round((Date.parse(c.after) - Date.parse(c.before)) / 864e5) : null;
              return (
                <tr key={`${c.ref.id}-${n}`}>
                  <td><Link to={`/orders?q=${encodeURIComponent(c.ref.id)}`} className="wc-po">{c.ref.id}</Link>{(count.get(c.ref.id) ?? 0) > 1 && <small>partial</small>}</td>
                  <td>{p ? part(p) : null}</td>
                  <td><PartRobots ids={robots[p] ?? []} /></td>
                  <td className="n">{c.qty != null ? c.qty.toLocaleString("en-US") : <span className="none">—</span>}</td>
                  <td className="n">{day(c.before) ?? <span className="none">—</span>}</td>
                  {hasNow && <td className="n">{after ?? <span className="none">—</span>}{c.ship && <small>Ship date {day(c.ship)}</small>}{delta && shift != null && shift > 0 && <small>+{shift} d</small>}</td>}
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {lines.length > limit && <button type="button" className="wc-more" onClick={() => setAll(!all)}>{all ? "Show fewer" : `+${lines.length - limit} ›`}</button>}
      {lines.length === 0 && offers.length > 0 && (
        <table className="wc-t">
          <colgroup><col /><col style={{ width: 76 }} /><col style={{ width: 90 }} /><col style={{ width: 110 }} /></colgroup>
          <thead><tr><th>Part</th><th>{robotsHead}</th><th className="n">From qty</th><th className="n">Price each</th></tr></thead>
          <tbody>
            {offers.map((c, n) => {
              const m = /Offer (?:per 1,000 |ea )?([\d.,]+) (\w{3})(?: at ([\d,]+))?/.exec(c.label);
              const p = partOf(c);
              return (
                <tr key={`${p}-${n}`}>
                  <td>{part(p)}</td>
                  <td><PartRobots ids={robots[p] ?? []} /></td>
                  <td className="n">{m?.[3] ? Number(m[3].replace(/,/g, "")).toLocaleString("en-US") : <span className="none">—</span>}</td>
                  <td className="n">{m ? `${m[2] === "USD" ? "$" : `${m[2]} `}${m[1]}` : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}

import type { Ladder } from "../../api/types";
import { shortDate } from "../../ui/format";

/** The PR-to-payment ladder in one strip: each rung's date, and whose move the wait before it was. A rung the data cannot show says so. */
export function LadderStrip({ ladder }: { ladder: Ladder }) {
  const rungs = ladder.rungs.filter((r) => r.state !== "na");
  return (
    <div className="ld">
      <ol className="ld-r">
        {rungs.map((r) => (
          <li key={r.key} className={`ld-${r.state}`} title={[r.label, r.date ? shortDate(r.date) : "", r.source ?? "", r.why ?? "", r.unknown ?? ""].filter(Boolean).join(" · ")}>
            <i aria-hidden />
            <b>{r.label}</b>
            <small>{r.date ? shortDate(r.date) : r.state === "now" ? "now" : r.state === "unknown" ? "unknown" : ""}</small>
            {r.held_by && r.days != null && r.days > 0 && <em>{r.held_by} · {r.days} d</em>}
          </li>
        ))}
      </ol>
      {ladder.waiting_on && <p className="ld-now">Now with <b>{ladder.waiting_on}</b>{ladder.days_waiting != null ? ` for ${ladder.days_waiting} days` : ""}{ladder.waiting_since ? ` (since ${shortDate(ladder.waiting_since)})` : ""}.</p>}
      {Object.keys(ladder.held ?? {}).length > 0 && <p className="ld-held">Days held so far: {Object.entries(ladder.held).map(([k, v]) => `${k} ${v}`).join(" · ")}</p>}
    </div>
  );
}

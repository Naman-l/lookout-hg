import type { ReactNode } from "react";

/** One stop on a stage strip: its name, an optional caption and whatever sits under it (the agents serving it). */
export type StripStop = { key: string; name: ReactNode; caption?: ReactNode; children?: ReactNode };

/** The hairline stage strip (item page FINAL 07). With `current` it marks where a case stands: the stops before are passed dots, the current one a ring
 * (a blue dot inside when it waits on the viewer), the rest open. Without `current` it is the static variant: every stop a passed dot, no ring, as on
 * Under the hood where it shows the steps every case goes through. */
export function StageStrip({ stops, current, mine = false, label, onHover }: { stops: StripStop[]; current?: number; mine?: boolean; label: string; onHover?: (key: string | null) => void }) {
  return (
    <ol className="ss" aria-label={label} style={{ gridTemplateColumns: `repeat(${stops.length}, minmax(0, 1fr))` }}>
      {stops.map((s, i) => {
        const state = current == null || i < current ? "done" : i === current ? `cur${mine ? " mine" : ""}` : "todo";
        return (
          <li key={s.key} className={`ss-stop ${state}`} aria-current={i === current ? "step" : undefined}
            onMouseEnter={onHover && (() => onHover(s.key))} onMouseLeave={onHover && (() => onHover(null))}>
            <b>{s.name}</b>
            {s.caption && <small>{s.caption}</small>}
            {s.children}
          </li>
        );
      })}
    </ol>
  );
}

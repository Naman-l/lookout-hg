import type { ReactElement } from "react";
import { useBuilds } from "../../api/useBuilds";

/** The company's robots as the buyer knows them: a name, a short key, a colour and a line icon, the same on every screen.
 * Read from the builds (the forecast's products), never written here: each robot takes a slot by product number, and the slot gives its colour and icon. */
export type Robot = { key: string; name: string; id: string; slot: number };

/** "Alpha A1" -> "A1": the short name a buyer uses for a robot. */
export const robotKey = (name: string) => name.split(" ").pop() ?? name;

export function useRobots(): Robot[] {
  const builds = useBuilds().data ?? [];
  const seen = new Map<string, string>();
  for (const b of builds) if (!seen.has(b.product.id)) seen.set(b.product.id, b.product.label ?? b.product.id);
  return [...seen].sort(([a], [b]) => a.localeCompare(b)).map(([id, name], slot) => ({ key: robotKey(name), name, id, slot }));
}

/** A line icon per slot (ICONS F71): a tote carrier on a drive base, a pallet mover with its fork mast, a picking arm on a pedestal. */
const PATHS: ReactElement[] = [
  <><rect x="3" y="14" width="18" height="4.5" rx="1.75" /><circle cx="7.5" cy="20" r="1.25" /><circle cx="16.5" cy="20" r="1.25" /><path d="M12 14v-3.5" /><path d="M4.5 5h15" /><path d="M6 5l1 5.5h10l1-5.5" /><path d="M10.2 7.5h3.6" /></>,
  <><rect x="2" y="10.5" width="6" height="8" rx="1.5" /><path d="M8.5 6v12.5" /><path d="M8.5 18.5h13.5" /><path d="M11 18.5v-1.5h8.5v1.5" /><rect x="11.5" y="10" width="7.5" height="7" rx=".75" /><circle cx="5" cy="20.5" r="1.25" /><circle cx="19.5" cy="20.5" r="1.25" /></>,
  <><path d="M4.5 21h11" /><rect x="7" y="17" width="5" height="4" rx="1" /><path d="M9.5 17v-5.75" /><circle cx="9.5" cy="10" r="1.25" /><path d="M10.6 9.3 16.5 5.3" /><circle cx="17.5" cy="4.6" r="1.25" /><path d="M18 5.8v4.2" /><path d="M16.4 10.5h3.2" /></>,
];
/** What the large drawing adds to the small icon: the arm's picked item. */
const EXTRA: (ReactElement | null)[] = [null, null, <rect key="item" x="15.5" y="12.5" width="5" height="3.5" rx=".6" />];

/** The robot's line icon, drawn in its slot's colour (tokens.css: --robot-1, --robot-2, --robot-3). */
export function RobotIcon({ slot, size = 16 }: { slot: number; size?: number }) {
  return (
    <svg className={`robot-ic robot-${(slot % PATHS.length) + 1}`} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      {PATHS[slot % PATHS.length]}
    </svg>
  );
}

/** The robot's large drawing for a page banner: the same lines at any size with a 2px stroke, decorative (aria-hidden). */
export function RobotDrawing({ slot, size = 320, className }: { slot: number; size?: number; className?: string }) {
  const n = slot % PATHS.length;
  return (
    <svg className={`robot-ic robot-draw robot-${n + 1}${className ? ` ${className}` : ""}`} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      {PATHS[n]}{EXTRA[n]}
    </svg>
  );
}

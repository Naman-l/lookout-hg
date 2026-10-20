import { useSyncExternalStore } from "react";

/** When the screen's data was last read from the server, and whether what is on screen is an older copy kept for offline use. */
type Fresh = { at: string | null; cached: boolean };
let state: Fresh = { at: null, cached: false };
const subs = new Set<() => void>();
const set = (next: Fresh) => { if (next.at !== state.at || next.cached !== state.cached) { state = next; subs.forEach((f) => f()); } };

/** Called by the client after every read: a live answer is fresh now; a kept copy carries the time it was read. */
export function noteRead(res: Response) {
  const kept = res.headers.get("x-lookout-cached");
  if (kept !== null) set({ at: kept || null, cached: true });
  else set({ at: new Date().toISOString(), cached: false });
}

export function useFreshness(): Fresh {
  return useSyncExternalStore((f) => { subs.add(f); return () => { subs.delete(f); }; }, () => state);
}

/** The time of day a record was made. Every record is made on the data's "today", so no weekday or date is printed. */
export const clockTime = (iso: string | null) => (iso ? new Date(iso).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false }) : "");
/** A run's own moment, absolute ("Oct 11, 20:29"): never "today", which reads against the data date. */
export const clock = (iso: string | null) => (iso ? `${new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" })}, ${clockTime(iso)}` : "");

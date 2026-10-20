import type { RunEvent } from "../api/types";

export interface Stream { events: RunEvent[]; typing: string }

/** Fold one streamed event into what the page holds. `step.delta` is the agent's words as they arrive: streamed, never stored, and it shares the seq of the last stored event, so it is kept apart from the stored events (and from their de-dup) and cleared when the finished `step.text` lands. */
export function foldEvent(s: Stream, e: RunEvent): Stream {
  if (e.type === "step.delta") return { ...s, typing: s.typing + e.summary };
  const typing = e.type === "step.text" ? "" : s.typing;
  if (s.events.some((p) => p.run_id === e.run_id && p.seq === e.seq)) return { ...s, typing };
  return { events: [...s.events, e], typing };
}

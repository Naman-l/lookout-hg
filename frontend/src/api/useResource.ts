import { useEffect, useRef, useState, useSyncExternalStore } from "react";

export type Resource<T> = { data?: T; error?: string; loading: boolean };

// One version for the whole app: anything that changes the server's state (an approval, a rejection, a run, an Ask that stages a draft) bumps it,
// and every resource on screen loads again, keeping what it shows until the new answer arrives. Counts, badges, queues, items and drafts agree without a reload.
let version = 0;
const listeners = new Set<() => void>();
export const invalidate = () => { version += 1; listeners.forEach((l) => l()); };
// Coming back to the window (or the tab) is a reason to look again: a draft the agent amended while you were away is never offered stale.
let last = 0;
if (typeof window !== "undefined") window.addEventListener("focus", () => { const now = Date.now(); if (now - last > 3000) { last = now; invalidate(); } });
const subscribe = (l: () => void) => { listeners.add(l); return () => { listeners.delete(l); }; };

/** Load on mount and whenever the dependencies change or the server's state does. Screens render the loading, empty and error states from this. */
export function useResource<T>(load: () => Promise<T>, deps: unknown[] = [], keep = false): Resource<T> {
  const [state, setState] = useState<Resource<T>>({ loading: true });
  const v = useSyncExternalStore(subscribe, () => version, () => 0);
  const seen = useRef(v);
  useEffect(() => {
    let live = true;
    const refresh = seen.current !== v; // a refresh keeps what is on screen
    seen.current = v;
    setState((prev) => (keep || refresh ? { ...prev, loading: !refresh } : { loading: true }));
    load().then(
      (data) => live && setState({ data, loading: false }),
      (e: Error) => live && setState((prev) => (refresh && prev.data ? { ...prev, loading: false } : { error: e.message, loading: false })),
    );
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, v]);
  return state;
}

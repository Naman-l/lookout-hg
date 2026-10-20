import { useSyncExternalStore } from "react";

/** Whether a media query matches now, kept live: the one place the app asks "is this a phone?" in code. */
export function useMedia(query: string): boolean {
  return useSyncExternalStore(
    (cb) => { const m = window.matchMedia(query); m.addEventListener("change", cb); return () => m.removeEventListener("change", cb); },
    () => window.matchMedia(query).matches,
    () => false,
  );
}

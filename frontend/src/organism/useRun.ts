import { useEffect, useState } from "react";
import { api, subscribeRun } from "../api/client";
import { invalidate } from "../api/useResource";
import type { RunDetail } from "../api/types";
import { foldEvent, type Stream } from "./runStream";

/** A run and its events, kept live (and the words being typed right now): stored events first, then the stream, de-duplicated by run and seq. */
export function useRun(runId: string) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [stream, setStream] = useState<Stream>({ events: [], typing: "" });
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true, off = () => {};
    setRun(null); setStream({ events: [], typing: "" }); setError(null);
    api.run(runId).then(
      (r) => {
        if (!live) return;
        setRun(r); setStream({ events: r.events ?? [], typing: "" });
        if (r.status === "running") {
          off = subscribeRun(runId, (e) => {
            if (!live) return;
            setStream((prev) => foldEvent(prev, e));
            if ((e.type === "run.finished" || e.type === "run.failed") && (!e.run_id || e.run_id === runId)) {      // the root run's end, not a specialist's: each delegated run sends its own run.finished first
              setRun((r) => (r ? { ...r, status: e.type === "run.failed" ? "failed" : "ok" } : r));
              api.run(runId).then((fresh) => { if (live && fresh.status !== "running") setRun(fresh); invalidate(); }).catch(() => {});
            }
          });
        }
      },
      (e: Error) => live && setError(e.message),
    );
    return () => { live = false; off(); };
  }, [runId]);
  return { run, events: stream.events, error, typing: stream.typing };
}

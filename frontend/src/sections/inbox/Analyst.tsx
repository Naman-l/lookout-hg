import { useState } from "react";
import { api } from "../../api/client";
import { useResource } from "../../api/useResource";
import type { Action } from "../../api/types";
import { Button, Notice } from "../../ds";
import { EntityLines } from "../../components/domain";
import { humanize } from "../../ui/format";
import { NO_AGENT } from "../../ui/copy";
import { useMe } from "../../api/useMe";
import { useAskState } from "../../shell/AskContext";

/** The Inbox analyst: what the message means, and (only for a contact on file) a drafted reply that waits for approval. Navigation is by button, never a link sentence. */
export function Analyst({ id, onFile }: { id: string; onFile: boolean }) {
  const { openRun } = useAskState();
  const { me } = useMe();
  const [busy, setBusy] = useState<"triage" | "reply" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const runs = useResource(() => api.runs().catch(() => []), [id]);
  const triage = runs.data?.find((x) => x.item_key === `triage:${id}`);
  const reply = runs.data?.find((x) => x.item_key === `reply:${id}`);
  const answer = useResource(() => (triage ? api.run(triage.run_id ?? "").catch(() => null) : Promise.resolve(null)), [triage?.run_id]);
  const drafts = useResource(() => api.actionsFor(`reply:${id}`).then((a) => a.filter((x) => x.item_key === `reply:${id}`)).catch(() => [] as Action[]), [id]);
  const reading = triage?.status === "running", drafting = reply?.status === "running"; // a run still going is not offered again
  const waiting = (drafts.data ?? []).find((a) => a.state === "proposed");
  const go = (kind: "triage" | "reply") => {
    setBusy(kind); setErr(null);
    (kind === "triage" ? api.triageRun(id, me ?? "") : api.replyRun(id, me ?? "")).then(
      (r) => { setBusy(null); openRun(r.run_id, kind === "triage" ? "What does this mean?" : "Draft a reply"); }, // the answer opens beside the message, not on the run log
      (e: Error) => { setBusy(null); setErr(e.message === "no-model" ? NO_AGENT : "The agent could not start. Try again."); },
    );
  };
  const rec = answer.data?.recommendation;
  return (
    <>
      {rec && (
        <div className="ib-read">
          <p className="ib-cap">What the analyst reads in it{answer.data?.recorded ? " · saved answer" : ""}</p>
          <div className="ds-decision"><EntityLines text={humanize(rec.finding)} /></div>
          {rec.grade?.checks_total != null && rec.grade.checks_passed != null && <p className="ds-caption">{rec.grade.checks_passed} of {rec.grade.checks_total} checks passed</p>}
        </div>
      )}
      <div className="ds-actions">
        <Button variant="primary" disabled={!!busy || reading} onClick={() => go("triage")}>{busy === "triage" ? "Starting…" : reading ? "Reading it…" : triage ? "Read it again" : "What does this mean?"}</Button>
        {onFile && <Button disabled={!!busy || drafting} onClick={() => go("reply")}>{busy === "reply" ? "Starting…" : drafting ? "Drafting…" : reply ? "Draft another reply" : "Draft a reply"}</Button>}
        {waiting && <Button to={`/approvals/${waiting.action_id}`}>Review the drafted reply</Button>}
        {triage && <Button variant="quiet" to={`/activity/${encodeURIComponent(triage.run_id ?? "")}`}>How we got here</Button>}
      </div>
      {!onFile && <p className="ds-note">No reply is offered: this sender is not a contact on file.</p>}
      {err && <Notice>{err}</Notice>}
    </>
  );
}

import { useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../../api/client";
import { invalidate } from "../../api/useResource";
import type { Action } from "../../api/types";
import { inr, longDate } from "../../ui/format";
import "./case.css";

const KIND: Record<string, string> = { supplier_request: "Letter to the vendor", internal_note: "Note inside the company", note: "On record", supplier_alias: "Vendor link" };

export const draftKind = (a: Action) => (a.type === "note" ? ((a.change as { kind?: string } | null)?.kind === "erp_update" ? "To enter in SAP" : (a.change as { kind?: string } | null)?.kind === "record" ? "Decision on record" : "Note") : KIND[a.type] ?? a.type);

/** Where a draft stands in words: waiting for the owner, signed and waiting for the countersign, sent (simulated), rejected. */
export function draftState(a: Action): string {
  const ch = (a.change ?? {}) as { owner?: string };
  if (a.state === "proposed") return `Waits for ${ch.owner ?? a.owner ?? "its owner"}'s signature${a.countersign ? `, then ${a.countersign}'s countersign` : ""}`;
  if (a.state === "signed") return `Signed by ${a.signed_by}; waits for ${a.countersign}'s countersign`;
  if (a.state === "approved") return "Approved; it goes out next";
  if (a.state === "executed") return a.type === "note" ? `Recorded by ${a.decided_by}` : `Sent (simulated) after ${a.signed_by && a.signed_by !== a.decided_by ? `${a.signed_by}'s signature and ${a.decided_by}'s countersign` : `${a.decided_by}'s approval`}`;
  return `Rejected by ${a.decided_by}${a.reason ? `: ${a.reason}` : ""}`;
}

/** The exact text that will be signed: who it goes to (on file), the DoA line, the letter itself; and, for the person whose move it is, sign / countersign,
 * edit or reject. Signing carries the text's hash: a draft changed since it was shown is refused. */
export function DraftView({ a, me, compact = false, onDone }: { a: Action; me: string | null; compact?: boolean; onDone?: (a: Action) => void }) {
  const [editing, setEditing] = useState(false);
  const [subject, setSubject] = useState(a.subject ?? "");
  const [body, setBody] = useState(a.body ?? "");
  const [reason, setReason] = useState("");
  const [rejecting, setRejecting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const ch = (a.change ?? {}) as { owner?: string; commits_inr?: number; doa_line?: string; to?: string; reason?: string; lines?: { po_line: string; was?: string; now: string }[] };
  const owner = ch.owner ?? a.owner ?? "";
  const mineToSign = !!me && a.state === "proposed" && owner === me;
  const mineToCounter = !!me && a.state === "signed" && a.countersign === me;
  const run = async (fn: () => Promise<Action>) => {
    setBusy(true); setErr("");
    try { const out = await fn(); invalidate(); onDone?.(out); } catch (e) { setErr(e instanceof ApiError ? e.detail || e.message : (e as Error).message); } finally { setBusy(false); }
  };
  const sign = () => run(() => api.approve(a.action_id, a.payload_hash, me ?? "", (a.unverified_checks ?? []).length > 0));
  const save = () => run(async () => { const out = await api.editAction(a.action_id, subject, body, me ?? ""); setEditing(false); return out; });
  const reject = () => run(() => api.reject(a.action_id, reason, me ?? ""));
  const to = a.recipient_name ? `${a.recipient_name} <${a.recipient}>` : a.recipient ?? ch.to ?? "";
  return (
    <div className={`df${compact ? " compact" : ""}`}>
      <p className="df-to">
        <span className="df-kind">{draftKind(a)}</span>
        {to && <> to <b>{to}</b> <small>(on file)</small></>}
        {a.item_key && !compact && <> · <Link to={`/items/${encodeURIComponent(a.item_key)}`}>the case</Link></>}
      </p>
      {(ch.commits_inr || a.doa_line) && <p className="df-doa">{ch.commits_inr ? <b>ⓢ commits {inr(ch.commits_inr)}</b> : null}{a.doa_line ? ` · ${a.doa_line}` : ""}</p>}
      {editing ? (
        <div className="df-edit">
          <input aria-label="Subject" value={subject} onChange={(e) => setSubject(e.target.value)} />
          <textarea aria-label="Text" rows={16} value={body} onChange={(e) => setBody(e.target.value)} />
        </div>
      ) : (
        <div className="df-mail">
          {a.subject && <p className="df-sub">{a.subject}</p>}
          <pre className="df-body">{a.body}</pre>
          {ch.reason && <p className="df-why"><b>Reason on record:</b> {ch.reason}</p>}
          {ch.lines && ch.lines.length > 0 && <table className="cp-t"><thead><tr><th>PO line</th><th>Was</th><th>Becomes</th></tr></thead>
            <tbody>{ch.lines.map((l) => <tr key={l.po_line}><td>{l.po_line}</td><td>{l.was ? longDate(l.was) : "—"}</td><td>{longDate(l.now)}</td></tr>)}</tbody></table>}
        </div>
      )}
      <p className={`df-state s-${a.state}`}>{draftState(a)}{a.edited_by ? ` · edited by hand by ${a.edited_by}` : ""}</p>
      {(a.unverified_checks ?? []).length > 0 && <p className="df-warn">The run that wrote this did not pass its checks: {(a.unverified_checks ?? []).join("; ")}. Signing confirms you checked the figures.</p>}
      {err && <p className="df-err" role="alert">{err}</p>}
      {(mineToSign || mineToCounter) && (
        <div className="df-act">
          {editing ? (
            <>
              <button type="button" className="b9 dark" disabled={busy} onClick={save}>Save the text</button>
              <button type="button" className="b9" disabled={busy} onClick={() => { setEditing(false); setSubject(a.subject ?? ""); setBody(a.body ?? ""); }}>Cancel</button>
            </>
          ) : rejecting ? (
            <>
              <input className="df-reason" placeholder="Why (the next draft follows it)" value={reason} onChange={(e) => setReason(e.target.value)} />
              <button type="button" className="b9 dark" disabled={busy || !reason.trim()} onClick={reject}>Reject</button>
              <button type="button" className="b9" disabled={busy} onClick={() => setRejecting(false)}>Cancel</button>
            </>
          ) : (
            <>
              <button type="button" className="b9 dark" disabled={busy} onClick={sign}>
                {mineToCounter ? "Countersign and send" : a.type === "note" ? "Sign" : a.countersign ? `Sign (then ${a.countersign.split(" ")[0]} countersigns)` : a.type === "internal_note" ? "Sign and send the note" : "Approve and send"}
              </button>
              {mineToSign && <button type="button" className="b9" disabled={busy} onClick={() => setEditing(true)}>Edit</button>}
              <button type="button" className="b9" disabled={busy} onClick={() => setRejecting(true)}>Reject</button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

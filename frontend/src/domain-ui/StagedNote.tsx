import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useResource } from "../api/useResource";
import type { Action, ActionItem } from "../api/types";
import { usePartNames } from "../api/usePartNames";
import { WhatChanges, type Change } from "./WhatChanges";
import "./staged-note.css";

/** Approvals for everything (F101, ui-ai-contract "Approvals = everything that needs a signature"): a note, a decision or a PO-line update staged on a
 * case waits for the same owner-only, hash-bound Approve as an email. Nothing is sent: approving records it ("Recorded"). */

export type StagedKind = "note" | "record" | "erp_update";
export type StagedChange = { kind: StagedKind; to?: string | null; reason?: string | null; lines?: { po_line: string; was?: string | null; now: string }[] | null; recheck_on?: string | null; option_kind?: string | null; owner?: string | null };

/** The staged change of a note the owner signs, or null for an email or a note the run logged itself (it carries no kind and is already done). */
export const stagedOf = (a: Action | null | undefined): StagedChange | null => {
  const c = a?.type === "note" ? (a.change as StagedChange | null | undefined) : null;
  return c && (c.kind === "note" || c.kind === "record" || c.kind === "erp_update") ? c : null;
};

const day = (iso?: string | null) => (iso ? new Date(`${iso.slice(0, 10)}T00:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" }) : "");
/** "Note to planning" / "Decision" / "PO lines to update": the heading, the server's subject. */
export const stagedTitle = (a: Action) => a.subject ?? "Note";
/** The staged item as Ask names it: "this note", "this decision", "this PO-line update". */
export const stagedNoun = (c: StagedChange) => (c.kind === "erp_update" ? "this PO-line update" : c.kind === "record" ? "this decision" : "this note");
/** What happens on Approve, said once under the button and once after it. */
export const stagedEffect = (c: StagedChange) => (c.kind === "erp_update" ? "to enter in the ERP" : c.kind === "record" ? "recorded on the case" : `recorded for ${c.to ?? "the reader"}`);

/** The staged item as it will be recorded: who it is for, the text, the reason and re-check date, or the PO lines as was → now. */
export type StagedEdit = { body: string; reason: string; recheck_on: string };

export function StagedDoc({ a, c, item, edit, onEdit }: { a: Action; c: StagedChange; item: ActionItem | null; edit?: StagedEdit | null; onEdit?: (e: StagedEdit) => void }) {
  const names = usePartNames();
  const lines = c.lines ?? [];
  const orders = useResource(() => Promise.all(lines.map((l) => api.order(l.po_line).catch(() => null))), [a.action_id]);
  const changes: Change[] = lines.map((l, k) => {
    const o = orders.data?.[k] as { part?: { id: string }; qty_open?: { value: string } } | null | undefined;
    const part = o?.part?.id;
    return { ref: { type: "po_line", id: l.po_line }, label: part ? `${names(part) ?? part} (${part})` : l.po_line, before: l.was ?? null, after: l.now,
             qty: o?.qty_open ? Number(o.qty_open.value) : null };      // the open quantity: what a signer checks against a date change (BUYER)
  });
  return (
    <div className="sn">
      <dl className="sn-meta">
        {c.kind === "note" && <><dt>To</dt><dd>{c.to}</dd></>}
        {item && <><dt>Case</dt><dd><Link to={`/items/${encodeURIComponent(item.key)}`}>{item.title}</Link></dd></>}
      </dl>
      {edit && onEdit ? (
        // The owner's own words before signing (UX F101): the statement, the reason, the re-check date. Esc restores (the caller).
        <div className="sn-edit">
          <textarea aria-label="Decision" autoFocus value={edit.body} onChange={(e) => onEdit({ ...edit, body: e.target.value })} />
          <label>Reason<input value={edit.reason} onChange={(e) => onEdit({ ...edit, reason: e.target.value })} /></label>
          <label>Re-check<input type="date" value={edit.recheck_on} onChange={(e) => onEdit({ ...edit, recheck_on: e.target.value })} /></label>
        </div>
      ) : a.body && <p className="sn-text">{a.body}</p>}
      {c.kind === "record" && !edit && (
        <dl className="sn-meta">
          {c.reason && <><dt>Reason</dt><dd>{c.reason}</dd></>}
          {c.recheck_on && <><dt>Re-check</dt><dd>{day(c.recheck_on)}</dd></>}
        </dl>
      )}
      {c.kind === "erp_update" && lines.length > 0 && <WhatChanges changes={changes} caption={item?.lines_in_scope && item.lines_in_scope > lines.length ? `${lines.length} of ${item.lines_in_scope} lines` : `${lines.length} PO line${lines.length === 1 ? "" : "s"}`} wasLabel="Was" nowLabel="Now" qtyLabel="Open qty" delta />}
    </div>
  );
}

/** Approve · Reject for a staged item: the same owner-only, hash-bound route as an email, no Edit (the text is the one staged), nothing sent. */
export function StagedDecision({ me, busy, c, onApprove, onReject, onEdit }: { me: string; busy?: boolean; c: StagedChange; onApprove: () => void; onReject: () => void; onEdit?: () => void }) {
  return (
    <div className="dd">
      <button type="button" className="db-btn go wide" disabled={busy} onClick={onApprove}>Approve</button>
      <div className="db-act">{onEdit && <button type="button" className="db-btn sm" onClick={onEdit}>Edit</button>}<button type="button" className="db-btn sm no" onClick={onReject}>Reject</button></div>
      <div className="db-cap">Nothing is sent · {stagedEffect(c)} on approval · as {me}</div>
    </div>
  );
}

/** After the decision: "Recorded Sep 25" with who approved it and what it is for. */
export function StagedState({ a, c, asOf }: { a: Action; c: StagedChange; asOf: string }) {
  return a.state === "rejected"
    ? <div className="db-state"><b>Rejected by {a.decided_by}</b><span>{a.reason}</span></div>
    : <div className="db-state"><b>Recorded {asOf}</b><span>Approved by {a.decided_by} · {stagedEffect(c)} · nothing was sent</span></div>;
}

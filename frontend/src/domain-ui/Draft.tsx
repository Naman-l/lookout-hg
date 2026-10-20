import type { ReactNode } from "react";
import type { Action } from "../api/types";
import { StateChip } from "../ds";

/** Exactly what will be sent: the recipient (on file), the subject and the body, as the buyer will approve them. The approval is bound to this text by its hash. */
export function Draft({ action, target }: { action: Action; target?: ReactNode }) {
  return (
    <div className="mail">
      <div className="h">
        <div><span className="k">To</span><span>{action.recipient} <StateChip tone="positive">contact on file</StateChip> {target}</span></div>
        <div><span className="k">Subject</span><b>{action.subject}</b></div>
      </div>
      <div className="b">{action.body}</div>
    </div>
  );
}

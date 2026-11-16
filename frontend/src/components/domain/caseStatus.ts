import type { ActionItem } from "../../api/types";

/** Where a case stands, in Today's words, shared by every screen that names a case: Today's rows, the sidebar count, Records' "In a case". */
export const owners = (i: ActionItem) => (i.owner ?? "").split(" · ").map((n) => n.trim()).filter(Boolean);
export const first = (n: string) => n.split(" ")[0];

export type Status = { word: string; tone: "you" | "oth" | "held" | "done"; step: number; full: string };

/** One word for where a case stands from the viewer's side: theirs (Decide, Approve, Countersign, Replied), someone else's (With <first name>, With Projects,
 * With the vendor), or held mail. */
export function statusOf(i: ActionItem, me: string | null): Status {
  const s = i.stage;
  if (i.tab === "trust") return { word: "Held", tone: "held", step: 0, full: "Held before anyone read it. Record the controls; nothing is paid, ordered or drafted from it." };
  if (!s) return { word: "Decide", tone: "you", step: 0, full: "The routes are ready to choose from." };
  const step = s.step - 1;
  const mine = !!me && owners(i).includes(me);
  switch (s.key) {
    case "found":
    case "decision_ready": return mine ? { word: "Decide", tone: "you", step, full: s.next_act } : { word: `With ${first(owners(i)[0] ?? "")}`, tone: "oth", step, full: `Waiting on ${owners(i).join(" and ")} to choose a route.` };
    case "worked": return { word: "Review", tone: mine ? "you" : "oth", step, full: s.next_act };
    case "drafted": return mine ? { word: "Approve", tone: "you", step, full: s.next_act } : { word: `With ${first(owners(i)[0] ?? "")}`, tone: "oth", step, full: `Waiting on ${owners(i).join(" and ")} to sign.` };
    case "signed": return s.waiting_on === me ? { word: "Countersign", tone: "you", step, full: s.next_act } : { word: `With ${first(s.waiting_on ?? "the Head")}`, tone: "oth", step, full: s.next_act };
    case "approved": return { word: s.label === "Recorded" ? "Recorded" : "Approved", tone: "done", step, full: s.next_act };
    case "sent": return { word: s.label === "Sent" ? "With vendor" : s.label, tone: "oth", step, full: s.next_act };
    default: return { word: "Replied", tone: mine ? "you" : "oth", step, full: s.next_act };
  }
}

/** The viewer's move: theirs to act on (held mail, decide, approve, countersign) or a reply to read. Anything with someone else waits on others. Today's
 * Yours and the sidebar count the same. */
export const yourMove = (i: ActionItem, me: string | null) => {
  const st = statusOf(i, me);
  return !!me && (st.tone === "you" || (st.tone === "held" && owners(i).includes(me)));
};

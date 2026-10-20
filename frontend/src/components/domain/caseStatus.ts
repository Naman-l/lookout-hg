import type { Action, ActionItem } from "../../api/types";

/** Where a case stands, in Today's words (FINAL 02 §3), shared by every screen that names a case: Today's rows, Records' case cells, a supplier's or part's "In a case". */
export const owners = (i: ActionItem) => (i.owner ?? "").split(" · ").map((n) => n.trim()).filter(Boolean);
export const first = (n: string) => n.split(" ")[0];

/** The date to act by: the item's own, or the data date for what is already past due (the chase) or held. */
export const actBy = (i: ActionItem, asOf: string | null) => i.act_by ?? (i.key === "deadline:chase" || i.group === "trust" ? asOf : null);

/** Whether the viewer picked an option on this case in this server run (the case page keeps it as lookout.chosen.<key>.<boot>.…). */
export function chosenOn(key: string, boot: string): boolean {
  try {
    for (let n = 0; n < sessionStorage.length; n++) { const k = sessionStorage.key(n); if (k?.startsWith(`lookout.chosen.${key}.${boot}.`) && sessionStorage.getItem(k)) return true; }
  } catch { /* nothing kept */ }
  return false;
}

export type Status = { word: string; tone: "start" | "you" | "oth" | "held"; step: number; full: string };
/** One word for where an item stands, from the viewer's side: the agent's step (Start, Review), the viewer's (Decide, Approve), someone else's (With <first name>), the supplier's (Sent, Replied). */
/** The cases where the viewer has a draft of their own waiting: a team case (the chase) holds one draft per buyer, and the stage names only one (AI-UI-SYNC A1). */
export function myDraftCases(actions: Action[] | null | undefined, me: string | null): Set<string> {
  return new Set((actions ?? []).filter((a) => a.state === "proposed" && a.item_key && me && (a as Action & { owner?: string | null }).owner === me).map((a) => a.item_key as string));
}

/** A draft the buyer has chosen (Khalid 11:35: the buyer decides, drafts follow her choice): a route she chose (the choose endpoint's flag), or a note or decision she staged herself. Only these wait in Approvals. */
export const chosenDraft = (a: Action) => a.type === "note" || !!(a as Action & { chosen?: boolean }).chosen;

/** The cases where the viewer's own waiting draft is one she chose: Approve; a prepared draft she has not chosen yet is Decide. */
export function myChosenCases(actions: Action[] | null | undefined, me: string | null): Set<string> {
  return new Set((actions ?? []).filter((a) => a.state === "proposed" && a.item_key && me && (a as Action & { owner?: string | null }).owner === me && chosenDraft(a)).map((a) => a.item_key as string));
}

/** The viewer's move: theirs to act on (held, start, review, decide, approve) or a reply to read. Anything with someone else or the supplier waits on others. Today's Yours and the sidebar count the same. */
export const yourMove = (i: ActionItem, st: Status, me: string | null) => !!me && owners(i).includes(me) && (st.tone !== "oth" || i.stage?.key === "answered");

export function statusOf(i: ActionItem, me: string | null, draftOwner: Map<string, string>, _boot?: string, mine?: Set<string>, chosen?: Set<string>): Status {
  const s = i.stage;
  const supplier = (i.refs ?? []).find((r) => r.type === "supplier")?.label ?? "the supplier";
  if (i.group === "trust") return { word: "Held", tone: "held", step: 0, full: `Held as suspected fraud. ${/do not order/i.test(i.title) ? "Do not order." : "Do not pay."}` };
  if (!s) return { word: "Start", tone: "start", step: 0, full: "Detected · not reviewed yet" };
  const step = s.step - 1;
  switch (s.key) {
    case "found": return { word: "Start", tone: "start", step, full: "Detected · not reviewed yet" };
    case "worked": return { word: "Review", tone: "start", step, full: "Worked · review the answer" };
    case "decision_ready": return { word: "Decide", tone: "you", step, full: "Options ready · yours to decide" };
    case "drafted": {
      const who = (me && mine?.has(i.key) ? me : "") || (s.action && draftOwner.get(s.action.id)) || owners(i)[0] || "";
      if (me && who === me && !chosen?.has(i.key)) return { word: "Decide", tone: "you", step: step - 1, full: "Lookout prepared a draft · choose your route" };      // her move: the route is hers to choose
      return me && who === me ? { word: "Approve", tone: "you", step, full: `Your email to ${supplier} is ready to approve.` } : { word: `With ${first(who)}`, tone: "oth", step, full: `Waiting on ${first(who)} to approve.` };
    }
    case "approved": return { word: "Approved", tone: "oth", step, full: "Approved; it goes out next." };
    case "sent": return { word: "Sent", tone: "oth", step, full: `Sent. Waiting for ${supplier} to answer.` };
    default: return { word: "Replied", tone: "oth", step, full: `${supplier} replied. Read what changed.` };
  }
}

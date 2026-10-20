import type { Quantity as Q, Money as M, Value as V } from "../api/types";
import { StateChip } from "../ds";
import { Value } from "./Value";
import { shortDate } from "../ui/format";

/* Values: a figure always says how sure we are of it, and opens its source. */
export { UnknownValue } from "./Unknown";
export { Value as ProvenanceValue } from "./Value";

export const Money = ({ value, whole }: { value: M; whole?: boolean }) => <Value value={value as V} tag={false} whole={whole} />;

/** A quantity with its unit; "up to" while stock on hand is unknown, because a shortage is then an upper bound. */
export function Quantity({ value, upTo }: { value: Q; upTo?: boolean }) {
  return <>{upTo && <span className="muted">up to </span>}<Value value={value as V} tag={false} /></>;
}

/** A date with its distance from the DATA date, not the clock: "Oct 10 · in 15 days", and a caution chip once it has passed. */
export function DateDue({ date, daysLeft }: { date: string; daysLeft?: number | null }) {
  const past = daysLeft != null && daysLeft < 0;
  const rel = daysLeft == null ? "" : daysLeft === 0 ? "that day" : daysLeft === 1 ? "in 1 day" : past ? `${-daysLeft} ${daysLeft === -1 ? "day" : "days"} ago` : `in ${daysLeft} days`;
  return <span>{shortDate(date)}{rel && <span className="muted"> · {rel}</span>}{past && <> <StateChip tone="caution">past</StateChip></>}</span>;
}

/** How a value was reached when it is not simply recorded. */
export const MethodBadge = ({ method }: { method: "inferred" | "flagged" }) => <StateChip tone={method === "flagged" ? "caution" : "unknown"}>{method === "flagged" ? "flagged" : "estimated"}</StateChip>;

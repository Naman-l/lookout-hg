import { Link } from "react-router-dom";
import type { ReactNode } from "react";
import { Notice, StateChip, Tile, Tiles } from "../ds";
import { Quantity as Qty } from "./Values";
import { LATE_ON_LATEST } from "../ui/copy";
import type { Quantity as Q, Money as M } from "../api/types";
import { Money } from "./Values";

export { Ladder as StageLadder } from "./Ladder";

/* Concepts: what the industry's words mean, drawn the same way everywhere. */

const KINDS = [
  { k: "covered", text: "dated supply lands in the month" },
  { k: "after_build", text: "arrive after the month ends", tone: "caution" as const },
  { k: "past_due", text: LATE_ON_LATEST, tone: "caution" as const },
  { k: "disrupted", text: "under a force-majeure notice", tone: "critical" as const },
  { k: "no_order", text: "no open order: unknown without stock data", tone: "unknown" as const },
  { k: "in_house", text: "built in-house, counted through their parts" },
];
/** The six counts of a build: how many bought parts are covered, late, disrupted or unknown. Counts, never a percent. */
export function ReadinessSummary({ counts }: { counts: Record<string, number> }) {
  return <Tiles>{KINDS.map((x) => <Tile key={x.k} figure={counts[x.k] ?? 0} label={x.text} tone={counts[x.k] ? x.tone : undefined} />)}</Tiles>;
}

/** A shortage: how many are short, in which month, before any stock is counted. */
export function ShortageFigure({ short, month }: { short: Q; month: string }) {
  const name = new Date(`${month}-01T00:00:00Z`).toLocaleString("en-US", { month: "long", timeZone: "UTC" });
  return <Tile tone="critical" figure={<Qty value={short} upTo />} label={`short in ${name}, before stock on hand`} />;
}

/** The new duty: the net figure to act on, the gross, and the one line that says what the two mean. */
export function TariffExposure({ net, gross }: { net: M; gross?: M | null }) {
  return (
    <>
      <Tiles><Tile figure={<Money value={net} />} label="New duty, net" />{gross && <Tile figure={<Money value={gross} />} label="Gross, if every line slips past Nov 1" />}</Tiles>
      <p className="ds-note">Net: what to act on (lines landing after Nov 1, and demand not yet ordered). Gross: if every open line slipped past Nov 1.</p>
    </>
  );
}

/** A message the system will not act on, and why. */
export function TrustFlag({ flags, children }: { flags: string[]; children?: ReactNode }) {
  return <Notice tone="risk">{children ?? <>This message looks suspicious: {flags.join(", ")}. Nothing can be approved from it, and no reply is offered.</>}</Notice>;
}

const EVENT: Record<string, string> = { force_majeure: "Force majeure", allocation: "Allocation", price_notice: "Price notice", delay: "Delay" };
/** A supplier's notice, named for what it is, with the message it came from. */
export function SupplierEvent({ kind, messageId, children }: { kind: keyof typeof EVENT | string; messageId?: string; children?: ReactNode }) {
  return (
    <span>
      <StateChip tone={kind === "force_majeure" ? "critical" : "caution"}>{EVENT[kind] ?? kind}</StateChip>
      {children && <> {children}</>}
      {messageId && <> <Link to={`/inbox/${encodeURIComponent(messageId)}`}>the notice</Link></>}
    </span>
  );
}

import { CalendarClock, CircleHelp, Landmark, PackageX, ShieldAlert, TrendingDown, type LucideIcon } from "lucide-react";
import { Tip } from "./Tip";

export type Kind = "cant_deliver" | "import_duty" | "deadline" | "held_message" | "open_question" | "supplier_at_risk";

/** One name everyone understands, one line of meaning. The backend's group names (disruption, tariff, trust, unknown) are not shown. */
export const KINDS: Record<Kind, { name: string; meaning: string; Icon: LucideIcon; tone?: "red" }> = {
  cant_deliver: { name: "Supplier can't deliver", meaning: "A supplier cannot ship what we ordered, for example after a plant fire.", Icon: PackageX },
  import_duty: { name: "New import duty", meaning: "A new tax on parts made in a country, from a set date.", Icon: Landmark },
  deadline: { name: "Deadline", meaning: "Money or an option is lost on a date.", Icon: CalendarClock },
  held_message: { name: "Held message", meaning: "A message that may be fraud; nothing can be done from it.", Icon: ShieldAlert, tone: "red" },
  open_question: { name: "Open question", meaning: "The data cannot answer; a person must.", Icon: CircleHelp },
  supplier_at_risk: { name: "Supplier at risk", meaning: "A supplier in financial trouble or changing its terms.", Icon: TrendingDown },
};
const ORDER = Object.keys(KINDS) as Kind[];

/** The API's group for an action item, as the kind a buyer sees. */
export const kindOfGroup = (group: string, key?: string): Kind =>
  key?.startsWith("risk:") ? "supplier_at_risk" : group === "disruption" ? "cant_deliver" : group === "tariff" ? "import_duty" : group === "deadline" ? "deadline" : group === "trust" ? "held_message" : "open_question";

export function ProblemKind({ kind, iconOnly }: { kind: Kind; iconOnly?: boolean }) {
  const k = KINDS[kind];
  return (
    <Tip tip={k.meaning}>
      <span className="dm-kind" data-tone={k.tone}>
        <k.Icon size={14} strokeWidth={1.75} aria-hidden />
        <span className={iconOnly ? "dm-sr" : undefined}>{k.name}</span>
      </span>
    </Tip>
  );
}

/** The legend on Today: every kind with what it means, closed by default so it costs one line. */
export function ProblemLegend() {
  return (
    <details className="dm-legend">
      <summary>What these mean</summary>
      <dl>
        {ORDER.map((id) => { const k = KINDS[id]; return (
          <div key={id}><dt data-tone={k.tone}><k.Icon size={14} strokeWidth={1.75} aria-hidden />{k.name}</dt><dd>{k.meaning}</dd></div>
        ); })}
      </dl>
    </details>
  );
}

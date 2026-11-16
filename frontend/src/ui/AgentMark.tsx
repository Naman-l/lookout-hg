import { Binoculars, BadgeCheck, Boxes, Database, FilePenLine, Inbox, Landmark, MapPin, Radar, Scale, TrendingUp } from "lucide-react";
import type { ReactNode } from "react";

// A small consistent mark and colour per agent, so delegation reads at a glance.
const MARKS: Record<string, { icon: ReactNode; label: string }> = {
  lookout: { icon: <Radar size={14} strokeWidth={1.75} />, label: "Lookout" },
  supply_planner: { icon: <Boxes size={14} strokeWidth={1.75} />, label: "Supply planner" },
  buyers_clerk: { icon: <FilePenLine size={14} strokeWidth={1.75} />, label: "Buyer’s clerk" },
  tariff_analyst: { icon: <Landmark size={14} strokeWidth={1.75} />, label: "Tariff analyst" },
  sourcing_analyst: { icon: <Scale size={14} strokeWidth={1.75} />, label: "Sourcing analyst" },
  verifier: { icon: <BadgeCheck size={14} strokeWidth={1.75} />, label: "Verifier" },
  site_planner: { icon: <MapPin size={14} strokeWidth={1.75} />, label: "Site requirement planner" },
  price_analyst: { icon: <TrendingUp size={14} strokeWidth={1.75} />, label: "Price and PV analyst" },
  inbox_analyst: { icon: <Inbox size={14} strokeWidth={1.75} />, label: "Inbox analyst" },
  data_steward: { icon: <Database size={14} strokeWidth={1.75} />, label: "Data steward" },
};

export function AgentMark({ agent }: { agent?: string | null }) {
  const m = (agent && MARKS[agent]) || { icon: <Binoculars size={14} strokeWidth={1.75} />, label: agent ?? "Agent" };
  return (
    <span className="mark" style={{ background: `var(--agent-${agent ?? "lookout"}, var(--agent-verifier))` }} title={m.label} aria-label={m.label}>
      {m.icon}
    </span>
  );
}

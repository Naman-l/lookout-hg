import { Binoculars, BadgeCheck, Boxes, FilePenLine, Landmark, Radar, Scale } from "lucide-react";
import type { ReactNode } from "react";

// A small consistent mark and colour per agent, so delegation reads at a glance.
const MARKS: Record<string, { icon: ReactNode; label: string }> = {
  lookout: { icon: <Radar size={14} strokeWidth={1.75} />, label: "Lookout" },
  supply_planner: { icon: <Boxes size={14} strokeWidth={1.75} />, label: "Supply planner" },
  buyers_clerk: { icon: <FilePenLine size={14} strokeWidth={1.75} />, label: "Buyer’s clerk" },
  tariff_analyst: { icon: <Landmark size={14} strokeWidth={1.75} />, label: "Tariff analyst" },
  sourcing_analyst: { icon: <Scale size={14} strokeWidth={1.75} />, label: "Sourcing analyst" },
  verifier: { icon: <BadgeCheck size={14} strokeWidth={1.75} />, label: "Verifier" },
};

export function AgentMark({ agent }: { agent?: string | null }) {
  const m = (agent && MARKS[agent]) || { icon: <Binoculars size={14} strokeWidth={1.75} />, label: agent ?? "Agent" };
  return (
    <span className="mark" style={{ background: `var(--agent-${agent ?? "lookout"}, var(--agent-verifier))` }} title={m.label} aria-label={m.label}>
      {m.icon}
    </span>
  );
}

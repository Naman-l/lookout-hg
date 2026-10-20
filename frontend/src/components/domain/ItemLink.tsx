import { Link } from "react-router-dom";
import { ChevronRight } from "lucide-react";
import { KINDS, kindOfGroup } from "./ProblemKind";
import { Stage, type StageKey } from "./Stage";

/** The work item a record belongs to, as one row: its kind icon, its title and where it stands. The whole row is the link. */
export function ItemLink({ id, title, group, stage, waitingOn }: { id: string; title: string; group: string; stage?: StageKey | null; waitingOn?: string | null }) {
  const k = KINDS[kindOfGroup(group)];
  return (
    <Link className="dm-itemlink" to={`/items/${encodeURIComponent(id)}`} aria-label={`${k.name}: ${title}`}>
      <k.Icon size={16} strokeWidth={1.5} aria-hidden />
      <span className="dm-t"><b>{title}</b><span className="dm-sub">{k.name}{stage && <Stage stage={stage} waitingOn={waitingOn} />}</span></span>
      <ChevronRight size={16} strokeWidth={1.5} aria-hidden />
    </Link>
  );
}

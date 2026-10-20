import { Link } from "react-router-dom";
import type { EntityRef } from "../../api/types";
import { api } from "../../api/client";
import { useResource } from "../../api/useResource";

/** A message is named by its subject, never by the file it came from ("2026-09-21_Quotation_QV-Q-2609-17_…"). */
const fileWords = (id: string) => id.replace(/^\d{4}-\d{2}-\d{2}_/, "").replace(/_/g, " ");

export function MessageChip({ r }: { r: EntityRef }) {
  const all = useResource(() => api.messages());
  const subject = (all.data ?? []).find((m) => m.ref.id === r.id)?.ref.label;
  const raw = r.label && r.label !== r.id ? r.label : null;
  return <Link className="chip" to={`/inbox?thread=${encodeURIComponent(r.id)}`}>{subject ?? raw ?? fileWords(r.id)}</Link>;
}

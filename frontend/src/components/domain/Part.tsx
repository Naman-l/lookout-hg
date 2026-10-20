import { Link } from "react-router-dom";
import { Cog } from "lucide-react";

/** A part: icon, short name, the product when two parts share a name, and the number in small mono. The whole chip is the link. */
export function Part({ id, name, product, to = true }: { id: string; name?: string | null; product?: string | null; to?: boolean }) {
  const inner = (
    <>
      <Cog size={14} strokeWidth={1.5} aria-hidden />
      {name && <span className="dm-name">{name}</span>}
      {name && product && <span className="dm-hint">· {product}</span>}
      <span className="dm-id">{id}</span>
    </>
  );
  const label = [name, product, id].filter(Boolean).join(" ");
  return to
    ? <Link className="dm-chip" to={`/parts/${encodeURIComponent(id)}`} title={label} aria-label={`Part ${label}`}>{inner}</Link>
    : <span className="dm-chip" title={label}>{inner}</span>;
}

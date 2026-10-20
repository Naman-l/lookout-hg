import { Link } from "react-router-dom";
import { Building2, CircleAlert, CircleCheck, CircleDashed } from "lucide-react";

export type SupplierTrust = "on_file" | "new" | "lookalike";
const TRUST = {
  on_file: { word: "On file", tone: "green", Icon: CircleCheck },
  new: { word: "New", tone: "amber", Icon: CircleDashed },
  lookalike: { word: "Look-alike", tone: "red", Icon: CircleAlert },
} as const;

/** A supplier: icon, name, country code and, when known, whether we have it on file. The whole chip is the link. */
export function Supplier({ id, name, country, trust, to = true }: { id: string; name?: string | null; country?: string | null; trust?: SupplierTrust; to?: boolean }) {
  const t = trust ? TRUST[trust] : null;
  const label = [name ?? id, country, t?.word].filter(Boolean).join(", ");
  const inner = (
    <>
      <Building2 size={14} strokeWidth={1.5} aria-hidden />
      <span className="dm-name">{name ?? id}</span>
      {country && <span className="dm-id">{country}</span>}
      {t && <span className="dm-tag" data-tone={t.tone}><t.Icon size={12} strokeWidth={2} aria-hidden />{t.word}</span>}
    </>
  );
  return to
    ? <Link className="dm-chip" to={`/suppliers/${encodeURIComponent(id)}`} title={label} aria-label={`Supplier ${label}`}>{inner}</Link>
    : <span className="dm-chip" title={label}>{inner}</span>;
}

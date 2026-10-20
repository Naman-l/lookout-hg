import { Link } from "react-router-dom";
import { Building2, ChevronRight, FileText, Package, TrendingUp } from "lucide-react";
import type { ReactNode } from "react";
import { api } from "../api/client";
import { useResource } from "../api/useResource";

const ICON = { size: 18, strokeWidth: 1.5 } as const;

function Rows({ rows }: { rows: { to: string; icon: ReactNode; label: string; note?: string }[] }) {
  return (
    <div className="lines wide">
      {rows.map((r) => (
        <Link key={r.to} className="ln link nav-row" to={r.to}>
          <span className="ic">{r.icon}</span>
          <span className="cell">{r.label}</span>
          <span className="muted">{r.note}</span>
          <ChevronRight size={16} strokeWidth={1.5} className="chev" />
        </Link>
      ))}
    </div>
  );
}

/** More: the lookups a phone needs (a part at the shelf, the records to read). Data, agent activity and import are desktop work. */
export function More() {
  const c = useResource(api.counts).data;
  return (
    <>
      <h1>More</h1>
      <Rows rows={[
        { to: "/suppliers", icon: <Building2 {...ICON} />, label: "Suppliers", note: c ? String(c.suppliers) : undefined },
        { to: "/parts", icon: <Package {...ICON} />, label: "Parts", note: c ? String(c.parts) : undefined },
        { to: "/orders", icon: <FileText {...ICON} />, label: "Orders", note: c ? `${c.open_po_lines} open` : undefined },
        { to: "/forecast", icon: <TrendingUp {...ICON} />, label: "Forecast and demand" },
      ]} />
    </>
  );
}

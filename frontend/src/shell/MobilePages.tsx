import { Link } from "react-router-dom";
import { BarChart3, Building2, ChevronRight, ClipboardList, FileText, Layers, Network, Package, ScanLine, Users } from "lucide-react";
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

/** More: what a phone needs beyond Today, Approvals and Inbox: the material lookup on site, the records, the Insights pages. */
export function More() {
  const c = useResource(() => api.counts()).data;
  return (
    <>
      <h1>More</h1>
      <Rows rows={[
        { to: "/lookup", icon: <ScanLine {...ICON} />, label: "Material lookup on site" },
        { to: "/vendors", icon: <Building2 {...ICON} />, label: "Vendors" },
        { to: "/materials", icon: <Package {...ICON} />, label: "Materials" },
        { to: "/prs", icon: <ClipboardList {...ICON} />, label: "PRs", note: c ? `${c.open_prs} open` : undefined },
        { to: "/pos", icon: <FileText {...ICON} />, label: "POs", note: c ? `${c.open_po_lines} open lines` : undefined },
        { to: "/requirements", icon: <Layers {...ICON} />, label: "Requirements" },
        { to: "/insights/team", icon: <Users {...ICON} />, label: "Team" },
        { to: "/org", icon: <Network {...ICON} />, label: "Organisation" },
        { to: "/insights/projects", icon: <BarChart3 {...ICON} />, label: "Projects" },
      ]} />
    </>
  );
}

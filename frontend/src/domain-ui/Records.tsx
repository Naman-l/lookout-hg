import { Link } from "react-router-dom";
import type { EntityRef } from "../api/types";
import { StateDot } from "../ds";

/* Records: every mention of a part, supplier, PO line or build reads the same way, on every screen. */

/** A part: its name first and its number after it in small mono. The number stands alone only where there is no name to give. */
export function PartRef({ id, name }: { id: string; name?: string | null; compact?: boolean }) {
  return (
    <Link className="partref" to={`/parts/${encodeURIComponent(id)}`}>
      {name ? <><span className="nm">{name}</span><span className="num-after">{id}</span></> : <span className="pn">{id}</span>}
    </Link>
  );
}

/** A supplier by name, with the one thing a buyer needs to know about it: whether it is on file. */
export function SupplierRef({ r, status = "on_file" }: { r: EntityRef; status?: "on_file" | "unvetted" | "hold" }) {
  const state = status === "on_file" ? undefined : status === "hold" ? "late" : "unknown";
  return (
    <Link className="ref-supplier" to={`/suppliers/${encodeURIComponent(r.id)}`}>
      {state && <StateDot state={state} />}{r.label ?? r.id}
      {status !== "on_file" && <span className="muted"> · {status === "hold" ? "on hold" : "not vetted"}</span>}
    </Link>
  );
}

/** A PO line as it is written on the order: the real number, no spaces around the slash. A short legacy form has no year to restore, so it stays as it came. */
export const poLineText = (id: string) => {
  const m = /^([A-Z]{2,4}-\d{2}-\d{5})\s*[/:]\s*(\d+)$/.exec(id.trim());
  return m ? `${m[1]}/${m[2]}` : id;
};
export function PoLineRef({ id }: { id: string }) {
  return <Link className="po" title={id} to={`/orders?who=everyone&q=${encodeURIComponent(poLineText(id))}&open=${encodeURIComponent(poLineText(id))}`}>{poLineText(id)}</Link>;
}

/** A build: the product and its month, "Model A · October". */
export function BuildRef({ product, month, to }: { product: string; month?: string; to?: string }) {
  const name = month ? `${product} · ${new Date(`${month}-01T00:00:00Z`).toLocaleString("en-US", { month: "long", timeZone: "UTC" })}` : product;
  return to ? <Link to={to}>{name}</Link> : <span>{name}</span>;
}

/** A company with its trust as a dot: green on file, hollow when new, red when the message is held. */
export function CompanyRef({ name, trust = "on_file", note }: { name: string; trust?: "on_file" | "new_sender" | "suspicious"; note?: string }) {
  return <span className={`co ${trust === "new_sender" ? "new" : trust === "suspicious" ? "fake" : ""}`}>{name}{note && <small>{note}</small>}</span>;
}

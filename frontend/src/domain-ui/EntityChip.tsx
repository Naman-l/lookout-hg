import { Link } from "react-router-dom";
import type { EntityRef } from "../api/types";
import { MessageChip } from "./message/Chip";
import { BuildRef, PartRef, PoLineRef, SupplierRef } from "./Records";
import { useBuilds } from "../api/useBuilds";
import { useSupplierNames } from "../api/useSupplierNames";

/** A supplier by name; a reference that arrives without one is looked up in the vendor master. */
function SupplierChip({ r }: { r: EntityRef }) {
  const nameOf = useSupplierNames();
  return <SupplierRef r={r.label ? r : { ...r, label: nameOf(r.id) ?? null }} />;
}

/** A robot on screen opens its build page ("will the parts be here for the month") for the month that has trouble. */
function BuildChip({ r }: { r: EntityRef }) {
  const builds = useBuilds().data ?? [];
  const b = builds.find((x) => x.product.id === r.id);
  return <BuildRef product={r.label ?? r.id} month={b?.month} />;      // plain text: the build pages are out of the demo
}

/** Every mention of a record, anywhere (tables, the Recommendation, the run stream), renders here, through the Ref for its kind. */
export function EntityChip({ r }: { r: EntityRef }) {
  switch (r.type) {
    case "supplier": case "supplier_record": return <SupplierChip r={r} />;
    case "part": return <PartRef id={r.id} name={r.label} />;
    case "po_line": case "po": return <PoLineRef id={r.id} />;
    case "message": return <MessageChip r={r} />;
    case "product": return <BuildChip r={r} />;
    case "item": return <Link className="chip" to={`/items/${r.id}`}>{r.label ?? r.id}</Link>;
    default: return <span className="chip">{r.label ?? r.id}</span>;
  }
}

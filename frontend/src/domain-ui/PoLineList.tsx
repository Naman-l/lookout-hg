import { useState } from "react";
import { Link } from "react-router-dom";
import type { PoLine } from "../api/types";
import { DataTable, TitleCell, type Col } from "../ds/DataTable";
import { poLineText } from "./Records";
import { PoLineStages } from "./Ladder";
import { shortDate, titleCase } from "../ui/format";
import { PAST_DUE } from "../ui/copy";
import { usePartNames } from "../api/usePartNames";

/** PO lines as table rows, open a row for its stages: the same table on Orders, a supplier and an item, on a phone and a desktop. */
export function PoLineList({ lines, showSupplier = true, showBuyer = true, header = true }: { lines: PoLine[]; showSupplier?: boolean; showBuyer?: boolean; header?: boolean }) {
  const partName = usePartNames();
  const [open, setOpen] = useState<Set<string>>(new Set());
  const toggle = (id: string) => setOpen((o) => { const n = new Set(o); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const qty = (l: PoLine) => (l.qty as { value: string; uom?: string });
  const tight = true; // Quantity and Status never clip: the first column gives way (beside the rail at 1280 only the line, Promised, Quantity and Status fit)
  const cols: Col<PoLine>[] = [
    { id: "line", head: "Part and order line", width: tight ? "minmax(120px,1fr)" : "minmax(240px,1fr)", cell: (l) => { const t = `${l.part.label ?? partName(l.part.id) ?? l.part.id}`; return <TitleCell title={t} sub={poLineText(l.ref.id ?? "")} tip={`${t} · ${poLineText(l.ref.id ?? "")}`} />; } },
    ...(showSupplier ? [{ id: "sup", head: "Supplier", width: tight ? "124px" : "200px", hide: "mid", phone: "hide", cell: (l: PoLine) => l.supplier.label ?? "" } as Col<PoLine>] : []),
    { id: "promise", head: "Promised", width: tight ? "80px" : "150px", hide: "narrow", label: "promised", cell: (l: PoLine) => <>{l.promise_date ? shortDate(l.promise_date) : "no date"}{l.revised_date && <small>revised {shortDate(l.revised_date)}</small>}</> },
    ...(showBuyer ? [{ id: "buyer", head: "Buyer", width: tight ? "84px" : "110px", hide: "mid", phone: "hide", cell: (l: PoLine) => l.buyer } as Col<PoLine>] : []),
    { id: "qty", head: "Quantity", width: tight ? "84px" : "110px", end: true, cell: (l: PoLine) => `${Number(qty(l).value).toLocaleString("en-US")} ${qty(l).uom ?? ""}`.trim() },
    { id: "status", head: "Status", width: tight ? "140px" : "150px", cell: (l: PoLine) => { const word = l.stale ? "may not be open" : l.days_past_due > 0 ? `${l.days_past_due} ${l.days_past_due === 1 ? "day" : "days"} ${PAST_DUE}` : titleCase(l.status); return <span style={{ color: l.stale ? "var(--ink-3)" : l.days_past_due > 0 ? "var(--critical)" : undefined }}>{word}</span>; } },
  ];
  return (
    <DataTable<PoLine> label="Order lines" two header={header} cols={cols} rows={lines} rowKey={(l) => l.ref.id ?? ""} onClick={(l) => toggle(l.ref.id ?? "")}
      state={(l) => (l.stale ? "unknown" : l.days_past_due > 0 ? "late" : undefined)}
      expand={(l) => open.has(l.ref.id ?? "") ? <div className="ds-rowx"><PoLineStages id={l.ref.id ?? ""} /><p><Link to={`/parts/${encodeURIComponent(l.part.id)}?s=orders`}>Open {l.part.id}</Link></p></div> : null} />
  );
}

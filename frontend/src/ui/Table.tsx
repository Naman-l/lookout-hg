import { useState, type ReactNode } from "react";

export interface Column<T> { head: string; num?: boolean; cut?: boolean; narrow?: "hide"; cell: (row: T) => ReactNode }

/** The plain table every record section and every expander uses. */
export function Table<T>({ cols, rows, empty, rowKey, expand }: { cols: Column<T>[]; rows: T[]; empty: string; rowKey: (row: T) => string; expand?: { label: string; render: (row: T) => ReactNode } }) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  const toggle = (k: string) => setOpen((o) => { const n = new Set(o); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  if (rows.length === 0) return <p className="empty">{empty}</p>;
  return (
    <div className="tablewrap">
      <table>
        <thead><tr>{cols.map((c) => <th key={c.head} className={`${c.num ? "num" : ""}${c.narrow ? " hide-narrow" : ""}`.trim()}>{c.head}</th>)}{expand && <th />}</tr></thead>
        <tbody>
          {rows.map((r) => (
            <Row key={rowKey(r)} r={r} k={rowKey(r)} cols={cols} expand={expand} open={open.has(rowKey(r))} toggle={toggle} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Row<T>({ r, k, cols, expand, open, toggle }: { r: T; k: string; cols: Column<T>[]; expand?: { label: string; render: (row: T) => ReactNode }; open: boolean; toggle: (k: string) => void }) {
  return (
    <>
            <tr>{cols.map((c) => <td key={c.head} className={`${c.num ? "num" : ""}${c.cut ? " cut" : ""}${c.narrow ? " hide-narrow" : ""}`.trim()} title={c.cut && typeof c.cell(r) === "string" ? (c.cell(r) as string) : undefined}>{c.cell(r)}</td>)}{expand && <td className="stages"><button type="button" className="linkbtn" aria-expanded={open} onClick={() => toggle(k)}>{open ? "Hide" : expand.label}</button></td>}</tr>
      {expand && open && <tr className="expand"><td colSpan={cols.length + 1}>{expand.render(r)}</td></tr>}
    </>
  );
}

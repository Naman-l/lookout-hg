import { useState } from "react";
import { isDate, isMoney, isUnknown, type Provenance, type Value as V } from "../api/types";
import { formatMoney, formatQuantity, monthYear, shortDate } from "../ui/format";
import { UnknownValue } from "./Unknown";

const LABEL: Record<Provenance["method"], string> = {
  stated: "recorded", computed: "calculated", inferred: "estimated", flagged: "flagged",
  unknown: "unknown", extracted: "stated",
};

/** The only way a number is printed. Shows the value, how it was obtained, and on click its source inline. */
export function Value({ value, tag = true, className, monthOnly = false, whole = false }: { value: V; tag?: boolean; className?: string; monthOnly?: boolean; whole?: boolean }) {
  const [open, setOpen] = useState(false);
  if (isUnknown(value)) return <UnknownValue u={value} />;
  const text = isMoney(value) ? formatMoney(value, whole) : isDate(value) ? (monthOnly ? monthYear(value.date) : shortDate(value.date)) : formatQuantity(value);
  const p = value.provenance;
  const approx = p.method === "inferred" ? "~" : "";
  return (
    <span className={`value ${className ?? ""}`}>
      <button type="button" className="value-btn" aria-expanded={open} onClick={() => setOpen(!open)}>{approx}{text}</button>
      {tag && <span className={`prov p-${p.method === "extracted" ? "stated" : p.method}`}>{LABEL[p.method]}</span>}
      {open && <ProvenancePanel p={p} />}
    </span>
  );
}

/** Where a figure comes from, in a buyer's words; a table name is never shown. */
const SOURCE: Record<string, string> = {
  po_lines: "purchase order line", parts: "item master", demand_forecast: "forecast", message: "supplier message", messages: "supplier message",
  bom_lines: "bill of materials", bom: "bill of materials", quotes: "quote", offers: "quote",
};
const sourceWords = (s: string | null | undefined) => SOURCE[s ?? ""] ?? "the records";

export function ProvenancePanel({ p }: { p: Provenance }) {
  return (
    <span className="src" role="note">
      <b>{LABEL[p.method][0].toUpperCase() + LABEL[p.method].slice(1)}</b> from {sourceWords(p.source)}
      {p.row ? `, ${p.row}` : ""}
      {p.raw && <span className="quote">{p.raw}</span>}
      {p.rule && <span className="muted"> · {p.rule}</span>}
    </span>
  );
}

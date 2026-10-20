import type { PoLine } from "../../api/types";

export type SortKey = "line" | "part" | "supplier" | "buyer" | "qty" | "open" | "promised";

/** What is still owed on a line, in dollars: open quantity times the unit price in USD. Unknown when the price has no USD value. */
export function openValue(l: PoLine): number | null {
  const usd = l.unit_price?.usd ?? (l.unit_price?.currency === "USD" ? l.unit_price.amount : null);
  const q = Number((l.qty as { value: string }).value);
  return usd == null || Number.isNaN(q) ? null : q * Number(usd);
}

const key: Record<SortKey, (l: PoLine) => string | number> = {
  line: (l) => l.ref.id ?? "", part: (l) => l.part.id ?? "", supplier: (l) => l.supplier.label ?? "", buyer: (l) => l.buyer,
  qty: (l) => Number((l.qty as { value: string }).value), open: (l) => openValue(l) ?? -1, promised: (l) => (l.stale ? "9999-stale" : l.promise_date ?? "9999"), // a line that may not be open sorts last
};

/** Sort lines by one column; a second click on the same column flips it. Past due comes first when sorting by date. */
export function sortLines(lines: PoLine[], by: SortKey, desc: boolean): PoLine[] {
  const f = key[by];
  return [...lines].sort((a, b) => { const x = f(a), y = f(b); const c = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y)); return desc ? -c : c; });
}

/** The one count: open lines (stale ones are not open), past due among them, and how many may not be open at all. */
export function countLines(lines: PoLine[]) {
  const stale = lines.filter((l) => l.stale).length;
  return { open: lines.length - stale, late: lines.filter((l) => !l.stale && (l.days_past_due ?? 0) > 0).length, stale };
}

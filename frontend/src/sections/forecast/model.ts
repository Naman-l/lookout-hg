import type { ForecastRow } from "../../api/types";

/** Robots per month across all products, and the total of every month. */
export function totals(rows: ForecastRow[]) {
  const months = rows[0]?.months.map((m) => m.month) ?? [];
  const byMonth = months.map((_, n) => rows.reduce((a, r) => a + (r.months[n]?.units ?? 0), 0));
  return { months, byMonth, all: byMonth.reduce((a, b) => a + b, 0) };
}

export const rowTotal = (r: ForecastRow) => r.months.reduce((a, m) => a + m.units, 0);

/** Points for a sparkline in a w x h box: the lowest month at the bottom, the highest at the top; a flat series sits in the middle. */
export function sparkPoints(values: number[], w: number, h: number, pad = 2): string {
  if (values.length === 0) return "";
  const lo = Math.min(...values), hi = Math.max(...values), span = hi - lo;
  return values.map((v, i) => {
    const x = values.length === 1 ? w / 2 : pad + (i * (w - 2 * pad)) / (values.length - 1);
    const y = span === 0 ? h / 2 : h - pad - ((v - lo) * (h - 2 * pad)) / span;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
}

import { formatMoney } from "../../ui/format";

export type MoneyIn = { amount: string | number; currency: string; usd?: string | null };

/** The way a buyer says money: $396K, $8,009 under $10K, $1.54M. Exact cents only on a quote price (`exact`; four decimals under 1). */
export function moneyText(m: MoneyIn, exact = false): string {
  const n = Number(m.usd ?? m.amount);
  const cur = m.usd != null ? "USD" : m.currency;
  if (!exact) return formatMoney({ amount: String(m.amount), currency: m.currency, usd: m.usd ?? null }, false);
  const d = n !== 0 && Math.abs(n) < 1 ? 4 : 2; // a price under one dollar needs its fourth decimal
  const digits = n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  return cur === "USD" ? `$${digits}` : cur === "EUR" ? `€${digits}` : `${digits} ${cur}`;
}

/** Tabular figures, one format everywhere. `risk` marks money that is at risk or owed late (red, with the word in the title). */
export function Money({ value, exact, risk }: { value: MoneyIn; exact?: boolean; risk?: boolean }) {
  return <span className="dm-money" data-tone={risk ? "red" : undefined} title={risk ? "Money at risk" : undefined}>{moneyText(value, exact)}</span>;
}

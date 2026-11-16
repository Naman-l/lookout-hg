import { inr } from "../../ui/format";

export type MoneyIn = { amount: string | number; currency?: string; base?: string | null };

/** The way the team says money: ₹1.4 Cr, ₹15 L, ₹8,500; `exact` writes every rupee with Indian grouping (₹42,49,224). */
export function moneyText(m: MoneyIn, exact = false): string {
  return inr(m.base ?? m.amount, exact);
}

/** Tabular figures, one format everywhere. `risk` marks money that is at risk (red, with the word in the title). */
export function Money({ value, exact, risk }: { value: MoneyIn; exact?: boolean; risk?: boolean }) {
  return <span className="dm-money" data-tone={risk ? "red" : undefined} title={risk ? "Money at risk" : undefined}>{moneyText(value, exact)}</span>;
}

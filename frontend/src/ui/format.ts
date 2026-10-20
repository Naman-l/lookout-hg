import type { Money, Quantity } from "../api/types";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];


/** "2026-10-10" -> "Oct 10". Absolute dates only; days left are computed against the data date by the server. */
export function shortDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [, m, d] = iso.split("-").map(Number);
  return `${MONTHS[m - 1]} ${d}`;
}

export function longDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  const dow = new Date(Date.UTC(y, m - 1, d)).toUTCString().slice(0, 3);
  return `${dow} ${MONTHS[m - 1]} ${d}, ${y}`;
}

const num = (s: string) => Number(s);
const group = (n: number, digits = 0) =>
  n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });

export function formatMoney(m: Pick<Money, "amount" | "currency" | "usd">, whole = false): string {
  const useUsd = m.usd != null;
  const n = num(useUsd ? m.usd! : m.amount);
  const cur = useUsd ? "USD" : m.currency;
  const sym = cur === "USD" ? "$" : cur === "EUR" ? "€" : "";
  if (Math.abs(n) >= 1_000_000) return `${sym}${group(n / 1_000_000, 2)}M`;
  if (Math.abs(n) >= 10_000) return `${sym}${group(n / 1000, 0)}K`;
  const digits = whole || Math.abs(n) >= 1000 || Number.isInteger(n) ? 0 : 2;
  return sym ? `${sym}${group(n, digits)}` : `${group(n, digits)} ${cur}`;
}

export function formatQuantity(q: Quantity): string {
  const x = num(q.value);
  const sign = q.value.startsWith("+") ? "+" : "";
  const n = sign + group(x, Number.isInteger(x) ? 0 : 1);
  return q.uom.startsWith("%") ? `${n}%` : n;
}

/** "2026-10-01" -> "Oct 2026" (a value that is really a month). */
export function monthYear(iso: string): string {
  const [y, m] = iso.split("-").map(Number);
  return `${MONTHS[m - 1]} ${y}`;
}

/** "OPEN" -> "Open": the data's own casing is not for a buyer's eyes. */
export const titleCase = (s: string) => (s ? s[0].toUpperCase() + s.slice(1).toLowerCase() : s);

const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

const AGENT_NAMES: Record<string, string> = {
  lookout: "Lookout", supply_planner: "Supply planner", buyers_clerk: "Buyer’s clerk", tariff_analyst: "Tariff analyst",
  sourcing_analyst: "Sourcing analyst", inbox_analyst: "Inbox analyst", data_steward: "Data steward", verifier: "Verifier", reviewer: "Reviewer",
};
export const agentName = (id?: string | null) => (id ? AGENT_NAMES[id] ?? id.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()) : "");

/** "1,539,053.57 USD" -> "$1.54M"; "188.9875 USD" -> "$188.99": the way a buyer says money. */
function sayMoney(n: number): string {
  const a = Math.abs(n);
  if (a >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (a >= 10_000) return `$${Math.round(n / 1000).toLocaleString("en-US")}K`;
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: a >= 1000 || Number.isInteger(n) ? 0 : 2, maximumFractionDigits: a >= 1000 || Number.isInteger(n) ? 0 : 2 })}`;
}

/** A quoted markdown table row ("| 1 | 8507.60 | Lithium-ion accumulators | 25% |") read as its cells; a separator row vanishes. Render only. */
export function pipeRowsInWords(text: string): string {
  return text.replace(/\|(?:[^|\n]*\|){2,}/g, (row) => {
    const cells = row.split("|").slice(1, -1).map((c) => c.trim());
    if (cells.every((c) => /^:?-{2,}:?$/.test(c) || c === "")) return "";
    if (cells.length >= 4 && /^\d{1,2}$/.test(cells[0])) cells.shift();
    return cells.filter(Boolean).join(" · ");
  }).replace(/ {2,}/g, " ");
}

/** Prose from the API may carry ISO dates; a buyer reads "Oct 13" and "October", never "2026-10-13". */
export function humanize(text: string | null | undefined): string {
  if (!text) return "";
  return pipeRowsInWords(text)
    .replace(/\b(\d+) order\(s\)/g, (_, n) => `${n} ${n === "1" ? "order" : "orders"}`)
    .replace(/\b([A-Z]{2,4}-\d{2}-\d{5})\s*\/\s*(\d+)\b/g, "$1/$2")
    .replace(/\b(\d[\d,]*(?:\.\d+)?)\s*USD\b/g, (_, n) => sayMoney(Number(String(n).replace(/,/g, ""))))
    .replace(/\b(lookout|supply_planner|buyers_clerk|tariff_analyst|sourcing_analyst|inbox_analyst|data_steward|verifier|reviewer)\b/g, (m) => AGENT_NAMES[m])
    .replace(/\s+as\s+A-[0-9a-f]{8}\b/g, "")
    .replace(/\s*\bA-[0-9a-f]{8}\b/g, "")
    .replace(/\b(20\d\d)-(\d\d)-(\d\d)\b/g, (_, y, m, d) => `${MONTHS[Number(m) - 1]} ${Number(d)}${y === "2026" ? "" : `, ${y}`}`)
    .replace(/\b(20\d\d)-(0[1-9]|1[0-2])\b(?!-)/g, (_, y, m) => `${MONTH_NAMES[Number(m) - 1]}${y === "2026" ? "" : ` ${y}`}`);
}

/** "claude-sonnet-5-5" as a person says it: "Sonnet 5.5". */
export const modelName = (m?: string | null) => {
  const x = (m ?? "").match(/(opus|sonnet|haiku|fable)-(\d+)-(\d+)/i);
  return x ? `${x[1][0].toUpperCase()}${x[1].slice(1).toLowerCase()} ${x[2]}.${x[3]}` : m ?? "";
};

/** Who may sign a draft: the draft's own owner when the API names one, else the owners of its item. A person's names, joined by " · ". */
export const signersOf = (a: { owner?: string | null }, itemOwner?: string | null) => (a.owner ?? itemOwner ?? "") as string;

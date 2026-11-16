import type { Money, Quantity } from "../api/types";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

/** "2026-10-10" -> "10 Oct" (day first, as HG writes dates). Days left are computed against the data date by the server. */
export function shortDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [, m, d] = iso.slice(0, 10).split("-").map(Number);
  return `${d} ${MONTHS[m - 1]}`;
}

/** "2026-10-20" -> "20 Oct 2026". */
export function longDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

/** "2026-10" or "2026-10-01" -> "Oct 2026". */
export function monthYear(iso: string): string {
  const [y, m] = iso.split("-").map(Number);
  return `${MONTHS[m - 1]} ${y}`;
}

/** "2026-11" -> "Nov". */
export const monthShort = (ym: string) => MONTHS[Number(ym.slice(5, 7)) - 1];

/** Indian digit grouping: 4249224 -> "42,49,224"; 128000 -> "1,28,000". */
export function enIn(n: number, digits = 0): string {
  return n.toLocaleString("en-IN", { minimumFractionDigits: 0, maximumFractionDigits: digits });
}

const trim = (x: number, places: number) => x.toFixed(places).replace(/\.?0+$/, "");

/** Rupees the way the team says them: ₹1.4 Cr (a crore and up), ₹15 L (a lakh and up), ₹8,500 below; `exact` writes every rupee (₹42,49,224). */
export function inr(amount: number | string | null | undefined, exact = false): string {
  if (amount == null || amount === "") return "—";
  const a = Number(amount);
  if (!Number.isFinite(a)) return "—";
  const sign = a < 0 ? "-" : "";
  const x = Math.abs(a);
  if (exact || x < 1e5) return `${sign}₹${enIn(x, x >= 100 ? 0 : 2)}`;
  if (x >= 1e7) { const cr = x / 1e7; return `${sign}₹${cr >= 100 ? enIn(Math.round(cr)) : trim(cr, cr < 10 ? 2 : 1)} Cr`; }
  const l = x / 1e5;
  return `${sign}₹${trim(l, l < 10 ? 1 : 0)} L`;
}

/** A Money as the screens show it (base currency, Indian units). */
export function formatMoney(m: Pick<Money, "amount" | "currency"> & { base?: string | null }, exact = false): string {
  return inr(m.base ?? m.amount, exact);
}

/** The base amount of a value that may be money, else null. */
export const baseOf = (v: unknown): number | null =>
  v && typeof v === "object" && "currency" in (v as object) ? Number((v as { base?: string | null; amount: string }).base ?? (v as { amount: string }).amount) : null;

export function formatQuantity(q: Pick<Quantity, "value" | "uom">): string {
  const x = Number(q.value);
  return `${enIn(x, Number.isInteger(x) ? 0 : 2)}${q.uom && q.uom !== "NO" ? ` ${q.uom}` : ""}`;
}

/** "1,28,000 MT", "18 KM", "2 NO". */
export const qty = (v: number | string | null | undefined, uom?: string | null) => (v == null ? "—" : `${enIn(Number(v), Number.isInteger(Number(v)) ? 0 : 2)}${uom ? ` ${uom}` : ""}`);

/** "OPEN" -> "Open". */
export const titleCase = (s: string) => (s ? s[0].toUpperCase() + s.slice(1).toLowerCase() : s);

const AGENT_NAMES: Record<string, string> = {
  lookout: "Lookout", site_planner: "Site requirement planner", buyers_clerk: "Buyer’s clerk", price_analyst: "Price and PV analyst",
  sourcing_analyst: "Sourcing analyst", inbox_analyst: "Inbox analyst", data_steward: "Data steward", verifier: "Verifier", reviewer: "Reviewer", code: "Drafted by code",
};
export const agentName = (id?: string | null) => (id ? AGENT_NAMES[id] ?? id.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()) : "");

/** Prose from the API may carry ISO dates; a buyer reads "13 Oct" and "October", never "2026-10-13". */
export function humanize(text: string | null | undefined): string {
  if (!text) return "";
  return text
    .replace(/\s*\bA-[0-9a-f]{8}\b/g, "")
    .replace(/\b(20\d\d)-(\d\d)-(\d\d)\b/g, (_, y, m, d) => `${Number(d)} ${MONTHS[Number(m) - 1]}${y === "2026" ? "" : ` ${y}`}`)
    .replace(/\b(20\d\d)-(0[1-9]|1[0-2])\b(?!-)/g, (_, y, m) => `${MONTH_NAMES[Number(m) - 1]}${y === "2026" ? "" : ` ${y}`}`);
}

/** "claude-sonnet-5-5" as a person says it: "Sonnet 5.5". */
export const modelName = (m?: string | null) => {
  const x = (m ?? "").match(/(opus|sonnet|haiku|fable)-(\d+)-(\d+)/i);
  return x ? `${x[1][0].toUpperCase()}${x[1].slice(1).toLowerCase()} ${x[2]}.${x[3]}` : m ?? "";
};

export const first = (n?: string | null) => (n ?? "").split(" ")[0];

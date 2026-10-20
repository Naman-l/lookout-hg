import type { BidColumn } from "../../api/types";

/** The landed-cost table's rows (F103; UX pain-analysis-ui §1 duty variant, §3 quote variant), from the bid tab GET /parts/{part}/compare. Pure, so it is unit-tested.
 * Ranked by what decides, the landed cost per piece, never the sheet price: the last PO pinned first as "current", then the offers cheapest landed first. */

export type Variant = "duty" | "quote";
export type Cell = { text: string; bold?: boolean; note?: string; tip?: string };
export type LandedRow = { key: string; label: string; current: boolean; cells: Record<string, Cell> };
export type LandedTable = { cols: { key: string; head: string; end?: boolean }[]; rows: LandedRow[]; line: string | null };

type L = BidColumn["landed"];
const num = (v: unknown): number | null => {
  if (v == null) return null;
  const x = typeof v === "object" ? Number((v as { usd?: string | null; amount?: string }).usd ?? (v as { amount?: string }).amount) : Number(v);
  return Number.isFinite(x) ? x : null;
};
const usd = (x: number | null) => (x == null ? "—" : `$${x.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);
/** +7.7% / −13.9% (a true minus sign; never coloured). */
export const pct = (x: number | null) => (x == null || !Number.isFinite(x) ? "—" : `${x >= 0 ? "+" : "−"}${Math.abs(x * 100).toFixed(1)}%`);
const vs = (a: number | null, b: number | null) => (a == null || b == null || b === 0 ? null : (a - b) / b);

const CODES: Record<string, string> = { china: "CN", malaysia: "MY", germany: "DE", vietnam: "VN", taiwan: "TW", japan: "JP", thailand: "TH", mexico: "MX", "united states": "US", usa: "US", india: "IN", korea: "KR", "south korea": "KR", indonesia: "ID", philippines: "PH", poland: "PL", czechia: "CZ", italy: "IT", switzerland: "CH" };
/** The origin as a code: the stated one, else the country the offer claims ("Malaysia (<site> assembly…)" -> MY). */
export function originOf(l: L): string | null {
  const o = l.offer;
  if (o.origin) return o.origin;
  const claim = (o.origin_claim ?? "").split(/[ (,]/)[0].toLowerCase();
  return CODES[claim] ?? (o.origin_claim ? o.origin_claim.split(" (")[0] : null);
}
const COUNTRY: Record<string, string> = { CN: "China", MY: "Malaysia", DE: "Germany", VN: "Vietnam", TW: "Taiwan", JP: "Japan", TH: "Thailand", MX: "Mexico", US: "US" };
/** "30% on orders above EUR 25,000 net" -> "30% prepay above EUR 25K"; "Net 30 (was 45)" -> "Net 30". */
export function termsText(l: L): string {
  const o = l.offer;
  const pre = (o.prepayment ?? "").match(/(\d+)% on orders above (\w{3}) ([\d,]+)/);
  const parts = [pre ? `${pre[1]}% prepay above ${pre[2]} ${Math.round(Number(pre[3].replace(/,/g, "")) / 1000)}K` : o.prepayment ?? "", (o.payment_terms ?? "").replace(/\s*\(.*\)$/, "")];
  return parts.filter(Boolean).join(" · ") || "—";
}

/** The rows and the line under the table. `shortOf` turns a supplier into the name a buyer says (the caller knows it; the default is its first word); `reviewed` names the offer under review (quote variant; the first offer by default). */
export function landedTable(columns: BidColumn[], variant: Variant, opts: { shortOf?: (id: string | null | undefined, name: string) => string; reviewed?: string; note?: string; order?: number } = {}): LandedTable {
  const short = (c: BidColumn) => { const name = (c.landed.offer.supplier_name ?? c.label).replace(/^Current:\s*/, "").replace(/\s*\(.*$/, ""); return opts.shortOf ? opts.shortOf(c.landed.offer.supplier?.id ?? null, name) : name.split(" ")[0]; };
  const cur = columns.find((c) => c.is_current) ?? null;
  const landed = (c: BidColumn) => num(c.landed.total_known_usd);
  const offers = columns.filter((c) => !c.is_current).sort((a, b) => (landed(a) ?? Infinity) - (landed(b) ?? Infinity));
  const curLanded = cur ? landed(cur) : null;
  const cheapest = offers.find((c) => landed(c) != null) ?? null;
  const brk = (c: BidColumn) => Number(c.landed.offer.qty_break ?? 0);
  // A quote bolds the break the order is priced at: the largest break at or under the order quantity (BUYER: 200 pcs reads as the 100-pc tier).
  const atOrder = variant === "quote" && opts.order ? offers.filter((c) => brk(c) > 0 && brk(c) <= opts.order!).sort((a, b) => brk(b) - brk(a))[0] : undefined;
  const reviewed = variant === "quote" ? atOrder ?? offers.find((c) => String(c.landed.offer.offer_id) === opts.reviewed) ?? offers[0] ?? null : null;
  const label = (c: BidColumn) => {
    const o = originOf(c.landed);
    if (c.is_current) return `Last PO · ${variant === "duty" ? COUNTRY[o ?? ""] ?? o ?? "—" : o ?? "—"}`;
    const place = c.landed.offer.incoterm_place ?? c.landed.offer.site;
    const tier = c.landed.offer.qty_break ? ` · ${Number(c.landed.offer.qty_break).toLocaleString("en-US")} pcs` : "";      // the price break the row is priced at
    return variant === "quote" ? `${short(c)} quote${tier}` : `${short(c)}${place && o !== "CN" ? ` ${place}` : o === "CN" ? " China" : ""} · ${o ?? "—"}`;
  };
  const dutyCell = (c: BidColumn): Cell => {
    const d = num(c.landed.duty_usd), s = c.landed.duty_status;
    if (d != null && d > 0) return { text: usd(d) };
    if (s === "unknown_origin") return { text: "$0", note: "if origin holds" };
    return { text: "—" };
  };
  const row = (c: BidColumn): LandedRow => {
    const l = c.landed, ld = landed(c), price = num(l.offer.unit_price_usd);
    const bold = variant === "duty" ? c === cheapest : c === reviewed;
    const ifChina = num(l.total_if_china_usd);
    const extra = (num(l.surcharge_usd) ?? 0) + (num(l.tooling_per_unit_usd) ?? 0);
    // F105: five columns each; "if China" rides in the Landed cell (non-China offers only), the surcharge in its hover.
    const cells: Record<string, Cell> = variant === "duty" ? {
      quoted: { text: usd(price) }, duty: dutyCell(c),
      landed: { text: usd(ld), bold, note: ifChina != null && originOf(l) !== "CN" ? `(if China ${usd(ifChina)})` : undefined },
      vs: { text: c.is_current ? "—" : pct(vs(ld, curLanded)), bold },
    } : {
      quoted: { text: usd(price) },
      landed: { text: usd(ld), bold, note: ifChina != null && originOf(l) !== "CN" ? `(if China ${usd(ifChina)})` : undefined, tip: extra ? `includes ${usd(extra)} surcharge / tooling per piece` : undefined },      // an unproven origin: what it lands at if ruled China, as on the duty table
      vsLanded: { text: c.is_current ? "—" : pct(vs(ld, curLanded)), bold }, terms: { text: c.is_current ? "—" : termsText(l) },
    };
    return { key: c.landed.offer.offer_id != null ? String(c.landed.offer.offer_id) : c.label, label: label(c), current: !!c.is_current, cells };
  };
  const cols = variant === "duty"
    ? [{ key: "quoted", head: "Quoted", end: true }, { key: "duty", head: "Duty", end: true }, { key: "landed", head: "Landed", end: true }, { key: "vs", head: "vs last + duty", end: true }]
    : [{ key: "quoted", head: "Quoted", end: true }, { key: "landed", head: "Landed", end: true }, { key: "vsLanded", head: "vs last landed", end: true }, { key: "terms", head: "Terms" }];
  const breaks = [...new Set(offers.map(brk).filter((b) => b > 0))].sort((a, b) => a - b);
  const fmt = (n: number) => n.toLocaleString("en-US");
  // Two or more breaks: say which one the order is priced at, until the supplier confirms it.
  const priced = atOrder && breaks.length > 1 ? `Quote lists ${breaks.slice(0, -1).map(fmt).join(", ")} and ${fmt(breaks[breaks.length - 1])} pcs; ${fmt(opts.order!)} pcs priced at the ${fmt(brk(atOrder))}-pc break until ${short(atOrder)} confirms.` : null;
  const line: string | null = opts.note ?? priced;      // F105: no code sentence; the bold cells say it
  const shown = offers;      // a quote shows each of its price breaks on file (the reviewed one bold); a duty table every offer
  return { cols, rows: [...(cur ? [row(cur)] : []), ...shown.map(row)], line: offers.length ? line : null };
}

/** One line for a further part under the table (F105): "<part>: <site> $2,238.52 vs $2,633.62 landed (−15.0%)": the cheapest offer against the last PO with duty. */
export function landedLine(part: string, columns: BidColumn[], shortOf?: (id: string | null | undefined, name: string) => string): string | null {
  const cur = columns.find((c) => c.is_current);
  const best = columns.filter((c) => !c.is_current).sort((a, b) => (num(a.landed.total_known_usd) ?? Infinity) - (num(b.landed.total_known_usd) ?? Infinity))[0];
  if (!cur || !best) return null;
  const a = num(best.landed.total_known_usd), b = num(cur.landed.total_known_usd);
  const name = best.landed.offer.incoterm_place ?? best.landed.offer.site ?? (shortOf ? shortOf(best.landed.offer.supplier?.id, best.landed.offer.supplier_name ?? best.label) : best.label.split(" ")[0]);
  return `${part}: ${name} ${usd(a)} vs ${usd(b)} landed (${pct(vs(a, b))})`;
}

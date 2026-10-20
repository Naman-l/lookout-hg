import type { ActionItem, PoLine } from "../../api/types";
import { actBy } from "../../components/domain/caseStatus";
import { openValue } from "../orders/model";

/** Records (FINAL 06): which case each supplier, part and PO line is in, the case's short name, and the orders' one order. Pure, so it is unit-tested. */

/** A case that rolls many records up (the chase, the quotes, the duty, the unknowns) gives way to a case of the record's own. */
export const isRollup = (key: string) => key === "deadline:chase" || key === "deadline:quotes" || key === "tariff:all" || key.startsWith("unknown:");

/** Today's title up to its first colon, without "(on time …)" or ", with …": "<Supplier> fire", "<Supplier> delivers late", "Spot offer at 13.5x the usual price". */
export const caseShort = (title: string) => title.split(": ")[0].replace(/\s*\(on time[^)]*\)/, "").replace(/, with .*$/, "").trim();

export type CaseIndex = { supplier: Map<string, ActionItem[]>; part: Map<string, ActionItem[]>; line: Map<string, ActionItem[]> };

const add = (m: Map<string, ActionItem[]>, id: string | null | undefined, i: ActionItem) => {
  if (!id) return;
  const a = m.get(id) ?? [];
  if (!a.includes(i)) a.push(i);
  m.set(id, a);
};

/** A supplier is in a case its refs name; a PO line when the case's refs or the lines its amount was computed from name it; a part when the refs name it or one of its lines is in a case. */
export function indexCases(items: ActionItem[], lines: PoLine[]): CaseIndex {
  const idx: CaseIndex = { supplier: new Map(), part: new Map(), line: new Map() };
  const partOf = new Map(lines.map((l) => [l.ref.id ?? "", l.part.id ?? ""]));
  for (const i of items) {
    const inputs = (i.at_stake as { provenance?: { inputs?: { type: string; id?: string | null }[] } } | null)?.provenance?.inputs ?? [];
    for (const r of i.refs ?? []) {
      if (r.type === "supplier") add(idx.supplier, r.id, i);
      if (r.type === "part") add(idx.part, r.id, i);
      if (r.type === "po_line") add(idx.line, r.id, i);
    }
    for (const r of inputs) if (r.type === "po_line") add(idx.line, r.id, i);
  }
  for (const [line, cases] of idx.line) for (const i of cases) add(idx.part, partOf.get(line), i);
  return idx;
}

/** The case a record's list cell shows, then the rest: a case of its own before a rollup, a supplier's real trouble before a message held in its name, the soonest act-by first. */
export function rankCases(cases: ActionItem[], asOf: string | null): ActionItem[] {
  const by = (i: ActionItem) => actBy(i, asOf) ?? "9999";
  return [...cases].sort((a, b) => (isRollup(a.key) ? 1 : 0) - (isRollup(b.key) ? 1 : 0) || (a.group === "trust" ? 1 : 0) - (b.group === "trust" ? 1 : 0) || by(a).localeCompare(by(b)));
}

/** The "In a case" block: every case, soonest act-by first, no date last. */
export const byActBy = (cases: ActionItem[], asOf: string | null) => [...cases].sort((a, b) => (actBy(a, asOf) ?? "9999").localeCompare(actBy(b, asOf) ?? "9999"));

/** Dollars as the lists read them: $2.91M, $396K, $3,892, $0. */
export function usd(x: number | null | undefined): string {
  if (x == null || Number.isNaN(x)) return "—";
  return x >= 1e6 ? `$${(x / 1e6).toFixed(2)}M` : x >= 1e4 ? `$${Math.round(x / 1e3)}K` : `$${Math.round(x).toLocaleString("en-US")}`;
}

/** "Sep 19", with the year only when it is not the data's year ("Mar 21 2025"). */
export function day(iso: string | null | undefined, year?: string): string {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-").map(Number);
  const mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][m - 1];
  return `${mon} ${d}${year && String(y) !== year ? ` ${y}` : ""}`;
}

/** Each supplier's short name as the cases write it (the shortest label any case gives its id), so a line can say "<Supplier> notice". */
export function supplierShorts(items: ActionItem[]): Map<string, string> {
  const m = new Map<string, string>();
  for (const i of items) for (const r of i.refs ?? []) if (r.type === "supplier" && r.id && r.label && (!m.has(r.id) || r.label.length < m.get(r.id)!.length)) m.set(r.id, r.label);
  return m;
}

/** A supplier's name without its legal form ("… Motor Co., Ltd." -> "… Motor"); the full name stays on hover. */
export const legalShort = (name: string | null | undefined) => (name ?? "").replace(/,?\s+(Co\.,?\s*Ltd\.?|Co\.\s*Ltd\.?|Ltd\.?|Inc\.?|LLC|GmbH|AG|Co\.|Corp\.?|Corporation|S\.A\.|B\.V\.)$/i, "").replace(/,?\s+(Co\.,?\s*Ltd\.?|Co\.|Ltd\.?)$/i, "").trim() || (name ?? "");

/** Three parts of the description, in sentence case: "Lidar, 2D safety, 270 deg". */
export const partName = (d: string | null | undefined, parts = 3) => {
  if (!d) return "";
  const t = d.split(", ").slice(0, parts).join(", ");
  return t === t.toUpperCase() ? t[0] + t.slice(1).toLowerCase() : t;
};

/** 8501314000 -> 8501.31.4000; other lengths as stored. */
export const htsText = (h: string) => { const d = h.replace(/\D/g, ""); return d.length === 10 ? `${d.slice(0, 4)}.${d.slice(4, 6)}.${d.slice(6)}` : h; };

const pastDue = (l: PoLine) => !l.stale && (l.days_past_due ?? 0) > 0;

/** The orders' one order: past due oldest first, then promised soonest, then no date; lines that may not be open go to the foot under their own label. */
export function orderLines(lines: PoLine[]): { open: PoLine[]; stale: PoLine[] } {
  const rank = (l: PoLine) => (pastDue(l) ? 0 : l.promise_date ? 1 : 2);
  const open = lines.filter((l) => !l.stale).sort((a, b) => rank(a) - rank(b) || (a.promise_date ?? "").localeCompare(b.promise_date ?? "") || (a.ref.id ?? "").localeCompare(b.ref.id ?? ""));
  const stale = lines.filter((l) => l.stale).sort((a, b) => (a.promise_date ?? "").localeCompare(b.promise_date ?? ""));
  return { open, stale };
}

export type When = "late" | "month" | "none";
/** Promised ▾: past due, promised in the data's month (and not yet past due), or no date. */
export function whenMatches(l: PoLine, when: When, asOf: string | null): boolean {
  if (when === "late") return pastDue(l);
  if (when === "none") return !l.promise_date;
  const d = l.revised_date ?? l.promise_date;
  return !!d && !!asOf && d.slice(0, 7) === asOf.slice(0, 7) && !pastDue(l);
}

/** What a part still has open in dollars, over its lines that are really open. */
export function openByPart(lines: PoLine[]): Map<string, number> {
  const m = new Map<string, number>();
  for (const l of lines) if (!l.stale) m.set(l.part.id ?? "", (m.get(l.part.id ?? "") ?? 0) + (openValue(l) ?? 0));
  return m;
}

/** The robots a supplier's open lines go into, from each part's robots. */
export function supplierRobots(lines: PoLine[], robotsOf: Map<string, string[]>): Map<string, Set<string>> {
  const m = new Map<string, Set<string>>();
  for (const l of lines) {
    if (l.stale) continue;
    const s = m.get(l.supplier.id ?? "") ?? new Set<string>();
    for (const r of robotsOf.get(l.part.id ?? "") ?? []) s.add(r);
    m.set(l.supplier.id ?? "", s);
  }
  return m;
}

/** The unfolded row's steps, read from the line's ladder rungs: the words a buyer uses, only the steps that are known. */
export type Rung = { key: string; state: string; date?: string | null; detail?: string; flag?: string | null };
export function receivedText(r: Rung | undefined, year?: string): string | null {
  if (!r || r.state === "unknown" || !r.detail) return null;
  if (/^Nothing received/i.test(r.detail)) return "Nothing yet";
  const m = r.detail.match(/^([\d.,]+) of ([\d.,]+) (\w+) received, last on (\w+ \d+)/);
  if (m) return `${Number(m[1]).toLocaleString("en-US")} of ${Number(m[2]).toLocaleString("en-US")} ${m[3]} · last ${m[4]}`;
  return r.date ? `Received ${day(r.date, year)}` : null;
}
/** "222 EA needed in October (182 robots of <Robot A>, 40 robots of <Robot B>); …" -> ["222 EA in Oct", "182 <Robot A>, 40 <Robot B>"]. */
export function neededText(r: Rung | undefined): [string, string] | null {
  if (!r || r.state !== "done" || !r.detail) return null;
  const m = r.detail.match(/^([\d.,]+ \w+) needed in (\w+)(?: \(([^)]*)\))?/);
  if (!m) return null;
  return [`${m[1]} in ${m[2].slice(0, 3)}`, (m[3] ?? "").replace(/ robots of /g, " ")];
}
/** "… notice of Sep 18 revised it to Nov 9" -> "Sep 18". */
export const noticeDate = (detail: string | undefined) => detail?.match(/notice of (\w+ \d+)/)?.[1] ?? null;

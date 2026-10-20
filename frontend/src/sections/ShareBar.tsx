import { isMoney, type ItemDetail, type Value } from "../api/types";
import { formatMoney, humanize } from "../ui/format";

type Num = NonNullable<ItemDetail["numbers"]>[number];

/** The per-part duty numbers of the tariff item, largest first. */
export const dutyNumbers = (i: ItemDetail): Num[] => (i.numbers ?? []).filter((n) => /^duty_net:HR-/.test(n.id ?? "") && n.value && isMoney(n.value as Value));
const usd = (n: Num) => Number(isMoney(n.value as Value) ? ((n.value as { usd?: string | null; amount: string }).usd ?? (n.value as { amount: string }).amount) : 0);
const TONES = ["var(--share-1)", "var(--share-2)", "var(--share-3)", "var(--share-4)", "var(--share-5)"];

/** Where the duty falls, by part: one bar, five largest named, the rest together. */
export function ShareBar({ item }: { item: ItemDetail }) {
  const rows = dutyNumbers(item).map((n) => ({ n, v: usd(n) })).sort((a, b) => b.v - a.v);
  if (rows.length === 0) return null;
  const top = rows.slice(0, 5), rest = rows.slice(5);
  const restV = rest.reduce((a, r) => a + r.v, 0);
  const total = rows.reduce((a, r) => a + r.v, 0) || 1;
  const segs = [...top.map((r, k) => ({ label: humanize(r.n.label ?? ""), money: r.n.value as never, v: r.v, tone: TONES[k] })), ...(rest.length ? [{ label: `${rest.length} more`, money: null, v: restV, tone: "var(--line)" }] : [])];
  return (
    <div className="share">
      <div className="small muted">Where the duty falls, by part</div>
      <div className="sbar" role="img" aria-label="Share of net duty by part">
        {segs.map((s, k) => <i key={k} style={{ flex: `${(s.v / total) * 100} 1 0`, background: s.tone }} title={`${s.label}${s.money ? " " + formatMoney(s.money) : ""}`} />)}
      </div>
      <div className="legend">
        {segs.map((s, k) => <span key={k}><i style={{ background: s.tone }} />{s.label}{s.money ? ` ${formatMoney(s.money)}` : ""}</span>)}
      </div>
    </div>
  );
}

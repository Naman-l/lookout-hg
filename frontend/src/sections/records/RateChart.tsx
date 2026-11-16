// Rate history: every PO line's rate for one material over time, one dot per line. One site or vendor can be picked out (its dots joined in
// order, the rest greyed); the tables beside it carry every value, so the chart only adds the shape.
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { MaterialDetail } from "../../api/types";
import { enIn, inr, longDate, monthShort } from "../../ui/format";
import { lineTo, rate } from "./shared";

type Point = MaterialDetail["history"][number];
export type Pick = { kind: "site" | "vendor"; key: string; label: string } | null;

const L = 60, R = 12, T = 12, B = 28;
const t = (iso: string) => Date.parse(`${iso.slice(0, 10)}T00:00:00Z`);

/** Clean tick steps (1, 2, 5 x 10^k) for a value axis from zero. */
function ticks(max: number, n = 4): number[] {
  if (max <= 0) return [0];
  const raw = max / n, k = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((m) => m * k).find((s) => s >= raw) ?? 10 * k;
  const out = [];
  for (let v = 0; v <= max + step * 0.001; v += step) out.push(v);
  if (out[out.length - 1] < max) out.push(out[out.length - 1] + step);
  return out;
}

/** The first of each month the span covers, thinned to at most `most` labels. */
function monthTicks(a: number, b: number, most: number): string[] {
  const s = new Date(a), e = new Date(b);
  const ey = e.getUTCFullYear(), em = e.getUTCMonth() + 1;
  const out: string[] = [];
  let y = s.getUTCFullYear(), m = s.getUTCMonth() + 1;
  while (y < ey || (y === ey && m <= em)) {
    const iso = `${y}-${String(m).padStart(2, "0")}-01`;
    if (t(iso) >= a) out.push(iso);
    m += 1;
    if (m > 12) { m = 1; y += 1; }
  }
  const every = Math.ceil(out.length / most);
  return out.filter((_, i) => i % every === 0);
}

export function RateChart({ history, uom, pick, projectName }: { history: Point[]; uom: string; pick: Pick; projectName: (id: string | null | undefined) => string }) {
  const nav = useNavigate();
  const box = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<Point | null>(null);
  // Drawn at the width it is shown at, so tick labels keep their size on a phone.
  const [W, setW] = useState(720);
  useEffect(() => {
    const el = box.current; if (!el) return;
    const ro = new ResizeObserver(() => setW(Math.max(280, Math.round(el.clientWidth))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const H = W < 520 ? 200 : 240;
  const geo = useMemo(() => {
    const xs = history.map((p) => t(p.date));
    let a = Math.min(...xs), b = Math.max(...xs);
    if (a === b) { a -= 15 * 864e5; b += 15 * 864e5; }
    const ys = ticks(Math.max(...history.map((p) => p.rate)));
    const top = ys[ys.length - 1] || 1;
    const x = (iso: string) => L + ((t(iso) - a) / (b - a)) * (W - L - R);
    const y = (v: number) => T + (1 - v / top) * (H - T - B);
    return { a, b, ys, x, y, months: monthTicks(a, b, W < 520 ? 4 : 6) };
  }, [history, W, H]);
  if (!history.length) return null;
  const on = (p: Point) => !pick || (pick.kind === "site" ? p.project === pick.key : p.vendor === pick.key);
  const lit = pick ? history.filter(on) : [];
  const lo = Math.min(...history.map((p) => p.rate)), hi = Math.max(...history.map((p) => p.rate));
  const tip = hover && { left: (geo.x(hover.date) / W) * 100, top: (geo.y(hover.rate) / H) * 100 };
  return (
    <figure className="rc-chart" ref={box}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Rate on each of ${history.length} PO lines, ${longDate(history[0].date)} to ${longDate(history[history.length - 1].date)}: ${rate(lo, uom)} to ${rate(hi, uom)}${pick ? `; ${pick.label} picked out` : ""}`}>
        {geo.ys.map((v) => (
          <g key={v}>
            <line className="rc-grid" x1={L} x2={W - R} y1={geo.y(v)} y2={geo.y(v)} />
            <text className="rc-tick" x={L - 8} y={geo.y(v)} dy="0.32em" textAnchor="end">{v === 0 ? "₹0" : inr(v)}</text>
          </g>
        ))}
        {geo.months.map((m) => (
          <text key={m} className="rc-tick" x={geo.x(m)} y={H - 8} textAnchor="middle">{monthShort(m)}{m.slice(5, 7) === "01" || m === geo.months[0] ? ` ${m.slice(2, 4)}` : ""}</text>
        ))}
        {lit.length > 1 && <polyline className="rc-line" points={lit.map((p) => `${geo.x(p.date)},${geo.y(p.rate)}`).join(" ")} />}
        {history.map((p) => (
          <g key={p.po_line} className={`rc-pt${on(p) ? (pick ? " lit" : "") : " dim"}${hover === p ? " hov" : ""}`}
            onPointerEnter={() => setHover(p)} onPointerLeave={() => setHover((h) => (h === p ? null : h))} onClick={() => nav(lineTo("po", p.po_line))}>
            <circle className="hit" cx={geo.x(p.date)} cy={geo.y(p.rate)} r={12} />
            <circle className="dot" cx={geo.x(p.date)} cy={geo.y(p.rate)} r={4} />
          </g>
        ))}
        {pick && lit.map((p) => <circle key={`l-${p.po_line}`} className="rc-dot-lit" cx={geo.x(p.date)} cy={geo.y(p.rate)} r={4} pointerEvents="none" />)}
      </svg>
      {hover && tip && (
        <div className={`rc-tip${tip.left > 60 ? " left" : ""}`} style={{ left: `${tip.left}%`, top: `${tip.top}%` }} role="status">
          <b>{rate(hover.rate, uom)}</b>
          <span>{projectName(hover.project) || "no project"} · {hover.vendor}</span>
          <span>{longDate(hover.date)} · PO {hover.po_line}</span>
        </div>
      )}
      <figcaption>
        {pick ? <><i className="rc-key lit" aria-hidden />{pick.label} ({enIn(lit.length)} {lit.length === 1 ? "line" : "lines"}) <i className="rc-key" aria-hidden />every other PO line</>
          : <>One dot per PO line ({enIn(history.length)}), rate per {uom}. Pick a site or a vendor below to follow it; a dot opens its PO.</>}
      </figcaption>
    </figure>
  );
}

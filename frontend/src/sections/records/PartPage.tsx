import { useState, type ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useAskContext } from "../../shell/AskContext";
import { api } from "../../api/client";
import { useResource } from "../../api/useResource";
import { useMe } from "../../api/useMe";
import { isMoney, type PartDetail, type Value as V } from "../../api/types";
import { Button, EmptyState, Notice, NotFound, PageHeader, SegmentedControl, Skeleton, Tile, Tiles } from "../../ds";
import { humanize, shortDate } from "../../ui/format";
import { RobotIcon } from "../../components/domain";
import { byActBy, htsText, partName, usd } from "./model";
import { BidTable } from "./BidTable";
import { PoLineTable } from "./PoLineTable";
import { CaseBlock, RobotSlots, setParam, useRecords } from "./ui";
import { ListBody, RecordsTabs } from "./lists";

const QTYS = [500, 1000];
const monthName = (m: string) => new Date(`${m}-01T00:00:00Z`).toLocaleString("en-US", { month: "long", timeZone: "UTC" });
const num = (v: unknown) => Number((v as { value?: string } | null)?.value ?? NaN);
type Lead = { planned_days?: number | null; median_days: number; receipts: number; later: number; rule?: string } | null;
/** "ERP lead 35 d · actual median 84 d over 18 receipts": the ERP's lead time beside what the closed lines really took (code-computed from the receipts). */
function leadText(a: Lead, planned: number) {
  const p = Number.isFinite(planned) ? planned : a?.planned_days ?? null;
  if (!a) return p != null ? `ERP lead ${p} d` : null;
  const tip = `${a.rule ?? "median of order to receipt over the closed PO lines"}${p != null ? `; ${a.later} of ${a.receipts} took longer than planned` : ""}`;
  return <span key="lead" title={tip}>{p != null ? `ERP lead ${p} d · ` : ""}actual median {a.median_days} d over {a.receipts} {a.receipts === 1 ? "receipt" : "receipts"}</span>;
}

/** A part (FINAL 06 §5): the cases it is in, three figures, where it is used, its open lines, and the quotes folded away. */
export function PartPage() {
  const { me } = useMe();
  const { id = "" } = useParams();
  const part = decodeURIComponent(id);
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const r = useRecords();
  const detail = useResource(() => api.partDetail(part).catch(() => null), [part]);
  const used = useResource(() => api.whereUsed(part).catch(() => []), [part]);
  const [qty, setQty] = useState(1000);
  const bid = useResource(() => api.compare(part, qty), [part, qty]);
  const [quotes, setQuotes] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useAskContext({ type: "part", id: part, label: part });
  const compare = () => { setBusy(true); setErr(null); api.compareRun(part, me ?? "").then((x) => nav(`/activity/${encodeURIComponent(x.run_id)}`), () => { setBusy(false); setErr("The comparison could not start."); }); };

  const d = detail.data;
  if (!detail.loading && !d) return <NotFound title="Part not found" line={`No part has the number ${part}.`} />;
  const p = d?.part ?? null;
  const parentOf = (paths: string[][]) => { const via = (paths[0] ?? []).slice(1, -1); return via[via.length - 1] ?? null; };
  const whereText = (u: { qty_per_robot: unknown; paths: string[][] }) => {
    const parent = parentOf(u.paths), n = Number(u.qty_per_robot);
    const name = parent ? partName(r.partById.get(parent)?.description, 1) || parent : null;
    return `${n} per robot · ${name ? `in the ${name} (${parent})` : "directly in the robot"}`;
  };
  const usedBy = new Map((used.data ?? []).map((u) => [u.product.id ?? "", u]));
  const metaTip = (rid: string) => { const u = usedBy.get(rid); if (!u) return "goes into it"; const parent = parentOf(u.paths); const name = parent ? partName(r.partById.get(parent)?.description, 1) : null; return `${Number(u.qty_per_robot)} per robot${name ? `, in the ${name.replace(/ assembly$/, "")}` : ""}`; };
  const lines = (r.lines.data ?? []).filter((l) => l.part.id === part);
  const cases = byActBy(r.idx.part.get(part) ?? [], r.asOf);
  const sep = <span className="sep">·</span>;
  const lead = d?.planned_lead_time ? num(d.planned_lead_time) : NaN;
  const price = d?.reference_price && isMoney(d.reference_price as V) ? Number((d.reference_price as { usd?: string; amount: string }).usd ?? (d.reference_price as { amount: string }).amount) : NaN;
  const meta: ReactNode[] = p ? [
    <RobotSlots key="rb" robots={r.robots} lit={r.robotsOf.get(part) ?? []} on={metaTip} off="not in it" />,
    p.category,
    typeof p.coo === "string" ? `Made in ${p.coo}` : "Origin not on file",
    typeof p.hts === "string" ? `HTS ${htsText(p.hts)}` : "HTS not on file",
    p.preferred_supplier ? <Link key="sup" className="rc-in" to={`/suppliers/${encodeURIComponent(p.preferred_supplier.id ?? "")}`}>{p.preferred_supplier.label}</Link> : null,
    leadText(d?.lead_time_actual ?? null, lead),
    Number.isFinite(price) ? `$${price.toFixed(2)} latest PO price` : null,
  ].filter(Boolean) : [];
  return (
    <div className="rc rc-fixed">
      <RecordsTabs on="parts" />
      <PageHeader
        title={p ? <>{partName(p.description) || part}<span className="rc-pid">{part}</span></> : <span className="skel" style={{ width: 320 }} />}
        meta={p ? <span className="rc-meta">{meta.map((m, n) => <span key={n} className="rc-meta">{n > 0 && sep}{m}</span>)}</span> : <Skeleton width={320} />}
      />
      <ListBody>
      <CaseBlock cases={cases} r={r} />
      {d && <Facts d={d} />}
      {(used.data ?? []).length > 0 && (
        <section className="rc-sec" aria-label="Where used">
          <h2 className="rc-h2">Where used</h2>
          {(used.data ?? []).map((u) => {
            const rb = r.robots.find((x) => x.id === u.product.id);
            return (
              <div key={u.product.id} className="rc-used">
                <span><b>{rb && <RobotIcon slot={rb.slot} />}{u.product.label}</b><small>{whereText(u as { qty_per_robot: unknown; paths: string[][] })}</small></span>
              </div>
            );
          })}
        </section>
      )}
      {lines.length > 0 && (
        <section className="rc-sec" aria-label="Open lines">
          <h2 className="rc-h2">Open lines <em>{lines.filter((l) => !l.stale).length}</em></h2>
          <PoLineTable label={`Open PO lines for ${part}`} lines={lines} r={r} drop="part" open={params.get("open")} onOpen={(o) => setParam(setParams, "open", o)} />
        </section>
      )}
      {d && <button type="button" className="rc-fold" aria-expanded={quotes} aria-controls="quotes" onClick={() => setQuotes(!quotes)}>
        Quotes{bid.data ? ` ${bid.data.columns.length}` : ""} · compare with the agent {quotes ? <ChevronDown size={14} aria-hidden /> : <ChevronRight size={14} aria-hidden />}
      </button>}
      {quotes && (
        <section id="quotes" className="rc-sec" aria-label="Quotes">
          <div className="ds-actions">
            <Button disabled={busy} onClick={compare}>{busy ? "Starting…" : "Compare quotes with the agent"}</Button>
            <SegmentedControl label="Quantity" items={QTYS.map((n) => ({ id: String(n), label: `${n.toLocaleString("en-US")} units` }))} value={String(qty)} onChange={(v) => setQty(Number(v))} />
          </div>
          {err && <Notice tone="risk">{err}</Notice>}
          {bid.loading && <Skeleton width={360} />}
          {bid.error && <Notice tone="risk">The quotes for this part could not be loaded.</Notice>}
          {bid.data && bid.data.columns.length === 0 && <EmptyState>No quotes or order history for this part.</EmptyState>}
          {bid.data && bid.data.columns.length > 0 && <BidTable cols={bid.data.columns} />}
          {bid.data && <p className="ds-note" style={{ marginTop: "var(--s4)" }}>{humanize(bid.data.note)}</p>}
        </section>
      )}
      </ListBody>
    </div>
  );
}

/** Three figures at most: how short the part leaves the first build, what is open, and the new duty. */
function Facts({ d }: { d: PartDetail }) {
  const sh = d.shortage, ex = d.exposure ?? null, open = d.part?.open_supply;
  const tiles: ReactNode[] = [];
  if (sh) tiles.push(<Tile key="short" figure={`up to ${num(sh.short).toLocaleString("en-US")}`} label={`short in ${monthName(sh.month)}, before stock on hand`} />);
  if (open && num(open) > 0) tiles.push(<Tile key="open" figure={`${num(open).toLocaleString("en-US")} ${(open as { uom?: string }).uom ?? ""}`.trim()} label={`open on ${d.open_lines} PO ${d.open_lines === 1 ? "line" : "lines"}`} />);
  if (ex?.status === "china_listed" && ex.net) tiles.push(<Tile key="duty" figure={usd(Number((ex.net as { usd?: string; amount: string }).usd ?? (ex.net as { amount: string }).amount))} label={`new duty, net, from ${shortDate(ex.effective_date ?? "")}`} />);
  else if (ex?.unknown) tiles.push(<Tile key="duty" figure="Unknown" label="new duty: origin not on file" />);
  return tiles.length === 0 ? null : <div className="rc-sec" style={{ marginTop: "var(--s5)" }}><Tiles>{tiles}</Tiles></div>;
}

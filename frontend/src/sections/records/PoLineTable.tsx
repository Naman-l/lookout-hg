import { Fragment, useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { api } from "../../api/client";
import { useResource } from "../../api/useResource";
import { useMedia } from "../../ui/useMedia";
import type { ActionItem, PoLine } from "../../api/types";
import { openValue } from "../orders/model";
import { day, neededText, noticeDate, orderLines, partName, rankCases, receivedText, usd, type Rung } from "./model";
import { CaseName, RobotHead, RobotSlots, type Records } from "./ui";

type Col = "line" | "part" | "robots" | "supplier" | "buyer" | "qty" | "open" | "promised" | "case";
const WIDTH: Record<Col, string> = { line: "150px", part: "minmax(0,1fr)", robots: "80px", supplier: "minmax(0,190px)", buyer: "64px", qty: "84px", open: "80px", promised: "128px", case: "minmax(0,170px)" };      // text columns give way on a narrow screen
const HEAD: Record<Col, string> = { line: "PO line", part: "Part", robots: "", supplier: "Supplier", buyer: "Buyer", qty: "Open qty", open: "Open value", promised: "Promise date", case: "Case" };      // the live vocabulary (F74)
const qtyOf = (l: PoLine) => l.qty as { value: string; uom?: string };
const dom = (id: string) => `pl-${id.replace(/[^A-Za-z0-9]/g, "-")}`;

/** PO line rows (COMPONENTS §1): one line per PO line, past due oldest first, the lines that may not be open at the foot. A row unfolds its promise history (§2); one at a time, Escape closes. */
export function PoLineTable({ lines, r, drop, everyone = false, open, onOpen, caseTitle, label }: {
  lines: PoLine[]; r: Records; drop?: "supplier" | "part"; everyone?: boolean; open: string | null; onOpen: (id: string | null) => void; caseTitle?: (i: ActionItem) => string; label: string;
}) {
  const mid = useMedia("(max-width: 1100px)"), phone = useMedia("(max-width: 760px)");
  const cols: Col[] = (["line", "part", "robots", "supplier", "buyer", "qty", "open", "promised", "case"] as Col[])
    .filter((c) => !(drop === "part" && (c === "part" || c === "robots")) && !(drop === "supplier" && c === "supplier") && (c !== "buyer" || everyone))
    .filter((c) => !(mid && (c === "robots" || c === "buyer" || c === "qty")) && !(phone && (c === "supplier" || c === "case" || (c === "part" && drop !== "part"))));
  const PHONE: Partial<Record<Col, string>> = { line: "minmax(0,1fr)", open: "64px", promised: "minmax(0,108px)" };      // a phone reads the line, what is open and when
  const template = cols.map((c) => (phone && PHONE[c]) || (c === "supplier" && drop === "part" ? "minmax(0,1fr)" : WIDTH[c])).join(" ");
  const { open: rows, stale } = orderLines(lines);
  const tableRef = useRef<HTMLDivElement>(null);

  // Escape folds the open row and puts focus back on it.
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || (e.target as HTMLElement).closest(".td-menu")) return;
      tableRef.current?.querySelector<HTMLButtonElement>(`#${dom(open)}-b`)?.focus();
      onOpen(null);
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onOpen]);

  const row = (l: PoLine) => {
    const id = l.ref.id ?? "", q = qtyOf(l), p = r.partById.get(l.part.id ?? "");
    const dpd = l.days_past_due ?? 0, redated = !!l.revised_date && l.revised_date !== l.promise_date;
    const fm = !!(l as PoLine & { disrupted_by?: unknown }).disrupted_by && dpd > 0;
    const c = rankCases(r.idx.line.get(id) ?? [], r.asOf)[0];
    const isOpen = open === id;
    const cell: Record<Col, () => JSX.Element> = {
      line: () => (
        <span role="cell" className="rc-pl-id">
          <button type="button" id={`${dom(id)}-b`} className="rc-stretch" aria-expanded={isOpen} aria-controls={`${dom(id)}-h`} onClick={() => onOpen(isOpen ? null : id)}>{id}</button>
          {l.status === "PARTIAL" && <small>Partial</small>}
        </span>
      ),
      part: () => (
        <span role="cell" className="rc-two">
          <Link className="rc-in" to={`/parts/${encodeURIComponent(l.part.id ?? "")}`} title={p?.description ?? l.part.id ?? ""}>{partName(p?.description, 2) || l.part.id}</Link>
          <small className="rc-id">{l.part.id}</small>
        </span>
      ),
      robots: () => <span role="cell"><RobotSlots robots={r.robots} lit={r.robotsOf.get(l.part.id ?? "") ?? []} on="goes into it" off="not in it" /></span>,
      supplier: () => <span role="cell" className="rc-sup"><Link className="rc-in" to={`/suppliers/${encodeURIComponent(l.supplier.id ?? "")}`} title={l.supplier.label ?? ""}>{r.supName(l.supplier.id, l.supplier.label)}</Link></span>,
      buyer: () => <span role="cell" className="rc-buyer">{l.buyer.split(" ")[0]}</span>,
      qty: () => <span role="cell" className="n rc-qty">{Number(q.value).toLocaleString("en-US")}<small> {q.uom}</small></span>,
      open: () => <span role="cell" className="n rc-open">{usd(openValue(l))}</span>,
      promised: () => (
        <span role="cell" className="rc-pr" title={dpd > 0 ? `${dpd} ${dpd === 1 ? "day" : "days"} past due` : undefined}>
          {l.promise_date ? <span>{day(l.promise_date, r.year)}{redated && <span className="rc-new"> <ArrowRight size={12} aria-label="now" /> {day(l.revised_date, r.year)}</span>}</span> : <span className="none">No date</span>}
          {fm && <small>Force majeure · no date</small>}
        </span>
      ),
      case: () => <CaseName i={c} title={c && caseTitle ? caseTitle(c) : undefined} />,
    };
    return (
      <Fragment key={id}>
        <div className={`rc-pl rc-hit${isOpen ? " open" : ""}`} role="row" style={{ gridTemplateColumns: template }}>{cols.map((k) => <Fragment key={k}>{cell[k]()}</Fragment>)}</div>
        {isOpen && <History line={l} r={r} />}
      </Fragment>
    );
  };

  return (
    <div className="rc-plt" role="table" aria-label={label} ref={tableRef}>
      <div className="rc-pl-h" role="row" style={{ gridTemplateColumns: template }}>
        {cols.map((c) => (c === "robots" ? <RobotHead key={c} robots={r.robots} /> : <span key={c} role="columnheader" className={c === "qty" || c === "open" ? "n" : undefined}>{HEAD[c]}</span>))}
      </div>
      {rows.map(row)}
      {stale.length > 0 && <div className="rc-foot" role="row"><span role="cell">May not be open · {stale.length}</span></div>}
      {stale.map(row)}
    </div>
  );
}

/** The row unfolded (COMPONENTS §2): Ordered → Promised → Supplier now says → Received, and on the right what is Needed. Only the steps the records know. */
function History({ line, r }: { line: PoLine; r: Records }) {
  const id = line.ref.id ?? "";
  const lad = useResource(() => api.phasesLine(id), [id]);
  const rungs = (lad.data?.rungs ?? []) as Rung[];
  const get = (k: string) => rungs.find((x) => x.key === k);
  const ordered = get("ordered"), promised = get("promised"), need = neededText(get("need"));
  const redated = !!line.revised_date && line.revised_date !== line.promise_date;
  const newest = line.revised_date ?? line.promise_date;
  const needMonth = get("need")?.date?.slice(0, 7);
  const after = !!(need && newest && needMonth && newest.slice(0, 7) > needMonth);
  const oq = ordered?.detail?.match(/^([\d.,]+) (\w+) ordered/);
  const steps: { k: string; label: string; main: string; sub?: string }[] = [];
  if (ordered?.date) steps.push({ k: "o", label: "Ordered", main: day(ordered.date, r.year), sub: oq ? `${Number(oq[1]).toLocaleString("en-US")} ${oq[2]}` : undefined });
  if (line.promise_date) steps.push({ k: "p", label: "Promised", main: day(line.promise_date, r.year), sub: "on the PO" });
  if (redated) {
    const n = noticeDate(promised?.detail);
    steps.push({ k: "n", label: "Supplier now says", main: day(line.revised_date, r.year), sub: n ? `${r.supName(line.supplier.id, line.supplier.label)} notice, ${n}` : undefined });
  } else if (promised?.flag === "disrupted") steps.push({ k: "n", label: "Supplier notice", main: "Force majeure", sub: "no new date yet" });
  const rec = receivedText(get("received"), r.year);
  if (rec) steps.push({ k: "r", label: "Received", main: rec });
  return (
    <div className="rc-hist" id={`${dom(id)}-h`} role="row" aria-label={`Promise history of ${id}`}>
      {lad.loading && !lad.data ? <span className="rc-hist-sk" aria-hidden><i /></span>
        : lad.error ? <span className="rc-hist-err">History could not be loaded.</span>
        : (
          <>
            <ol className="rc-steps">
              {steps.map((s, n) => (
                <li key={s.k}>
                  {n > 0 && <ArrowRight className="rc-arr" size={14} aria-hidden />}
                  <span><small>{s.label}</small><b>{s.main}</b>{s.sub && <small>{s.sub}</small>}</span>
                </li>
              ))}
            </ol>
            {need && <span className="rc-need"><small>Needed</small><b>{need[0]}</b><small>{[need[1], after ? "arrives after" : ""].filter(Boolean).join(" · ")}</small></span>}
          </>
        )}
    </div>
  );
}

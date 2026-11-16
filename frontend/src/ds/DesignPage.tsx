import { Button, Notice, PageHeader, StateChip, Tile, Tiles } from "./index";
import { DataTable, TitleCell, type Col } from "./DataTable";
import { VERTICALS, VerticalIcon } from "../components/domain";
import { inr, longDate, shortDate } from "../ui/format";

/** Sample rows, invented for this page (no record of the dataset). */
type Sample = { title: string; sub: string; amount: number; by: string };
const ROWS: Sample[] = [
  { title: "Project A: MFC for the transformers not issued", sub: "After PO · PO firm to 31 Oct", amount: 1.4e7, by: "2026-10-25" },
  { title: "Project B: 32 PR lines short-closed after the RFQ", sub: "Requirement · 4 vendors quoted", amount: 3.4275e7, by: "2026-11-08" },
  { title: "Vendor C: PV claim on the wrong base month", sub: "Price · claimed ₹53 L", amount: 938396, by: "2026-10-25" },
];

/** The design system, on one page: the tokens a screen may use, the five vertical colours and icons, the controls, a table in the one template. */
export function DesignPage() {
  const cols: Col<Sample>[] = [
    { id: "t", head: "Case", width: "minmax(0,1fr)", cell: (x) => <TitleCell title={x.title} sub={x.sub} /> },
    { id: "a", head: "₹ at stake", width: "110px", end: true, cell: (x) => inr(x.amount) },
    { id: "b", head: "Act by", width: "90px", end: true, cell: (x) => shortDate(x.by) },
  ];
  return (
    <div className="uth">
      <PageHeader title="Design system" meta={<span>Tokens, the vertical identities, controls and the one table · {longDate("2026-10-20")}</span>} />
      <h2>Verticals</h2>
      <p style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>{VERTICALS.map((v) => <span key={v.id} style={{ display: "inline-flex", gap: 8, alignItems: "center" }}><VerticalIcon id={v.id} size={22} /> <b>{v.name}</b> <small>--vert-{v.id}</small></span>)}</p>
      <h2>Money and dates</h2>
      <p>{[8500, 15e5, 1.4e7, 3.2e9].map((n) => inr(n)).join(" · ")} · exact {inr(4249224, true)} · {shortDate("2026-10-28")} · {longDate("2026-10-20")}</p>
      <h2>Controls</h2>
      <p style={{ display: "flex", gap: 8 }}><Button variant="primary">Approve and send</Button><Button>Edit</Button><Button variant="quiet">Reject</Button></p>
      <p style={{ display: "flex", gap: 8 }}><StateChip tone="critical">Held</StateChip><StateChip tone="caution">Countersign</StateChip><StateChip tone="positive">Sent</StateChip><StateChip tone="unknown">Unknown</StateChip></p>
      <Notice>A notice states a fact once, plainly.</Notice>
      <h2>Tiles</h2>
      <Tiles><Tile figure={inr(3.43e7)} label="enquiry spent" /><Tile figure="23 days" label="with Projects" tone="caution" /><Tile figure="6 of 6" label="checks passed" tone="positive" /></Tiles>
      <h2>The table</h2>
      <DataTable label="Sample cases" cols={cols} rows={ROWS} rowKey={(x) => x.title} />
    </div>
  );
}

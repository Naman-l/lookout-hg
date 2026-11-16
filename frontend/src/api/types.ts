// The API types come from api/openapi.yaml (generated from the server's own schema) via `npm run types` (src/api/schema.d.ts); everything here aliases it.
// Decimals arrive as strings. Optional fields stay optional; the server always sends the required ones.
import type { components } from "./schema";

type S = components["schemas"];
export type EntityRef = S["EntityRef"];
export type Provenance = S["Provenance"];
export type Money = S["Money"];
export type Quantity = S["Quantity"];
export type Unknown = S["Unknown"];
export type DateValue = S["DateValue"];
export type Value = Money | Quantity | Unknown | DateValue;
export const isUnknown = (v: Value): v is Unknown => "owner" in v;
export const isMoney = (v: Value): v is Money => "currency" in v;
export const isQuantity = (v: Value): v is Quantity => "uom" in v && !("currency" in v);
export const isDate = (v: Value): v is DateValue => "date" in v;

export type Counts = S["Counts"];
export type ActionItem = S["ActionItem"];
export type ActionItemDetail = S["ActionItemDetail"];
export type ItemDetail = ActionItemDetail;
export type Stage = S["Stage"];
export type SiteImpact = S["SiteImpact"];
export type DatedRow = S["DatedRow"];
export type Finding = S["Finding"];
export type Deadline = S["Deadline"];
export type VendorPanel = S["VendorPanel"];
export type ProjectPanel = S["ProjectPanel"];
export type HeldMessage = S["HeldMessage"];
export type LinkedCase = S["LinkedCase"];
export type Decision = S["Decision"];
export type Route = S["Route"];
export type Recipient = S["Recipient"];
export type DoaLine = S["DoaLine"];
export type Action = S["Action"];
export type OutboxMessage = S["OutboxMessage"];
export type Span = S["Span"];

export type MessageSummary = S["MessageSummary"] & { from?: string };
export type MessageDetail = S["MessageDetail"];
export type QuoteFacts = S["QuoteFacts"];
export type LineMove = S["LineMove"];
export type DatedFact = S["DatedFact"];

export type VendorRow = S["VendorRow"];
export type VendorDetail = S["VendorDetail"];
export type Delivery = S["Delivery"];
export type MaterialRow = S["MaterialRow"];
export type MaterialDetail = S["MaterialDetail"];
export type PrLine = S["PrLineView"];
export type PoLine = S["PoLineView"];
export type PrDetail = S["PrDetail"];
export type PoDetail = S["PoDetail"];
export type Ladder = S["Ladder"];
export type Rung = S["Rung"];
export type ProjectRow = S["ProjectRow"];
export type RequirementRow = S["RequirementRow"];
export type FrontStatus = S["FrontStatus"];
export type SupplyByMonth = S["SupplyByMonth"];
export type MonthRow = S["MonthRow"];
export type CsView = S["CsView"];
export type QuoteView = S["QuoteView"];
export type VendorQuote = S["VendorQuote"];
export type QuoteBeside = S["QuoteBeside"];
export type LedgerItem = S["LedgerItem"];
export type Person = S["Person"];
export type DataIssue = S["DataIssue"];
export type SearchHit = S["Hit"];
export type BuildStamp = S["BuildStamp"];
export type BuildStep = S["BuildStep"];
export type Source = S["Source"];
export type ImportDeck = S["ImportDeck"];
export type ImportQuestion = S["ImportQuestion"];
export type ImportAnswer = S["ImportAnswer"];
export type ImportDryRun = S["ImportDryRun"];

export interface Health {
  ok: boolean; boot: string; agent_live: boolean; as_of: string; company: string; company_short: string; base_currency: string;
  id_patterns?: Record<string, string>; sources?: SourceStamp[];
}
/** One source's own export date, for the shell's data-as-of hover. */
export interface SourceStamp { key: string; title: string; date: string | null; stale: boolean; kind: string }

// The runs (the agent layer): hand-kept until the run routes are in the generated contract.
export interface RunEvent {
  run_id: string; parent_run_id?: string | null; seq: number; ts: string; t_ms: number; type: string; agent: string; agent_label: string;
  tool_use_id?: string | null; summary: string; refs?: EntityRef[]; payload?: Record<string, unknown>;
}
export interface VerifierResult { passed: boolean; checked: number; failures: string[]; claims?: { text: string; ok: boolean; id?: string }[] }
export interface Recommendation {
  finding?: string; recommended?: { kind: string; reason?: string; number_ids?: string[] } | null; unknowns?: Unknown[]; number_ids?: string[];
  answer?: string; reading?: string; tables?: unknown[]; drafted_by?: string;
}
export interface Run {
  run_id: string; item_key: string; workflow: string; status: string; started_at: string; wall_ms?: number | null; asked_by?: string | null;
  recorded?: boolean; mode?: string; model?: string | null; title?: string | null; cost_usd?: string | null; drafts?: number; checks?: string | null; grade?: number | null;
}
export interface RunDetail extends Run { events?: RunEvent[]; recommendation?: Recommendation | null; verifier?: VerifierResult | null; review?: { grade: number; notes: string[] } | null; question?: string | null }
export interface Agents { agents: { name: string; label: string; does: string; tools: string[]; runs: number }[]; mode: string; recordings: number }
export type EvalsSummary = { rounds: unknown[] };

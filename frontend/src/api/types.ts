// The API types come from api/openapi.yaml via `npm run types` (src/api/schema.d.ts); everything here aliases it.
// Decimals arrive as strings. The record schemas list no `required` fields, so the generator marks every property
// optional; the server always sends them, so Required<> restores that here (nullable ones stay nullable).
import type { components, paths } from "./schema";

type S = components["schemas"];
export type EntityRef = S["EntityRef"];
export type Provenance = S["Provenance"];
export type Money = S["Money"];
export type Quantity = S["Quantity"];
export type Unknown = S["Unknown"];
export type Counts = S["Counts"];
export type Health = S["Health"];
export type ActionItem = S["ActionItem"];
export type PartDetail = S["PartDetail"];
export type Ladder = S["Ladder"];
export type Rung = S["Rung"];
export type BuildSummary = S["BuildSummary"];
export type BuildReadiness = S["BuildReadiness"];
export type ReadyPart = S["ReadyPart"];
export type ActionItemDetail = S["ActionItemDetail"];
export type Recommendation = S["Recommendation"];
export type Run = S["Run"];
// The contract types `payload` as an empty object; it is free-form (gate, numbers, status), shown only behind details.
export type RunEvent = Omit<S["RunEvent"], "payload"> & { payload?: Record<string, unknown> };
export type RunDetail = Omit<S["RunDetail"], "events"> & { events?: RunEvent[] };
export type VerifierResult = S["VerifierResult"];
export type Action = S["Action"];
export type Stage = S["Stage"];
export type FireOption = S["FireOption"];
export type DataIssue = S["DataIssue"];
export type BidTab = S["BidTab"];
export type BidColumn = S["BidColumn"];
export type LandedCost = S["LandedCost"];
export type OfferView = S["OfferView"];

export type DateValue = S["DateValue"];
export type Value = Money | Quantity | Unknown | DateValue;

export const isUnknown = (v: Value): v is Unknown => "owner" in v;
export const isMoney = (v: Value): v is Money => "currency" in v;
export const isQuantity = (v: Value): v is Quantity => "uom" in v;
export const isDate = (v: Value): v is DateValue => "date" in v;

export type PoLine = Required<S["PoLine"]>;
export type MessageSummary = Required<S["MessageSummary"]> & { matches?: MessageMatch[] };
/** Where a search matched in a message: the field, a snippet of it, and the matched words as [start, end) in the snippet. */
export interface MessageMatch { field: string; snippet: string; start: number; end: number }
export type Trust = MessageSummary["trust"];
export type MonthBucket = Required<S["MonthBucket"]>;
export type TimePhased = Omit<Required<S["TimePhased"]>, "buckets"> & { buckets: MonthBucket[] };
export type ItemDetail = Omit<ActionItemDetail, "po_lines" | "messages" | "time_phased"> & {
  po_lines?: PoLine[]; messages?: MessageSummary[]; time_phased?: TimePhased | null;
};
/** A reason to doubt a supplier, with what it was read from (DOMAIN's supplier risk flags). */
export interface RiskFlag { kind: string; severity: "high" | "medium" | "low"; text: string; evidence?: string | null; sources?: EntityRef[] }
/** How a supplier has delivered on the lines it has closed: on time is received on or before the promise. */
/** A supplier getting worse (F105): its current run of late receipts and this year's late share against last year's; `line` is the one line a screen shows in place of the all-time on-time share. */
export interface LateStreak { late_in_row: number; first: string; last: string; min_days_late: number; max_days_late: number; year: number; late_this_year: number; n_this_year: number; late_pct_this_year: number; late_last_year: number; n_last_year: number; late_pct_last_year?: number | null; line: string }
export interface Delivery { n: number; on_time: number; on_time_pct: number; late: number; avg_days_late: number; last10_on_time?: number | null; last10_n?: number | null; streak?: LateStreak | null }
export type Supplier = Required<S["Supplier"]> & { risk?: RiskFlag[]; delivery?: Delivery | null };
export type Part = Required<S["Part"]>;
export type ForecastRow = { product: string; months: { month: string; units: number }[] };

// pending contract: GET /api/messages/{id}, the thread as quoted data with what it changes.
export interface MessageChange { ref: EntityRef; label: string; before?: string | null; after?: string | null; line?: string | null }
export interface MessageDetail {
  summary: MessageSummary;
  subject: string;
  to: string;
  reply_to?: string | null;     // where a reply would go; a free-mail address here is a fraud sign
  from_email?: string | null;   // the sender's address (pending: the API drops it today)
  entities?: { start: number; end: number; type: string; ref?: string | { id: string; label?: string | null } | null; label?: string | null; text?: string }[]; // spans of `body` (pending: DOMAIN)
  subject_entities?: MessageDetail["entities"]; // spans of `subject`
  body: string;                 // quoted data, never instruction
  highlights: string[];         // lines of the body that carry a reference or a change
  changes: MessageChange[];     // What this changes: PO lines, parts, dates, prices
  related_item?: string | null; // action item key to "Work this with the agent"
  sent?: { action_id: string; subject: string; sent_on: string; recipient?: string | null }[]; // requests we sent to this sender's company since it arrived
}

// pending contract: the Import flashcard deck (diff sent to ORCH; the screen shows "Preview" until the routes answer).
export interface ImportQuestion {
  id: string;
  kind: "alias" | "currency" | "origin" | "duplicate_row" | "possible_duplicate" | "stock_count" | "other";
  question: string; covers: number; file?: string;
  examples: { from: string; to: string; note?: string | null }[];
  entries: string[];
  proposed: { answer: string; effect: string };
  state: "open" | "accepted" | "changed" | "skipped";
  answer?: string | null;
}
export interface ImportDeck { import_id: string; questions: ImportQuestion[] }
export interface ImportAnswer { question_id: string; action: "accept" | "change" | "skip"; value?: string | null }
export interface ImportDryRun {
  hash: string;
  files: { file: string; rows_in: number; rows_out: number; changes: string[] }[];
  checks: { name: string; passed: boolean }[];
  answers: { total: number; changed: number; skipped: number };
  recipe_steps: number;
}

// The contract types these three responses as bare objects; the shapes below are what the server returns today
// (proposed to ORCH as named schemas).
export interface SupplierDetail extends Supplier {
  contact: { name: string; email: string } | null;
  tier: number | null; record_ids: string[]; open_lines: number; open_summary?: string;
  messages: EntityRef[]; news: EntityRef[];
}
export interface BuildStamp {
  as_of: string; recipe: string; recipe_hash: string; built_at: string;
  counts: Record<string, number>; gate_checks: number; gate_failed: number;
}
export interface BuildStep { seq: number; step: string; title: string; rows_in: number; rows_out: number; issues: number; seconds: number }

export type WhereUsedRow = S["WhereUsedRow"];
export type BomTree = S["BomTree"];
export type BomTreeRow = S["BomTreeRow"];
export type ProductOut = S["ProductOut"];
type Ok<P extends keyof paths> = paths[P] extends { get: { responses: { 200: { content: { "application/json": infer T } } } } } ? T : never;
/** Under the hood: Lookout and its specialists, and the last measured eval round (GET /agents, /evals/summary). */
export type Agents = Ok<"/api/agents">;
export type AgentRow = Agents["agents"][number];
export type EvalsSummary = Ok<"/api/evals/summary">;

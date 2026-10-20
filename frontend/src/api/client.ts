// The typed client. Every read goes through `get`, every start of a run through `startOn`: one place each.
import { noteRead } from "./freshness";
import { invalidate } from "./useResource";
import type { FireOption, BuildReadiness, BuildSummary, Ladder, PartDetail, EntityRef, BomTree, ProductOut, WhereUsedRow, BuildStamp, BuildStep, SupplierDetail, BidTab, DataIssue, ImportAnswer, ImportDeck, ImportDryRun, MessageDetail, MessageSummary, Action, ActionItem, Counts, ForecastRow, Health, ItemDetail, Part, PoLine, Run, RunDetail, RunEvent, Supplier, OfferView, Agents, EvalsSummary } from "./types";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`/api${path}`);
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  noteRead(res);
  return (await res.json()) as T;
}

/** A failed call keeps its status and the server's own sentence, so a screen can say what happened in words. */
export class ApiError extends Error {
  constructor(public status: number, public detail: string, path: string) { super(`${status} ${path}`); }
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) {
    const detail = await res.json().then((d) => (typeof d?.detail === "string" ? d.detail : ""), () => "");
    throw new ApiError(res.status, detail, path);
  }
  const out = (await res.json()) as T;
  invalidate();
  return out;
}

/** A change to a record (PATCH): same error handling as `post`. */
async function patch<T>(path: string, method: "PATCH", body: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, { method, headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) {
    const detail = await res.json().then((d) => (typeof d?.detail === "string" ? d.detail : ""), () => "");
    throw new ApiError(res.status, detail, path);
  }
  const out = (await res.json()) as T;
  invalidate();
  return out;
}

/** One PO line as the record holds it (GET /orders/{po_line}). */
export type OrderLine = {
  po_line: EntityRef; part: EntityRef; supplier: EntityRef; buyer: string | null; status: string;
  qty_open: { value: string; uom: string }; line_value?: { usd?: string | null } | null; unit_price?: { usd?: string | null } | null; promise: string | null; revised_promise: string | null; days_past_due: number | null;
};

/** Start a run on an item. A run already in progress answers 409 with its own RunRef; either way the caller gets a run id. */
async function startRun(key: string, askedBy: string, live = false): Promise<{ run_id: string; status: string; existing?: boolean }> {
  const res = await fetch(`/api/action-items/${encodeURIComponent(key)}/runs`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ asked_by: askedBy, ...(live ? { live: true } : {}) }),
  });
  if (res.ok || res.status === 409) { const out = (await res.json()) as { run_id: string; status: string }; invalidate(); return { ...out, existing: res.status === 409 }; }
  throw new Error(`${res.status} start run`);
}

const PAGE_KINDS: Record<string, string> = { "": "today", items: "case", approvals: "approvals", inbox: "inbox", builds: "build", suppliers: "supplier", parts: "part", orders: "orders",
  forecast: "forecast", data: "data", hood: "hood", activity: "activity", shelf: "shelf", more: "more" };

/** The page the buyer asks from (h10): its kind from the route, and a label read from what is on screen (the title, then the pressed tab and filters). */
export function pageNow(): { kind: string; label: string } | null {
  try {
    const seg = location.pathname.split("/")[1] ?? "";
    const kind = location.pathname.startsWith("/parts/bom") ? "bom" : location.pathname.startsWith("/data/import") ? "import" : PAGE_KINDS[seg] ?? seg;
    const main = document.querySelector("main .content");
    const title = main?.querySelector("h1")?.textContent?.trim() ?? "";
    const on = [...(main?.querySelectorAll('[aria-current="step"], [aria-pressed="true"], [aria-selected="true"], [aria-current="page"]') ?? [])]      // a case's open step first (Ask on Analysis knows it is on Analysis)
      .map((e) => (e.textContent ?? "").replace(/^\s*\d+\s*/, "").replace(/\s*\d[\d,]*\s*$/, "").trim()).filter((t) => t && t.length <= 40).slice(0, 3);
    return { kind, label: [title, ...on].filter(Boolean).join(" · ").slice(0, 160) };
  } catch { return null; }
}

/** Ask Lookout a question; the entity on screen goes along as context, and the page it was asked from. Answers stream like any run. */
async function ask(question: string, context: EntityRef | null, askedBy: string, threadId?: string | null): Promise<{ run_id: string; status: string }> {
  const page = pageNow();
  const res = await fetch("/api/ask", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ question, context, asked_by: askedBy, ...(threadId ? { thread_id: threadId } : {}), ...(page ? { page } : {}) }) });
  if (res.status === 503) throw new Error("no-model");
  if (!res.ok) throw new Error(`${res.status} ask`);
  const out = (await res.json()) as { run_id: string; status: string };
  invalidate();
  return out;
}

/** Compare quotes for a part with the Sourcing analyst (starts a run). */
async function compareRun(part: string, askedBy: string): Promise<{ run_id: string; status: string }> {
  const res = await fetch(`/api/parts/${encodeURIComponent(part)}/compare-runs`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ asked_by: askedBy }) });
  if (res.ok || res.status === 409) return (await res.json()) as { run_id: string; status: string };
  throw new Error(`${res.status} compare`);
}

type RunRefOut = { run_id: string; status: string };
async function startOn(path: string, body: unknown, what: string): Promise<RunRefOut> {
  const res = await fetch(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  if (res.ok || res.status === 409) return (await res.json()) as RunRefOut;
  throw new Error(res.status === 503 ? "no-model" : res.status === 422 ? "bad-file" : `${res.status} ${what}`);
}
/** The Inbox analyst: read a message ("What does this mean?"), or draft a reply that waits for approval. */
const triageRun = (message: string, askedBy: string) => startOn(`/api/messages/${encodeURIComponent(message)}/triage-runs`, { asked_by: askedBy }, "triage");
const replyRun = (message: string, askedBy: string) => startOn(`/api/messages/${encodeURIComponent(message)}/reply-runs`, { asked_by: askedBy }, "reply");
/** The Data steward: read an unfamiliar CSV and propose how to load it. Nothing is loaded. */
const stewardRun = (filename: string, text: string, askedBy: string) => startOn("/api/imports/steward-runs", { filename, text, asked_by: askedBy }, "steward");

export const api = {
  startRun,
  triageRun,
  replyRun,
  stewardRun,
  ask,
  compareRun,
  health: () => get<Health>("/health"),
  askExamples: () => get<{ question: string; context?: EntityRef | null }[]>("/ask/examples"),
  agents: () => get<Agents>("/agents"),
  evalsSummary: () => get<EvalsSummary>("/evals/summary"),
  counts: (buyer?: string | null) => get<Counts>(buyer ? `/counts?buyer=${encodeURIComponent(buyer)}` : "/counts"),
  actionItems: (owner?: string) => get<ActionItem[]>(owner ? `/action-items?owner=${encodeURIComponent(owner)}` : "/action-items"),
  options: (key: string) => get<FireOption[]>(`/action-items/${encodeURIComponent(key)}/options`),
  item: (key: string, owner?: string | null) => get<ItemDetail>(`/action-items/${encodeURIComponent(key)}${owner ? `?owner=${encodeURIComponent(owner)}` : ""}`),
  run: (id: string) => get<RunDetail>(`/runs/${id}`),
  actions: (state?: Action["state"]) => get<Action[]>(state ? `/actions?state=${state}` : "/actions"),
  action: (id: string) => get<Action>(`/actions/${id}`),
  editAction: (id: string, subject: string, body: string, edited_by: string, decision?: { reason?: string; recheck_on?: string }) => patch<Action>(`/actions/${id}`, "PATCH", { subject, body, edited_by, ...(decision ?? {}) }),
  order: (poLine: string) => get<OrderLine>(`/orders/${encodeURIComponent(poLine)}`),
  approve: (id: string, payload_hash: string, approved_by: string, confirm_unverified = false) => post<Action>(`/actions/${id}/approve`, { payload_hash, approved_by, ...(confirm_unverified ? { confirm_unverified } : {}) }),
  reject: (id: string, reason: string, rejected_by: string) => post<Action>(`/actions/${id}/reject`, { reason, rejected_by }),
  messages: (f: { q?: string; kind?: string; supplier?: string; trust?: string } = {}) => {
    const p = new URLSearchParams(Object.entries(f).filter(([, v]) => v) as [string, string][]).toString();
    return get<MessageSummary[]>(p ? `/messages?${p}` : "/messages");
  },
  thread: (id: string) => get<MessageDetail>(`/messages/${encodeURIComponent(id)}`),
  dataIssues: () => get<DataIssue[]>("/data-issues"),
  partOffers: (part: string) => get<OfferView[]>(`/parts/${encodeURIComponent(part)}/offers`),
  compare: (part: string, qty?: number) => get<BidTab>(`/parts/${encodeURIComponent(part)}/compare${qty ? `?qty=${qty}` : ""}`),
  supplier: (id: string) => get<SupplierDetail>(`/suppliers/${encodeURIComponent(id)}`),
  stamp: () => get<BuildStamp>("/data/stamp"),
  steps: () => get<BuildStep[]>("/data/steps"),
  products: () => get<ProductOut[]>("/products"),
  bom: (product: string) => get<BomTree>(`/products/${encodeURIComponent(product)}/bom`),
  partDetail: (part: string) => get<PartDetail>(`/parts/${encodeURIComponent(part)}`),
  phasesLine: (line: string) => get<Ladder>(`/phases?po_line=${encodeURIComponent(line)}`),
  phases: (part: string) => get<Ladder>(`/phases?part=${encodeURIComponent(part)}`),
  builds: () => get<BuildSummary[]>("/builds"),
  readiness: (product: string, month: string) => get<BuildReadiness>(`/builds/${encodeURIComponent(product)}/${encodeURIComponent(month)}/readiness`),
  whereUsed: (part: string) => get<WhereUsedRow[]>(`/parts/${encodeURIComponent(part)}/where-used`),
  runs: () => get<Run[]>("/runs"),
  actionsFor: (itemKey: string) => get<Action[]>(`/actions?item_key=${encodeURIComponent(itemKey)}`),
  recordControl: (itemKey: string, control: string, by: string) => post<Action>(`/action-items/${encodeURIComponent(itemKey)}/controls`, { control, by }),
  orders: () => get<PoLine[]>("/orders"),
  suppliers: () => get<Supplier[]>("/suppliers"),
  parts: () => get<Part[]>("/parts"),
  forecast: () => get<ForecastRow[]>("/forecast"),
};

/** Live run events: Server-Sent Events (reconnects with Last-Event-ID by itself). Returns an unsubscribe. */
export function subscribeRun(runId: string, onEvent: (e: RunEvent) => void): () => void {
  const es = new EventSource(`/api/runs/${runId}/events`);
  es.onmessage = (m) => onEvent(JSON.parse(m.data) as RunEvent);
  for (const t of ["run.started", "step.text", "step.delta", "child.started", "child.finished", "tool.called", "tool.result", "action.staged", "verifier.result", "run.finished", "run.failed"])
    es.addEventListener(t, (m) => onEvent(JSON.parse((m as MessageEvent).data) as RunEvent));
  return () => es.close();
}

/** The Import deck: questions, answers, a dry run, then approve. */
const send = async (path: string, body: unknown, what: string) => {
  const res = await fetch(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error(`${res.status} ${what}`);
};
export const imports = {
  async deck(): Promise<ImportDeck> {
    const res = await fetch("/api/imports/questions");
    if (!res.ok) throw new Error(`${res.status} questions`);
    return (await res.json()) as ImportDeck;
  },
  answer: (answers: ImportAnswer[], answeredBy: string) => send("/api/imports/answers", { answers, answered_by: answeredBy }, "answers"),
  async dryRun(): Promise<ImportDryRun> {
    const res = await fetch("/api/imports/dry-run");
    if (!res.ok) throw new Error(`${res.status} dry-run`);
    return (await res.json()) as ImportDryRun;
  },
  approve: (hash: string, approvedBy: string) => send("/api/imports/approve", { hash, approved_by: approvedBy }, "approve"),
};

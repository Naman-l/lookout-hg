// The typed client. Every read goes through `get`, every start of a run through `startOn`: one place each.
import { noteRead } from "./freshness";
import { invalidate } from "./useResource";
import type { Action, ActionItem, Counts, DataIssue, Health, ItemDetail, MessageDetail, MessageSummary, Route, Run, RunDetail, RunEvent, BuildStamp, BuildStep, EntityRef,
  VendorRow, VendorDetail, VendorQuote, MaterialRow, MaterialDetail, PrLine, PoLine, PrDetail, PoDetail, Ladder, ProjectRow, RequirementRow, FrontStatus, SupplyByMonth, CsView, Person,
  SearchHit, Agents, EvalsSummary, ImportDeck, ImportAnswer, ImportDryRun } from "./types";

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

/** Start a run on an item. A run already in progress answers 409 with its own RunRef; either way the caller gets a run id. */
async function startRun(key: string, askedBy: string, live = false): Promise<{ run_id: string; status: string; existing?: boolean }> {
  const res = await fetch(`/api/action-items/${encodeURIComponent(key)}/runs`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ asked_by: askedBy, ...(live ? { live: true } : {}) }),
  });
  if (res.ok || res.status === 409) { const out = (await res.json()) as { run_id: string; status: string }; invalidate(); return { ...out, existing: res.status === 409 }; }
  throw new Error(`${res.status} start run`);
}

const PAGE_KINDS: Record<string, string> = { "": "today", items: "case", approvals: "approvals", inbox: "inbox", vendors: "vendor", materials: "material", prs: "prs", pos: "pos",
  requirements: "requirements", workfronts: "workfronts", insights: "insights", brief: "brief", data: "data", hood: "hood", activity: "activity", lookup: "lookup", more: "more" };

/** The page the buyer asks from (h10): its kind from the route, and a label read from what is on screen (the title, then the pressed tab and filters). */
export function pageNow(): { kind: string; label: string } | null {
  try {
    const seg = location.pathname.split("/")[1] ?? "";
    const kind = location.pathname.startsWith("/data/import") ? "import" : PAGE_KINDS[seg] ?? seg;
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

/** Compare the quotes for a material with the Sourcing analyst (starts a run). */
async function compareRun(material: string, askedBy: string): Promise<{ run_id: string; status: string }> {
  const res = await fetch(`/api/materials/${encodeURIComponent(material)}/compare-runs`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ asked_by: askedBy }) });
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

const qs = (f: Record<string, string | number | boolean | null | undefined>) => {
  const p = new URLSearchParams(Object.entries(f).filter(([, v]) => v != null && v !== "").map(([k, v]) => [k, String(v)])).toString();
  return p ? `?${p}` : "";
};
const enc = encodeURIComponent;

export const api = {
  startRun,
  triageRun,
  replyRun,
  stewardRun,
  ask,
  compareRun,
  health: () => get<Health>("/health"),
  askExamples: (kind?: string, key?: string, on?: EntityRef | null) =>
    get<{ question: string; context?: EntityRef | null }[]>(`/ask/examples${qs({ page: kind, key, ctx_type: on?.type, ctx_id: on?.id, ctx_label: on?.label ?? undefined })}`),
  askEverywhere: () => get<{ question: string; context?: EntityRef | null }[]>("/ask/everywhere"),
  agents: () => get<Agents>("/agents"),
  evalsSummary: () => get<EvalsSummary>("/evals/summary"),
  counts: (buyer?: string | null) => get<Counts>(`/counts${qs({ buyer })}`),
  actionItems: (owner?: string | null) => get<ActionItem[]>(`/action-items${qs({ owner })}`),
  item: (key: string, owner?: string | null) => get<ItemDetail>(`/action-items/${enc(key)}${qs({ owner })}`),
  routes: (key: string, owner?: string | null) => get<Route[]>(`/action-items/${enc(key)}/routes${qs({ owner })}`),
  itemRuns: (key: string) => get<Run[]>(`/action-items/${enc(key)}/runs`),
  choose: (key: string, kind: string, by: string, reason = "") => post<Action>(`/action-items/${enc(key)}/routes/${enc(kind)}/choose`, { by, reason }),
  stage: (key: string, body: { kind: "note" | "record" | "erp_update"; staged_by: string; text: string; to?: string; reason?: string; recheck_on?: string | null; option_kind?: string | null }) =>
    post<Action>(`/action-items/${enc(key)}/actions`, body),
  recordControl: (itemKey: string, control: string, by: string) => post<Action>(`/action-items/${enc(itemKey)}/controls`, { control, by }),
  run: (id: string) => get<RunDetail>(`/runs/${id}`),
  runs: () => get<Run[]>("/runs"),
  actions: (state?: Action["state"]) => get<Action[]>(`/actions${qs({ state })}`),
  actionsFor: (itemKey: string) => get<Action[]>(`/actions${qs({ item_key: itemKey })}`),
  action: (id: string) => get<Action>(`/actions/${id}`),
  editAction: (id: string, subject: string, body: string, edited_by: string, decision?: { reason?: string; recheck_on?: string }) => patch<Action>(`/actions/${id}`, "PATCH", { subject, body, edited_by, ...(decision ?? {}) }),
  approve: (id: string, payload_hash: string, approved_by: string, confirm_unverified = false) => post<Action>(`/actions/${id}/approve`, { payload_hash, approved_by, ...(confirm_unverified ? { confirm_unverified } : {}) }),
  reject: (id: string, reason: string, rejected_by: string) => post<Action>(`/actions/${id}/reject`, { reason, rejected_by }),
  messages: (f: { q?: string; owner?: string | null; kind?: string; trust?: string } = {}) => get<MessageSummary[]>(`/messages${qs(f)}`),
  thread: (id: string) => get<MessageDetail>(`/messages/${enc(id)}`),
  dataIssues: () => get<DataIssue[]>("/data-issues"),
  stamp: () => get<BuildStamp>("/data/stamp"),
  steps: () => get<BuildStep[]>("/data/steps"),
  people: () => get<Person[]>("/people"),
  search: (q: string) => get<SearchHit[]>(`/search${qs({ q })}`),
  vendors: () => get<VendorRow[]>("/vendors"),
  vendor: (id: string) => get<VendorDetail>(`/vendors/${enc(id)}`),
  vendorQuotes: (id: string) => get<VendorQuote[]>(`/vendors/${enc(id)}/quotes`),
  materials: () => get<MaterialRow[]>("/materials"),
  material: (code: string) => get<MaterialDetail>(`/materials/${enc(code)}`),
  prs: (f: { status?: string; buyer?: string | null; project?: string } = {}) => get<PrLine[]>(`/prs${qs(f)}`),
  pr: (no: string) => get<PrDetail>(`/prs/${enc(no)}`),
  pos: (f: { status?: string; buyer?: string | null; project?: string; vendor?: string; material?: string } = {}) => get<PoLine[]>(`/pos${qs(f)}`),
  po: (no: string) => get<PoDetail>(`/pos/${enc(no)}`),
  order: (line: string) => get<PoLine>(`/orders/${line}`),
  ladder: (f: { pr_line?: string; po_line?: string }) => get<Ladder>(`/ladder${qs(f)}`),
  projects: () => get<ProjectRow[]>("/projects"),
  requirements: (project?: string) => get<RequirementRow[]>(`/requirements${qs({ project })}`),
  supply: (project: string, material: string) => get<SupplyByMonth>(`/supply${qs({ project, material })}`),
  workfronts: (project: string) => get<FrontStatus[]>(`/workfronts${qs({ project })}`),
  cs: (no: string) => get<CsView>(`/cs/${no}`),
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

// The Organisation page's reads and writes: the chart, and the edits a person makes to it. Every write answers with the whole chart.
import type { components } from "../../api/schema";

type S = components["schemas"];
export type OrgChart = S["OrgChart"];
export type OrgNode = S["OrgNode"];
export type OrgEdit = S["OrgEdit"];
export type OrgFields = S["OrgFields"];

/** A refused call keeps its status and the server's sentence ("Someone cannot report to a person who reports to them."), so the editor can say it. */
export class OrgError extends Error {
  constructor(public status: number, public detail: string) { super(detail || `${status}`); }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, body === undefined ? { method } : { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) {
    const detail = await res.json().then((d) => (typeof d?.detail === "string" ? d.detail : ""), () => "");
    throw new OrgError(res.status, detail || "The server could not make that change.");
  }
  return (await res.json()) as T;
}

const seg = encodeURIComponent;

export const org = {
  chart: () => call<OrgChart>("GET", "/org"),
  add: (fields: OrgFields) => call<OrgChart>("POST", "/org/people", fields),
  change: (id: string, fields: OrgFields) => call<OrgChart>("PATCH", `/org/people/${seg(id)}`, fields),
  remove: (id: string, by: string) => call<OrgChart>("DELETE", `/org/people/${seg(id)}?by=${seg(by)}`),
  undo: (by: string) => call<OrgChart>("POST", "/org/undo", { by }),
  reset: (by: string) => call<OrgChart>("POST", "/org/reset", { by }),
};

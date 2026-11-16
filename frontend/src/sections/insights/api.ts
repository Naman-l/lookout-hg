// The Insights reads: one fetch helper and the shapes from the contract (api/openapi.yaml -> api/schema.d.ts).
import type { components } from "../../api/schema";

type S = components["schemas"];
export type Figure = S["Figure"];
export type TeamResponse = S["TeamResponse"];
export type MemberSummary = S["MemberSummary"];
export type MemberPage = S["MemberPage"];
export type ProjectsResponse = S["ProjectsResponse"];
export type ProjectFigures = S["ProjectFigures"];
export type ProjectPage = S["ProjectPage"];
export type EstimateMonth = S["EstimateMonth"];
export type PricingResponse = S["PricingResponse"];
export type PricingRow = S["PricingRow"];
export type PricingDetail = S["PricingDetail"];
export type SitePrice = S["SitePrice"];
export type MonthRate = S["MonthRate"];
export type EstimatesResponse = S["EstimatesResponse"];
export type EstimateRow = S["EstimateRow"];
export type Brief = S["Brief"];
export type BriefSection = S["BriefSection"];

/** A read that failed keeps its status and the server's sentence, so a page can say what happened (403: not yours to see; 404: no such record). */
export class ReadError extends Error {
  constructor(public status: number, public detail: string) { super(detail || `${status}`); }
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`/api${path}`);
  if (!res.ok) {
    const detail = await res.json().then((d) => (typeof d?.detail === "string" ? d.detail : ""), () => "");
    throw new ReadError(res.status, detail);
  }
  return (await res.json()) as T;
}

const q = (viewer?: string | null) => (viewer ? `?viewer=${encodeURIComponent(viewer)}` : "");
const seg = encodeURIComponent;

export const insights = {
  team: (viewer?: string | null) => get<TeamResponse>(`/insights/team${q(viewer)}`),
  member: (person: string, viewer?: string | null) => get<MemberPage>(`/insights/team/${seg(person)}${q(viewer)}`),
  projects: () => get<ProjectsResponse>("/insights/projects"),
  project: (id: string) => get<ProjectPage>(`/insights/projects/${seg(id)}`),
  pricing: () => get<PricingResponse>("/insights/pricing"),
  material: (code: string) => get<PricingDetail>(`/insights/pricing/${seg(code)}`),
  estimates: () => get<EstimatesResponse>("/insights/estimates"),
  brief: (person: string) => get<Brief>(`/brief/${seg(person)}`),
};

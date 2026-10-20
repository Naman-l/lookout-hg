import { api } from "./client";
import { useResource } from "./useResource";

/** The company the data belongs to, from the build (GET /api/health: `company`, `company_short`), never typed into a screen. */
export function useCompany(): { full: string; short: string } {
  const h = useResource(api.health).data;
  return { full: h?.company ?? "the company", short: h?.company_short ?? "the company" };
}

import { api } from "./client";
import { useResource } from "./useResource";
import type { BuildSummary } from "./types";

/** The builds (one per robot and month), read once and shared: a chip on any page can find its build page. */
export const useBuilds = () => useResource<BuildSummary[]>(() => api.builds().catch(() => []), []);

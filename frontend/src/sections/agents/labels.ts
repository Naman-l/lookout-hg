import { api } from "../../api/client";
import { useResource } from "../../api/useResource";

/** Each agent's name as a buyer reads it, from the registry (GET /agents), so a raw name in a recording ("tariff_analyst") never shows. */
export function useAgentLabels(): (name: string, fallback?: string | null) => string {
  const ag = useResource(() => api.agents().catch(() => null));
  const by = new Map((ag.data?.agents ?? []).map((a) => [a.name, a.label]));
  return (name, fallback) => by.get(name) ?? (fallback && fallback !== name ? fallback : name.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()));
}

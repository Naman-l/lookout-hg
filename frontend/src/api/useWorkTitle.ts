import { api } from "./client";
import { useResource } from "./useResource";
import { humanize } from "../ui/format";

/** What a piece of agent work or a draft is FOR, in words: "Reply to Sam Cho (Acme Motors…)", "Import purchase_orders_export.csv", or the item's own title. */
export function useWorkTitle(): (key: string | undefined | null) => string {
  const items = useResource(() => api.actionItems().catch(() => []));
  const msgs = useResource(() => api.messages().catch(() => []));
  return (key) => {
    const k = key ?? "";
    const [kind, ...rest] = k.split(":"), id = rest.join(":");
    const m = (msgs.data ?? []).find((x) => x.ref.id === id);
    const co = m?.company && m.company !== "not on file" ? ` (${m.company})` : "";
    if (kind === "reply") return `Reply to ${m?.from ?? "a supplier"}${co}`;
    if (kind === "triage") return `Read ${m?.from ?? "a supplier"}'s message`;
    if (kind === "import") return `Import ${id}`;
    if (kind === "compare") return `Compare quotes for ${id}`;
    return humanize(items.data?.find((i) => i.key === k)?.title ?? k);
  };
}

import { api } from "./client";
import { useResource } from "./useResource";

/** supplier id -> name, for records whose reference arrives without a label. */
export function useSupplierNames() {
  const r = useResource(api.suppliers);
  const map = new Map((r.data ?? []).map((s) => [s.ref.id ?? "", s.ref.label ?? ""]));
  return (id: string) => map.get(id) || undefined;
}

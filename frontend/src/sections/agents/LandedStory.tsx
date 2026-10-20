import { useMemo } from "react";
import { api } from "../../api/client";
import { useResource } from "../../api/useResource";
import type { ActionItem } from "../../api/types";
import { LandedCostTable } from "../../components/domain/LandedCostTable";
import { supplierShorts } from "../records/model";

/** The landed-cost table's story page (/dev/landed-cost): both variants on live data, for review before it is mounted in the case page's Analysis card. */
export function LandedStory() {
  const items = useResource(() => api.actionItems().catch(() => [] as ActionItem[]));
  const shorts = useMemo(() => supplierShorts(items.data ?? []), [items.data]);
  // The parts the cases name: the import-duty case's first two (duty variant), the supplier-risk cases' parts (quote variant).
  const parts = (pick: (i: ActionItem) => boolean, n: number) => [...new Set((items.data ?? []).filter(pick).flatMap((i) => (i.refs ?? []).filter((r) => r.type === "part").map((r) => r.id)))].slice(0, n);
  const duty = parts((i) => i.group === "tariff", 2), quote = parts((i) => i.key.startsWith("risk:"), 8);
  const shortOf = (id: string | null | undefined, name: string) => (id && shorts.get(id)) || name.split(" ")[0];
  return (
    <div className="ag">
      <div className="ag-title"><h1>Landed cost</h1><p>LandedCostTable · duty and quote variants · GET /parts/{"{part}"}/compare</p></div>
      {duty[0] && <section className="ag-sec"><div className="ag-h"><h2>Landed cost with the new duty · {duty[0]}</h2><span>duty variant</span></div><LandedCostTable part={duty[0]} variant="duty" shortOf={shortOf} also={duty.slice(1)} /></section>}
      {quote.map((p) => <section key={`q-${p}`} className="ag-sec"><div className="ag-h"><h2>Quote check · {p}</h2><span>quote variant</span></div><LandedCostTable part={p} variant="quote" shortOf={shortOf} /></section>)}
    </div>
  );
}

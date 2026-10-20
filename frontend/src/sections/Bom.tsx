import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { SegmentedControl } from "../ds";
import { ListBody, PartsTabs, RecordsHead } from "./records/lists";
import { ChevronDown, ChevronRight } from "lucide-react";
import { api } from "../api/client";
import { useResource } from "../api/useResource";
import { LoadError } from "../ds/LoadError";
import { invalidate } from "../api/useResource";
import type { BomTreeRow } from "../api/types";
import { EntityChip } from "../domain-ui/EntityChip";
import { Value } from "../domain-ui/Value";
import type { Value as V } from "../api/types";

const FLAGS: Record<string, string> = { obsolete_child: "obsolete part", orphan_child: "not in the item master", second_placement: "second placement", unit_mismatch: "unit converted", exact_duplicate_rows: "duplicate row dropped" };

/** A robot's indented bill of materials, in drawing order, with the defects marked and assemblies that fold. */
export function Bom() {
  const nav = useNavigate();
  const { id } = useParams();
  const products = useResource(api.products);
  const pid = id ?? products.data?.[0]?.part_number ?? "";
  const bom = useResource(() => (pid ? api.bom(pid) : Promise.resolve(null)), [pid]);
  const [shut, setShut] = useState<Set<number>>(new Set());
  const rows = bom.data?.rows ?? [];
  const visible = useMemo(() => {
    const out: { row: BomTreeRow; i: number }[] = [];
    let hide = Infinity;
    rows.forEach((row, i) => {
      const lvl = row.level ?? 0;
      if (lvl <= hide) hide = Infinity;
      if (lvl > hide) return;
      out.push({ row, i });
      if (shut.has(i)) hide = lvl;
    });
    return out;
  }, [rows, shut]);
  const toggle = (i: number) => setShut((s) => { const n = new Set(s); if (n.has(i)) n.delete(i); else n.add(i); return n; });
  return (
    <div className="rc rc-fixed">
      <RecordsHead on="parts" />
      <PartsTabs on="bom" />
      <div style={{ margin: "var(--s4) 0" }}>
        <SegmentedControl label="Robot" value={pid} onChange={(id) => nav(`/parts/bom/${id}`)} items={(products.data ?? []).map((p) => ({ id: p.part_number, label: p.name }))} />
      </div>
      <ListBody reset={pid}>
      {bom.loading && <span className="skel" style={{ width: 320 }} />}
      {bom.error && <LoadError what="the bill of materials" retry={invalidate} />}
      {rows.length > 0 && (
        <div className="tablewrap">
          <table className="bomt">
            <thead><tr><th>Find</th><th>Part</th><th className="num">Per parent</th><th className="num">Per robot</th><th /></tr></thead>
            <tbody>
              {visible.map(({ row, i }) => (
                <tr key={i} className={row.obsolete ? "obs" : ""}>
                  <td className="muted num">{row.find_no}</td>
                  <td className="cut">
                    <span className="tree" style={{ paddingLeft: ((row.level ?? 1) - 1) * 20 }}>
                      {row.is_assembly
                        ? <button type="button" className="fold-btn" aria-label={shut.has(i) ? "Open" : "Fold"} onClick={() => toggle(i)}>{shut.has(i) ? <ChevronRight size={14} strokeWidth={1.5} /> : <ChevronDown size={14} strokeWidth={1.5} />}</button>
                        : <span className="fold-btn" />}
                      <EntityChip r={row.part} />
                    </span>
                  </td>
                  <td className="num"><Value value={row.qty_per as V} tag={false} /></td>
                  <td className="num"><Value value={row.qty_per_robot as V} tag={false} /></td>
                  <td>{[...(row.defects ?? [])].map((d) => <span key={d} className="badge s-pending flag">{FLAGS[d] ?? d}</span>)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      </ListBody>
    </div>
  );
}

import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown, Search, SlidersHorizontal, X } from "lucide-react";
import { useFits } from "./useFits";

export type FilterOption = { value: string; label: string; count?: number };
export type FilterDef = { id: string; label: string; options: FilterOption[] };
/** The chosen value of each filter; a filter with no entry is off. */
export type FilterValue = Record<string, string | undefined>;

/** One row above a list: a search box and a chip per filter (Owner, Kind, Act by…). A chip opens a menu of its options; once chosen it reads "Owner: Ana" with a clear button.
 * When the chips do not fit beside the search box, they fold into one Filters button, so the bar stays one row at any width. Used by every list. */
export function FilterBar({ label, search, onSearch, placeholder = "Search this list", filters, value, onChange }: {
  label: string; search?: string; onSearch?: (q: string) => void; placeholder?: string;
  filters: FilterDef[]; value: FilterValue; onChange: (v: FilterValue) => void;
}) {
  const [openId, setOpenId] = useState<string | null>(null);
  const [at, setAt] = useState<HTMLElement | null>(null);
  const root = useRef<HTMLDivElement | null>(null);
  const menu = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!openId) return;
    const inside = (t: EventTarget | null) => !!t && (root.current?.contains(t as Node) || menu.current?.contains(t as Node));
    const down = (e: PointerEvent) => { if (!inside(e.target)) setOpenId(null); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") setOpenId(null); };
    // The menu floats over the page: a scroll anywhere else (the list behind, the page) closes it rather than leaving it adrift.
    const scroll = (e: Event) => { if (!menu.current?.contains(e.target as Node)) setOpenId(null); };
    const resize = () => setOpenId(null);
    document.addEventListener("pointerdown", down); window.addEventListener("keydown", key);
    window.addEventListener("scroll", scroll, true); window.addEventListener("resize", resize);
    return () => { document.removeEventListener("pointerdown", down); window.removeEventListener("keydown", key); window.removeEventListener("scroll", scroll, true); window.removeEventListener("resize", resize); };
  }, [openId]);
  const set = (id: string, v: string | undefined) => onChange({ ...value, [id]: v });
  const active = filters.filter((f) => value[f.id]).length + (search ? 1 : 0);
  const { box, full, fits } = useFits(onSearch ? 160 : 0);
  const chosenCount = filters.filter((f) => value[f.id]).length;
  return (
    <div className="fb" role="group" aria-label={`Filter ${label}`} ref={(el) => { root.current = el; box.current = el; }}>
      {onSearch && (
        <label className="fb-search">
          <Search size={16} strokeWidth={1.5} aria-hidden />
          <input aria-label={`Search ${label}`} placeholder={placeholder} value={search ?? ""} onChange={(e) => onSearch(e.target.value)} />
        </label>
      )}
      <div ref={full} className={`fb-chips${fits ? "" : " ds-ghost"}`} aria-hidden={fits ? undefined : true} {...(fits ? {} : { inert: "" as unknown as boolean })}>
      {filters.map((f) => {
        const chosen = f.options.find((o) => o.value === value[f.id]);
        return (
          <div key={f.id} className="fb-chip-wrap">
            <button type="button" className={`fb-chip${chosen ? " on" : ""}`} aria-haspopup="menu" aria-expanded={openId === f.id} onClick={(e) => { setAt(e.currentTarget); setOpenId(openId === f.id ? null : f.id); }}>
              <span>{chosen ? `${f.label}: ${chosen.label}` : f.label}</span><ChevronDown size={14} strokeWidth={1.5} aria-hidden />
            </button>
            {chosen && <button type="button" className="fb-clear" aria-label={`Clear ${f.label}`} onClick={() => set(f.id, undefined)}><X size={14} strokeWidth={1.5} aria-hidden /></button>}
            {openId === f.id && (
              <Floating menuRef={menu} at={at} align="start" label={f.label}>
                <Options f={f} value={value} pick={(v) => { set(f.id, v); setOpenId(null); }} />
              </Floating>
            )}
          </div>
        );
      })}
      {active > 0 && <button type="button" className="fb-reset" onClick={() => { onChange({}); onSearch?.(""); }}>Clear all</button>}
      </div>
      {!fits && filters.length > 0 && (
        <div className="fb-chip-wrap">
          <button type="button" className={`fb-chip${chosenCount ? " on-n" : ""}`} aria-haspopup="menu" aria-expanded={openId === "*"} aria-label={`Filters${chosenCount ? `, ${chosenCount} on` : ""}`} onClick={(e) => { setAt(e.currentTarget); setOpenId(openId === "*" ? null : "*"); }}>
            <SlidersHorizontal size={14} strokeWidth={1.5} aria-hidden />{chosenCount > 0 && <em>{chosenCount}</em>}
          </button>
          {openId === "*" && (
            <Floating menuRef={menu} at={at} align="end" label={`Filter ${label}`}>
              {filters.map((f) => (
                <div key={f.id} className="fb-group" role="group" aria-label={f.label}>
                  <div className="fb-group-h">{f.label}</div>
                  <Options f={f} value={value} pick={(v) => set(f.id, v)} />
                </div>
              ))}
              {active > 0 && <button type="button" className="fb-menu-reset" onClick={() => { onChange({}); onSearch?.(""); setOpenId(null); }}>Clear all</button>}
            </Floating>
          )}
        </div>
      )}
    </div>
  );
}

/** A menu that floats over the page, never inside a list's scroll: fixed to the bar's edge, its own scroll, one line per option. */
function Floating({ menuRef, at, align, label, children }: { menuRef: React.MutableRefObject<HTMLDivElement | null>; at: HTMLElement | null; align: "start" | "end"; label: string; children: ReactNode }) {
  const [pos, setPos] = useState<{ top: number; left?: number; right?: number } | null>(null);
  useLayoutEffect(() => {
    if (!at) return;
    const r = at.getBoundingClientRect();
    setPos(align === "end" ? { top: r.bottom + 4, right: Math.max(window.innerWidth - r.right, 8) } : { top: r.bottom + 4, left: Math.min(r.left, window.innerWidth - 308) });
  }, [at, align]);
  return createPortal(
    <div ref={menuRef} className="fb-menu fb-float" role="menu" aria-label={label} style={pos ? { top: pos.top, left: pos.left ?? "auto", right: pos.right ?? "auto" } : { visibility: "hidden" }}>{children}</div>,
    document.body,
  );
}

/** A filter's options; a long list shows the six with the most rows first, the rest one click away. */
function Options({ f, value, pick }: { f: FilterDef; value: FilterValue; pick: (v: string | undefined) => void }) {
  const [all, setAll] = useState(false);
  const many = f.options.length > 6 && f.options.every((o) => o.count != null);
  const top = many && !all ? [...f.options].sort((a, b) => (b.count ?? 0) - (a.count ?? 0)).slice(0, 6) : f.options;
  const chosen = f.options.find((o) => o.value === value[f.id]);
  const shown = chosen && !top.includes(chosen) ? [chosen, ...top] : top;
  return (
    <>
      {shown.map((o) => (
        <button key={o.value} type="button" role="menuitemradio" title={o.label} aria-checked={o.value === value[f.id]} onClick={() => pick(o.value === value[f.id] ? undefined : o.value)}>
          {o.value === value[f.id] ? <Check size={16} strokeWidth={1.5} aria-hidden /> : <i aria-hidden />}<span>{o.label}</span>{o.count != null && <small>{o.count}</small>}
        </button>
      ))}
      {many && !all && <button type="button" className="fb-more" onClick={() => setAll(true)}><i aria-hidden /><span>Show all {f.options.length}</span></button>}
    </>
  );
}

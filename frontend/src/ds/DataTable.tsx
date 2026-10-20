import { Fragment, type CSSProperties, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { StateDot, type State } from "./index";

/** One column of a DataTable. `hide` drops it on a narrower screen ("mid" under 1440 px, "narrow" under 1200 px: what the full template needs beside the sidebar) so the others keep their widths; `label` prefixes the cell on a phone, where a row becomes a title and a line of facts. */
export type Col<T> = { id: string; head: ReactNode; width: string; end?: boolean; hide?: "mid" | "narrow"; label?: string; phone?: "hide"; cell: (x: T) => ReactNode };

type Props<T> = {
  cols: Col<T>[]; rows: T[]; rowKey: (x: T) => string;
  to?: (x: T) => string; onClick?: (x: T) => void; active?: (x: T) => boolean; onHover?: (x: T) => void;
  state?: (x: T) => State | undefined; expand?: (x: T) => ReactNode;
  /** show the column headers (a page with several groups shows them once) */
  header?: boolean; two?: boolean; label: string;
  /** a small control at the end of a row, shown when the row is pointed at or focused (Ask in place) */
  rowAction?: (x: T) => ReactNode;
};

/** Widths are fixed except the first column, the title, which takes what is left up to 720 px; the table itself stops at 1440 px, so a wide screen is not a line of words with its numbers far away. */
const track = (w: string, first: boolean) => (first ? w.replace(/,1fr\)$/, ",720px)") : w);
const tpl = (cols: { width: string }[], dot: boolean) => `${dot ? "24px " : ""}${cols.map((c, n) => track(c.width, n === 0)).join(" ")}`;

/** The one table: a shared column template, a 56 px row (64 px with a second line), numbers right-aligned, long text cut with a tooltip in the first cell only. */
export function DataTable<T>({ cols, rows, rowKey, to, onClick, active, onHover, state, expand, header = true, two = false, label, rowAction }: Props<T>) {
  const dot = !!state;
  const style = {
    "--cols": tpl(cols, dot),
    "--cols-mid": tpl(cols.filter((c) => c.hide !== "mid"), dot),
    "--cols-narrow": tpl(cols.filter((c) => !c.hide), dot),
  } as CSSProperties;
  const cells = (x: T) => (
    <>
      {dot && <span className="dt-c dt-dot" role="cell"><StateDot state={state!(x) ?? "low"} /></span>}
      {cols.map((c, n) => <span key={c.id} role="cell" className={`dt-c${n === 0 ? " dt-main" : ""}${c.end ? " end" : ""}`} data-hide={c.hide} data-phone={c.phone} data-label={c.label}>{c.cell(x)}</span>)}
    </>
  );
  return (
    <div className={`dt${two ? " two" : ""}${rowAction ? " has-act" : ""}`} role="table" aria-label={label} style={style}>
      {header && (
        <div className="dt-head" role="row">
          {dot && <span role="presentation" />}
          {cols.map((c) => <span key={c.id} role="columnheader" className={c.end ? "end" : undefined} data-hide={c.hide} data-phone="hide">{c.head}</span>)}
        </div>
      )}
      {rows.map((x) => {
        const cls = `dt-row${active?.(x) ? " active" : ""}`;
        const on = onHover ? () => onHover(x) : undefined;
        return (
          <Fragment key={rowKey(x)}>
            <div className={rowAction ? "dt-rw" : "dt-rw plain"}>
            {to ? <Link role="row" className={cls} to={to(x)} onMouseEnter={on}>{cells(x)}</Link>
              : onClick ? <button type="button" role="row" className={cls} onClick={() => onClick(x)} onMouseEnter={on}>{cells(x)}</button>
              : <div role="row" className={cls}>{cells(x)}</div>}
            {rowAction && <div className="dt-ra">{rowAction(x)}</div>}
            </div>
            {expand?.(x)}
          </Fragment>
        );
      })}
    </div>
  );
}

/** A title with a quieter line under it: the first cell of most tables. The full text is the tooltip. */
export function TitleCell({ title, sub, tip }: { title: ReactNode; sub?: ReactNode; tip?: string }) {
  return <span className="dt-title" title={tip}><b>{title}</b>{sub ? <small>{sub}</small> : null}</span>;
}

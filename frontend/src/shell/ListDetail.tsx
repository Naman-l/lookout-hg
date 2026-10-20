import type { ReactNode } from "react";

/** A list on the left and the open thing on the right at a desktop; on a phone one or the other (the list until something is open, then that thing with a way back). */
export function ListDetail({ list, detail, open }: { list: ReactNode; detail: ReactNode; open: boolean }) {
  return (
    <div className={`ld${open ? " is-open" : ""}`}>
      <div className="ld-list">{list}</div>
      <div className="ld-detail">{detail}</div>
    </div>
  );
}

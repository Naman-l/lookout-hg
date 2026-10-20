import type { ReactNode } from "react";

/** A quiet expander, closed by default: the evidence is one click away, never in the way. */
export function Expander({ title, hint, children, open }: { title: string; hint?: ReactNode; children: ReactNode; open?: boolean }) {
  return (
    <details className="x" open={open}>
      <summary>{title}{hint !== undefined && <span className="h">{hint}</span>}</summary>
      <div className="body">{children}</div>
    </details>
  );
}

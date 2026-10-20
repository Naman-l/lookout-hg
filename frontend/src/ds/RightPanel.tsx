import type { ReactNode } from "react";

/** The one right panel (F104, FINAL 07 §7): an outlined frame, sticky, its own scroll; sections with hairlines between them,
 * 12/600 titles, nothing folds. Content stays per screen. `wide` is the Ask panel's 400 px; below 1100 px it sits under the main column. */
export function RightPanel({ label, wide, className, children }: { label: string; wide?: boolean; className?: string; children: ReactNode }) {
  return <aside className={`ds-rp${wide ? " wide" : ""}${className ? ` ${className}` : ""}`} aria-label={label}>{children}</aside>;
}

/** One section: a title (and an optional summary on the right), then its body. An empty section is not drawn. */
function Section({ title, summary, className, children }: { title?: ReactNode; summary?: ReactNode; className?: string; children?: ReactNode }) {
  if (!children) return null;
  return (
    <section className={`ds-rps${className ? ` ${className}` : ""}`}>
      {title && <div className="ds-rph"><h4>{title}</h4>{summary && <span>{summary}</span>}</div>}
      {children}
    </section>
  );
}
RightPanel.Section = Section;

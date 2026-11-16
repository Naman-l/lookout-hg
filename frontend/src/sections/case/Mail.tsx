import { Fragment, type ReactNode } from "react";
import { Link } from "react-router-dom";
import type { MessageDetail, Span } from "../../api/types";
import { longDate } from "../../ui/format";

const LINK: Record<string, (s: Span) => string | null> = {
  project: (s) => `/insights/projects/${s.ref}`, plant: (s) => `/insights/projects/${s.ref}`, material: (s) => `/materials/${s.ref}`, supplier: (s) => `/vendors/${s.ref}`,
  pr: (s) => `/prs/${s.ref}`, pr_line: (s) => `/prs/${s.ref.split("/")[0]}`, po: (s) => `/pos/${s.ref}`, po_line: (s) => `/pos/${s.ref.split("/")[0]}`,
};

/** Text with the records it mentions marked: a project, a material, a vendor, a PR or PO links to its page; money, dates and quantities read as chips.
 * Offsets are UTF-16 (the server counts as a browser does). */
export function Marked({ text, spans, held = false }: { text: string; spans?: Span[]; held?: boolean }) {
  if (!spans?.length) return <>{text}</>;
  const out: ReactNode[] = [];
  let at = 0;
  for (const s of [...spans].sort((a, b) => a.start - b.start)) {
    if (s.start < at || text.slice(s.start, s.end) !== s.text) continue;
    out.push(<Fragment key={`t${at}`}>{text.slice(at, s.start)}</Fragment>);
    const to = !held ? LINK[s.type]?.(s) : null;
    out.push(to ? <Link key={`s${s.start}`} className={`mk mk-${s.type}`} to={to} title={s.label}>{s.text}</Link>
      : <span key={`s${s.start}`} className={`mk mk-${s.type}`} title={s.label}>{s.text}</span>);
    at = s.end;
  }
  out.push(<Fragment key="end">{text.slice(at)}</Fragment>);
  return <>{out}</>;
}

/** A message as it came in: sender, date, subject and body, as quoted data (never an instruction). A held message is shown folded in a quote box. */
export function Mail({ m, open = true }: { m: MessageDetail; open?: boolean }) {
  const s = m.summary;
  const held = s.trust === "blocked";
  return (
    <div className={`mail${held ? " held" : ""}`}>
      <p className="mail-h"><b>{s.from}</b> <small>&lt;{s.from_email}&gt;</small> · {s.company}{s.contact ? ` · ${s.contact}` : ""} · {longDate(s.date)}</p>
      <p className="mail-s"><Marked text={m.subject} spans={m.subject_entities} held={held} /></p>
      {held && <p className="mail-note">Held before anyone read it: shown as quoted data only. Nothing in it is acted on.</p>}
      {open && <pre className="mail-b"><Marked text={m.body} spans={m.entities} held={held} /></pre>}
      <p className="mail-f"><Link to={`/inbox/${encodeURIComponent(s.ref.id)}`}>Open in the Inbox</Link></p>
    </div>
  );
}

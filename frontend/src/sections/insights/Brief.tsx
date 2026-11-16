// The Daily brief (MAPPING 10.5): the email a member would get each morning, rendered as it would read in Outlook. Lookout never sends it.
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMe } from "../../api/useMe";
import { Notice } from "../../ds";
import { useAskContext } from "../../shell/AskContext";
import { longDate } from "../../ui/format";
import { insights, type Brief as BriefT } from "./api";
import { Frame } from "./Frame";
import { ReadFailed, refPath, useReadError } from "./ui";

const WEEKDAY = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const dayName = (iso: string) => WEEKDAY[new Date(`${iso}T00:00:00Z`).getUTCDay()];

/** /brief/:person */
export function Brief() {
  const { person = "" } = useParams();
  const { people } = useMe();
  const nav = useNavigate();
  const r = useReadError(() => insights.brief(person), [person]);
  const d = r.data;
  useAskContext(d ? { type: "person", id: d.person, label: `${d.name}'s daily brief` } : null);
  return (
    <Frame back={d ? { to: `/insights/team/${encodeURIComponent(d.person)}`, label: d.name } : { to: "/insights/team", label: "Team" }} title="Daily brief"
      meta={d ? <><span>{d.name}</span><span className="sep">·</span><span>{d.role}</span><span className="sep">·</span><span>as of {longDate(d.date)}</span></> : undefined}
      actions={people.length > 0 ? (
        <label className="ins-pick"><span className="ins-sr">Brief for</span>
          <select value={d?.name ?? ""} onChange={(e) => nav(`/brief/${encodeURIComponent(e.target.value)}`)} aria-label="Brief for">
            {!d && <option value="">Choose…</option>}
            {people.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}
          </select>
        </label>) : undefined}>
      {r.loading ? <div className="ins-sk" aria-busy="true" aria-label="Loading the brief"><i /><i /><i /><i /></div>
        : r.error || !d ? <ReadFailed e={r.error!} what="the brief" notFound={{ title: "No such member", line: `Nobody called “${person}” is on the SCM team.` }} />
        : (
          <div className="ins-body">
            <Notice>Lookout does not send this; it is how the morning email would read.</Notice>
            <Mail d={d} />
          </div>
        )}
    </Frame>
  );
}

function Mail({ d }: { d: BriefT }) {
  return (
    <article className="ins-mail" aria-label={`Email: ${d.subject}`}>
      <header className="ins-mail-h">
        <h2>{d.subject}</h2>
        <dl>
          <div><dt>From</dt><dd>{d.sender}</dd></div>
          <div><dt>To</dt><dd>{d.to}</dd></div>
          <div><dt>Date</dt><dd>{dayName(d.date)}, {longDate(d.date)}</dd></div>
        </dl>
      </header>
      <div className="ins-mail-b">
        <p>{d.greeting}</p>
        <p>{d.intro}</p>
        {d.sections.map((s) => (
          <section key={s.key} className="ins-mail-s">
            <h3>{s.title}{s.lines.length > 0 && <small> · {s.lines.length + s.more - (s.key === "others" && s.lines.some((l) => !l.ref) ? 1 : 0)}</small>}</h3>
            {s.lines.length === 0 ? <p className="ins-mail-none">{s.empty}</p> : (
              <ul>
                {s.lines.map((l, i) => {
                  const to = l.ref ? refPath(l.ref) : null;
                  return (
                    <li key={`${l.ref ?? ""}:${i}`} className={l.ref ? undefined : "sum"}>
                      <span>{to ? <Link to={to}>{l.text}</Link> : l.text}</span>
                      {l.figure && <b>{l.figure}</b>}
                    </li>
                  );
                })}
              </ul>
            )}
            {s.more > 0 && <p className="ins-mail-more">and {s.more} more on <Link to={`/insights/team/${encodeURIComponent(d.person)}`}>{d.name.split(" ")[0]}'s Team page</Link></p>}
          </section>
        ))}
        <p className="ins-mail-sig">— {d.sign_off}</p>
        <p className="ins-mail-foot">Every line is computed from the SAP exports, the trackers and the shared inbox as of {longDate(d.date)}. Nothing in this brief was sent.</p>
      </div>
    </article>
  );
}

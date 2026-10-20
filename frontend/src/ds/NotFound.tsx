import { Link, useNavigate } from "react-router-dom";

/** One not-found page for every record (DATA-13): a plain title, one line naming what was asked for, Back and Today, and a pointer to search. No red: nothing broke. */
export function NotFound({ title, line }: { title: string; line: string }) {
  const nav = useNavigate();
  const back = () => (window.history.length > 1 ? nav(-1) : nav("/"));
  return (
    <section className="ds-nf" aria-labelledby="ds-nf-h">
      <h1 id="ds-nf-h">{title}</h1>
      <p>{line}</p>
      <div className="ds-nf-a"><button type="button" className="ds-btn outline" onClick={back}>Back</button><Link to="/">Today</Link></div>
      <small>Or search with ⌘K.</small>
    </section>
  );
}

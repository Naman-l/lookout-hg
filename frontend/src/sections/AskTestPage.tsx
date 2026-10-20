import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useResource, invalidate } from "../api/useResource";
import type { Action } from "../api/types";
import { CaseAskPanel } from "./CaseAsk";
import { AskForChanges } from "./AskForChanges";
import "./case-page.css";

/** The test page for the case Ask panel (/dev/ask/<case key>): the case's drafts on the left (what its Approval card lists), the panel on the right.
 * It proves a turn that prepares something lands on the case, before BUILD-13 mounts the panel on the case page. */
export function AskTestPage() {
  const key = decodeURIComponent(useParams().id ?? "");
  const item = useResource(() => api.item(key), [key]);
  const [tick, setTick] = useState(0);
  const drafts = useResource(() => api.actionsFor(key).then((a) => a.filter((x) => x.item_key === key)).catch(() => [] as Action[]), [key, tick]);
  const [open, setOpen] = useState(true);
  const [seed, setSeed] = useState<string | undefined>();
  const [hl, setHl] = useState<string | null>(null);
  useEffect(() => { const t = setInterval(() => setTick((n) => n + 1), 4000); return () => clearInterval(t); }, []);
  const i = item.data;
  if (!i) return <p style={{ padding: 24 }}>{item.error ? "No such case." : "Loading…"}</p>;
  return (
    <div className="cp">
      <header className="cp-head"><div className="cp-crumb"><Link to={`/items/${encodeURIComponent(key)}`}>Case</Link> › Ask test</div><h1>{i.title}</h1></header>
      <div className="cp-cols" style={{ gridTemplateColumns: open ? "minmax(0,1fr) 400px" : undefined }}>
        <div className="cp-stack">
          <section className="cp-card" id="step-Approval" aria-label="Approval">
            <div className="cp-ch"><div><b>Approval</b><span className="kp">Drafts filed under this case</span></div>
              <button type="button" className="cp-link" onClick={() => { invalidate(); setTick((n) => n + 1); }}>Refresh</button></div>
            {(drafts.data ?? []).length === 0 ? <p className="cp-none">Nothing drafted for this case.</p> : (
              <table className="cp-t"><thead><tr><th>Draft</th><th>To</th><th>State</th><th>From</th></tr></thead>
                <tbody>{drafts.data!.map((a) => <tr key={a.action_id} style={hl === a.action_id ? { background: "var(--raised)" } : undefined}><td><Link to={`/approvals/${a.action_id}`}>{a.title ?? a.subject ?? a.action_id}</Link></td><td style={{ wordBreak: "break-all" }}>{a.recipient ?? "—"}</td><td>{a.state}</td><td>{a.run_id ?? "—"}</td></tr>)}</tbody></table>
            )}
            {(drafts.data ?? []).filter((a) => a.state === "proposed").sort((x, y) => x.action_id.localeCompare(y.action_id)).slice(0, 1).map((a) => <AskForChanges key={a.action_id} action={a} onAmended={() => { invalidate(); setTick((n) => n + 1); }} />)}
            <div className="cp-foot"><button type="button" className="b9" onClick={() => { setSeed(`Another way through for ${i.title.split(":")[0]}…`); setOpen(true); }}>Ask for another option</button>
              {!open && <button type="button" className="b9 dark" onClick={() => setOpen(true)}>Ask Lookout</button>}</div>
          </section>
        </div>
        {open && <CaseAskPanel caseKey={key} title={i.title.split(":")[0]} about="Decision" seed={seed} onClose={() => setOpen(false)}
          onReview={(id) => { setHl(id); invalidate(); setTick((n) => n + 1); document.getElementById("step-Approval")?.scrollIntoView({ behavior: "smooth" }); }} />}
      </div>
    </div>
  );
}

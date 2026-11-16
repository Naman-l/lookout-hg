import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { useResource } from "../../api/useResource";
import { NotFound } from "../../ds";
import "./agents.css";

const STEPS: [string, string][] = [
  ["Find", "Detectors in code read the records (SAP exports, the sheets, the trackers, the mail) and raise one case per cause, with its ₹ at stake and the rule behind it, its act-by date, its owners and whose move it is."],
  ["Lay out", "Each kind of case has a code table of routes: what each changes, the earliest help, the cost, who it goes to. Figures are the records'."],
  ["Work", "A run reads the case with the specialists its kind needs, every figure cited by the id of the lookup it came from, and recommends one route (advice). The verifier and the Reviewer check it."],
  ["Choose", "The owner chooses a route. The Buyer's clerk's draft follows: a letter to the vendor's contact on file, or a note to the person on file who owns the function."],
  ["Sign", "The owner signs the exact text (by its hash). Above the delegation-of-authority threshold the Head of SCM countersigns the same text before anything goes out."],
  ["Send and hear back", "Sent (simulated) to the contact on file; the case waits on the vendor or the function until they answer. A reply's changes become an entry to make in SAP, for signature."],
];
const GUARDS = [
  "A held message (a look-alike sender, a free-mail reply-to, a change of bank details, text aimed at software) is never read by a run and nothing is drafted from it.",
  "A draft goes only to a contact on file, never to an address read from a message; no draft mentions bank details.",
  "Only the owner signs; a stale or second approval is refused; a draft that commits money above the DoA threshold waits for the countersign.",
  "Every figure a run states is a figure a lookup returned, checked by the verifier; what the records cannot say is an open question with an owner.",
];

/** Under the hood: how Lookout works for the SCM team, who its specialists are, and how runs are made on this machine. */
export function UnderTheHood() {
  const a = useResource(api.agents);
  const runs = useResource(api.runs);
  if (a.error) return <NotFound title="Under the hood" line="The agent layer is not running on this server." />;
  const recorded = (runs.data ?? []).filter((r) => r.recorded);
  return (
    <div className="uth">
      <h1>Under the hood</h1>
      <p className="uth-mode">{a.data?.mode}</p>
      <h2>How a case is worked</h2>
      <ol className="uth-steps">{STEPS.map(([h, t]) => <li key={h}><b>{h}</b><span>{t}</span></li>)}</ol>
      <h2>The specialists</h2>
      <table className="cp-t"><thead><tr><th>Specialist</th><th>What it does</th><th>Its tools</th><th className="n">Runs</th></tr></thead>
        <tbody>{(a.data?.agents ?? []).map((x) => <tr key={x.name}><td><b>{x.label}</b></td><td>{x.does}</td><td><small>{x.tools.join(", ")}</small></td><td className="n">{x.runs}</td></tr>)}</tbody></table>
      <h2>Who works each kind of case</h2>
      <table className="cp-t"><tbody>{Object.entries((a.data as unknown as { plans?: Record<string, string[]> })?.plans ?? {}).map(([k, v]) => <tr key={k}><td>{k}</td><td>{v.length ? v.join(" → ") : "nobody: a held message is never worked"}</td></tr>)}</tbody></table>
      <h2>Guardrails, in code</h2>
      <ul className="uth-g">{GUARDS.map((g) => <li key={g}>{g}</li>)}</ul>
      <h2>Recordings</h2>
      <p className="uth-mode">{a.data?.recordings ?? 0} mocked recordings (written by hand to show how a model's run reads; no model ran) are replayed on their cases; every other run is drafted by code. {recorded.length > 0 && <>Latest replays: {recorded.slice(0, 2).map((r) => <Link key={r.run_id} to={`/activity/${r.run_id}`}>{r.item_key}</Link>).reduce((x, y) => <>{x}, {y}</>)}.</>}</p>
      <p><Link to="/activity">Agent activity ›</Link></p>
    </div>
  );
}

import { useState } from "react";
import { Button } from "../ds";
import { useMe } from "../api/useMe";

/** First open, or "change": who is using Lookout. The choice signs approvals and starts Today on your own items. */
export function WhoAreYou({ onClose }: { onClose?: () => void }) {
  const { me, setMe, people } = useMe();
  const [pick, setPick] = useState<string | null>(me);
  const go = () => { if (pick) { setMe(pick); onClose?.(); } };
  return (
    <>
      <div className="dim" onClick={onClose} aria-hidden />
      <div className="whoami" role="dialog" aria-modal="true" aria-label="Who are you?">
        <h2>Who are you?</h2>
        <p className="muted">Lookout shows your items first and signs approvals in your name. It remembers this on this computer; there is no sign-in.</p>
        <div className="people" role="radiogroup" aria-label="Buyers">
          {people.map((p) => (
            <button key={p.name} type="button" role="radio" aria-checked={pick === p.name} className={`pcard${pick === p.name ? " sel" : ""}`} onClick={() => setPick(p.name)}>
              <span className="av l">{p.initials}</span><b>{p.name}</b>{p.note && <span className="s">{p.note}</span>}
            </button>
          ))}
        </div>
        <p className="muted sm">The names come from the team table in the data.</p>
        <div className="ds-act">
          <div className="what"><b>{pick ? `Continue as ${pick}` : "Choose who you are"}</b><small>change any time from the top bar</small></div>
          <Button variant="primary" disabled={!pick} onClick={go}>Continue</Button>
        </div>
      </div>
    </>
  );
}

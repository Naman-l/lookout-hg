import { Link, useLocation, useNavigate } from "react-router-dom";
import { ChevronLeft, Search } from "lucide-react";
import { initials } from "../api/useMe";
import { shortDate } from "../ui/format";

const ICON = { size: 22, strokeWidth: 1.5 } as const;

const TITLES: [RegExp, string][] = [
  [/^\/$/, "Today"], [/^\/items\//, "Case"], [/^\/approvals/, "Approvals"], [/^\/inbox\/[^/]+/, "Message"], [/^\/inbox/, "Inbox"],
  [/^\/data\/import/, "Import"], [/^\/data\/?$/, "Data"], [/^\/vendors\/[^/]+/, "Vendor"], [/^\/materials\/[^/]+/, "Material"], [/^\/prs\/[^/]+/, "PR"], [/^\/pos\/[^/]+/, "PO"],
  [/^\/(vendors|materials|prs|pos|requirements|workfronts)/, "Records"], [/^\/insights\/team/, "Team"], [/^\/insights\/projects/, "Projects"], [/^\/insights\/pricing/, "Pricing"],
  [/^\/insights\/estimates/, "Estimates"], [/^\/brief/, "Daily brief"], [/^\/lookup/, "Material lookup"],
  [/^\/activity\//, "How we got here"], [/^\/activity/, "Agent activity"], [/^\/more/, "More"], [/^\/hood/, "Under the hood"],
];
const TOP = /^\/(approvals|inbox|vendors|materials|prs|pos|requirements|workfronts|data|activity|more|lookup|hood|insights\/(team|projects|pricing|estimates))?\/?$/;
/** A main place (not a page below one): its own name is already in the header, so the page does not repeat it. */
export const isPlace = (path: string) => TOP.test(path);

/** The phone's header: one 52 px row. A back arrow on a page below a main place, else the place's name; icon buttons on the right (ask or find, you); the data date, as a tiny tag, on Today only. */
export function PhoneBar({ me, asOf, onAsk, onMe }: { me: string | null; asOf?: string; onAsk: () => void; onMe: () => void }) {
  const here = useLocation().pathname;
  const nav = useNavigate();
  const title = TITLES.find(([re]) => re.test(here))?.[1] ?? "Lookout";
  const deep = !TOP.test(here);
  return (
    <div className="pbar" role="banner">
      {deep && <button type="button" className="pb-icon" aria-label="Back" onClick={() => nav(-1)}><ChevronLeft {...ICON} aria-hidden /></button>}
      <h1 className="pb-title">{title}</h1>
      {here === "/" && asOf && <Link className="pb-asof" to="/data">data {shortDate(asOf)}</Link>}
      <span className="pb-actions">
        <button type="button" className="pb-icon" aria-label="Ask Lookout or find a record" onClick={onAsk}><Search {...ICON} aria-hidden /></button>
        {me && <button type="button" className="pb-icon" aria-label={`You are ${me}. Change`} onClick={onMe}><span className="av">{initials(me)}</span></button>}
      </span>
    </div>
  );
}

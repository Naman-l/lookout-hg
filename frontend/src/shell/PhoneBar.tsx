import { Link, useLocation, useNavigate } from "react-router-dom";
import { ChevronLeft, Search } from "lucide-react";
import { initials } from "../api/useMe";
import { shortDate } from "../ui/format";

const ICON = { size: 22, strokeWidth: 1.5 } as const;

const TITLES: [RegExp, string][] = [
  [/^\/$/, "Today"], [/^\/items\//, "Item"], [/^\/approvals/, "Approvals"], [/^\/inbox\/[^/]+/, "Message"], [/^\/inbox/, "Inbox"],
  [/^\/data\/import/, "Import"], [/^\/data\/?$/, "Data"], [/^\/parts\/[^/]+/, "Part"], [/^\/suppliers\/[^/]+/, "Supplier"], [/^\/(orders|forecast|data)\/[^/]+/, "Details"], [/^\/(suppliers|parts|orders|forecast|data)/, "Records"],
  [/^\/activity\//, "How we got here"], [/^\/activity/, "Agent activity"], [/^\/more/, "More"], [/^\/shelf/, "Shelf"], [/^\/design/, "Design"],
];
const TOP = /^\/(approvals|inbox|suppliers|parts|orders|forecast|data|activity|more|shelf|design)?\/?$/;
/** A main place (not a page below one): its own name is already in the header, so the page does not repeat it. */
export const isPlace = (path: string) => TOP.test(path);

/** The phone's header: one 52 px row. A back arrow on a page below a main place, else the place's name; icon buttons on the right (search or ask, you); the data date, as a tiny tag, on Today only. */
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
        <button type="button" className="pb-icon" aria-label="Search" onClick={onAsk}><Search {...ICON} aria-hidden /></button>
        {me && <button type="button" className="pb-icon" aria-label={`You are ${me}. Change`} onClick={onMe}><span className="av">{initials(me)}</span></button>}
      </span>
    </div>
  );
}

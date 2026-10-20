import { useRef } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { Building2, CheckCircle2, Ellipsis, Inbox, List, MessageCircle } from "lucide-react";
import { api } from "../api/client";
import { useResource } from "../api/useResource";
import { useTableLabels } from "../ui/useTableLabels";
import { clockTime, useFreshness } from "../api/freshness";
import { longDate, shortDate } from "../ui/format";
import { useMedia } from "../ui/useMedia";
import { AskComposer } from "./AskBox";
import { SearchBar } from "./SearchBar";
import { AskPanel } from "./AskPanel";
import { AskProvider, useAskState } from "./AskContext";
import { useMe, initials } from "../api/useMe";
import { useCompany } from "../api/useCompany";
import { WhoAreYou } from "./WhoAreYou";
import { PhoneBar, isPlace } from "./PhoneBar";
import { SideNav, TabBar, type NavDef } from "../ds";
import { chosenDraft, myChosenCases, myDraftCases, statusOf, yourMove } from "../components/domain/caseStatus";
import type { Action } from "../api/types";

const ICON = { size: 16, strokeWidth: 1.5 } as const;

/** The panel: Work (Today, Approvals, Inbox), this month's builds (one per robot), Records (Suppliers, Parts, Orders, Forecast); Data and Under the hood sit quietly at the foot. */
export function Shell() {
  return <AskProvider><Frame /></AskProvider>;
}

function Frame() {
  const { open: askOpen, setOpen: setAskOpen, context: askAbout } = useAskState();
  const askInSlot = askOpen && askAbout?.type === "item";      // on a case the panel takes the rail's slot: the shell keeps its two columns
  const phone = useMedia("(max-width: 760px)");
  const here = useLocation().pathname;
  const health = useResource(api.health);
  // The data date opens Data; its hover says when the data was rebuilt and what needs a person (FINAL 09 §4).
  const stamp = useResource(() => api.stamp().catch(() => null));
  const issues = useResource(() => api.dataIssues().catch(() => []));
  const asOfTip = stamp.data ? `Rebuilt ${new Date(stamp.data.built_at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false })} from the raw files\n${stamp.data.gate_checks - stamp.data.gate_failed} of ${stamp.data.gate_checks} load checks passed · ${(issues.data ?? []).filter((x) => x.handling === "flag" || x.handling === "leave").length} issues need a person` : undefined;
  const company = useCompany();
  const fresh = useFreshness();
  const { me, ready, choosing, choose } = useMe();
  const changing = choosing;
  const setChanging = (on: boolean) => choose(on);
  const mainRef = useRef<HTMLElement>(null);
  useTableLabels(() => mainRef.current);
  const mine = useResource(() => api.actionItems(me ?? undefined).catch(() => []), [me], true);
  // The panel is the buyer's map: the work (Today, Approvals, Inbox), then the records.
  const msgs = useResource(() => api.messages().catch(() => []), [here], true);
  // A number appears only where something needs this person: items waiting on them, drafts to sign, held messages, robots at risk.
  const acts = useResource(() => api.actions().catch(() => [] as Action[]), [here], true);
  const draftOwner = new Map((acts.data ?? []).map((a) => [a.action_id, (a as Action & { owner?: string | null }).owner ?? ""]));
  const myDrafts = myDraftCases(acts.data, me);
  const myChosen = myChosenCases(acts.data, me);
  const myMove = (mine.data ?? []).filter((i) => yourMove(i, statusOf(i, me, draftOwner, "", myDrafts, myChosen), me)).length;      // the same count as Today's Yours
  // Approvals: the chosen drafts this person signs (the same rule as the Approvals list); everyone's when no one is chosen.
  const toSignChosen = (acts.data ?? []).filter((a) => a.state === "proposed" && chosenDraft(a) && (!me || (a as Action & { owner?: string | null }).owner === me)).length;
  // Inbox: the same number as the Inbox's Yours tab (FINAL 04, one count rule): the messages whose owner is this person.
  const nInbox = me ? (msgs.data ?? []).filter((m) => (m.owner ?? "").split(" · ").includes(me)).length : 0;
  const side: NavDef[] = [
    { section: "Work", to: "/", label: "Today", icon: <List {...ICON} />, count: me && mine.data ? myMove || undefined : undefined, end: true, match: ["/", "/items"] },
    { to: "/approvals", label: "Approvals", icon: <CheckCircle2 {...ICON} />, count: toSignChosen || undefined },
    { to: "/inbox", label: "Inbox", icon: <Inbox {...ICON} />, count: nInbox || undefined },
    { section: "Records", to: "/suppliers", label: "Records", icon: <Building2 {...ICON} />, match: ["/suppliers", "/parts", "/orders", "/forecast"] },      // one entry (Khalid: compact); the pages carry the tab row
  ];
  const ask = () => setAskOpen(true);
  const tabs: NavDef[] = [
    { to: "/", label: "Today", icon: <List {...TAB} />, end: true },
    { to: "/approvals", label: "Approvals", icon: <CheckCircle2 {...TAB} />, count: toSignChosen || undefined, hot: true },
    { to: "/inbox", label: "Inbox", icon: <Inbox {...TAB} /> },
    { to: "/ask", label: "Ask", icon: <MessageCircle {...TAB} />, onClick: ask },
    { to: "/more", label: "More", icon: <Ellipsis {...TAB} /> },
  ];
  return (
    <div className={`app${askOpen && !askInSlot ? " ai-open" : ""}${askOpen && !here.startsWith("/items") ? " ai-over" : ""}`}>
      <aside className="side">
        <div className="brand">Lookout<small>{health.data ? company.full : "\u00a0"}</small></div>
        <SideNav items={side} />
        <div className="side-foot">
          <NavLink to="/data">Data</NavLink>
          <NavLink to="/hood">Under the hood</NavLink>
        </div>
      </aside>
      <main className="main" ref={mainRef} data-place={isPlace(here)} data-route={here.split("/")[1] || "today"}>
        {phone ? (
          <PhoneBar me={me} asOf={health.data?.as_of} onAsk={ask} onMe={() => setChanging(true)} />
        ) : null}
        <div className={phone ? "top phone-off" : "top"}>
          {me && <div className="me"><span className="av">{initials(me)}</span><span className="me-you">You are </span><b>{me}</b><span className="me-dot"> · </span><button type="button" className="linkbtn" onClick={() => setChanging(true)}>change</button></div>}
          <SearchBar />
          <div className="asof" title={fresh.at && !fresh.cached ? `Read from the server at ${clockTime(fresh.at)}` : undefined}>
            {health.data ? <Link className="asof-link" to="/data" title={asOfTip}><span className="asof-l">Data as of {longDate(health.data.as_of)}</span><span className="asof-s">Data {shortDate(health.data.as_of)}</span></Link> : <span className="skel" style={{ width: 96 }} />}
          </div>
          {fresh.cached && <div className="offline" role="status">Offline: showing what was last read{fresh.at ? ` at ${clockTime(fresh.at)}` : ""}. Approving needs a connection.</div>}
        </div>
        <div className="content"><Outlet /></div>
        {!askOpen && <AskComposer />}
        {ready && (!me || changing) && <WhoAreYou onClose={me ? () => setChanging(false) : undefined} />}
      </main>
      <AskPanel />
      <TabBar items={tabs} isOn={(to) => inAny(here, ROOTS[to] ?? [])} />
    </div>
  );
}

const TAB = { size: 22, strokeWidth: 1.5 } as const;
const ROOTS: Record<string, string[]> = { "/": ["/", "/items"], "/approvals": ["/approvals"], "/inbox": ["/inbox"], "/more": ["/more", "/shelf", "/suppliers", "/parts", "/orders", "/forecast", "/activity", "/data", "/design"] };
const inAny = (here: string, roots: string[]) => roots.some((r) => (r === "/" ? here === "/" : here === r || here.startsWith(r + "/")));

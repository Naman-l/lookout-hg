import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { BarChart3, Building2, CheckCircle2, ChevronDown, Ellipsis, Inbox, IndianRupee, List, MessageCircle, Network, Scale, UserRoundCog, Users } from "lucide-react";
import { api } from "../api/client";
import { useResource } from "../api/useResource";
import { useTableLabels } from "../ui/useTableLabels";
import { clockTime, useFreshness } from "../api/freshness";
import { longDate, shortDate } from "../ui/format";
import { useMedia } from "../ui/useMedia";
import { CommandBar } from "./CommandBar";
import { AskPanel } from "./AskPanel";
import { AskProvider, useAskState } from "./AskContext";
import { useMe, initials } from "../api/useMe";
import { useCompany } from "../api/useCompany";
import { WhoAreYou } from "./WhoAreYou";
import { PhoneBar, isPlace } from "./PhoneBar";
import { SideNav, TabBar, type NavDef } from "../ds";
import { yourMove } from "../components/domain/caseStatus";

const ICON = { size: 16, strokeWidth: 1.5 } as const;

/** The panel: Work (Today, Approvals, Inbox), Insights (Team, Projects, Pricing, Estimates), Records; Data and Under the hood sit quietly at the foot. */
export function Shell() {
  return <AskProvider><Frame /></AskProvider>;
}

function Frame() {
  const { open: askOpen, palette, setPalette } = useAskState();
  const phone = useMedia("(max-width: 760px)");
  const here = useLocation().pathname;
  const health = useResource(api.health);
  // The data date opens Data; its hover lists every source with its own export date, a stale one marked, and the load checks.
  const stamp = useResource(() => api.stamp().catch(() => null));
  const sources = health.data?.sources ?? [];
  const asOfTip = [
    ...sources.filter((x) => x.date).map((x) => `${x.title}: ${longDate(x.date)}${x.stale ? "  (stale)" : ""}`),
    stamp.data ? `Rebuilt ${new Date(stamp.data.built_at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false })} · ${stamp.data.gate_checks - stamp.data.gate_failed} of ${stamp.data.gate_checks} load checks passed` : "",
  ].filter(Boolean).join("\n");
  const stale = sources.filter((x) => x.stale).length;
  const company = useCompany();
  const fresh = useFreshness();
  const { me, ready, choosing, choose, people } = useMe();
  const setChanging = (on: boolean) => choose(on);
  const mainRef = useRef<HTMLElement>(null);
  useTableLabels(() => mainRef.current);
  const mine = useResource(() => (me ? api.actionItems(me).catch(() => []) : Promise.resolve([])), [me, here], true);
  const counts = useResource(() => api.counts(me).catch(() => null), [me, here], true);
  const msgs = useResource(() => (me ? api.messages({ owner: me }).catch(() => []) : Promise.resolve([])), [me, here], true);
  // A number appears only where something needs this person: cases that are their move, drafts to sign or countersign, their messages.
  const myMove = (mine.data ?? []).filter((i) => yourMove(i, me)).length;
  const toSign = (counts.data?.to_sign_mine ?? 0) + (counts.data?.countersign_mine ?? 0);
  const nInbox = (msgs.data ?? []).length;
  const side: NavDef[] = [
    { section: "Work", to: "/", label: "Today", icon: <List {...ICON} />, count: me && mine.data ? myMove || undefined : undefined, end: true, match: ["/", "/items"] },
    { to: "/approvals", label: "Approvals", icon: <CheckCircle2 {...ICON} />, count: toSign || undefined },
    { to: "/inbox", label: "Inbox", icon: <Inbox {...ICON} />, count: nInbox || undefined },
    { section: "Insights", to: "/insights/team", label: "Team", icon: <Users {...ICON} />, match: ["/insights/team", "/brief"] },
    { to: "/org", label: "Organisation", icon: <Network {...ICON} /> },
    { to: "/insights/projects", label: "Projects", icon: <BarChart3 {...ICON} /> },
    { to: "/insights/pricing", label: "Pricing", icon: <IndianRupee {...ICON} /> },
    { to: "/insights/estimates", label: "Estimates", icon: <Scale {...ICON} /> },
    { section: "Records", to: "/vendors", label: "Records", icon: <Building2 {...ICON} />, match: ["/vendors", "/materials", "/prs", "/pos", "/requirements", "/workfronts"] },
  ];
  const ask = () => setPalette(true);      // the phone's Ask and search open the command sheet: one place to ask or find
  const tabs: NavDef[] = [
    { to: "/", label: "Today", icon: <List {...TAB} />, end: true },
    { to: "/approvals", label: "Approvals", icon: <CheckCircle2 {...TAB} />, count: toSign || undefined, hot: true },
    { to: "/inbox", label: "Inbox", icon: <Inbox {...TAB} /> },
    { to: "/ask", label: "Ask", icon: <MessageCircle {...TAB} />, onClick: ask },
    { to: "/more", label: "More", icon: <Ellipsis {...TAB} /> },
  ];
  return (
    <div className={`app${askOpen ? " ai-open ai-over" : ""}`}>      {/* the answer lies over the right edge on every page: a case keeps its columns, a list its table */}
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
        {/* the header: where the data stands (left), the one place to ask or find (centre), who you are (right) */}
        <header className={phone ? "top phone-off" : "top"}>
          <div className="top-l asof" title={fresh.at && !fresh.cached ? `Read from the server at ${clockTime(fresh.at)}` : undefined}>
            {health.data ? (
              <Link className={`asof-link fresh${stale ? " is-stale" : ""}`} to="/data" title={asOfTip}>
                <i className="fresh-dot" aria-hidden /><span className="asof-l">Data as of {longDate(health.data.as_of)}</span><span className="asof-s">Data {shortDate(health.data.as_of)}</span>
                {stale ? <small className="asof-stale">{stale} stale</small> : null}
              </Link>
            ) : <span className="skel" style={{ width: 96 }} />}
          </div>
          <CommandBar />
          <div className="top-r">{me && <MeMenu me={me} role={people.find((p) => p.name === me)?.note?.split(" · ")[0]} onChange={() => setChanging(true)} />}</div>
          {fresh.cached && <div className="offline" role="status">Offline: showing what was last read{fresh.at ? ` at ${clockTime(fresh.at)}` : ""}. Approving needs a connection.</div>}
        </header>
        <div className="content"><Outlet /></div>
        {phone && palette && <div className="cmd-scrim"><CommandBar sheet onClose={() => setPalette(false)} /></div>}
        {ready && (!me || choosing) && <WhoAreYou onClose={me ? () => setChanging(false) : undefined} />}
      </main>
      <AskPanel />
      <TabBar items={tabs} isOn={(to) => inAny(here, ROOTS[to] ?? [])} />
    </div>
  );
}

/** Who is using Lookout: their initials, name and role; the menu switches to another member (no sign-in: the name goes on every approval). */
function MeMenu({ me, role, onChange }: { me: string; role?: string; onChange: () => void }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const down = (e: PointerEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("pointerdown", down); window.addEventListener("keydown", key);
    return () => { document.removeEventListener("pointerdown", down); window.removeEventListener("keydown", key); };
  }, [open]);
  return (
    <div className="me" ref={box}>
      <button type="button" className="me-btn" aria-haspopup="menu" aria-expanded={open} aria-label={`You are ${me}${role ? `, ${role}` : ""}. Switch person`} onClick={() => setOpen(!open)}>
        <span className="av">{initials(me)}</span>
        <span className="me-t"><b>{me}</b>{role && <small>{role}</small>}</span>
        <ChevronDown size={14} strokeWidth={1.5} aria-hidden />
      </button>
      {open && (
        <div className="me-menu" role="menu">
          <p className="me-menu-h">Chosen by name on this computer, no sign-in<small>Your name goes on every draft you sign.</small></p>
          <button type="button" role="menuitem" onClick={() => { setOpen(false); onChange(); }}><UserRoundCog size={16} strokeWidth={1.5} aria-hidden />Switch person</button>
        </div>
      )}
    </div>
  );
}

const TAB = { size: 22, strokeWidth: 1.5 } as const;
const ROOTS: Record<string, string[]> = { "/": ["/", "/items"], "/approvals": ["/approvals"], "/inbox": ["/inbox"], "/more": ["/more", "/lookup", "/vendors", "/materials", "/prs", "/pos", "/requirements", "/workfronts", "/insights", "/brief", "/activity", "/data", "/hood"] };
const inAny = (here: string, roots: string[]) => roots.some((r) => (r === "/" ? here === "/" : here === r || here.startsWith(r + "/")));

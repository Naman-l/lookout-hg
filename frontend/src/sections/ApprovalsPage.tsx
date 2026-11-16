import { useMemo } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useResource } from "../api/useResource";
import type { Action, ActionItem } from "../api/types";
import { useMe } from "../api/useMe";
import { useMedia } from "../ui/useMedia";
import { useAskContext } from "../shell/AskContext";
import { inr, shortDate } from "../ui/format";
import { DraftView, draftKind, draftState } from "./case/Draft";
import "./approvals.css";

type Tab = "sign" | "others" | "sent" | "rejected";
const TABS: { id: Tab; label: string; empty: string }[] = [
  { id: "sign", label: "To approve", empty: "Nothing waits for your signature." }, { id: "others", label: "With others", empty: "Nothing waits on anyone else." },
  { id: "sent", label: "Sent", empty: "Nothing sent yet." }, { id: "rejected", label: "Rejected", empty: "Nothing rejected." },
];
const ownerOf = (a: Action) => String((a.change as { owner?: string } | null)?.owner ?? a.owner ?? "");
const kindOf = (a: Action) => String((a.change as { kind?: string } | null)?.kind ?? "");
/** Everything that needs a signature: letters to vendors, notes inside the company, entries to make in SAP and decisions on record. Choices and
 * recorded controls are history, not drafts. */
const signable = (a: Action) => (a.type === "supplier_request" || a.type === "internal_note" || a.type === "supplier_alias" || ["record", "erp_update", "note"].includes(kindOf(a)))
  && (a.chosen || !a.run_id || a.state !== "proposed");      // a draft a run prepared reaches Approvals only once its owner chooses its route
const first = (n?: string | null) => (n ?? "").split(" ")[0];

/** Approvals: the drafts that wait for a signature. Yours to sign; for the Head of SCM, the ones that need the countersign (signed by their owner, above
 * the DoA threshold); the ones that wait on others; what was sent; what was rejected. The exact text is signed, by its hash. */
export function ApprovalsPage() {
  const { me } = useMe();
  const { tab: tabParam, id } = useParams();
  const nav = useNavigate();
  const wide = useMedia("(min-width: 1024px)");
  const acts = useResource(() => api.actions(), [], true);
  const items = useResource(() => api.actionItems().catch(() => [] as ActionItem[]));
  const titles = useMemo(() => new Map((items.data ?? []).map((i) => [i.key, i.title])), [items.data]);
  const all = (acts.data ?? []).filter(signable);
  const counter = all.filter((a) => a.state === "signed" && a.countersign === me);
  const mine = all.filter((a) => a.state === "proposed" && ownerOf(a) === me);
  const groups: Record<Tab, Action[]> = {
    sign: [...counter, ...mine],
    others: all.filter((a) => (a.state === "proposed" && ownerOf(a) !== me) || (a.state === "signed" && a.countersign !== me)),
    sent: all.filter((a) => a.state === "executed" || a.state === "approved"),
    rejected: all.filter((a) => a.state === "rejected"),
  };
  const sel = id ? all.find((a) => a.action_id === id) : undefined;
  const tab: Tab = (tabParam as Tab) ?? (sel ? (Object.keys(groups) as Tab[]).find((t) => groups[t].includes(sel)) ?? "sign" : "sign");
  const rows = groups[tab];
  const shown = sel ?? (wide ? rows[0] : undefined);
  useAskContext(shown ? { type: "action", id: shown.action_id, label: shown.subject ?? "draft" } : null);
  const row = (a: Action) => {
    const ch = (a.change ?? {}) as { commits_inr?: number };
    const you = (a.state === "proposed" && ownerOf(a) === me) || (a.state === "signed" && a.countersign === me);
    return (
      <Link key={a.action_id} to={`/approvals/${a.action_id}`} className={`apq-row${shown?.action_id === a.action_id ? " on" : ""}`}>
        <b title={a.subject ?? ""}>{a.subject ?? draftKind(a)}</b>
        <small>{draftKind(a)}{a.recipient_name ? ` · to ${a.recipient_name}` : ""}{a.item_key ? ` · ${titles.get(a.item_key) ?? a.item_key}` : ""}</small>
        <span className="apq-l3"><span className={`w${you ? " you" : ""}`}>{a.state === "signed" ? (a.countersign === me ? "Needs your countersign" : `With ${first(a.countersign)} to countersign`)
          : a.state === "proposed" ? (ownerOf(a) === me ? "Yours to sign" : `With ${first(ownerOf(a))}`) : draftState(a)}</span>
          <span className="by">{ch.commits_inr ? `ⓢ ${inr(ch.commits_inr)}` : shortDate(a.proposed_at)}</span></span>
      </Link>
    );
  };
  return (
    <div className={`apx${wide ? " three" : ""}`}>
      <h1 className="apx-h">Approvals</h1>
      <div className="apx-tabs" role="group" aria-label="Drafts">
        {TABS.map((t) => <button key={t.id} type="button" aria-pressed={tab === t.id} className={tab === t.id ? "on" : undefined} onClick={() => nav(`/approvals/tab/${t.id}`)}>{t.label} <em>{groups[t.id].length}</em></button>)}
      </div>
      <div className="apx-grid">
        <div className="apq" role="list" aria-label={TABS.find((t) => t.id === tab)?.label}>
          {acts.loading && !acts.data ? [0, 1, 2].map((n) => <div key={n} className="apq-sk"><i /><i /></div>)
            : rows.length === 0 ? <p className="apq-empty">{TABS.find((t) => t.id === tab)?.empty}</p>
            : tab === "sign" ? <>
              {counter.length > 0 && <p className="apq-g">Needs your countersign · {counter.length}</p>}{counter.map(row)}
              {mine.length > 0 && counter.length > 0 && <p className="apq-g">Yours to sign · {mine.length}</p>}{mine.map(row)}
            </> : rows.map(row)}
        </div>
        <div className="apd">
          {shown ? <>
            {!wide && <button type="button" className="cp-link apd-back" onClick={() => nav(`/approvals/tab/${tab}`)}>‹ All drafts</button>}
            <h2 className="apd-h">{shown.subject ?? draftKind(shown)}</h2>
            <DraftView a={shown} me={me} />
          </> : <p className="apq-empty">{rows.length ? "Choose a draft to read it in full." : ""}</p>}
        </div>
      </div>
    </div>
  );
}

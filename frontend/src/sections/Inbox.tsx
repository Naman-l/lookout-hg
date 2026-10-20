import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { CircleAlert, CircleCheck, CircleDashed } from "lucide-react";
import { api } from "../api/client";
import { useResource } from "../api/useResource";
import type { MessageSummary, Trust } from "../api/types";
import { shortDate } from "../ui/format";
import { EmptyState, Notice, PageHeader, Row, Skeleton } from "../ds";
import { FilterBar, type FilterValue } from "../ds/FilterBar";
import { ListDetail } from "../shell/ListDetail";
import { useNamed } from "../ui/useNamed";
import { useMedia } from "../ui/useMedia";
import { Message } from "./inbox/Message";
import { headline } from "./inbox/model";
import { Match } from "./inbox/Match";
import "./inbox/inbox.css";

export const TRUST: Record<Trust, { label: string; cls: string }> = {
  on_file: { label: "on file", cls: "s-ok" }, new_sender: { label: "new sender", cls: "t-plain" }, suspicious: { label: "suspicious", cls: "t-trust" },
};

/** The inbox: messages on the left, the open one on the right with its sender, trust and linked item beside it. */
export function Inbox() {
  const named = useNamed();
  const { id } = useParams();
  const key = id ? decodeURIComponent(id) : "";
  const [q, setQ] = useState("");
  const [dq, setDq] = useState("");
  useEffect(() => { const t = setTimeout(() => setDq(q.trim()), 200); return () => clearTimeout(t); }, [q]);
  const [vals, setVals] = useState<FilterValue>({});
  const all = useResource(() => api.messages(), []);
  const r = useResource(() => api.messages({ q: dq, kind: vals.kind, supplier: vals.supplier, trust: vals.trust }), [dq, vals.kind, vals.supplier, vals.trust], true);
  const list = r.data ?? [];
  const everything = all.data ?? [];
  const count = (f: (m: MessageSummary) => boolean) => everything.filter(f).length;
  const kinds = [...new Set(everything.map((m) => m.kind).filter((k): k is string => !!k))];
  const suppliers = [...new Map(everything.filter((m) => m.supplier?.id).map((m) => [m.supplier!.id, m.supplier!.label ?? m.supplier!.id])).entries()];
  const filters = [
    { id: "kind", label: "Kind", options: kinds.map((k) => ({ value: k, label: k[0].toUpperCase() + k.slice(1), count: count((m) => m.kind === k) })) },
    { id: "trust", label: "Trust", options: [{ value: "suspicious", label: "Held", count: count((m) => m.trust === "suspicious") }, { value: "new_sender", label: "New sender", count: count((m) => m.trust === "new_sender") }, { value: "on_file", label: "On file", count: count((m) => m.trust === "on_file") }] },
    { id: "supplier", label: "Supplier", options: suppliers.map(([id, label]) => ({ value: id, label, count: count((m) => m.supplier?.id === id) })) },
  ];
  const nav = useNavigate();
  const wide = useMedia("(min-width: 1200px)");
  useEffect(() => { const first = list.find((m) => m.trust === "suspicious") ?? list[0]; if (wide && !key && first) nav(`/inbox/${encodeURIComponent(first.ref.id)}`, { replace: true }); }, [wide, key, list[0]?.ref.id]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <>
      <PageHeader title="Inbox" />
      {r.error && <Notice tone="risk">The inbox could not be loaded.</Notice>}
      <div className="ib-ld"><ListDetail open={!!key}
        list={
          <>
            <FilterBar label="messages" search={q} onSearch={setQ} placeholder="Search sender, subject, part, PO line" filters={filters} value={vals} onChange={setVals} />
            {r.loading && <Skeleton width={260} />}
            {r.data && list.length === 0 && <EmptyState>{dq || Object.values(vals).some(Boolean) ? "No message matches." : "No supplier messages."}</EmptyState>}
            {list.map((m) => (
              <Row key={m.ref.id} to={`/inbox/${encodeURIComponent(m.ref.id)}`} active={m.ref.id === key}
                title={<Sender m={m} />}
                sub={m.matches?.length ? <Match x={m.matches[0]} /> : `${m.kind ? `${m.kind[0].toUpperCase()}${m.kind.slice(1)} · ` : ""}${named(headline(m.summary, m.kind))}`} note={shortDate(m.date)} />
            ))}
          </>
        }
        detail={key ? <Message id={key} onBack={() => nav("/inbox")} /> : <EmptyState>Choose a message to see what it changes.</EmptyState>} /></div>
    </>
  );
}


/** The company in a list row, with its trust as an icon and a word (never colour alone). */
function Sender({ m }: { m: MessageSummary }) {
  const name = m.company && m.company !== "not on file" ? m.company : m.from || "Unknown sender";
  const [Icon, word, tone] = m.trust === "suspicious" ? [CircleAlert, "Held", "red"] as const : m.trust === "new_sender" ? [CircleDashed, "New sender", "amber"] as const : [CircleCheck, "On file", "green"] as const;
  return <span className="ib-co"><span className="ib-co-name">{name}</span>{m.replied && <span className="ib-replied" title="We sent this sender a request after this message">replied</span>}<span className="ib-trust" data-tone={tone} title={word}><Icon size={12} strokeWidth={2} aria-hidden />{m.trust === "on_file" ? <span className="dm-sr">{word}</span> : word}</span></span>;
}

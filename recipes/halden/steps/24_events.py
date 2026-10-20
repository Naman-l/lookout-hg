"""Write down what happened and what lapses, as records, from the messages, the offers, the news and the tariff notice.

Defect: events and dates live inside emails and news items: a supplier's fire, a price rise, a holiday closure, a shortage warning, a quote's
last day, a price lock that ends on a date, a broker's cut-off. Each is read where it is written, so no list of them exists and no screen or agent can
ask "what lapses in the next 30 days" or "what has happened to this supplier".
Rule: `events` (a force-majeure notice, a price change, a closure, a slip, a news item matched to a supplier, the tariff notice) and `deadlines`
(a quote's validity, a price lock, revised dates promised, a last shipment before a closure, an old address's last day, the broker's exclusion cut-off) are rebuilt from the records already read, each with its
source, its supplier, its owner (the buyer on most of the supplier's lines) and the lines and parts it touches. A news item gets a topic from
the recipe's vocabulary (answers.yaml, news_topics): the first topic whose words appear in the headline or summary, else 'other'.
Consequence if ignored: a ransomware attack on a supplier with open orders, a supplier's insolvency filing and a price lock that ends in a week sit in
three places no one reads together.
"""
import json
import re

import pandas as pd


def _owner(po, identity_id):
    mine = po[po.identity_id == identity_id].buyer_id.dropna()
    return mine.value_counts().index[0] if len(mine) else None


def _refs(items):
    return json.dumps([{"type": t, "id": i} for t, i in items]) if items else None


def _topic(vocab, text):
    low = text.lower()
    return next((topic for topic, words in vocab.items() if any(w.lower() in low for w in words)), "other")


def run(ctx):
    msgs, mev, offers, news = ctx.t["messages"], ctx.t["message_events"], ctx.t["offers"], ctx.t["news_items"]
    po, rules = ctx.t["po_lines"], ctx.t["tariff_rules"]
    vocab = ctx.answers.get("news_topics") or {}
    by_id = msgs.set_index("id")
    events, deadlines = [], []

    def event(kind, date, identity, title, detail, source_type, source_id, refs=None, topic=None):
        events.append(dict(kind=kind, topic=topic, date=date, identity_id=identity if isinstance(identity, str) else None, title=title, detail=detail,
                           source_type=source_type, source_id=source_id, owner=_owner(po, identity) if isinstance(identity, str) else None, refs_json=_refs(refs)))

    def deadline(kind, due, identity, detail, source_type, source_id, refs=None):
        deadlines.append(dict(kind=kind, due_date=due, identity_id=identity if isinstance(identity, str) else None, detail=detail, source_type=source_type,
                              source_id=source_id, owner=_owner(po, identity) if isinstance(identity, str) else None, refs_json=_refs(refs)))

    for e in mev.itertuples():
        m = by_id.loc[e.message_id]
        ident = m.identity_id if pd.notna(m.identity_id) else None
        if e.kind in ("force_majeure", "price_change", "closure") and e.ref_type == "supplier":
            lines = [("po_line", x) for x in mev[(mev.message_id == e.message_id) & (mev.ref_type == "po_line")].ref_id.unique()]
            event(e.kind, m.date, ident or e.ref_id, m.subject, e.detail, "message", e.message_id, lines)
        elif e.kind == "deadline":
            kind = ("revised_dates" if "revised delivery dates" in e.detail else "lead_time_change" if "longer lead time" in e.detail else "last_shipment" if e.detail.startswith("last shipment")
                    else "address_forwarding" if "forward only until" in e.detail else "price_lock")
            deadline(kind, e.date_to, ident or e.ref_id, e.detail, "message", e.message_id)
    for mid, g in mev[mev.kind == "promise_revision"].groupby("message_id"):
        m = by_id.loc[mid]
        event("slip", m.date, m.identity_id if pd.notna(m.identity_id) else None, m.subject, f"moves the promise date of {g.ref_id.nunique()} PO lines", "message", mid,
              [("po_line", x) for x in g.ref_id.unique()])
    ok = offers[offers.validity_date.notna() & offers.identity_id.notna() & (offers.trust != "blocked")]
    for (ident, due, quote_no, mid), g in ok.groupby(["identity_id", "validity_date", "quote_no", "message_id"], dropna=False):
        deadline("quote_validity", due, ident, f"quote {quote_no} lapses" if isinstance(quote_no, str) else "quote lapses", "offer", mid, [("part", p) for p in sorted(g.part_number.dropna().unique())])
    for n in news[news.match_kind == "supplier"].itertuples():
        event("news", n.date, n.identity_id, n.headline, n.summary, "news", n.id, topic=_topic(vocab, f"{n.headline} {n.summary or ''}"))
    if len(rules):
        notice = (ctx.data / "external" / "tariff_notice.md").read_text(encoding="utf-8")
        issued = re.search(r"Issued (\d{4}-\d{2}-\d{2})", notice)
        first = rules.sort_values("effective_date").iloc[0]
        event("tariff_notice", issued.group(1) if issued else first.effective_date, None, "New additional duties on products of China",
              f"{int(round(first.rate * 100))}% from {first.effective_date} on the listed codes; the next tranche follows", "notice", "tariff_notice")
        cut = rules.exclusion_contact_by.dropna()
        if len(cut):
            deadline("exclusion_requests", cut.iloc[0], None, "the broker's cut-off to discuss exclusion requests", "notice", "tariff_notice")
    ctx.t["events"] = pd.DataFrame(events, columns=["kind", "topic", "date", "identity_id", "title", "detail", "source_type", "source_id", "owner", "refs_json"]).sort_values(["date", "kind"]).reset_index(drop=True)
    ctx.t["events"].insert(0, "id", range(1, len(ctx.t["events"]) + 1))
    ctx.t["deadlines"] = pd.DataFrame(deadlines, columns=["kind", "due_date", "identity_id", "detail", "source_type", "source_id", "owner", "refs_json"]).sort_values(["due_date", "kind"]).reset_index(drop=True)
    ctx.t["deadlines"].insert(0, "id", range(1, len(ctx.t["deadlines"]) + 1))
    ctx.issue("events.read_from_text", "quotes/ and external/", "Events and dates that exist only inside emails and news items", len(events) + len(deadlines), "infer",
              "Written down as records: each event and deadline keeps its source message, offer, news item or notice, its supplier, its owner and the lines or parts it touches.",
              "A deadline in an email is found when it has passed; an event about a supplier is read by whoever happens to open the message.",
              f"{len(events)} events, {len(deadlines)} deadlines", "ERP admin")

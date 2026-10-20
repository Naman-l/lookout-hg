"""Match the news feed to suppliers with a confidence, and mark places, other companies and market news.

Defect: news names companies the way a journalist does (Jade Peak Power for Jadepeak, Hangzhou Vistaray, Meiya Mould), a place
is not a company (Taoyuan, Xiamen), and companies with the same first word are different businesses (Yunzhan Ceramics,
Hallerbeck Immobilien, Corvell Home Fitness, Wrenfield Logistics).
Rule: compare the name the headline gives (the entity plus the capitalised words after it) with each supplier's names, with
spaces removed. All of the headline's name inside a supplier's name -> supplier (0.95; 0.8 when only the spelling differs);
the same first word with extra words that are not in the supplier's name -> other_company (kept, linked to nobody); a
supplier city or country -> place (the suppliers there are listed); no entity -> market. Nothing is linked on a first word alone.
Consequence if ignored: a kiln fire at a ceramics plant is read as Yunzhan's motor plant; a real quake in Taoyuan reaches no one.
"""
import json
import re

import pandas as pd

STOP = {"inc", "co", "ltd", "llc", "gmbh", "corp", "company", "the", "and", "of", "limited", "technology", "technologies"}


def _toks(s):
    return [re.sub(r"[^a-z]", "", w.lower()) for w in re.split(r"[\s,]+", s) if re.sub(r"[^a-z]", "", w.lower()) not in STOP | {""}]


def run(ctx):
    items = json.loads((ctx.data / "external" / "supplier_news.json").read_text(encoding="utf-8"))
    items = [n for n in items if n["date"] <= ctx.as_of.isoformat()]   # published after the data date: not in the feed yet
    rec = ctx.t["supplier_records"]
    names = {i: [n for n in g.name] for i, g in rec.groupby("identity_id")}
    cities = {}
    for r in rec.itertuples():
        for place in filter(None, [r.city and r.city.split(",")[0].strip().lower()]):
            cities.setdefault(place, set()).add(r.identity_id)
    rows = []
    for n in items:
        ent = n["entity_mentioned"]
        kind, ident, conf, ev = "unrelated", None, None, None
        if not ent:
            kind, ev = "market", "no company named: commodity, port or market news"
        elif ent.lower() in cities:
            kind, ev = "place", "a place, not a company; suppliers located there: " + ", ".join(sorted(cities[ent.lower()]))
        else:
            head = n["headline"]
            i = head.lower().find(ent.split()[0].lower())
            phrase = [ent.split()[0]]
            if i >= 0:
                words = head[i:].split()[1:]
                for w in words:
                    if w[:1].isupper() and w.lower() not in ("to", "adds"):
                        phrase.append(w)
                    else:
                        break
            ptoks = _toks(" ".join(phrase) if len(phrase) > len(ent.split()) else ent)
            best = None
            for ident_id, ns in names.items():
                stoks = {t for nm in ns for t in _toks(nm)}
                inside = [t for t in ptoks if t in stoks or any(t in s or s in t and len(s) > 3 for s in stoks)]
                spaced = "".join(ptoks)
                if ptoks and len(inside) == len(ptoks):
                    best = (ident_id, 0.95, "name in the headline is inside the supplier's name")
                    break
                if spaced and any(spaced in "".join(_toks(nm)) or "".join(_toks(nm)) in spaced for nm in ns):
                    best = (ident_id, 0.8, "same name, spelled differently")
                    break
                if inside and ptoks[0] in stoks and best is None:
                    best = (None, None, f"shares the word '{ptoks[0]}' with supplier {ident_id} but the headline's company has other words: {' '.join(phrase)}")
            if best and best[0]:
                kind, ident, conf, ev = "supplier", best[0], best[1], best[2]
            elif best:
                kind, ev = "other_company", best[2]
            else:
                kind, ev = "unrelated", "no supplier by that name"
        rows.append(dict(id=n["id"], date=n["date"], source=n.get("source"), headline=n["headline"], summary=n.get("summary"),
                         entity_raw=ent, identity_id=ident, match_kind=kind, confidence=conf, match_evidence=ev))
    ctx.t["news_items"] = pd.DataFrame(rows)
    df = ctx.t["news_items"]
    ctx.issue("news.entity_matching", "supplier_news.json", "News names companies as a journalist would; places and same-name companies are not suppliers",
              int((df.match_kind != "supplier").sum()), "flag",
              "Matched by the name in the headline with a confidence; places, other companies and market news are kept and linked to nobody.",
              "A fire at a different company with a similar name read as a supplier's; an earthquake in a supplier's city reaching no supplier.",
              "; ".join((df[df.match_kind == "other_company"].entity_raw + " (" + df[df.match_kind == "other_company"].id + ")").head(4)), "ERP admin")

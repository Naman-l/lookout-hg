"""Ask over the company's records, answered by code: the question is read for what it names (a vendor by any word of its name only it has, or
its code; a project by its name, an alias or its plant; a material; a vertical; a member of the team; "my") and for what it wants (who is
largest, what is late, how many, what falls due, where things stand). Lookout plans the lookups a specialist would make, runs them in order, and
answers with the rows behind the answer, each linked to its record, and what to ask next. A word the records do not hold is never guessed at:
the plan returns None and Ask says what it can answer instead.

Each lookup is a `Look` (which specialist, which tool, why, what it found), streamed as the run's steps so the buyer watches the work happen."""

from __future__ import annotations

import calendar
import difflib
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app import db as app_db
from app.domain import lookups
from app.domain.attention import service as attention
from app.domain.common import AS_OF
from app.domain.fmt import en_in, inr, md, month

WORD = re.compile(r"[a-z0-9&]+")
# words a question is made of: never read as the name of a vendor, a project or a material
STOP = frozenset("""
a about above across after against all also am an and any are as at be been before being below between both but by can could did do does doing
done each few for from get give go had has have having he her here hers him his how i if in into is it its just let like me more most my no nor
not now of off on once only or other our out over own per please same she should show so some such tell than that the their them then there
these they this those through to too under until up us very was we were what when where which while who whom whose why will with would you your
open opened closed close top biggest largest highest lowest least best worst late early due overdue past rate rates price prices cost costs pay
paid paying spend spent value total many much number count list lists every month months week weeks year years today days day next last stand
status doing summary overview need needs needed wait waits waiting case cases item items vendor vendors supplier suppliers project projects site
sites material materials order orders ordered line lines po pos pr prs work front fronts long lead approved library msme invoice invoices payment
payments delivery deliveries deliver delivered delivering receipt receipts held mail mails message messages inbox guarantee guarantees team member
members buyer buyers new old oldest newest sign signature approve approval approvals plate attention compare versus median average still yet
energy power engineering ltd pvt limited private india company industries enterprises works systems solutions services traders trading
group corporation corp co llp structures equipment products supply supplies supplier's quote quotes rfq
""".split())
VERTICAL_RE = {"roads": r"\broads?\b|\bhighways?\b", "railway": r"\brail(?:way)?s?\b", "bess": r"\bbess\b|\bbatter(?:y|ies)\b",
               "solar": r"\bsolar\b", "td": r"\bt ?& ?d\b|\btransmission\b|\bsubstations?\b"}
LIB_VERTICAL = {"transmission line": "td", "t&d": "td", "railway": "railway", "solar": "solar", "bess": "bess", "roads": "roads"}
WAITING = {"project": "Projects", "projects": "Projects", "finance": "Finance", "qa": "QA", "quality": "QA", "vendor": "Vendor", "vendors": "Vendor",
           "the vendor": "Vendor", "management": "Management", "scm": "SCM"}
ROWS = 8


@dataclass
class Look:
    agent: str  # a specialist from the registry, or "lookout"
    tool: str
    args: dict
    why: str
    found: str


@dataclass
class Asked:
    """What a question names and wants, read by code."""

    q: str
    low: str
    vendors: list[str] = field(default_factory=list)  # supplier identities
    projects: list[str] = field(default_factory=list)
    materials: list[str] = field(default_factory=list)
    verticals: list[str] = field(default_factory=list)
    buyer: str | None = None  # a team member's id
    mine: bool = False
    top: int = ROWS
    within: int | None = None  # days ahead of the data date ("this week", "next 30 days")
    since: str | None = None  # an ISO date the question counts from ("this year", "this month")
    waiting_on: str | None = None

    def has(self, pattern: str) -> bool:
        return re.search(pattern, self.low) is not None


def _norm(text: str) -> str:
    return " " + " ".join(WORD.findall((text or "").lower().replace("'s ", " "))) + " "


def _words(text: str) -> list[str]:
    return WORD.findall((text or "").lower())


def _unique_words(names: dict[str, str], avoid: set[str]) -> dict[str, str]:
    """{word: the one key whose name holds it}: words of four letters or more that only one name has, none of them ordinary words (nor, in
    singular or plural, a word of `avoid`)."""
    seen: dict[str, set[str]] = {}
    for k, name in names.items():
        for w in set(_words(name)):
            if len(w) >= 4 and w.isalpha() and w not in STOP and not {w, w.rstrip("s"), w + "s"} & avoid:
                seen.setdefault(w, set()).add(k)
    return {w: next(iter(ks)) for w, ks in seen.items() if len(ks) == 1}


def _find(text: str, words: dict[str, str], avoid: set[str] = frozenset()) -> list[str]:
    """The keys the question's words name, in the order the question names them; a misspelt word of five letters or more (not an ordinary word,
    nor one of `avoid`) finds its closest name."""
    out: list[str] = []
    for w in _words(text):
        k = words.get(w)
        if k is None and len(w) >= 5 and w not in STOP and not {w, w.rstrip("s"), w + "s"} & avoid:
            near = difflib.get_close_matches(w, list(words), n=1, cutoff=0.86)
            k = words[near[0]] if near else None
        if k and k not in out:
            out.append(k)
    return out


# ------------------------------------------------------------------------------------------------------------------------------ reading
def read(session: Session, q: str, context: dict | None, asked_by: str | None) -> Asked:
    a = Asked(q=q, low=q.lower())
    text = _norm(q)
    mats = lookups.materials(session)
    mat_vocab = {w for m in mats.values() for w in _words(f"{m.description} {m.category}")}
    projects = lookups.projects(session)
    proj_names = {pid: " ".join([p.name, *(al.alias for al in lookups.aliases(session).get(pid, []) if al.method != "unresolved")]) for pid, p in projects.items()}
    proj_vocab = {w for n in proj_names.values() for w in _words(n)}
    vert_words = {"roads", "road", "railway", "rail", "bess", "solar", "transmission", "substation"}

    # projects: a whole name or alias, a word only one project has, or "plant NNNN"
    for pid, p in projects.items():
        names = [p.name, p.id.replace("-", " "), *(al.alias for al in lookups.aliases(session).get(pid, []) if al.method != "unresolved"
                                                  and len((al.project_ids or pid).split(",")) == 1)]
        if any(len(n) >= 3 and _norm(n) in text for n in names) and pid not in a.projects:
            a.projects.append(pid)
    for pid in _find(q, _unique_words(proj_names, vert_words), mat_vocab):
        if pid not in a.projects:
            a.projects.append(pid)
    for code in re.findall(r"\bplant\s+(\d{4})\b", a.low):
        pl = lookups.plants(session).get(code)
        if pl and pl.project_id and pl.project_id not in a.projects:
            a.projects.append(pl.project_id)

    # vendors: the name without its legal words, a word only that vendor has (not a material's or a project's word), or a vendor code
    idents = lookups.identities(session)
    vnames = {i: lookups.vendor_name(session, i) for i in idents}
    for i, name in vnames.items():
        core = re.split(r"\s+(?:pvt|private|ltd|limited|llp|co\.)\b", name, flags=re.I)[0]
        if len(core) >= 5 and _norm(core) in text and i not in a.vendors:
            a.vendors.append(i)
    for i in _find(q, _unique_words(vnames, mat_vocab | proj_vocab), mat_vocab | proj_vocab):
        if i not in a.vendors:
            a.vendors.append(i)
    for code in re.findall(r"\b(1\d{5})\b", q):
        i = lookups.identity_of(session, code)
        if i and i not in a.vendors:
            a.vendors.append(i)

    # materials: the code, else the words of the description or category; a word few materials share counts more than one many do
    a.materials = [c for c in re.findall(r"\b(11\d{6})\b", q) if c in mats]
    if not a.materials:
        df: dict[str, int] = {}
        for m in mats.values():
            for w in set(_words(f"{m.description} {m.category}")):
                df[w] = df.get(w, 0) + 1
        asked = {w for w in _words(q) if len(w) >= 3 and re.search("[a-z]", w) and w not in STOP and w not in proj_vocab} - {w for i in a.vendors for w in _words(vnames[i])}
        asked |= {w[:-1] for w in asked if w.endswith("s")}
        score = {code: sum(1 / df[w] for w in asked if w in set(_words(f"{m.description} {m.category}"))) for code, m in mats.items()}
        best = max(score.values(), default=0)
        if best >= 1 / 12:
            a.materials = sorted((c for c, s in score.items() if s >= best - 1e-9), key=lambda c: -_po_count(session, c))

    a.verticals = [v for v, pat in VERTICAL_RE.items() if re.search(pat, a.low)]
    in_vendor = {w for i in a.vendors for w in _words(vnames[i])}
    for b in lookups.team(session).values():
        first = b.name.split()[0].lower()
        if first not in in_vendor and re.search(rf"\b({re.escape(b.name.lower())}|{re.escape(first)})('s)?\b", a.low):
            a.buyer = b.id
            break
    a.mine = bool(re.search(r"\b(?:my|mine)\b|\bi\b|(?<!tell )(?<!show )(?<!give )(?<!let )(?<!help )\bme\b", a.low)) and a.buyer is None
    if a.mine:
        me = lookups.member_of(session, asked_by)
        a.buyer = me.id if me else None
    m = re.search(r"\btop\s+(\d{1,2})\b|\b(\d{1,2})\s+(?:biggest|largest|top|oldest|worst)\b", a.low)
    if m:
        a.top = max(1, min(25, int(m.group(1) or m.group(2))))
    a.within, a.since = _window(a.low)
    w = re.search(r"\bwait(?:s|ing)?\s+(?:on|for)\s+(the vendor|projects?|finance|qa|quality|vendors?|management|scm)\b", a.low)
    a.waiting_on = WAITING.get(w.group(1)) if w else None

    # the page the question was asked from narrows it, unless the question names its own
    if context and context.get("type") and context.get("id"):
        kind, id_ = context["type"], context["id"]
        if kind == "project" and not a.projects:
            a.projects = [id_]
        elif kind == "supplier" and not a.vendors:
            a.vendors = [lookups.identity_of(session, id_) or id_]
        elif kind == "material" and not a.materials:
            a.materials = [id_]
        elif kind == "person" and a.buyer is None and lookups.member_of(session, id_):
            a.buyer = lookups.member_of(session, id_).id
        elif kind == "item" and re.search(r"\b(this|the|that)\s+(vendor|supplier|project|site)\b", a.low):
            d = attention.item_detail(session, id_)
            if d is not None:
                if re.search(r"\b(vendor|supplier)\b", a.low) and not a.vendors:
                    a.vendors = list(dict.fromkeys(r.id for r in d.refs if r.type == "supplier"))
                if re.search(r"\b(project|site)\b", a.low) and not a.projects:
                    a.projects = [p.id for p in d.projects]
    return a


def _window(low: str) -> tuple[int | None, str | None]:
    """(days ahead, or None; an ISO date counted from, or None) from the question's words."""
    m = re.search(r"\b(?:next|within|in the next|coming)\s+(\d{1,3})\s+days?\b", low)
    if m:
        return int(m.group(1)), None
    if re.search(r"\bthis week\b|\bnext 7 days\b|\bnext week\b", low):
        return 7 if "next week" not in low else 14, None
    if re.search(r"\btoday\b", low) and re.search(r"\bdue\b|\bact\b", low):
        return 0, None
    if re.search(r"\bthis month\b", low):
        last = calendar.monthrange(AS_OF.year, AS_OF.month)[1]
        return (date(AS_OF.year, AS_OF.month, last) - AS_OF).days, AS_OF.replace(day=1).isoformat()
    if re.search(r"\blast month\b", low):
        first = (AS_OF.replace(day=1) - timedelta(days=1)).replace(day=1)
        return None, first.isoformat()
    if re.search(r"\bthis (?:financial |fiscal )?year\b|\bthis fy\b|\bytd\b|\bso far this year\b", low):
        fy = AS_OF.year if AS_OF.month >= 4 else AS_OF.year - 1
        return None, date(fy, 4, 1).isoformat()
    m = re.search(r"\b(?:last|past)\s+(\d{1,2})\s+months?\b", low)
    if m:
        return None, (AS_OF - timedelta(days=30 * int(m.group(1)))).isoformat()
    return None, None


def _last_rates(session: Session) -> dict[tuple[str | None, str | None], float]:
    """{(material, plant): the newest PO line's rate there; (material, None): the newest anywhere}: what a PR line is worth, as prs.service prices it, in one pass."""
    from app.domain.orders.service import all_lines  # noqa: PLC0415

    best: dict[tuple, tuple[str, str, float]] = {}
    cut = AS_OF.isoformat()
    for l in all_lines(session).values():
        if not l.material or l.doc_date > cut:
            continue
        for k in ((l.material, l.plant), (l.material, None)):
            if k not in best or (l.doc_date, l.id) > best[k][:2]:
                best[k] = (l.doc_date, l.id, l.rate_base)
    return {k: v[2] for k, v in best.items()}


def _po_count(session: Session, code: str) -> int:
    from app.domain.orders.service import all_lines  # noqa: PLC0415

    return sum(1 for l in all_lines(session).values() if l.material == code)


def _scope(session: Session, a: Asked) -> str:
    """The filters in words: ' on <project>', ' with <vendor>', ' in BESS', ' on <member>'s group'."""
    parts = []
    if a.projects:
        parts.append(" on " + _join([lookups.project_name(session, p) for p in a.projects]))
    if a.vendors:
        parts.append(" with " + _join([lookups.vendor_name(session, v) for v in a.vendors]))
    if a.verticals:
        parts.append(" in " + _join([lookups.VERTICAL_NAMES.get(v, v) for v in a.verticals]))
    if a.materials and len(a.materials) <= 2:
        parts.append(" for " + _join([lookups.materials(session)[m].description for m in a.materials]))
    elif a.materials:
        cats = {lookups.materials(session)[m].category for m in a.materials}
        parts.append(f" for {next(iter(cats)).lower()}" if len(cats) == 1 else f" for {len(a.materials)} matching materials")
    if a.buyer:
        parts.append(f" on {'your' if a.mine else lookups.member_name(session, a.buyer) + chr(39) + 's'} purchasing group")
    return "".join(parts)


def _join(xs: list[str]) -> str:
    xs = [x for x in xs if x]
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1] if xs else ""


def _row(label: str, url: str, cells: list[str], sub: str | None = None) -> dict:
    return {"label": label, "url": url, "sub": sub, "cells": [{"say": c, "id": ""} for c in cells]}


def _table(title: str, by: str, columns: list[str], rows: list[dict], limit: int = ROWS, all_url: str | None = None) -> dict:
    return {"kind": "rows", "title": title, "by": by, "columns": columns, "rows": rows[:limit], "more": max(0, len(rows) - limit), "all_url": all_url}


def _amount(x) -> float:
    return float(getattr(x, "amount", 0) or 0) if x is not None else 0.0


def _vertical_of(session: Session, pid: str | None) -> str | None:
    return lookups.vertical_of_project(session, pid) if pid else None


def _qs(**kw) -> str:
    from urllib.parse import urlencode  # noqa: PLC0415

    return "?" + urlencode({k: v for k, v in kw.items() if v}) if any(kw.values()) else ""


# ------------------------------------------------------------------------------------------------------------------------------- the plan
def plan(session: Session, q: str, context: dict | None, asked_by: str | None) -> tuple[dict, list[Look]] | None:
    """(the Recommendation, the lookups made), or None when the question names nothing the records hold."""
    a = read(session, q, context, asked_by)
    looks: list[Look] = []
    item_ctx = bool(context and context.get("type") == "item")
    listing = a.has(r"\b(which|list|show|how many|top|most|all|every|biggest|largest|oldest|worst|count|compare)\b")
    deictic = bool(re.search(r"\b(this|the|that)\s+(vendor|supplier|project|site)\b", a.low))
    if item_ctx and not (listing or deictic):
        return None      # a question about the case on screen: its own handlers answer it

    route = _route(a)
    if route is None:
        return None
    rec = route(session, a, looks, asked_by)
    if rec is None:
        return None
    rec.setdefault("numbers", [])
    rec["drafted_by"] = "code"
    rec["plan"] = [{"agent": l.agent, "tool": l.tool, "why": l.why, "found": l.found} for l in looks]
    return rec, looks


def _route(a: Asked):
    vendor, project = a.has(r"\bvendors?\b|\bsuppliers?\b|\bwho (?:supplies|do we buy)\b"), a.has(r"\bprojects?\b|\bsites?\b")
    # "open PO value" is a measure of vendors or projects; the subject is POs when the question asks for them, or names nothing else
    pr = a.has(r"\bprs?\b|\bpurchase requisitions?\b|\brequisitions?\b|\bindents?\b")
    po = a.has(r"\b(?:pos|po lines?|purchase orders?|order lines?|open orders)\b") or (a.has(r"\bpo\b") and not (vendor or project))
    late = a.has(r"\blate\b|\bon[- ]time\b|\bdeliver(?:y|ies|s|ed)?\b|\breceipts?\b|\bstreak\b|\bdelay(?:s|ed)?\b")
    overdue = a.has(r"\boverdue\b|\bpast (?:their |the )?due\b|\bpast due\b|\bbehind\b|\bslipp")
    if a.has(r"\b(?:to |for )?(?:my )?(?:sign|signature|countersign|approve)\b|\bapprovals?\b") and not a.has(r"\b(prepare|draft|write)\b"):
        return approvals
    if a.has(r"\bmsme\b|\b45[- ]day|\budyam\b") and a.has(r"\bdue\b|\bpay|\binvoice|\b45|\bowe"):
        return msme
    if a.has(r"\b(?:lcs?|bgs?|abgs?|pbgs?|guarantees?|letters? of credit)\b"):
        return guarantees
    if a.has(r"\blong[- ]lead\b|\border[- ]by\b|\bnot (?:yet )?ordered\b|\blook ?ahead\b"):
        return lookahead
    if a.has(r"\bwork ?fronts?\b|\breadiness\b|\bfronts? (?:at risk|stop)"):
        return workfronts
    if a.has(r"\b(?:above|over|below|more than) (?:the )?median\b|\boverpa(?:y|id|ying)\b|\bpays? (?:the )?most\b") and not (a.materials and a.projects):
        return above_median
    if a.has(r"\b(?:which|top|what|the) (?:\d+ )?(?:projects|sites)\b") and not a.projects and not a.has(r"\bpa(?:y|id|ys)\b"):
        return projects_ranked
    if a.has(r"\bworkload\b|\bon (?:\w+'s |my |their )?plate\b|\bworking on\b|\bwho (?:on|in) the team\b|\bteam\b|\bbusiest\b") and not (vendor or po or pr):
        return team
    if a.has(r"\b(?:e?mails?|messages?|inbox|letters?)\b") and not a.has(r"\b(prepare|draft|write)\b"):
        return inbox
    if a.has(r"\bcases?\b|\bneeds? (?:my |our )?attention\b|\balerts?\b"):
        return cases
    if a.has(r"\bspen[dt]\b|(?<!open )\bpo value\b|\bhow much (?:have we|did we|we) (?:ordered|bought)\b|\bpurchases\b|\bbought\b|\bordered from\b"):
        return spend
    if a.has(r"\bnot in (?:the |our )?(?:approved )?library\b|\bunapproved\b|\bnot approved\b|\boutside (?:the )?library\b|\boff[- ]library\b"):
        return pos if po else vendors_library
    if late and (vendor or not (po or pr)) and not overdue and not a.has(r"\bdue\b"):
        return vendors_delivery
    if overdue or (late and po):
        return pos
    if pr:
        return prs
    if po:
        return pos
    if a.waiting_on or a.has(r"\bdue (?:this|next|today|in|within)\b|\bwhat is due\b|\burgent\b|\bat risk\b|\bact on\b|\bto do\b"):
        return cases
    if a.materials and a.has(r"\brates?\b|\bprices?\b|\bpa(?:y|id|ys)\b|\bcosts?\b|\bwhat does\b"):
        return material_rate
    if vendor and not a.vendors:
        return vendors_ranked
    if project and not a.projects:
        return projects_ranked
    if a.materials and not (a.vendors or a.projects):
        return material_rate
    if a.vendors:
        return vendor_profile
    if a.projects:
        return project_overview
    if a.buyer:
        return team
    return None


# ---------------------------------------------------------------------------------------------------------------------------- the answers
def vendors_ranked(session: Session, a: Asked, looks: list[Look], asked_by: str | None) -> dict:
    from app.domain.suppliers.service import list_vendors  # noqa: PLC0415

    rows = list_vendors(session)
    looks.append(Look("sourcing_analyst", "list_vendors", {}, "Read every company in the vendor master with what is open with it, how it delivers and what the library approves it for.",
                      f"{len(rows)} vendors on file, {sum(1 for r in rows if r.open_lines)} with open POs"))
    keep = _vendor_filter(session, a, looks)
    rows = [r for r in rows if keep(r.ref.id)]
    if a.has(r"\bmsme\b"):
        rows = [r for r in rows if r.msme]
    spend = a.has(r"\bspen[dt]\b|(?<!open )\bpo value\b|\bbought\b|\bordered\b")
    if a.has(r"\bhow many\b|\bcount\b|\bnumber of\b"):
        n_open = sum(1 for r in rows if r.open_lines)
        return {"finding": f"{en_in(len(rows))} vendors{_scope(session, a)} on file; {en_in(n_open)} have open POs, worth {inr(sum(_amount(r.open_value) for r in rows))}.",
                "tables": [_vendor_table(rows, spend, a.top)], "follow_ups": _vendor_follow(rows)}
    rows = sorted(rows, key=lambda r: -(_amount(r.po_value) if spend else _amount(r.open_value)))
    total = sum(_amount(r.po_value if spend else r.open_value) for r in rows)
    top = [r for r in rows if _amount(r.po_value if spend else r.open_value) > 0][: a.top]
    if not top:
        return {"finding": f"No vendor{_scope(session, a)} has {'any PO value on file' if spend else 'an open PO'}.", "follow_ups": ["Which vendors have the most open PO value?"]}
    share = sum(_amount(r.po_value if spend else r.open_value) for r in top) / total if total else 0
    what = "PO value on file" if spend else "open PO value"
    return {"finding": f"The {len(top)} vendors{_scope(session, a)} with the most {what}: " + "; ".join(f"{r.name} {inr(_amount(r.po_value if spend else r.open_value))}" for r in top[:3])
                       + (f"; together {inr(sum(_amount(r.po_value if spend else r.open_value) for r in top))}, {share:.0%} of the {inr(total)} {what} across {en_in(sum(1 for r in rows if _amount(r.po_value if spend else r.open_value)))} vendors." if len(rows) > len(top) else "."),
            "points": [{"label": "Not in the library", "text": f"{sum(1 for r in top if not r.in_library)} of these"}, {"label": "On a late streak", "text": f"{sum(1 for r in top if r.streak)} of these"}],
            "tables": [_vendor_table(top, spend, a.top, "/vendors" + _qs(show="open"))], "follow_ups": _vendor_follow(top)}


def _vendor_filter(session: Session, a: Asked, looks: list[Look]):
    """Vendors that sold to the project(s), into the vertical(s), the material(s) asked about (any PO line on file), else every vendor."""
    from app.domain.orders.service import all_lines  # noqa: PLC0415
    from app.domain.suppliers.service import library_verticals  # noqa: PLC0415

    if not (a.projects or a.verticals or a.materials or a.buyer):
        return lambda ident: True
    sold = {l.identity_id for l in all_lines(session).values()
            if (not a.projects or l.project_id in a.projects) and (not a.materials or l.material in a.materials) and (not a.buyer or l.buyer_id == a.buyer)
            and (not a.verticals or _vertical_of(session, l.project_id) in a.verticals)}
    lib = {i for i in lookups.identities(session) if a.verticals and {LIB_VERTICAL.get(v.lower(), v.lower()) for v in library_verticals(session, i)} & set(a.verticals)}
    looks.append(Look("sourcing_analyst", "open_pos", {"project": ",".join(a.projects) or None, "material": ",".join(a.materials) or None},
                      "Find the vendors with a PO line on file" + _scope(session, a) + ".", f"{len(sold | lib)} vendors"))
    return lambda ident: ident in sold or ident in lib


def _vendor_table(rows, spend: bool, limit: int, all_url: str | None = None) -> dict:
    return _table("Vendors", "Sourcing analyst", ["PO value" if spend else "Open value", "Open lines", "On time"],
                  [_row(r.name, f"/vendors/{r.ref.id}", [inr(_amount(r.po_value if spend else r.open_value)), en_in(r.open_lines), f"{r.on_time_pct}%" if r.on_time_pct is not None else "—"],
                        sub=("not in the library" if not r.in_library else ", ".join(r.verticals) or "in the library, not approved") + (" · MSME" if r.msme else ""))
                   for r in rows], limit=limit, all_url=all_url)


def _vendor_follow(rows) -> list[str]:
    out = [f"What is open with {rows[0].name}?"] if rows else []
    return out + ["Which vendors with open POs are not in the approved library?", "Which vendors are on a late streak?"]


def vendors_library(session: Session, a: Asked, looks: list[Look], asked_by: str | None) -> dict:
    from app.domain.suppliers.service import list_vendors  # noqa: PLC0415

    keep = _vendor_filter(session, a, looks)
    rows = [r for r in list_vendors(session) if keep(r.ref.id)]
    out = sorted([r for r in rows if not r.in_library and r.open_lines], key=lambda r: -_amount(r.open_value))
    pending = [r for r in rows if r.in_library and not r.verticals and r.open_lines]
    looks.append(Look("sourcing_analyst", "vendor_library", {}, "Check each vendor with open POs against the approved vendor library.", f"{len(out)} not in it, {len(pending)} in it but not approved"))
    if not out and not pending:
        return {"finding": f"Every vendor with an open PO{_scope(session, a)} is in the approved library.", "follow_ups": ["Which vendors have the most open PO value?"]}
    value = sum(_amount(r.open_value) for r in out)
    return {"finding": f"{len(out)} vendors with open POs{_scope(session, a)} are not in the approved library, holding {inr(value)} on {en_in(sum(r.open_lines for r in out))} open lines"
                       + (f"; the largest are {_join([f'{r.name} ({inr(_amount(r.open_value))})' for r in out[:2]])}" if out else "")
                       + (f". {len(pending)} more are in the library but not yet approved ({_join([r.name for r in pending[:2]])})." if pending else "."),
            "tables": [_vendor_table(out + pending, False, a.top, "/vendors" + _qs(library="out"))],
            "follow_ups": [f"What is open with {out[0].name}?" if out else "Which vendors have the most open PO value?", "Which open POs go to vendors not in the library?"]}


def vendors_delivery(session: Session, a: Asked, looks: list[Look], asked_by: str | None) -> dict:
    from app.domain.suppliers.service import list_vendors  # noqa: PLC0415

    keep = _vendor_filter(session, a, looks)
    rows = [r for r in list_vendors(session) if keep(r.ref.id) and r.receipts]
    looks.append(Look("sourcing_analyst", "vendor_record", {"vendor": "each"}, "Read each vendor's receipts against the PO line's delivery date: on time, late, and the run of late receipts it is on now.",
                      f"{len(rows)} vendors with receipts on file"))
    best = a.has(r"\bbest\b|\bmost reliable\b|\bon[- ]time\b") and not a.has(r"\bnot on[- ]time\b|\blate\b|\bworst\b")
    if a.vendors:
        rows = [r for r in rows if r.ref.id in a.vendors]
    elif not best:
        rows = [r for r in rows if r.receipts >= 3]
    rows = sorted(rows, key=lambda r: ((-(r.on_time_pct or 0), -r.receipts) if best else ((r.on_time_pct or 0), -r.streak, -r.receipts)))
    streak = [r for r in rows if r.streak]
    if not rows:
        return {"finding": f"No vendor{_scope(session, a)} has receipts on file against a dated PO line, so the records cannot say how it delivers."}
    head = rows[: a.top]
    word = "best" if best else "lowest"
    if not best and all((r.on_time_pct or 0) >= 90 for r in head) and not a.vendors:
        return {"finding": f"None of the {len(rows)} vendors{_scope(session, a)} with receipts on file delivers late often: the lowest on-time share is {head[0].on_time_pct}% ({head[0].name}, {en_in(head[0].receipts)} receipts).",
                "tables": [_table("Delivery record", "Sourcing analyst", ["On time", "Receipts", "Late streak"],
                                  [_row(r.name, f"/vendors/{r.ref.id}", [f"{r.on_time_pct}%", en_in(r.receipts), str(r.streak) if r.streak else "—"]) for r in head], limit=a.top)],
                "follow_ups": ["Which vendors are on a late streak?", "Which open POs are past due?"]}
    return {"finding": f"The {word} on-time records{_scope(session, a)}: " + "; ".join(f"{r.name} {r.on_time_pct}% of {en_in(r.receipts)}" + (f" ({r.streak} late in a row)" if r.streak else "") for r in head[:3])
                       + f". {len(streak)} vendor{'s are' if len(streak) != 1 else ' is'} on a late streak now." + (" On time is a receipt posted on or before the line's delivery date." if not best else ""),
            "tables": [_table("Delivery record", "Sourcing analyst", ["On time", "Receipts", "Late streak"],
                              [_row(r.name, f"/vendors/{r.ref.id}", [f"{r.on_time_pct}%", en_in(r.receipts), str(r.streak) if r.streak else "—"], sub=f"{inr(_amount(r.open_value))} open" if r.open_lines else None) for r in head],
                              limit=a.top, all_url="/vendors" + _qs(show="streak"))],
            "follow_ups": [f"What is open with {head[0].name}?", "Which open POs are past due?", "Which cases wait on the vendor?"]}


def vendor_profile(session: Session, a: Asked, looks: list[Look], asked_by: str | None) -> dict:
    from app.domain.orders.service import list_lines  # noqa: PLC0415
    from app.domain.suppliers.service import profile  # noqa: PLC0415

    if len(a.vendors) > 1:
        rows = [profile(session, v) for v in a.vendors[:6]]
        rows = [r for r in rows if r]
        looks.append(Look("sourcing_analyst", "vendor_record", {"vendor": ",".join(a.vendors[:6])}, "Read each vendor's record side by side.", f"{len(rows)} vendors"))
        return {"finding": "Side by side: " + "; ".join(f"{r.name} {inr(_amount(r.open_value))} open, {r.delivery.on_time_pct if r.delivery.on_time_pct is not None else '—'}% on time" for r in rows) + ".",
                "tables": [_vendor_table(rows, False, 6)], "follow_ups": [f"What is open with {rows[0].name}?"] if rows else []}
    v = profile(session, a.vendors[0])
    if v is None:
        return None
    looks.append(Look("sourcing_analyst", "vendor_record", {"vendor": v.ref.id}, "Read the vendor's record: its codes, library approval, on-time receipts, MSME dues and guarantees.", v.delivery.line))
    lines = [l for l in list_lines(session, status="open", vendor=v.ref.id) if (not a.projects or (l.project and l.project.id in a.projects))]
    looks.append(Look("sourcing_analyst", "open_pos", {"vendor": v.ref.id}, f"List the open PO lines with {v.name}" + (" on " + _join([lookups.project_name(session, p) for p in a.projects]) if a.projects else "") + ".",
                      f"{len(lines)} open lines"))
    late = [l for l in lines if l.days_past_due]
    cases = [i for i in attention.what_needs_attention(session) if any(r.type == "supplier" and r.id == v.ref.id for r in i.refs)]
    looks.append(Look("lookout", "list_items", {"vendor": v.ref.id}, "Find the cases on Today that name this vendor.", f"{len(cases)} cases"))
    lib = ("approved for " + ", ".join(v.verticals)) if v.verticals else ("in the library, not yet approved" if v.in_library else "not in the approved library")
    parts = [f"{v.name}: {inr(sum(_amount(l.open_value) for l in lines))} open on {en_in(len(lines))} PO line{'s' if len(lines) != 1 else ''}" + (f", {len(late)} past due" if late else ""),
             v.delivery.line.rstrip("."), lib]
    if v.msme_due:
        parts.append(f"MSME: {len(v.msme_due)} invoice{'s' if len(v.msme_due) != 1 else ''} worth {inr(sum(_amount(m.amount) for m in v.msme_due))} fall due by {md(v.msme_due[0].due_by)}")
    points = [{"label": "Codes", "text": ", ".join(v.codes)}, {"label": "Contact on file", "text": v.contact.name or "none on file"}]
    if v.guarantees:
        points.append({"label": "LC / BG", "text": "; ".join(f"{g['kind']} {inr(g['amount'])} ({g['status'] or 'status not stated'})" for g in v.guarantees[:3])})
    tables = [_table("Open PO lines", "Sourcing analyst", ["Open value", "Due"],
                     [_row(f"{l.ref.id} · {l.text}", f"/pos/{l.po}", [inr(_amount(l.open_value)), (md(l.revised[-1].date) + " (vendor)") if l.revised else md(l.delivery_date)],
                           sub=(l.project.label if l.project else None)) for l in sorted(lines, key=lambda l: -_amount(l.open_value))],
                     all_url="/pos" + _qs(q=v.name, who="all"))]
    if cases:
        tables.append(_cases_table(cases, "Cases that name this vendor"))
    return {"finding": "; ".join(parts) + ".", "points": points, "tables": tables,
            "follow_ups": [f"Which of {v.name}'s POs are past due?" if late else f"How has {v.name} delivered?", "Which vendors are on a late streak?"]}


def pos(session: Session, a: Asked, looks: list[Look], asked_by: str | None) -> dict:
    from app.domain.orders.service import all_lines, revisions, view  # noqa: PLC0415

    overdue = a.has(r"\boverdue\b|\bpast (?:their |the )?due\b|\bpast due\b|\blate\b|\bbehind\b|\bslipp")
    off_lib = a.has(r"\bnot in (?:the |our )?(?:approved )?library\b|\bunapproved\b|\bnot approved\b|\boutside (?:the )?library\b")
    due_by = (AS_OF + timedelta(days=a.within)).isoformat() if a.within is not None else None
    today = AS_OF.isoformat()
    lines = [l for l in all_lines(session).values() if l.status == "open"
             and (not a.vendors or l.identity_id in a.vendors) and (not a.projects or l.project_id in a.projects) and (not a.materials or l.material in a.materials)
             and (not a.buyer or l.buyer_id == a.buyer) and (not a.verticals or _vertical_of(session, l.project_id) in a.verticals)
             and (not overdue or (l.delivery_date and l.delivery_date < today)) and (not off_lib or "not_in_library" in (l.flags or ""))
             and (not due_by or (l.delivery_date and today <= l.delivery_date <= due_by))]
    what = "past-due " if overdue else ""
    looks.append(Look("site_planner", "open_pos", {"vendor": ",".join(a.vendors) or None, "project": ",".join(a.projects) or None},
                      "List the open PO lines" + _scope(session, a) + (", past their delivery date" if overdue else "") + (" to vendors not in the approved library" if off_lib else "")
                      + (f", due by {md(due_by)}" if due_by else "") + ".", f"{len(lines)} lines"))
    value = sum(l.open_value for l in lines)
    noun = "open PO line" + ("s" if len(lines) != 1 else "")
    if not lines:
        return {"finding": f"No {what}{noun}{_scope(session, a)}" + (" to vendors outside the approved library" if off_lib else "") + (f" falls due by {md(due_by)}" if due_by else "") + ".",
                "follow_ups": ["Which open POs are past due?", "Which vendors have the most open PO value?"]}
    rev = revisions(session)
    if overdue:
        lines.sort(key=lambda l: (l.delivery_date or "", -l.open_value))
        oldest = lines[0]
        moved = sum(1 for l in lines if rev.get(l.id))
        one = len(lines) == 1
        finding = (f"{en_in(len(lines))} open PO line{'' if one else 's'}{_scope(session, a)} {'is past its' if one else 'are past their'} SAP delivery date, worth {inr(value)} open: {'' if one else 'the oldest, '}{oldest.po_no}/{oldest.item} "
                   f"({oldest.short_text}, {lookups.vendor_name(session, oldest.identity_id)}), was due {md(oldest.delivery_date)}, {(AS_OF - date.fromisoformat(oldest.delivery_date)).days} days ago."
                   + (f" The vendor's mail has moved the date on {'it' if one else f'{moved} of them'}." if moved else ""))
        lines.sort(key=lambda l: -l.open_value)
    else:
        lines.sort(key=lambda l: (l.delivery_date or "9999") if due_by else -l.open_value)
        n_po = len({l.po_no for l in lines})
        late = sum(1 for l in lines if l.delivery_date and l.delivery_date < today)
        finding = (f"{en_in(len(lines))} {what}{noun} on {en_in(n_po)} PO{'s' if n_po != 1 else ''}{_scope(session, a)}" + (" to vendors not in the approved library" if off_lib else "")
                   + (f" fall due by {md(due_by)}" if due_by else "") + f", worth {inr(value)} open" + (f"; {en_in(late)} are past due." if late and not due_by else "."))
    views = [view(session, l) for l in lines[:40]]
    by_vendor: dict[str, float] = {}
    for l in lines:
        by_vendor[l.identity_id] = by_vendor.get(l.identity_id, 0) + l.open_value
    points = [{"label": "Largest vendors", "text": "; ".join(f"{lookups.vendor_name(session, i)} {inr(v)}" for i, v in sorted(by_vendor.items(), key=lambda x: -x[1])[:3])}] if len(by_vendor) > 1 else []
    url = "/pos" + _qs(who="all", project=a.projects[0] if len(a.projects) == 1 else None, vertical=a.verticals[0] if len(a.verticals) == 1 else None,
                       q=lookups.vendor_name(session, a.vendors[0]) if len(a.vendors) == 1 else None, flag="vendor not in the approved library" if off_lib else None)
    return {"finding": finding, "points": points,
            "tables": [_table("Open PO lines" if not overdue else "Past due, largest first", "Site requirement planner", ["Open value", "Due"],
                              [_row(f"{x.ref.id} · {x.text}", f"/pos/{x.po}", [inr(_amount(x.open_value)), (md(x.delivery_date) + (f" (+{x.days_past_due} d)" if x.days_past_due else ""))],
                                    sub=f"{x.vendor.label}" + (f" · {x.project.label}" if x.project else "")) for x in views], limit=a.top, all_url=url)],
            "follow_ups": ([f"What is open with {lookups.vendor_name(session, max(by_vendor, key=by_vendor.get))}?"] if by_vendor and not a.vendors else [])
            + (["Which open POs are past due?"] if not overdue else ["Which vendors are on a late streak?"]) + ["Which cases wait on the vendor?"]}


def prs(session: Session, a: Asked, looks: list[Look], asked_by: str | None) -> dict:
    from app.domain.prs.service import all_lines  # noqa: PLC0415

    lines = [l for l in all_lines(session).values() if l.status == "open" and (not a.projects or l.project_id in a.projects) and (not a.materials or l.material in a.materials)
             and (not a.buyer or l.buyer_id == a.buyer) and (not a.verticals or _vertical_of(session, l.project_id) in a.verticals)]
    looks.append(Look("site_planner", "open_prs", {"project": ",".join(a.projects) or None}, "List the open PRs" + _scope(session, a) + ", with their age and need date.", f"{len(lines)} open PR lines"))
    if not lines:
        return {"finding": f"No open PR line{_scope(session, a)}.", "follow_ups": ["Which open POs are past due?"]}
    start = lambda l: l.released or l.created  # noqa: E731
    age = lambda l: (AS_OF - date.fromisoformat(start(l))).days  # noqa: E731
    waiting = None
    if a.waiting_on:
        from app.domain.insights.service import ladders  # noqa: PLC0415

        lad = ladders(session)
        lines = [l for l in lines if (x := lad.get(f"pr_line:{l.id}")) and x.waiting_on == a.waiting_on]
        looks.append(Look("site_planner", "pr_ladder", {"pr_line": "each"}, f"Walk each open PR line from need to payment to see whose move it is now.", f"{len(lines)} wait on {a.waiting_on}"))
        waiting = a.waiting_on
    lines.sort(key=lambda l: -age(l))
    rate = _last_rates(session)
    priced = [(l, rate.get((l.material, l.plant)) or rate.get((l.material, None))) for l in lines]
    value = sum((l.qty_base if l.qty_base is not None else l.qty) * r for l, r in priced if r)
    unpriced = sum(1 for _, r in priced if not r)
    past = [l for l in lines if l.needed_by and l.needed_by < AS_OF.isoformat()]
    n_pr = len({l.pr_no for l in lines})
    if not lines:
        return {"finding": f"No open PR line{_scope(session, a)} waits on {waiting}." if waiting else f"No open PR line{_scope(session, a)}."}
    o = lines[0]
    by_project: dict[str, int] = {}
    for l in lines:
        by_project[l.project_id or ""] = by_project.get(l.project_id or "", 0) + 1
    finding = (f"{en_in(len(lines))} open PR lines on {en_in(n_pr)} PRs{_scope(session, a)}" + (f" wait on {waiting}" if waiting else "")
               + f", worth about {inr(value)} at the last PO rates" + (f" ({unpriced} with no rate on file)" if unpriced else "")
               + f". The oldest, PR {o.pr_no}/{o.item} ({o.short_text}), has waited {age(o)} days" + (f"; {en_in(len(past))} are past their need date." if past else "."))
    points = [{"label": "Most open lines", "text": "; ".join(f"{lookups.project_name(session, p) or 'no project'} {n}" for p, n in sorted(by_project.items(), key=lambda x: -x[1])[:3])}] if len(by_project) > 1 else []
    url = "/prs" + _qs(who="all", project=a.projects[0] if len(a.projects) == 1 else None, vertical=a.verticals[0] if len(a.verticals) == 1 else None)
    return {"finding": finding, "points": points,
            "tables": [_table("Open PR lines, oldest first", "Site requirement planner", ["Age", "Need by"],
                              [_row(f"{l.pr_no}/{l.item} · {l.short_text}", f"/prs/{l.pr_no}", [f"{age(l)} d", md(l.needed_by) if l.needed_by else "—"],
                                    sub=(lookups.project_name(session, l.project_id) or "no project") + (f" · {lookups.member_name(session, l.buyer_id)}" if l.buyer_id else "")) for l in lines],
                              limit=a.top, all_url=url)],
            "follow_ups": [f"Where does PR {o.pr_no} stand?", "Which PRs wait on Projects?" if waiting != "Projects" else "Which cases wait on Projects?",
                           f"How is {lookups.project_name(session, o.project_id)} doing?" if o.project_id and not a.projects else "Which open POs are past due?"]}


def _cases_table(items, title: str = "Cases") -> dict:
    def stake(i) -> str:
        x = i.at_stake
        return inr(float(x.amount)) if x is not None and hasattr(x, "amount") else (f"{en_in(x.value)} {x.uom}" if x is not None and hasattr(x, "uom") else "—")
    return _table(title, "Lookout", ["At stake", "Act by"], [_row(i.title, f"/items/{i.key}", [stake(i), md(i.act_by) if i.act_by else "—"],
                                                                 sub=f"{i.owner} · waits on {i.waiting_on}") for i in items])


def cases(session: Session, a: Asked, looks: list[Look], asked_by: str | None) -> dict:
    owner = lookups.member_name(session, a.buyer) if a.buyer else None
    if owner is None and a.within is not None and not (a.projects or a.vendors or a.verticals) and asked_by and lookups.member_of(session, asked_by):
        owner, a.mine = lookups.member_of(session, asked_by).name, True      # "what is due this week" is the asker's own
    items = attention.what_needs_attention(session, owner)
    looks.append(Look("lookout", "list_items", {"owner": owner}, "Read Today: every case the code found" + (f", {owner}'s share" if owner else "") + ", ranked.", f"{len(items)} cases"))
    due_by = (AS_OF + timedelta(days=a.within)).isoformat() if a.within is not None else None
    items = [i for i in items if (not a.projects or any(p.id in a.projects for p in i.projects)) and (not a.verticals or set(i.verticals) & set(a.verticals))
             and (not a.vendors or any(r.type == "supplier" and r.id in a.vendors for r in i.refs)) and (not a.waiting_on or i.waiting_on == a.waiting_on)
             and (not due_by or (i.act_by and i.act_by <= due_by)) and (not a.has(r"\burgent\b|\bhigh\b|\bserious\b") or i.severity == "high")]
    whose = "of your " if a.mine else (f"of {owner}'s " if owner else "")
    filt = _scope(session, Asked(q=a.q, low=a.low, projects=a.projects, vendors=a.vendors, verticals=a.verticals))
    if not items:
        return {"finding": f"No {whose[3:]}case{filt}" + (f" waits on {a.waiting_on}" if a.waiting_on else "") + (f" must be acted on by {md(due_by)}" if due_by else "") + ".",
                "follow_ups": ["What needs attention across the company?", "Which open POs are past due?"]}
    stake = sum(float(i.at_stake.amount) for i in items if i.at_stake is not None and hasattr(i.at_stake, "amount"))
    high = sum(1 for i in items if i.severity == "high")
    finding = (f"{len(items)} {whose if len(items) != 1 else whose[3:]}case{'s' if len(items) != 1 else ''}{filt}" + (f" wait{'s' if len(items) == 1 else ''} on {a.waiting_on}" if a.waiting_on else " need attention")
               + (f", to be acted on by {md(due_by)}" if due_by else "") + (f"; {high} high" if high else "") + (f", {inr(stake)} at stake in all" if stake else "")
               + ". First: " + "; ".join(f"{i.title}" + (f" (by {md(i.act_by)})" if i.act_by else "") for i in items[:3]) + ".")
    waits: dict[str, int] = {}
    for i in items:
        waits[i.waiting_on] = waits.get(i.waiting_on, 0) + 1
    return {"finding": finding, "points": [{"label": "Waiting on", "text": ", ".join(f"{k} {v}" for k, v in sorted(waits.items(), key=lambda x: -x[1]))}],
            "tables": [_cases_table(items[: max(a.top, 8)])],
            "follow_ups": ["Which cases wait on Projects?" if a.waiting_on != "Projects" else "Which cases wait on Finance?", "What is due this week?" if due_by is None else "Which open POs are past due?",
                           "Who on the team has the most open cases?"]}


def projects_ranked(session: Session, a: Asked, looks: list[Look], asked_by: str | None) -> dict:
    from app.domain.projects.service import list_projects  # noqa: PLC0415

    rows = [p for p in list_projects(session) if not a.verticals or p.vertical in a.verticals]
    looks.append(Look("site_planner", "list_projects", {}, "Read every project with its open PRs, open PO lines and open value.", f"{len(rows)} projects"))
    items = attention.what_needs_attention(session)
    looks.append(Look("lookout", "list_items", {}, "Count the cases on Today per project.", f"{len(items)} cases"))
    n_cases = {p.ref.id: sum(1 for i in items if any(x.id == p.ref.id for x in i.projects)) for p in rows}
    if a.has(r"\bcases?\b|\battention\b|\brisks?\b|\bissues?\b|\bproblems?\b|\btrouble\b"):
        key, what = (lambda p: -n_cases[p.ref.id]), "the most open cases"
    elif a.has(r"\bprs?\b|\brequisitions?\b"):
        key, what = (lambda p: -p.open_prs), "the most open PR lines"
    else:
        key, what = (lambda p: -p.open_value), "the most open PO value"
    rows.sort(key=key)
    head = rows[: a.top]
    return {"finding": f"The projects{_scope(session, Asked(q='', low='', verticals=a.verticals))} with {what}: " + "; ".join(
                f"{p.name} ({inr(p.open_value)} open, {n_cases[p.ref.id]} case{'s' if n_cases[p.ref.id] != 1 else ''})" for p in head[:3]) + ".",
            "tables": [_table("Projects", "Site requirement planner", ["Open PO value", "Open PRs", "Cases"],
                              [_row(p.name, f"/insights/projects/{p.ref.id}", [inr(p.open_value), en_in(p.open_prs), str(n_cases[p.ref.id])],
                                    sub=f"{lookups.VERTICAL_NAMES.get(p.vertical, p.vertical)} · {p.stage}") for p in head], limit=a.top, all_url="/insights/projects")],
            "follow_ups": [f"How is {head[0].name} doing?", "Which open POs are past due?", "Which cases wait on Projects?"] if head else []}


def project_overview(session: Session, a: Asked, looks: list[Look], asked_by: str | None) -> dict:
    from app.domain.orders.service import all_lines as po_lines  # noqa: PLC0415
    from app.domain.projects.service import list_projects  # noqa: PLC0415
    from app.domain.prs.service import all_lines as pr_lines  # noqa: PLC0415

    pid = a.projects[0]
    p = next((x for x in list_projects(session) if x.ref.id == pid), None)
    if p is None:
        return None
    looks.append(Look("site_planner", "list_projects", {"project": pid}, f"Read {p.name}: its vertical, stage, plants and people on file.", f"{p.vertical} · {p.stage}"))
    po = [l for l in po_lines(session).values() if l.project_id == pid and l.status == "open"]
    late = [l for l in po if l.delivery_date and l.delivery_date < AS_OF.isoformat()]
    looks.append(Look("site_planner", "open_pos", {"project": pid}, f"List {p.name}'s open PO lines and those past their delivery date.", f"{len(po)} open, {len(late)} past due"))
    pr = [l for l in pr_lines(session).values() if l.project_id == pid and l.status == "open"]
    oldest = max(pr, key=lambda l: (AS_OF - date.fromisoformat(l.released or l.created)).days, default=None)
    looks.append(Look("site_planner", "open_prs", {"project": pid}, f"List {p.name}'s open PRs, oldest first.", f"{len(pr)} open PR lines"))
    items = [i for i in attention.what_needs_attention(session) if any(x.id == pid for x in i.projects)]
    looks.append(Look("lookout", "list_items", {"project": pid}, f"Find the cases on Today for {p.name}.", f"{len(items)} cases"))
    by_vendor: dict[str, float] = {}
    for l in po:
        by_vendor[l.identity_id] = by_vendor.get(l.identity_id, 0) + l.open_value
    looks.append(Look("sourcing_analyst", "open_pos", {"project": pid, "by": "vendor"}, "Group the open value by vendor.", f"{len(by_vendor)} vendors"))
    finding = (f"{p.name} ({lookups.VERTICAL_NAMES.get(p.vertical, p.vertical)}, {p.stage}): {inr(p.open_value)} open on {en_in(len(po))} PO lines"
               + (f", {en_in(len(late))} past due ({inr(sum(l.open_value for l in late))})" if late else "") + f"; {en_in(len(pr))} open PR lines"
               + (f", the oldest waiting {(AS_OF - date.fromisoformat(oldest.released or oldest.created)).days} days" if oldest else "")
               + f"; {len(items)} case{'s' if len(items) != 1 else ''} need{'s' if len(items) == 1 else ''} attention" + (f", first {items[0].title}." if items else "."))
    points = [x for x in [{"label": "Project head", "text": p.head} if p.head else None, {"label": "Planner", "text": p.planner} if p.planner else None,
                          {"label": "Plants", "text": ", ".join(p.plants)} if p.plants else None] if x]
    tables = []
    if items:
        tables.append(_cases_table(items, f"Cases on {p.name}"))
    if by_vendor:
        tables.append(_table("Largest open vendors", "Sourcing analyst", ["Open value"], [_row(lookups.vendor_name(session, i), f"/vendors/{i}", [inr(v)]) for i, v in sorted(by_vendor.items(), key=lambda x: -x[1])],
                             limit=5, all_url="/pos" + _qs(who="all", project=pid)))
    return {"finding": finding, "points": points, "tables": tables,
            "follow_ups": [f"Which POs on {p.name} are past due?", f"Which PRs on {p.name} are the oldest?", f"Which work fronts on {p.name} are at risk?"]}


def material_rate(session: Session, a: Asked, looks: list[Look], asked_by: str | None) -> dict:
    from app.domain.materials.service import detail  # noqa: PLC0415

    code = a.materials[0]
    d = detail(session, code)
    if d is None:
        return None
    sites = [s for s in d.by_site if s.last_rate]
    looks.append(Look("sourcing_analyst", "rate_history", {"material": code}, f"Read what each site last paid for {d.description}.", f"{len(sites)} sites"))
    if not sites:
        return {"finding": f"{d.description} ({code}): no site has a PO rate on file" + (f"; {d.open_prs} open PR lines ask for it." if d.open_prs else "."),
                "follow_ups": ["Which sites pay above the median?"]}
    sites.sort(key=lambda s: s.last_rate)
    unit = f"/{d.base_uom}" if d.base_uom else ""
    mine = [s for s in sites if s.project.id in a.projects]
    if mine:
        s = mine[0]
        gap = (s.last_rate - d.median) / d.median if d.median else 0
        text = (f"{s.project.label} last paid {inr(s.last_rate)}{unit} for {d.description} ({s.vendor}, {md(s.last_date)}); the median across {len(sites)} sites is {inr(d.median)}{unit}"
                + (f", so it pays {gap:+.0%}" if d.median and abs(gap) >= 0.01 else "") + (f"; the budget rate is {inr(s.budget)}." if s.budget else "."))
    else:
        text = (f"{d.description}: {len(sites)} site{'s' if len(sites) != 1 else ''} buy it, from {inr(sites[0].last_rate)}{unit} ({sites[0].project.label}) to {inr(sites[-1].last_rate)}{unit} ({sites[-1].project.label})"
                + (f"; median {inr(d.median)}{unit}." if d.median else "."))
    others = [m for m in a.materials[1:4]]
    return {"finding": text + (" The records hold each site's rate, not the reason for a gap (haul, quality, the unit kept)." if len(sites) > 1 else ""),
            "points": [{"label": "Also matched", "text": ", ".join(lookups.materials(session)[m].description for m in others)}] if others else [],
            "tables": [_table(f"{d.description} by site", "Sourcing analyst", ["Last rate", "Date"],
                              [_row(s.project.label, f"/insights/projects/{s.project.id}", [inr(s.last_rate), md(s.last_date)], sub=s.vendor) for s in sites], limit=10, all_url=f"/materials/{code}")],
            "follow_ups": [f"Why does {sites[-1].project.label} pay more for {d.description.split()[0].lower()} than {sites[0].project.label}?" if len(sites) > 1 else "Which sites pay above the median?",
                           f"Which open PRs ask for {d.description}?", "Which sites pay above the median?"]}


def above_median(session: Session, a: Asked, looks: list[Look], asked_by: str | None) -> dict:
    from app.domain.materials.service import detail, list_materials  # noqa: PLC0415

    mats = [m for m in list_materials(session) if m.projects >= 3 and m.spread and m.spread > 1.05 and (not a.materials or m.code in a.materials)]
    looks.append(Look("sourcing_analyst", "list_materials", {}, "Find the materials three or more sites buy whose highest site rate is above the lowest.", f"{len(mats)} materials"))
    rows = []
    for m in mats:
        d = detail(session, m.code)
        if not d or not d.median:
            continue
        for s in d.by_site:
            if s.last_rate and s.last_rate > d.median * 1.05 and (not a.projects or s.project.id in a.projects) and (not a.verticals or _vertical_of(session, s.project.id) in a.verticals):
                rows.append((m, d, s, (s.last_rate - d.median) / d.median))
    looks.append(Look("sourcing_analyst", "rate_history", {"material": "each"}, "Read each site's last rate beside the median of the sites.", f"{len(rows)} site rates above the median by 5% or more"))
    if not rows:
        return {"finding": f"No site{_scope(session, a)} pays more than 5% above the median of the sites buying the same material."}
    rows.sort(key=lambda r: -r[3])
    m, d, s, g = rows[0]
    return {"finding": f"{len(rows)} site rates{_scope(session, a)} sit 5% or more above the median for their material; the widest: {s.project.label} paid {inr(s.last_rate)} for {d.description} against a median of {inr(d.median)} ({g:+.0%})."
                       " The records hold each rate, not why (haul, quality, the unit kept): each site's buyer can say.",
            "tables": [_table("Above the median", "Sourcing analyst", ["Last rate", "Median", "Above"],
                              [_row(f"{d.description} · {s.project.label}", f"/materials/{m.code}", [inr(s.last_rate), inr(d.median), f"{g:+.0%}"], sub=s.vendor) for m, d, s, g in rows], limit=a.top,
                              all_url="/insights/pricing")],
            "follow_ups": [f"What does each site pay for {d.description}?", "Which vendors have the most open PO value?"]}


def msme(session: Session, a: Asked, looks: list[Look], asked_by: str | None) -> dict:
    from app.domain.suppliers.service import list_vendors, msme_due  # noqa: PLC0415

    vs = [v for v in list_vendors(session) if v.msme and (not a.vendors or v.ref.id in a.vendors)]
    rows = [(v, m) for v in vs for m in msme_due(session, v.ref.id)]
    looks.append(Look("sourcing_analyst", "msme_due", {}, "Read each MSME vendor's unpaid invoices against the 45-day limit.", f"{len(rows)} invoices due within 45 days, {len(vs)} MSME vendors"))
    if a.within is not None:
        rows = [(v, m) for v, m in rows if m.days_left <= a.within]
    if not rows:
        return {"finding": f"No unpaid MSME invoice{_scope(session, a)} falls due" + (f" in the next {a.within} days" if a.within is not None else " within 45 days") + ".",
                "follow_ups": ["Which vendors have the most open PO value?"]}
    rows.sort(key=lambda r: r[1].due_by)
    over = [(v, m) for v, m in rows if m.days_left < 0]
    total = sum(_amount(m.amount) for _, m in rows)
    return {"finding": f"{len(rows)} unpaid MSME invoices worth {inr(total)}{_scope(session, a)} fall due within 45 days" + (f"; {len(over)} are already past the limit ({inr(sum(_amount(m.amount) for _, m in over))})" if over else "")
                       + f". Soonest: {rows[0][0].name}, invoice {rows[0][1].invoice}, {inr(_amount(rows[0][1].amount))} by {md(rows[0][1].due_by)}.",
            "points": [{"label": "Rule", "text": "an MSME invoice is paid within 45 days of its date (MSMED Act, section 15)"}],
            "tables": [_table("MSME invoices, soonest first", "Sourcing analyst", ["Amount", "Due by", "Days left"],
                              [_row(f"{m.invoice} · {v.name}", f"/vendors/{v.ref.id}", [inr(_amount(m.amount)), md(m.due_by), str(m.days_left)], sub=f"PO {m.po}" if m.po else None) for v, m in rows],
                              limit=a.top, all_url="/vendors" + _qs(msme="yes"))],
            "follow_ups": [f"What is open with {rows[0][0].name}?", "Which LCs and guarantees need action?"]}


def guarantees(session: Session, a: Asked, looks: list[Look], asked_by: str | None) -> dict:
    from app.domain.orders.service import lines_of_po  # noqa: PLC0415
    from app.domain.payments.service import guarantees as all_g  # noqa: PLC0415

    gs = all_g(session)
    looks.append(Look("site_planner", "guarantees", {}, "Read the LC and BG register: what is to be opened by when, what expires, what advance is not yet recovered.", f"{len(gs)} on the register"))

    def proj(g) -> str | None:
        ls = lines_of_po(session, g.po) if g.po else []
        return ls[0].project_id if ls else None
    gs = [g for g in gs if (not a.vendors or lookups.identity_of(session, g.vendor_code) in a.vendors) and (not a.projects or proj(g) in a.projects)]
    act = [g for g in gs if g.days_left is not None and g.days_left <= (a.within if a.within is not None else 60) and (g.status or "").lower() not in ("closed", "released", "returned")]
    act.sort(key=lambda g: (g.days_left < 0, g.days_left if g.days_left >= 0 else -g.days_left))
    lapsed = [g for g in act if g.days_left < 0]
    if not gs:
        return {"finding": f"No LC or BG on the register{_scope(session, a)}."}
    unrec = sum(g.unrecovered or 0 for g in gs)
    soon = [g for g in act if g.days_left >= 0]
    when = lambda g: ("to be opened by " if g.to_open_by and not g.issued_on else "expires ") + md(g.to_open_by if g.to_open_by and not g.issued_on else g.expiry)  # noqa: E731
    return {"finding": f"{len(gs)} LCs and BGs on the register{_scope(session, a)}; {len(act)} need action"
                       + (f": {len(lapsed)} already past their date with the register still open (the oldest, {lapsed[-1].kind} for {lapsed[-1].vendor_name}, {inr(lapsed[-1].amount)})" if lapsed else "")
                       + (f"{';' if lapsed else ':'} {len(soon)} within {a.within if a.within is not None else 60} days, first {soon[0].kind}{' ' + soon[0].number if soon[0].number else ''} for {soon[0].vendor_name} ({inr(soon[0].amount)}), {when(soon[0])}" if soon else "")
                       + "." + (f" Advance not yet recovered against receipts: {inr(unrec)}." if unrec else ""),
            "tables": [_table("Needs action, soonest first" if act else "The register", "Site requirement planner", ["Amount", "Date", "Days left"],
                              [_row(f"{g.kind}{' ' + g.number if g.number else ''} · {g.vendor_name}", f"/vendors/{lookups.identity_of(session, g.vendor_code) or ''}",
                                    [inr(g.amount), md(g.to_open_by if g.to_open_by and not g.issued_on else g.expiry), str(g.days_left) if g.days_left is not None else "—"], sub=f"PO {g.po} · {g.status or 'status not stated'}" if g.po else g.status)
                               for g in (act or gs)], limit=a.top)],
            "follow_ups": ["Which MSME invoices fall due soon?", "Which cases wait on Finance?"]}


def lookahead(session: Session, a: Asked, looks: list[Look], asked_by: str | None) -> dict:
    from app.domain.lookahead.service import items  # noqa: PLC0415

    rows = [x for x in items(session) if not x.ordered and (not a.projects or x.project in a.projects) and (not a.verticals or _vertical_of(session, x.project) in a.verticals)]
    looks.append(Look("price_analyst", "lookahead", {"project": ",".join(a.projects) or None}, "Read the long-lead items not yet ordered, their order-by dates and what each month's wait costs.", f"{len(rows)} not ordered"))
    if not rows:
        return {"finding": f"Every long-lead item on the look-ahead{_scope(session, a)} has a PO on file."}
    rows.sort(key=lambda x: x.order_by or "9999")
    past = [x for x in rows if x.order_by and x.order_by < AS_OF.isoformat()]
    wait = sum(x.delay_cost or 0 for x in rows)
    return {"finding": f"{len(rows)} long-lead items{_scope(session, a)} are not yet ordered, worth {inr(sum(x.value for x in rows))}" + (f"; {len(past)} are past their order-by date" if past else "")
                       + (f". A month's wait on the price-variation-linked ones costs about {inr(wait)} at the index's average rise." if wait else "."),
            "tables": [_table("Not yet ordered, soonest order-by first", "Price and PV analyst", ["Value", "Order by", "Basis"],
                              [_row(f"{x.item}", f"/insights/projects/{x.project}" if x.project else "/requirements", [inr(x.value), md(x.order_by) if x.order_by else "—", x.price_basis], sub=f"{x.project_name} · lead {x.lead}") for x in rows],
                              limit=a.top, all_url="/requirements")],
            "follow_ups": ["What does a month's wait cost on these items?", "Which work fronts are at risk?"]}


def workfronts(session: Session, a: Asked, looks: list[Look], asked_by: str | None) -> dict:
    from app.domain.requirements import service as req  # noqa: PLC0415

    pids = a.projects or [p for p in lookups.work_fronts(session) if not a.verticals or _vertical_of(session, p) in a.verticals]
    rows = []
    for pid in pids:
        for f in req.readiness(session, pid):
            if f.late or f.disrupted or f.no_po:
                rows.append((pid, f))
    looks.append(Look("site_planner", "workfront_readiness", {"project": ",".join(a.projects) or "each"}, "Check each work front month by month: covered in time, late, under a disruption, or with no PO.",
                      f"{len(rows)} front-months short of cover on {len({p for p, _ in rows})} projects"))
    if not rows:
        return {"finding": f"Every work front{_scope(session, a)} is covered in time by a PO for the next three months."}
    rows.sort(key=lambda r: (r[1].stops_on or "9999", -(r[1].late + r[1].no_po)))
    pid, f = rows[0]
    return {"finding": f"{len(rows)} work-front months{_scope(session, a)} are short of cover; the soonest: {f.front} on {lookups.project_name(session, pid)} could stop from {md(f.stops_on)}"
                       f" ({f.late} line{'s' if f.late != 1 else ''} covered only by a later PO, {f.no_po} with no PO)." + " Up to: site stock is not in the data.",
            "tables": [_table("Work fronts short of cover", "Site requirement planner", ["Month", "Late", "No PO"],
                              [_row(f"{f.front} · {lookups.project_name(session, pid)}", f"/workfronts{_qs(project=pid)}", [month(f.month), str(f.late), str(f.no_po)], sub=("stops from " + md(f.stops_on)) if f.stops_on else None)
                               for pid, f in rows], limit=a.top, all_url="/workfronts")],
            "follow_ups": [f"How is {lookups.project_name(session, pid)} doing?", "Which long-lead items are not yet ordered?"]}


def inbox(session: Session, a: Asked, looks: list[Look], asked_by: str | None) -> dict:
    from app.domain.inbox.service import list_messages, mark_replied  # noqa: PLC0415

    rows = mark_replied(session, list_messages(session))
    looks.append(Look("inbox_analyst", "inbox_overview", {}, "List the inbox as the code classified it: who sent each, whether it can be trusted, what it means.", f"{len(rows)} messages"))
    held = a.has(r"\bheld\b|\bblocked\b|\buntrusted\b|\bsuspicious\b|\bfraud|\blook-?alike\b|\bphish|\bbank\b")
    unanswered = a.has(r"\bunanswered\b|\bnot (?:yet )?(?:answered|replied)\b|\bno reply\b|\bawaiting (?:a )?reply\b|\bpending reply\b")
    rows = [m for m in rows if (not a.vendors or (m.vendor and m.vendor.id in a.vendors)) and (not held or m.trust != "ok") and (not unanswered or (not m.replied and m.sender_class == "vendor"))]
    if a.since:
        rows = [m for m in rows if m.date[:10] >= a.since]
    rows.sort(key=lambda m: m.date, reverse=True)
    if not rows:
        return {"finding": f"No message{_scope(session, a)}" + (" is held" if held else "") + (" waits for a reply" if unanswered else "") + "."}
    n_held = sum(1 for m in rows if m.trust == "blocked")
    return {"finding": f"{len(rows)} message{'s' if len(rows) != 1 else ''}{_scope(session, a)}" + (" held or under review" if held else "") + (" wait for a reply" if unanswered else "")
                       + (f"; {n_held} held as untrusted (nothing is acted on from them)" if n_held and not held else "") + f". Newest: \"{rows[0].ref.label}\" from {rows[0].company}, {md(rows[0].date[:10])}: {rows[0].summary}",
            "tables": [_table("Messages, newest first", "Inbox analyst", ["Date", "Trust"],
                              [_row(m.ref.label or m.ref.id, f"/inbox/{m.ref.id}", [md(m.date[:10]), {"ok": "ok", "review": "review", "blocked": "held"}.get(m.trust, m.trust)], sub=f"{m.company} · {m.kind}") for m in rows],
                              limit=a.top, all_url="/inbox")],
            "follow_ups": ["Which messages are held as untrusted?" if not held else "Which vendor mails are not answered yet?", "Which cases wait on the vendor?"]}


def spend(session: Session, a: Asked, looks: list[Look], asked_by: str | None) -> dict:
    from app.domain.orders.service import all_lines  # noqa: PLC0415

    lines = [l for l in all_lines(session).values() if (not a.since or l.doc_date >= a.since) and (not a.vendors or l.identity_id in a.vendors) and (not a.projects or l.project_id in a.projects)
             and (not a.materials or l.material in a.materials) and (not a.buyer or l.buyer_id == a.buyer) and (not a.verticals or _vertical_of(session, l.project_id) in a.verticals)]
    looks.append(Look("sourcing_analyst", "po_value", {"since": a.since}, "Add up the value of the PO lines on file" + _scope(session, a) + (f" dated from {md(a.since, True)}" if a.since else "") + ".", f"{len(lines)} PO lines"))
    if not lines:
        return {"finding": f"No PO line on file{_scope(session, a)}" + (f" since {md(a.since, True)}" if a.since else "") + "."}
    total = sum(l.value for l in lines)
    if a.has(r"\bby (?:project|site)s?\b"):
        key, name, url, title = (lambda l: l.project_id or ""), (lambda k: lookups.project_name(session, k) or "no project"), (lambda k: f"/insights/projects/{k}"), "By project"
    elif a.has(r"\bby (?:vendor|supplier)s?\b") or not (a.has(r"\bby (?:vertical|business)\b") or a.vendors):
        key, name, url, title = (lambda l: l.identity_id), (lambda k: lookups.vendor_name(session, k)), (lambda k: f"/vendors/{k}"), "By vendor"
    else:
        key, name, url, title = (lambda l: _vertical_of(session, l.project_id) or ""), (lambda k: lookups.VERTICAL_NAMES.get(k, k or "no vertical")), (lambda k: "/pos" + _qs(who="all", vertical=k, status="any")), "By vertical"
    groups: dict[str, float] = {}
    for l in lines:
        groups[key(l)] = groups.get(key(l), 0) + l.value
    head = sorted(groups.items(), key=lambda x: -x[1])
    first = min(l.doc_date for l in lines)
    return {"finding": f"{inr(total)} ordered on {en_in(len(lines))} PO lines{_scope(session, a)}, dated {md(first, True)} to {md(max(l.doc_date for l in lines), True)}. "
                       + f"{title}: " + "; ".join(f"{name(k)} {inr(v)} ({v / total:.0%})" for k, v in head[:3]) + ".",
            "points": [{"label": "Rule", "text": "the value of each PO line as SAP states it (ME2N), whether received or not"}],
            "tables": [_table(title, "Sourcing analyst", ["PO value", "Share"], [_row(name(k), url(k), [inr(v), f"{v / total:.0%}"]) for k, v in head], limit=a.top)],
            "follow_ups": ["Which vendors have the most open PO value?", "How much have we ordered this year by vertical?"]}


def team(session: Session, a: Asked, looks: list[Look], asked_by: str | None) -> dict:
    from app.domain.orders.service import all_lines as po_lines  # noqa: PLC0415
    from app.domain.prs.service import all_lines as pr_lines  # noqa: PLC0415

    members = [b for b in lookups.team(session).values() if not a.buyer or b.id == a.buyer]
    po, pr = [l for l in po_lines(session).values() if l.status == "open"], [l for l in pr_lines(session).values() if l.status == "open"]
    rows = []
    for b in members:
        items = attention.what_needs_attention(session, b.name)
        mine_po = [l for l in po if l.buyer_id == b.id]
        rows.append((b, items, sum(1 for l in pr if l.buyer_id == b.id), len(mine_po), sum(l.open_value for l in mine_po)))
    looks.append(Look("lookout", "list_items", {"owner": a.buyer or "each"}, "Read each member's share of the cases on Today, and the open PRs and PO lines on their purchasing groups.", f"{len(rows)} members"))
    if a.buyer and rows:
        b, items, n_pr, n_po, value = rows[0]
        return {"finding": f"{'You have' if a.mine else b.name + ' has'} {len(items)} case{'s' if len(items) != 1 else ''} on Today" + (f", first {items[0].title}" if items else "")
                           + f"; {en_in(n_pr)} open PR lines and {en_in(n_po)} open PO lines ({inr(value)}) on {'your' if a.mine else 'their'} purchasing groups.",
                "points": [{"label": "Role", "text": b.role}], "tables": [_cases_table(items)] if items else [],
                "follow_ups": [f"Which open POs on {'my' if a.mine else b.name + chr(39) + 's'} group are past due?", f"Which open PRs on {'my' if a.mine else b.name + chr(39) + 's'} group are the oldest?"]}
    rows.sort(key=lambda r: (-len(r[1]), -r[4]))
    return {"finding": "Cases on Today by member: " + "; ".join(f"{b.name} {len(items)}" for b, items, *_ in rows[:4]) + ". A team case counts once for each member who owns a share of it.",
            "tables": [_table("The team", "Lookout", ["Cases", "Open PRs", "Open PO value"],
                              [_row(b.name, f"/insights/team/{b.id}", [str(len(items)), en_in(n_pr), inr(value)], sub=b.role) for b, items, n_pr, n_po, value in rows], limit=12, all_url="/insights/team")],
            "follow_ups": [f"What is on {rows[0][0].name.split()[0]}'s plate?" if rows else "What needs attention?", "Which cases wait on Projects?"]}


def approvals(session: Session, a: Asked, looks: list[Look], asked_by: str | None) -> dict:
    from app.domain.actions import approvers, ledger  # noqa: PLC0415
    from app.domain.actions.api import _picks  # noqa: PLC0415

    who = approvers.resolve(app_db.DB_PATH, asked_by) if asked_by else None
    picks = _picks()
    waiting = [x for x in ledger.list_actions(app_db.DB_PATH, "proposed") if x.action_id in picks or not x.run_id]
    signed = ledger.list_actions(app_db.DB_PATH, "signed")
    mine = []
    for x in waiting:
        try:
            if who and who in (approvers.owners_of_action(app_db.DB_PATH, x) or {who}):
                mine.append(x)
        except approvers.OwnerLookupError:
            pass
    counter = [x for x in signed if who and x.countersign == who]
    looks.append(Look("buyers_clerk", "requests_for", {"owner": asked_by}, "Read the approvals ledger: drafts waiting for their owner's signature, and signed drafts waiting for a countersign.",
                      f"{len(mine)} to sign, {len(counter)} to countersign"))
    rows = [(x, "to sign") for x in mine] + [(x, "to countersign") for x in counter]
    if not rows:
        return {"finding": f"Nothing waits for your signature: {len(waiting)} drafts across the team wait for their owners, {len(signed)} signed drafts for a countersign.",
                "follow_ups": ["What is due this week?", "Which cases need attention?"]}
    return {"finding": f"{len(mine)} draft{'s' if len(mine) != 1 else ''} wait{'s' if len(mine) == 1 else ''} for your signature and {len(counter)} for your countersign. Nothing is sent until it is signed.",
            "tables": [_table("Waiting for you", "Buyer's clerk", ["Waits", "Since"], [_row(x.subject or x.type, f"/approvals/{x.action_id}", [w, md((x.proposed_at or "")[:10]) if x.proposed_at else "—"],
                                                                                         sub=x.recipient_name or x.recipient) for x, w in rows], limit=a.top, all_url="/approvals")],
            "follow_ups": ["What is due this week?", "Which cases wait on Finance?"]}


# --------------------------------------------------------------------------------------------------------------------------- suggestions
def suggestions(session: Session, page: str | None, context: dict | None) -> list[str]:
    """Questions about the page on screen, each one the plan answers, naming real records where it can (the largest vendor, the busiest project)."""
    from app.domain.projects.service import list_projects  # noqa: PLC0415
    from app.domain.suppliers.service import list_vendors  # noqa: PLC0415

    vendors = list_vendors(session)
    v = next((r.name for r in vendors if r.open_lines), None)
    projects = sorted(list_projects(session), key=lambda p: -p.open_value)
    p = projects[0].name if projects else None
    kind, label = (context or {}).get("type"), (context or {}).get("label")
    if kind == "project" and label:
        return [f"How is {label} doing?", f"Which POs on {label} are past due?", f"Which PRs on {label} are the oldest?", f"Which work fronts on {label} are at risk?"]
    if kind == "supplier" and label:
        return [f"What is open with {label}?", f"How has {label} delivered?", f"Which messages came from {label}?"]
    if kind == "material" and label:
        return [f"What does each site pay for {label}?", f"Which open PRs ask for {label}?", "Which sites pay above the median?"]
    if kind == "person" and label and "brief" not in label:
        return [f"What is on {label.split()[0]}'s plate?", f"Which open POs on {label.split()[0]}'s group are past due?"]
    by_page = {
        "today": ["What is due this week?", "Which cases wait on Projects?", "Which open POs are past due?", "What is waiting for my signature?"],
        "vendor": ["Which vendors have the most open PO value?", "Which vendors with open POs are not in the approved library?", "Which vendors are on a late streak?",
                   "Which MSME invoices fall due soon?"] + ([f"What is open with {v}?"] if v else []),
        "pos": ["Which open POs are past due?", "Which open POs fall due this week?", "Which LCs and guarantees need action?", "How much have we ordered this year by vertical?"],
        "prs": ["Which open PRs are the oldest?", "Which PRs wait on Projects?"] + ([f"How many open PRs does {p} have?"] if p else []),
        "materials": ["Which sites pay above the median?", "Which long-lead items are not yet ordered?"],
        "requirements": ["Which long-lead items are not yet ordered?", "Which work fronts are at risk?"],
        "workfronts": ["Which work fronts are at risk?", "Which long-lead items are not yet ordered?"],
        "team": ["Who on the team has the most open cases?", "What is on my plate?", "Which cases wait on Projects?"],
        "projects": ["Which projects have the most open cases?", "Which projects have the most open PO value?"] + ([f"How is {p} doing?"] if p else []),
        "pricing": ["Which sites pay above the median?", "How much have we ordered this year by vertical?"],
        "estimates": ["Which sites pay above the median?", "Which long-lead items are not yet ordered?"],
        "insights": ["Which projects have the most open cases?", "Which sites pay above the median?"],
        "inbox": ["Which messages are held as untrusted?", "Which vendor mails are not answered yet?"],
        "approvals": ["What is waiting for my signature?", "What is due this week?"],
    }
    return by_page.get(page or "", [])


def everywhere(session: Session) -> list[str]:
    """Questions about the whole company, for the bar's 'Everything' list."""
    return ["Which vendors have the most open PO value?", "Which open POs are past due?", "Which projects have the most open cases?", "Which MSME invoices fall due soon?",
            "Which vendors are on a late streak?", "How much have we ordered this year by vertical?"]

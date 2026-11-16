"""The organisation chart: the SCM organogram as the build read it (org_people), with the edits people made on the Organisation page laid over it.

Edits are a ledger, not a rewrite: each add, change or removal is a row in `org_edits`, kept in order with who made it and when, and the chart is
the sheet's rows with every edit not undone applied in turn. The table is created here, not by the build, so a rebuild carries it over like the
approval ledger (imports/build.py _carry_over): the sheet is read again and the same edits laid over it. An edit to a box the sheet no longer has
is kept and shown as not applied.

The chart is what HG's organogram says and what people corrected on it. Who owns which purchasing group, what each member may sign and who sees whose
Team page stay the recipe's answers (the buyers table); the Team page groups and describes people as the chart does.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone

from app.domain import lookups
from app.domain.org.schema import OrgChart, OrgEdit, OrgFields, OrgNode

_DDL = """
CREATE TABLE IF NOT EXISTS org_edits (
  edit_id TEXT PRIMARY KEY, seq INTEGER NOT NULL, at TEXT NOT NULL, by TEXT NOT NULL, op TEXT NOT NULL, person_id TEXT NOT NULL,
  person TEXT, fields_json TEXT NOT NULL, undone_at TEXT, undone_by TEXT
);
"""
FIELDS = ("name", "designation", "reports_to", "category", "portfolio", "responsibilities", "vacancy")
LABELS = {"name": "name", "designation": "designation", "reports_to": "reports to", "category": "desk", "portfolio": "portfolio",
          "responsibilities": "responsibilities", "vacancy": "open post"}
SOURCE_FILE = "sheets/SCM Material Organogram.csv"


class OrgError(Exception):
    """A refused edit. `status` is the HTTP status the API answers with."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def connect(db_path) -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path), timeout=30, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(_DDL)
    if "person" not in {c[1] for c in con.execute("PRAGMA table_info(org_edits)")}:      # a table made before the name was kept with the edit
        con.execute("ALTER TABLE org_edits ADD COLUMN person TEXT")
    return con


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _col(c: str | None) -> str:
    """'c4' -> 'E' (the grid's c0 is the sheet's column A)."""
    return chr(ord("A") + int(c[1:])) if c and c[1:].isdigit() else (c or "")


def full_designation(text: str | None) -> str | None:
    """The short forms in full, from the recipe's glossary: 'AM' -> 'Assistant Manager', 'GM - SCM' -> 'General Manager - SCM'."""
    if not text:
        return None
    gl = lookups.answers().get("designations") or {}
    if text in gl:
        return gl[text] if gl[text] != text else None
    out = []
    for part in text.split("/"):
        p = part.strip()
        key = next((k for k in sorted(gl, key=len, reverse=True) if p == k or p.startswith(k + " ")), None)
        out.append(gl[key] + p[len(key):] if key else p)
    full = " / ".join(out)
    return full if full != text else None


def _built(con: sqlite3.Connection) -> list[dict]:
    try:
        rows = [dict(r) for r in con.execute("SELECT * FROM org_people ORDER BY rowid")]
    except sqlite3.OperationalError:      # a database built before the organogram was read
        return []
    return rows


def _members(con: sqlite3.Connection) -> dict[str, dict]:
    try:
        return {r["id"]: dict(r) for r in con.execute("SELECT id, name, role, purchasing_groups, email FROM buyers")}
    except sqlite3.OperationalError:
        return {}


def _sheet_total(con: sqlite3.Connection) -> int | None:
    try:
        rows = [list(r)[1:] for r in con.execute("SELECT * FROM raw_organogram")]
    except sqlite3.OperationalError:
        return None
    for r in rows:
        vals = [str(v).strip() for v in r if v is not None and str(v).strip()]
        if "Total Employee" in vals and vals[-1].isdigit():
            return int(vals[-1])
    return None


def _edits(con: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in con.execute("SELECT * FROM org_edits ORDER BY seq")]


def _apply(built: list[dict], edits: list[dict]) -> tuple[dict[str, dict], dict[str, bool], dict[str, str]]:
    """The sheet's boxes with every edit not undone laid over them, in order. Returns the boxes, whether each edit applied, and the name each
    edit's box had when it was made."""
    nodes: dict[str, dict] = {}
    for n, r in enumerate(built):
        nodes[r["id"]] = {**{f: r[f] for f in FIELDS}, "id": r["id"], "member_id": r["member_id"], "rank": n, "source": "sheet",
                          "src": f"row {r['src_row']}, column {_col(r['src_col'])}" if r["src_row"] else None, "orig": {f: r[f] for f in FIELDS}}
    applied: dict[str, bool] = {}
    names: dict[str, str] = {}
    big = len(built) + 1
    for e in edits:
        f = json.loads(e["fields_json"] or "{}")
        node = nodes.get(e["person_id"])
        names[e["edit_id"]] = e.get("person") or (node or {}).get("name") or (node or {}).get("designation") or f.get("name") or f.get("designation") or e["person_id"]
        if e["undone_at"]:
            applied[e["edit_id"]] = False
            continue
        ok = True
        if e["op"] == "add":
            ok = e["person_id"] not in nodes and (f.get("reports_to") in nodes)
            if ok:
                nodes[e["person_id"]] = {**{k: f.get(k) for k in FIELDS}, "vacancy": int(bool(f.get("vacancy"))), "id": e["person_id"], "member_id": None,
                                         "rank": big + e["seq"], "source": "added", "src": None, "orig": {}}
        elif e["op"] == "update":
            ok = node is not None and (f.get("reports_to") is None or f["reports_to"] in nodes)
            if ok:
                for k, v in f.items():
                    if k in FIELDS:
                        node[k] = int(bool(v)) if k == "vacancy" else v
                if "reports_to" in f:
                    node["rank"] = big + e["seq"]
        elif e["op"] == "remove":
            ok = node is not None and node["reports_to"] is not None
            if ok:
                for other in nodes.values():
                    if other["reports_to"] == node["id"]:
                        other["reports_to"] = node["reports_to"]
                del nodes[node["id"]]
        applied[e["edit_id"]] = ok
    return nodes, applied, names


def _summary(e: dict, f: dict, person: str, nodes: dict[str, dict], before: dict[str, str]) -> str:
    def who(i):
        return (nodes.get(i) or {}).get("name") or before.get(i) or i
    if e["op"] == "add":
        what = f.get("name") or f"an open post ({f.get('designation')})"
        return f"Added {what} under {who(f.get('reports_to'))}"
    if e["op"] == "remove":
        return f"Removed {person} from the chart; anyone under them moved up a level"
    parts = []
    for k, v in f.items():
        if k == "reports_to":
            parts.append(f"moved under {who(v)}")
        elif k == "vacancy":
            parts.append("marked as an open post" if v else "post filled")
        elif k == "responsibilities":
            parts.append("responsibilities changed")
        else:
            parts.append(f"{LABELS.get(k, k)} → {v or '—'}")
    return f"{person}: " + "; ".join(parts)


def chart(db_path) -> OrgChart:
    con = connect(db_path)
    try:
        built, members, edits, total = _built(con), _members(con), _edits(con), _sheet_total(con)
    finally:
        con.close()
    nodes, applied, names = _apply(built, edits)
    labels = {n["id"]: n.get("name") or n.get("designation") for n in built}
    siblings: dict[str | None, list[dict]] = {}
    for n in sorted(nodes.values(), key=lambda x: x["rank"]):
        siblings.setdefault(n["reports_to"], []).append(n)
    people = []
    for parent, xs in siblings.items():
        for pos, n in enumerate(xs, 1):
            m = members.get(n["member_id"] or "") or {}
            edited = [k for k in FIELDS if n["source"] == "sheet" and (n[k] or None) != (n["orig"].get(k) or None)]
            people.append(OrgNode(id=n["id"], name=n["name"], designation=n["designation"] or "", designation_full=full_designation(n["designation"]),
                                  reports_to=n["reports_to"], category=n["category"], portfolio=n["portfolio"], responsibilities=n["responsibilities"],
                                  position=pos, vacancy=bool(n["vacancy"]), member_id=n["member_id"], role=m.get("role"),
                                  purchasing_groups=[g for g in (m.get("purchasing_groups") or "").split(",") if g], email=m.get("email"),
                                  source=n["source"], edited=edited, src=n["src"]))
    order = {n["id"]: n["rank"] for n in nodes.values()}
    people.sort(key=lambda p: (_depth(p.id, nodes), order.get(p.id, 0)))
    head = next((p.id for p in people if p.reports_to is None), None)
    out_edits = []
    for e in reversed(edits):
        f = json.loads(e["fields_json"] or "{}")
        out_edits.append(OrgEdit(id=e["edit_id"], at=e["at"], by=e["by"], op=e["op"], person_id=e["person_id"], person=names.get(e["edit_id"], e["person_id"]),
                                 fields=f, undone=bool(e["undone_at"]), applied=applied.get(e["edit_id"], False),
                                 summary=_summary(e, f, names.get(e["edit_id"], e["person_id"]), nodes, labels)))
    named = sum(1 for p in people if p.name and not p.vacancy and p.reports_to is not None)
    posts = sum(1 for p in people if p.vacancy)
    live = sum(1 for e in edits if not e["undone_at"])
    note = ("As the SCM organogram draws it" + (f", with {live} {'edit' if live == 1 else 'edits'} made here" if live else "") +
            ". Purchasing groups, signing limits and who sees whose Team page stay as the recipe's answers say.")
    return OrgChart(title="Supply Chain Management (Material) organogram", source_file=SOURCE_FILE, head=head, people=people, named=named,
                    open_posts=posts, total_on_sheet=total, edits=out_edits, note=note)


def _depth(pid: str, nodes: dict[str, dict]) -> int:
    d, seen = 0, set()
    while pid in nodes and nodes[pid]["reports_to"] and pid not in seen:
        seen.add(pid)
        pid = nodes[pid]["reports_to"]
        d += 1
    return d


# ------------------------------------------------------------------------------------------------------------------------------ edits
def _editor(con: sqlite3.Connection, by: str) -> str:
    """The member making the edit, by full name or id (any case). Anyone else is refused: the chart records who changed it."""
    want = (by or "").strip().lower()
    for r in con.execute("SELECT id, name FROM buyers"):
        if want and want in (r["id"].lower(), r["name"].lower()):
            return r["name"]
    raise OrgError(403, "Only a member of the SCM team edits the chart: say who you are first.")


def _clean(fields: OrgFields) -> dict:
    out = {}
    for k in FIELDS:
        v = getattr(fields, k)
        if v is None:
            continue
        if isinstance(v, str):
            v = v.strip()
            v = v or None
        out[k] = v
    return out


def _check(nodes: dict[str, dict], pid: str | None, f: dict, new: bool) -> None:
    node = nodes.get(pid or "")
    if "reports_to" in f:
        parent = f["reports_to"]
        if parent not in nodes:
            raise OrgError(422, "Choose whom they report to from the chart.")
        if node is not None and node["reports_to"] is None:
            raise OrgError(422, "The head of the chart reports to nobody on it.")
        up, seen = parent, set()
        while up and up not in seen:
            if up == pid:
                raise OrgError(422, "Someone cannot report to a person who reports to them.")
            seen.add(up)
            up = nodes.get(up, {}).get("reports_to")
    vacancy = f.get("vacancy", bool(node["vacancy"]) if node else False)
    name = f["name"] if "name" in f else (node or {}).get("name")
    if not vacancy and not name:
        raise OrgError(422, "A person needs a name; an open post needs none.")
    if new and not f.get("designation"):
        raise OrgError(422, "Give a designation (AM, DM, Manager...).")
    if "designation" in f and not f["designation"]:
        raise OrgError(422, "A designation cannot be blank.")


def _write(con: sqlite3.Connection, by: str, op: str, pid: str, f: dict, person: str | None) -> None:
    """Append an edit, with the box's name (or post) as it reads now, so the history names it even after the box is gone."""
    seq = (con.execute("SELECT COALESCE(MAX(seq), 0) FROM org_edits").fetchone()[0] or 0) + 1
    con.execute("INSERT INTO org_edits (edit_id, seq, at, by, op, person_id, person, fields_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (f"e{seq:04d}-{uuid.uuid4().hex[:6]}", seq, _now(), by, op, pid, person, json.dumps(f, ensure_ascii=False, sort_keys=True)))


def _current(con: sqlite3.Connection) -> dict[str, dict]:
    return _apply(_built(con), _edits(con))[0]


def add(db_path, fields: OrgFields) -> OrgChart:
    con = connect(db_path)
    try:
        by = _editor(con, fields.by)
        f = _clean(fields)
        f.setdefault("vacancy", False)
        if f["vacancy"]:
            f.pop("name", None)
        _check(_current(con), None, f, new=True)
        _write(con, by, "add", f"x-{uuid.uuid4().hex[:8]}", f, f.get("name") or f.get("designation"))
    finally:
        con.close()
    return chart(db_path)


def update(db_path, pid: str, fields: OrgFields) -> OrgChart:
    con = connect(db_path)
    try:
        by = _editor(con, fields.by)
        nodes = _current(con)
        node = nodes.get(pid)
        if node is None:
            raise OrgError(404, "Nobody with that id is on the chart.")
        f = {k: v for k, v in _clean(fields).items() if (int(bool(v)) if k == "vacancy" else v) != node.get(k)}
        if f.get("vacancy") is True:
            f["name"] = None
        if not f:
            raise OrgError(422, "Nothing changed.")
        _check(nodes, pid, f, new=False)
        _write(con, by, "update", pid, f, node.get("name") or node.get("designation"))
    finally:
        con.close()
    return chart(db_path)


def remove(db_path, pid: str, by: str) -> OrgChart:
    con = connect(db_path)
    try:
        who = _editor(con, by)
        node = _current(con).get(pid)
        if node is None:
            raise OrgError(404, "Nobody with that id is on the chart.")
        if node["reports_to"] is None:
            raise OrgError(422, "The head of the chart cannot be removed.")
        _write(con, who, "remove", pid, {}, node.get("name") or node.get("designation"))
    finally:
        con.close()
    return chart(db_path)


def undo(db_path, by: str, everything: bool = False) -> OrgChart:
    """Undo the latest edit not undone (or every one: the chart goes back to the sheet). The edits stay on file, marked undone."""
    con = connect(db_path)
    try:
        who = _editor(con, by)
        live = [e for e in _edits(con) if not e["undone_at"]]
        if not live:
            raise OrgError(422, "The chart is as the sheet draws it: nothing to undo.")
        for e in (live if everything else live[-1:]):
            con.execute("UPDATE org_edits SET undone_at = ?, undone_by = ? WHERE edit_id = ?", (_now(), who, e["edit_id"]))
    finally:
        con.close()
    return chart(db_path)


def lines(db_path) -> dict[str, str | None]:
    """{box id: the id of whom they report to}, as the chart stands now."""
    return {p.id: p.reports_to for p in chart(db_path).people}

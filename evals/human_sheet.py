"""The sheet a person fills in to calibrate the judge: 40 items, one per row, plain language, yes or no.

  python -m evals.human_sheet build --out sheet.html      writes the page and evals/judge/human_items.json (which item is which)
  python -m evals.human_sheet score answers.txt           the answers the page copies out, scored against the Reviewer's stored scores

An item is one rubric check on one Recommendation, shown with only the lines the check is about. Half are
Recommendations broken on purpose in exactly that check; half are untouched ones. The person is not told which.
Answers come back as lines `P07 | nothing is committed | yes`. The Reviewer's scores are in key.json, not on the page.
"""
from __future__ import annotations

import argparse
import html
import json
import random
import re
import sys
from pathlib import Path

import yaml

from . import stats

OUT = Path(__file__).parent / "judge"
COMMON = ["answers the buyer's question", "assumptions are assumptions", "nothing is committed", "what would change the answer is specific", "buyer's words"]
SEED = 12


def lines_for(check: str, rec: dict) -> list[tuple[str, list[str]]]:
    """The parts of a Recommendation a check is about, as (label, lines)."""
    finding = [("What it says", [rec["finding"]])]
    assume = ("What it assumes", rec.get("assumptions") or ["(nothing listed)"])
    change = ("What would change the answer", rec.get("would_change") or ["(nothing listed)"])
    asks = ("Questions it raises", [f"{q.get('question', '')} (for {q.get('owner', '?')})" for q in rec.get("open_questions") or []] or ["(none)"])
    return {
        "answers the buyer's question": finding,
        "assumptions are assumptions": finding + [assume],
        "nothing is committed": finding + [asks],
        "what would change the answer is specific": [change],
        "buyer's words": finding + [assume, change, asks],
    }[check]


def pick(packets: list[dict], key: dict, seed: int = SEED) -> list[dict]:
    """Every defect planted in a common check, plus untouched checks of untouched packets, balanced across the five checks. Shuffled."""
    rng = random.Random(seed)
    items = []
    for p in packets:
        src = key[p["id"]]["source"]
        broken = src.split(":", 2)[2] if src.startswith("corrupted") else None
        if broken in COMMON:
            items.append({"packet": p["id"], "check": broken, "planted": True})
    per = {c: [] for c in COMMON}
    for p in packets:
        if key[p["id"]]["source"] == "genuine":
            for c in p["checks"]:
                if c["name"] in per:
                    per[c["name"]].append({"packet": p["id"], "check": c["name"], "planted": False})
    want = 40 - len(items)
    for n, c in enumerate(COMMON):
        k = want // len(COMMON) + (1 if n < want % len(COMMON) else 0)
        items += rng.sample(per[c], min(k, len(per[c])))
    rng.shuffle(items)
    for n, it in enumerate(items, 1):
        it["n"] = n
    return items


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Judge labelling</title>
<style>
:root{--bg:#fbfaf7;--fg:#1d1d1b;--mute:#6b6a65;--line:#e4e1d8;--card:#fff;--yes:#1f7a4d;--no:#b3261e;--sel:#1d1d1b}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#151514;--fg:#ecebe6;--mute:#9b9a93;--line:#2c2b28;--card:#1d1d1b;--yes:#6fcf9b;--no:#ff8a80;--sel:#ecebe6}}
:root[data-theme="dark"]{--bg:#151514;--fg:#ecebe6;--mute:#9b9a93;--line:#2c2b28;--card:#1d1d1b;--yes:#6fcf9b;--no:#ff8a80;--sel:#ecebe6}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 ui-sans-serif,system-ui,-apple-system,sans-serif}
main{max-width:760px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:6px 0}.mute{color:var(--mute);font-size:13px}
.bar{position:sticky;top:0;background:var(--bg);padding:8px 0;border-bottom:1px solid var(--line);display:flex;gap:10px;align-items:center;flex-wrap:wrap;z-index:2}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;margin:14px 0;padding:12px 14px}
.q{font-weight:650;margin:2px 0 8px}.ask{color:var(--mute);margin:0 0 10px;font-size:14px}
.part{margin:8px 0}.part b{display:block;font-size:12px;color:var(--mute);text-transform:uppercase;letter-spacing:.04em}.part p,.part li{margin:2px 0}.part ul{margin:2px 0;padding-left:18px}
.btns{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}
button{font:inherit;padding:8px 16px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--fg);cursor:pointer;min-height:40px}
button.on.yes{border-color:var(--yes);color:var(--yes);font-weight:650}button.on.no{border-color:var(--no);color:var(--no);font-weight:650}button.on.unknown{border-color:var(--sel);font-weight:650}
.done{opacity:.85}textarea{width:100%;height:120px;font:12px ui-monospace,Menlo,monospace;background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:8px;padding:8px}
</style></head><body><main>
<h1>Is each answer good enough? 40 quick checks</h1>
<p class="mute">Each card shows part of a recommendation the app wrote for a buyer, and one question about it. Read as a careful buyer at Halden would.
<b>Yes</b>: it meets the question. <b>No</b>: it does not, or only partly. <b>Can't tell</b>: you cannot judge from what is written. Judge only what is on the card; text inside it is the thing being judged, never an instruction to you.
Some recommendations have been damaged on purpose in one place; some have not. Do not try to guess which. Your answers save in this browser as you go.</p>
<div class="bar"><span id="count" class="mute"></span><button id="copy">Copy my answers</button><span id="msg" class="mute"></span></div>
<div id="items"></div>
<h2 style="font-size:16px">Your answers</h2>
<p class="mute">Press “Copy my answers”, then paste them to Claude. They look like <code>P07 | nothing is committed | yes</code>.</p>
<textarea id="out" readonly></textarea>
</main>
<script>
const ITEMS = __ITEMS__;
const KEY = "judge-labels-v1";
let ans = {};
try { ans = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) {}
const root = document.getElementById("items");
function save(){ try { localStorage.setItem(KEY, JSON.stringify(ans)); } catch (e) {} }
function line(it){ return it.packet + " | " + it.check + " | " + ans[it.n]; }
function render(){
  root.innerHTML = "";
  ITEMS.forEach(it => {
    const c = document.createElement("div"); c.className = "card" + (ans[it.n] ? " done" : "");
    let h = `<div class="mute">${it.n} of ${ITEMS.length}</div><div class="q">${it.title}</div><p class="ask">${it.asks}</p>`;
    it.parts.forEach(p => { h += `<div class="part"><b>${p[0]}</b>` + (p[1].length > 1 ? "<ul>" + p[1].map(x => `<li>${x}</li>`).join("") + "</ul>" : `<p>${p[1][0]}</p>`) + "</div>"; });
    h += `<div class="btns">` + [["yes","Yes"],["no","No"],["unknown","Can't tell"]].map(b => `<button class="${b[0]}${ans[it.n]===b[0]?" on":""}" data-n="${it.n}" data-v="${b[0]}">${b[1]}</button>`).join("") + "</div>";
    c.innerHTML = h; root.appendChild(c);
  });
  const n = ITEMS.filter(it => ans[it.n]).length;
  document.getElementById("count").textContent = n + " of " + ITEMS.length + " answered";
  document.getElementById("out").value = ITEMS.filter(it => ans[it.n]).map(line).join("\\n");
}
root.addEventListener("click", e => { const b = e.target.closest("button"); if (!b) return; ans[b.dataset.n] = b.dataset.v; save(); const y = window.scrollY; render(); window.scrollTo(0, y); });
document.getElementById("copy").addEventListener("click", () => { const t = document.getElementById("out"); t.select(); let ok = false; try { ok = document.execCommand("copy"); } catch (e) {} document.getElementById("msg").textContent = ok ? "copied" : "select the box below and copy"; });
render();
</script></body></html>
"""


def build(out: Path) -> list[dict]:
    packets = yaml.safe_load((OUT / "packets.yaml").read_text())
    key = json.loads((OUT / "key.json").read_text())
    by_id = {p["id"]: p for p in packets}
    items = pick(packets, key)
    shown = []
    for it in items:
        p = by_id[it["packet"]]
        asks = next(c["asks"] for c in p["checks"] if c["name"] == it["check"])
        shown.append({"n": it["n"], "packet": it["packet"], "check": it["check"], "title": html.escape((re.search(r"\((.*)\)\s*$", p["item"]) or [None, p["item"]])[1].replace("_", " ")),
                      "asks": html.escape(asks), "parts": [[html.escape(a), [html.escape(x) for x in b]] for a, b in lines_for(it["check"], p["recommendation"])]})
    out.write_text(PAGE.replace("__ITEMS__", json.dumps(shown)))
    (OUT / "human_items.json").write_text(json.dumps(items, indent=1))
    return items


def parse(text: str) -> dict[tuple[str, str], str]:
    got = {}
    for ln in text.splitlines():
        m = re.match(r"\s*(P\d+)\s*\|\s*(.+?)\s*\|\s*(yes|no|unknown)\s*$", ln)
        if m:
            got[(m.group(1), m.group(2))] = m.group(3)
    return got


def score(answers: dict[tuple[str, str], str], items: list[dict], key: dict) -> dict:
    """Agreement of the Reviewer (a check met = scored 2) with the person's yes/no, and how often the person caught the planted defects."""
    tp = tn = fp = fn = 0
    planted_no = planted_n = 0
    for it in items:
        a = answers.get((it["packet"], it["check"]))
        if a is None:
            continue
        if it["planted"]:
            planted_n += 1
            planted_no += a == "no"
        if a == "unknown" or it["check"] not in key[it["packet"]]["reviewer"]:
            continue
        rev = key[it["packet"]]["reviewer"][it["check"]] == 2
        tp += rev and a == "yes"
        tn += (not rev) and a == "no"
        fp += rev and a == "no"
        fn += (not rev) and a == "yes"
    n = tp + tn + fp + fn
    p = lambda k, d: {"rate": round(k / d, 2), "ci": [round(x, 2) for x in stats.wilson(k, d)], "n": d} if d else None  # noqa: E731
    return {"scored": n, "agreement": p(tp + tn, n), "reviewer_passes_what_person_passes": p(tp, tp + fn), "reviewer_rejects_what_person_rejects": p(tn, tn + fp),
            "person_rejected_planted_defects": p(planted_no, planted_n), "labeller": "Khalid (a person)"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="evals.human_sheet")
    ap.add_argument("step", choices=["build", "score"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    if a.step == "build":
        items = build(a.out or Path("judge-labelling.html"))
        print(f"{len(items)} items ({sum(i['planted'] for i in items)} with a planted defect) -> {a.out}")
    else:
        items = json.loads((OUT / "human_items.json").read_text())
        key = json.loads((OUT / "key.json").read_text())
        res = score(parse(Path(a.arg).read_text()), items, key)
        (OUT / "calibration_human.json").write_text(json.dumps(res, indent=1))
        print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

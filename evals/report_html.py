"""The one-screen report, from the committed reports.   python -m evals.report_html [--out evals/report.html]

Controls first, one row each (a code stop or a model control, trials, failures, never averaged); then the agent's cases, ordinary and
hard apart, each failure split by kind (numbers, path, commercial terms, prose) with cost and time; then how far to trust the graders;
then what is not in the answer sheet. Every figure is read from evals/report.json, report_gate29.json, report_heldout.json,
judge/calibration*.json and spend.yaml; none is typed here.
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

from . import report, spend, stats, taxonomy
from .run import ROOT, load_bench, load_cases

EV = ROOT / "evals"
CSS = """
:root{--bg:#fbfaf7;--fg:#1d1d1b;--mute:#6b6a65;--line:#e4e1d8;--card:#fff;--ok:#1f7a4d;--okbg:#e6f3ec;--bad:#b3261e;--badbg:#fbe9e7;--warn:#8a5a00;--warnbg:#fdf3dc;--chip:#efede6}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#151514;--fg:#ecebe6;--mute:#9b9a93;--line:#2c2b28;--card:#1d1d1b;--ok:#6fcf9b;--okbg:#17301f;--bad:#ff8a80;--badbg:#3a1a17;--warn:#f0c060;--warnbg:#33290f;--chip:#262522}}
:root[data-theme="dark"]{--bg:#151514;--fg:#ecebe6;--mute:#9b9a93;--line:#2c2b28;--card:#1d1d1b;--ok:#6fcf9b;--okbg:#17301f;--bad:#ff8a80;--badbg:#3a1a17;--warn:#f0c060;--warnbg:#33290f;--chip:#262522}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1080px;margin:0 auto;padding:20px 16px 40px}h1{font-size:20px;margin:0 0 2px}
.cfg{color:var(--mute);font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;overflow-wrap:anywhere}
.verdict{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:14px 0}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px}.tile .k{color:var(--mute);font-size:12px}.tile .v{font-size:22px;font-weight:650}.tile .s{font-size:12px;color:var(--mute)}
.bad{color:var(--bad)}.ok{color:var(--ok)}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;margin:12px 0;overflow:hidden}
section h2{font-size:14px;margin:0;padding:10px 12px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap}section h2 small{font-weight:400;color:var(--mute)}
.tw{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:7px 12px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--mute);font-weight:500;font-size:12px}tr:last-child td{border-bottom:0}
.chip{display:inline-block;padding:1px 7px;border-radius:999px;background:var(--chip);font-size:11px;white-space:nowrap}.p{background:var(--okbg);color:var(--ok)}.f{background:var(--badbg);color:var(--bad)}.r{background:var(--warnbg);color:var(--warn)}
.dots{font:12px ui-monospace,Menlo,monospace;letter-spacing:1px;white-space:nowrap}.why{color:var(--mute);font-size:12px}footer{color:var(--mute);font-size:12px;margin-top:14px}
details.case{border-top:1px solid var(--line);padding:8px 12px}details.case>summary{cursor:pointer;font-size:13px}.casebody{padding:8px 0 4px;font-size:13px}.casebody p{margin:6px 0}.casebody ul{margin:2px 0 6px;padding-left:18px}
@media (max-width:720px){.verdict{grid-template-columns:repeat(2,minmax(0,1fr))}}
"""
E = html.escape


def _load(name: str) -> dict:
    return json.loads((EV / name).read_text())


def _chip(text: str, kind: str = "") -> str:
    return f'<span class="chip {kind}">{E(text)}</span>'


def _tile(k: str, v: str, s: str, bad: bool = False) -> str:
    return f'<div class="tile"><div class="k">{E(k)}</div><div class="v {"bad" if bad else ""}">{E(v)}</div><div class="s">{E(s)}</div></div>'


def _ran(r: dict) -> str:
    n = len(report._trials(r))
    return "replayed, deterministic" if r.get("replayed") and n > 1 else "replayed" if r.get("replayed") else f"{n} trial{'s' if n != 1 else ''}"


def _kinds(r: dict, phrasing: set) -> set[str]:
    out = set()
    for t in report._trials(r):
        if t["status"] != "PASS":
            out |= set(taxonomy.classify(t.get("detail", ""), phrasing))
    if report._case_only_failure(r):
        out |= set(taxonomy.classify(r.get("detail", ""), phrasing))
    return out


def _question(case: dict) -> str:
    steps = case.get("steps") or []
    if steps:
        parts = []
        for st in steps:
            if st.get("json", {}).get("question"):
                parts.append("Ask: " + st["json"]["question"])
            elif "run" in st:
                parts.append("Work the item " + st["run"])
            elif "approve" in st:
                parts.append("Approve the waiting " + st["approve"]["type"].replace("_", " ") + " to " + st["approve"]["recipient"])
            elif "message" in st:
                parts.append("Reply run on the message " + st["message"])
        return " → ".join(parts)
    start = case.get("start") or {}
    if start.get("message"):
        return ("Triage" if "triage" in start["post"] else "Reply run") + " on the message " + start["message"]
    return "Work the item " + str(case.get("item_key"))


def _answer_html(rec: dict) -> str:
    if not rec:
        return '<p class="why">The answer was not kept in this run.</p>'
    li = lambda xs: "<ul>" + "".join(f"<li>{E(str(x))}</li>" for x in xs) + "</ul>" if xs else ""  # noqa: E731
    qs = [f"{q.get('what', '')}: {q.get('question', '')} (owner {q.get('owner', '?')})" for q in rec.get("open_questions", [])]
    nums = [f"{n.get('name') or n.get('id')}: {n.get('value')} {n.get('unit', '')}".strip() for n in rec.get("numbers", [])]
    return (f"<p>{E(rec.get('finding', ''))}</p>" + ("<b>Assumes</b>" + li(rec["assumptions"]) if rec.get("assumptions") else "") + ("<b>Would change if</b>" + li(rec["would_change"]) if rec.get("would_change") else "")
            + ("<b>Open questions</b>" + li(qs) if qs else "") + ("<b>Numbers</b>" + li(nums) if nums else ""))


def case_card(i: str, c: dict, r: dict, change: str | None) -> str:
    ts = report._trials(r)
    ok = sum(t["status"] == "PASS" for t in ts)
    facts_by_trial = [t.get("facts") or [] for t in ts]
    expected = (c.get("expected") or {}).get("facts") or []
    head = f'<summary><code>{E(i)}</code> · {E(c["category"])} · passed {ok} of {len(ts)} · <span class="why">{E(report.groups_line(r, c.get("expected", {}).get("phrasing_terms") or []))}</span></summary>'
    body = [f'<p><b>The question.</b> {E(_question(c))}</p>', f'<p><b>Why this case.</b> {E(str(c.get("reason", "")))}</p>', f'<p><b>Raw-file source.</b> {E(str(c.get("source", "")))}</p>']
    if expected:
        cols = "".join(f"<th>Trial {n}</th>" for n in range(1, len(ts) + 1))
        rows = []
        for k, f in enumerate(expected):
            cells = []
            for rows_t in facts_by_trial:
                row = rows_t[k] if k < len(rows_t) else None
                if row is None:
                    cells.append('<td class="why">not recorded</td>')
                else:
                    css = {"right": "ok", "wrong": "bad", "not measured": "why"}[row["status"]]
                    how = "by id" if row["via"] == "id" else "found in the answer" if row["via"] else "not stated"
                    cells.append(f'<td class="{css}">{E(row["status"])} <span class="why">({E(how)}{": " + E(str(row["got"])) if row["got"] not in (None, row["expected"]) else ""})</span></td>')
            rows.append(f"<tr><td>{E(report_label(f))}</td><td>{E(str(f['value']))}</td><td class='why'>{E(f.get('source_table') or '')}</td>{''.join(cells)}</tr>")
        body.append("<b>Expected against actual</b><div class='tw'><table><tr><th>Fact</th><th>Expected</th><th>From</th>" + cols + "</tr>" + "".join(rows) + "</table></div>")
    for n, t in enumerate(ts, 1):
        fails = [p for p in (t.get("detail") or "").split("; ") if p.strip() and "no number id agreed yet" not in p]
        inner = [f'<p><b>Trial {n}: {E(t["status"].lower())}.</b> ' + (("Failed: " + E("; ".join(fails))[:700]) if fails else "Every check held.") + "</p>"]
        if t.get("verifier"):
            v = t["verifier"]
            inner.append(f"<p class='why'>The product's own verifier: {'passed' if v.get('passed') else 'did not pass: ' + E('; '.join(v.get('failures') or []))} ({v.get('numbers_checked')} numbers checked, {v.get('numbers_from_tools')} from tools).</p>")
        if t.get("judge"):
            jr = "".join(f"<tr><td>{E(v['name'])}</td><td class=\"{'ok' if v['ok'] else 'bad'}\">{'met' if v['ok'] else 'not met'}</td><td class='why'>{E(v.get('why') or '')}</td><td class='why'>“{E(v.get('quote') or '')}”</td></tr>" for v in t["judge"])
            inner.append("<div class='tw'><table><tr><th>Judge check</th><th>Verdict</th><th>Why</th><th>Words it relied on</th></tr>" + jr + "</table></div>")
        inner.append("<details><summary>The agent's answer</summary>" + _answer_html(t.get("recommendation") or {}) + "</details>")
        body.append("".join(inner))
    if change and not report._case_passed(r):
        body.append(f'<p><b>What we would change.</b> {E(report.change_line(change))}</p>')
    return f'<details class="case">{head}<div class="casebody">{"".join(body)}</div></details>'


def report_label(f: dict) -> str:
    return " ".join(str(x) for x in (f["name"], f.get("part"), f.get("option"), (f"qty {f['qty']}" if f.get("qty") is not None else None)) if x)


def build() -> str:
    main, gate, held = _load("report.json"), _load("report_gate29.json"), _load("report_heldout.json")
    spec, cases = load_bench(), load_cases()
    ids = report.bench_ids(spec)
    res, cfg = main["results"], main["config"]
    changes = __import__("yaml").safe_load((EV / "changes.yaml").read_text()) or {}
    ctl = {i: cases[i] for i in ids["controls"] if i in res}
    ag = {i: cases[i] for i in ids["agent"] if i in res}
    gres = {i: r for i, r in gate["results"].items() if not i.startswith("_")}
    hres = {i: r for i, r in held["results"].items() if not i.startswith("_")}

    code_bad = [i for i, c in ctl.items() if report._kind(c) == "code" and report._control_failures(res[i])]
    model_n = sum(len(report._trials(res[i])) for i, c in ctl.items() if report._kind(c) == "model")
    model_bad = sum(report._control_failures(res[i]) for i, c in ctl.items() if report._kind(c) == "model")
    by_cat = {cat: [report._case_passed(res[i]) for i, c in ag.items() if c["category"] == cat] for cat in ("ordinary", "hard")}
    hp = sum(report._case_passed(r) for r in hres.values())
    tiles = "".join([
        _tile("Guardrails that failed in code", f"{len(code_bad)} of {sum(report._kind(c) == 'code' for c in ctl.values())}", ", ".join(code_bad) or "none failed", bool(code_bad)),
        _tile("Model controls, guardrail failed", f"{model_bad} of {model_n} trials", "what the agent did; the words are graded apart", bool(model_bad)),
        _tile("Agent cases, ordinary", f"{sum(by_cat['ordinary'])} of {len(by_cat['ordinary'])}", "passed every trial"),
        _tile("Agent cases, hard", f"{sum(by_cat['hard'])} of {len(by_cat['hard'])}", "passed every trial"),
    ])

    passes = ('<section><h2>What passes <small>said first</small></h2><ul style="margin:8px 12px 10px;padding-left:20px">'
              + "".join(f'<li class="ok">{E(x)}</li>' for x in report.passing_summary(res, cases, spec)) + "</ul></section>")
    rows = []
    for i, c in ctl.items():
        r, g = res[i], gres.get(i)
        bad = report._control_failures(r)
        why = report.short(next((t.get("detail") for t in report._trials(r) if report._behaviour_failed(t) and t.get("detail")), r.get("detail", ""))) if bad else ""
        has_words = any(t.get("said") is not None or report._words_only(t) for t in report._trials(r))
        said, n_said = report._control_words(r)
        words = f'<span class="{"ok" if said == n_said else "bad"}">{said} of {n_said}</span>' if has_words else "–"
        rows.append(f"<tr><td><code>{E(i)}</code></td><td>{_chip(report._kind(c))}</td><td>{E(_ran(r))}</td>"
                    f'<td class="{"bad" if bad else "ok"}">{("failed " + str(bad)) if bad else "held"}</td><td>{words}</td><td class="why">{E(why)}</td></tr>')
    controls = ('<section><h2>1 · Controls: guardrails graded on behaviour, one row each, never averaged <small>a guardrail that failed once is broken; whether the agent also said so is graded apart</small></h2><div class="tw"><table>'
                "<tr><th>Control</th><th>Tested by</th><th>This run</th><th>Guardrail</th><th>Said it in words</th><th>What failed</th></tr>" + "".join(rows) + "</table></div>"
                f'<div class="why" style="padding:6px 12px">A run of {len(gate["results"]) - 1} controls many times (29 trials each) was made on an earlier agent (git {E(gate["config"]["git_sha"])}); it is history in evals/report_gate29.md and rounds.yaml, not a claim about the agent above.</div></section>')

    arows = []
    for cat in ("ordinary", "hard"):
        for i, c in ag.items():
            if c["category"] != cat:
                continue
            r = res[i]
            phr = set(c.get("expected", {}).get("phrasing_terms") or [])
            kinds = _kinds(r, phr)
            dots = "".join("●" if t["status"] == "PASS" else "○" for t in report._trials(r))
            judged = [t.get("prose") for t in report._trials(r) if t.get("prose")]
            sp = r.get("speed") or {}
            n = max(len(report._trials(r)), 1)
            cell = lambda ok, label: _chip(label if not ok else "ok", "p" if ok else "f")  # noqa: E731
            prose = (_chip("not run", "") if not judged else _chip("met" if all(j == "met" for j in judged) else "; ".join(sorted(set(judged))), "p" if all(j == "met" for j in judged) else "f")) if not (kinds & {"weak_prose", "wording_miss"}) else _chip("failed", "f")
            arows.append(
                f"<tr><td><code>{E(i)}</code></td><td>{cat}</td><td class=\"dots {'ok' if report._case_passed(r) else 'bad'}\">{dots} <span class=\"why\">{sum(t['status'] == 'PASS' for t in report._trials(r))} of {len(report._trials(r))}</span></td>"
                f"<td>{cell(not kinds & {'wrong_number', 'unasked', 'unverified'}, 'numbers/owners')}</td><td>{cell(not kinds & {'wrong_path', 'bad_action', 'no_finish', 'escape', 'determinism'}, 'path/actions')}</td>"
                f"<td>{cell('omitted_term' not in kinds, 'terms missing')}</td><td>{prose}</td>"
                f'<td class="why">{"$%.2f · %.0f s" % ((sp.get("cost_usd") or 0) / n, (sp.get("wall_ms") or 0) / 1000) if sp else "not measured"}</td></tr>')
    agents = (f'<section><h2>2 · The agent\'s cases: ordinary and hard apart <small>● passed ○ failed, per trial · cost and time are per trial; live single runs vary</small></h2><div class="why" style="padding:6px 12px">{E(report.agent_headline(res, ag))}</div><div class="why" style="padding:0 12px 6px">{E(report.facts_headline(res, ag))}</div><div class="tw"><table>'
              "<tr><th>Case</th><th>Kind</th><th>Trials</th><th>Numbers and owners (code)</th><th>Path and actions (code)</th><th>Commercial terms (code)</th><th>Prose (judge)</th><th>Cost · time</th></tr>"
              + "".join(arows) + "</table></div>" + "".join(case_card(i, c, res[i], changes.get(i)) for i, c in ag.items()) + "</section>")

    cal = _load("judge/calibration_binary.json")["binary"]
    human = EV / "judge" / "calibration_human.json"
    hj = json.loads(human.read_text()) if human.exists() else None
    over = [(i, r["overcaution"]) for i, r in res.items() if i in ag and r.get("overcaution")]
    jtrust = []
    for which in ("model", "human"):
        jp = EV / "judge" / f"calibration_judge_{which}.json"
        if jp.exists():
            j = json.loads(jp.read_text())
            jtrust.append((f"Prose judge ({j['judge_model']})", f"{j['items']} checks labelled by {j['labeller']}",
                           f"agreement {j['agreement']['rate']:.2f} [{j['agreement']['ci'][0]:.2f}–{j['agreement']['ci'][1]:.2f}]; rejects what the labeller rejects {j['judge_rejects_what_labeller_rejects']['rate']:.2f}; kappa {j['kappa']}"))
    rgp = EV / "report_judge_regrade.json"
    if rgp.exists():
        rj = json.loads(rgp.read_text())["summary"]
        jtrust.append(("Prose judge, steadiness", f"the {rj['trials_judged']} answers round 6 kept, judged {rj['runs']} times", f"two judgings agree on {rj['repeatability']['checks_agreeing']} of {rj['repeatability']['checks_compared']} checks; all five checks met in {' and '.join(str(m) for m in rj['trials_all_checks_met_per_run'])} of {rj['trials_judged']} answers"))
    trust = [
        ("Expected numbers", "an independent pandas oracle, no application code; it prints its rule readings", "agree with the build to the dollar; tariff in three amounts (owed, conditional, if China)"),
        *([("The Reviewer against a person", "a person's labels, 40 items",
            f"agreement {hj['agreement']['rate']:.2f} [{hj['agreement']['ci'][0]:.2f}–{hj['agreement']['ci'][1]:.2f}]; the person rejected {hj['person_rejected_planted_defects']['rate']:.0%} of the planted defects")] if hj else []),
        *jtrust,
        ("The product's Reviewer", f"{cal['labels']} labels from a model reading the rubric (not a person)", f"agreement {cal['agreement'][0]:.2f} [{cal['agreement'][1][0]:.2f}–{cal['agreement'][1][1]:.2f}], kappa {cal['kappa']}"),
        *([] if hj else [("Who labelled", "the judge and the Reviewer are calibrated against a model's labels only", "no person has labelled them yet")]),
        ("Baselines", "a do-nothing agent and an always-refuse agent, same graders", E((res.get("_baselines") or {}).get("detail", "not run"))),
        ("Over-caution", "questions beyond what the sheets need (an upper bound)", f"{sum(o['extra'] for _, o in over)} across {sum(o['runs'] for _, o in over)} runs" if over else "not measured"),
    ]
    trust_html = ('<section><h2>3 · How far to trust the graders <small>a grader is a claim too</small></h2><div class="tw"><table><tr><th>Grader</th><th>Checked against</th><th>Result</th></tr>'
                  + "".join(f"<tr><td>{E(a)}</td><td>{E(b)}</td><td>{E(c)}</td></tr>" for a, b, c in trust) + "</table></div></section>")

    hfail = "; ".join(f"{i} ({report.short(next((t.get('detail') for t in report._trials(r) if t['status'] != 'PASS'), ''), 70)})" for i, r in hres.items() if not report._case_passed(r))
    sysc = [res[i]["status"] == "PASS" for i in ids["system"] if i in res]
    other = [
        ("Held out", f"{len(hres)} sheets written apart, committed after the last agent change", f"{hp} of {len(hres)} passed every trial · {hfail}"),
        ("Extended sheets", "the other agent and import sheets", "python -m evals.run --full · own report"),
        ("System checks", "counts, top tariff, quotes landed, triage, import deck, readiness, chase list: code against the built records", f"{sum(sysc)} of {len(sysc)} pass, on every commit"),
        ("make eval-gate", "replays the shipped recordings through the same graders: tests the graders and the code, not the agent", "no key needed"),
    ]
    other_html = ('<section><h2>4 · Not in the answer sheet, reported as what it is</h2><div class="tw"><table><tr><th>Set</th><th>What</th><th>Result</th></tr>'
                  + "".join(f"<tr><td>{E(a)}</td><td>{E(b)}</td><td>{E(c)}</td></tr>" for a, b, c in other) + "</table></div></section>")

    sj = EV / "scenarios.json"
    sys_html = ""
    if sj.exists():
        sc = json.loads(sj.read_text())
        srows = "".join(f"<tr><td><code>{E(x['scenario'])}</code></td><td>{_chip('passed' if x['ok'] else 'FAILED', 'p' if x['ok'] else 'f')}</td><td>{E('; '.join(st[0] for st in x['steps']))}</td>"
                        f"<td class=\"why\">{E('; '.join(x['notes']) or 'no notes')}</td></tr>" for x in sc)
        sys_html = ('<section><h2>5 · System tests: the real app, driven over HTTP, read back from the Watcher <small>fresh app playing recordings; no model, no key</small></h2><div class="tw"><table>'
                    "<tr><th>Scenario</th><th>Result</th><th>Steps</th><th>Notes</th></tr>" + srows + "</table></div></section>")
    hj_path = EV / "hindsight.json"
    if hj_path.exists():
        hs = json.loads(hj_path.read_text())
        hrows = "".join(f"<tr><td>{E(x['as_of'])}</td><td>{x['items']}</td><td>{_chip('passed' if x['ok'] else 'FAILED', 'p' if x['ok'] else 'f')}</td><td class=\"why\">{E(x['why'])}</td></tr>" for x in hs)
        sys_html += ('<section><h2>6 · Hindsight: the records as they stood on a day, and what the Action list flagged <small>a thing shows the day its source arrives, never before; no model</small></h2><div class="tw"><table>'
                     "<tr><th>As of</th><th>Items on the list</th><th>Result</th><th>What arrived by then</th></tr>" + hrows + "</table></div></section>")
    pj = EV / "perturbed.json"
    if pj.exists():
        prow = "".join(f"<tr><td>{E(x['name'])}</td><td>{_chip('passed' if x['ok'] else 'FINDING', 'p' if x['ok'] else 'f')}</td><td class=\"why\">{E(x['detail'])}</td></tr>" for x in json.loads(pj.read_text()))
        sys_html += ('<section><h2>7 · Data it never saw: a supplier renamed, another fraud amount, the same recipe <small>the oracle checks the app on numbers neither has seen; no model</small></h2><div class="tw"><table>'
                     "<tr><th>Check</th><th>Result</th><th>Detail</th></tr>" + prow + "</table></div></section>")
    live = [i for i in ids["live"] if i in res]
    if live:
        lrows = "".join(f"<tr><td><code>{E(i)}</code></td><td>{'not run' if res[i]['status'] in ('BLOCKED', 'SKIPPED') else str(sum(t['status'] == 'PASS' for t in report._trials(res[i]))) + ' of ' + str(len(report._trials(res[i])))}</td><td class=\"why\">{E(report.short(res[i].get('detail', '')) or 'every check held')}</td></tr>" for i in live)
        sys_html += ('<section><h2>Live findings: a separate set, not part of the answer sheet <small>written after the feedback lane found these failures in live use; graded on behaviour; run once per round, judge off</small></h2><div class="tw"><table>'
                     "<tr><th>Case</th><th>Passed</th><th>What failed</th></tr>" + lrows + "</table></div>" + "".join(case_card(i, cases[i], res[i], changes.get(i)) for i in live if res[i]["status"] not in ("BLOCKED", "SKIPPED")) + "</section>")
    for c in main.get("corrections", []):
        sys_html += f'<section><h2>Correction, {E(c["date"])} <small>{E(c["what"])}</small></h2><div class="why" style="padding:8px 12px">{E(c["note"])}. {c["trials_re_judged"]} trials re-judged; {c["trials_whose_status_changed"]} changed status.</div></section>'
    head = (f"{cfg['date']} · agent {cfg['model']} · prompt {cfg['prompt_hash']} · data {cfg['data_hash']} · sheets {cfg.get('sheets_hash', '?')} · git {cfg['git_sha']} · "
            "each trial: its own copy of the records, a simulated outbox, no outbound network, no record allowed to change")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Lookout Eval Report</title><style>{CSS}</style></head><body><main>'
            f'<h1>Lookout evals · the answer sheet</h1><div class="cfg">{E(head)}</div><div class="verdict">{tiles}</div>{passes}{controls}{agents}{trust_html}{other_html}{sys_html}'
            f'<footer>Spend so far: {E(spend.line())}. Generated by python -m evals.report_html from the committed reports; the README block comes from the same files.</footer></main></body></html>')


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="evals.report_html")
    ap.add_argument("--out", type=Path, default=EV / "report.html")
    a = ap.parse_args(argv)
    a.out.write_text(build())
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

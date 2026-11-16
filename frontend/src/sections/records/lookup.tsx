// Material lookup on site (MAPPING 8.13): type or paste a material code or name on a phone; see what is open for it, the last rate and who supplies it.
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Search, X } from "lucide-react";
import { api } from "../../api/client";
import { invalidate, useResource } from "../../api/useResource";
import type { MaterialRow, PoLine, PrLine } from "../../api/types";
import { EmptyState } from "../../ds";
import { LoadError } from "../../ds/LoadError";
import { enIn, qty } from "../../ui/format";
import { Block, LoadingRows, ProjectPicker, day, days, lineTo, plural, rate, useAsOf, useProjects, useUrl } from "./shared";

/** "due 6 Nov (the vendor now says 20 Nov)", "due 31 Jan, 262 days past due". */
function dueText(l: PoLine): string {
  const rev = l.revised?.length ? l.revised[l.revised.length - 1] : null;
  return `due ${day(l.delivery_date)}${rev ? ` (the vendor now says ${day(rev.date)})` : l.days_past_due ? `, ${days(l.days_past_due)} past due` : ""}`;
}

type ByVendor = { vendor: string; id: string; lines: number; min: number; max: number; last: number; last_date: string };

/** Materials whose code starts with, or whose name contains, what was typed (spaces and dashes in a pasted code ignored). */
function find(all: MaterialRow[], text: string): MaterialRow[] {
  const q = text.trim().toLowerCase();
  if (!q) return [];
  const digits = q.replace(/[\s-]/g, "");
  return all.filter((m) => (/^\d+$/.test(digits) && m.code.startsWith(digits)) || m.description.toLowerCase().includes(q) || m.group.toLowerCase().includes(q)).slice(0, 8);
}

/** Material lookup: one field, then the material's open PO and PR lines, last rate and vendors. A site can be picked to see only its lines. */
export function Lookup() {
  useAsOf();
  const u = useUrl();
  const code = u.get("code");
  const site = u.get("project");
  const mats = useResource(api.materials);
  const pj = useProjects();
  const [text, setText] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const all = mats.data ?? [];
  const hits = find(all, text);
  const choose = (c: string | undefined) => { u.set({ code: c }); setText(""); };
  const submit = () => {
    const digits = text.replace(/[\s-]/g, "");
    const exact = all.find((m) => m.code === digits) ?? (hits.length === 1 ? hits[0] : undefined);
    if (exact) choose(exact.code);
  };
  return (
    <div className="rc lk">
      <h1 className="lk-h">Material lookup</h1>
      <p className="lk-sub">Type or paste a material code, or part of its name.</p>
      <form className="lk-f" role="search" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <label className="lk-q">
          <Search size={20} strokeWidth={1.5} aria-hidden />
          <input ref={input} autoFocus={!code} inputMode="search" enterKeyHint="search" autoComplete="off" spellCheck={false} placeholder="Material code or name" aria-label="Material code or name"
            value={text} onChange={(e) => setText(e.target.value)} />
          {text && <button type="button" aria-label="Clear" onClick={() => { setText(""); input.current?.focus(); }}><X size={18} strokeWidth={1.5} aria-hidden /></button>}
        </label>
      </form>
      {mats.error && <LoadError what="the material master" retry={invalidate} />}
      {text.trim() && (
        <ul className="lk-hits" aria-label="Matching materials">
          {mats.loading && !mats.data ? <li><LoadingRows n={2} /></li>
            : hits.length === 0 ? <li className="lk-none">No material matches “{text.trim()}”.</li>
            : hits.map((m) => (
              <li key={m.code}>
                <button type="button" onClick={() => choose(m.code)}>
                  <b>{m.description}</b>
                  <small>{m.code} · {m.base_uom}{m.open_po_lines || m.open_prs ? ` · ${plural(m.open_po_lines, "open PO line")}, ${plural(m.open_prs, "open PR")}` : ""}</small>
                </button>
              </li>
            ))}
        </ul>
      )}
      {code && !text.trim() && <Found code={code} site={site} onSite={(id) => u.set({ project: id })} projects={pj} />}
      {!code && !text.trim() && all.length > 0 && <p className="lk-sub">{enIn(all.length)} materials in the master.</p>}
    </div>
  );
}

function Found({ code, site, onSite, projects }: { code: string; site?: string; onSite: (id: string | undefined) => void; projects: ReturnType<typeof useProjects> }) {
  const m = useResource(() => api.material(code), [code]);
  const pos = useResource(() => api.pos({ material: code, status: "open" }), [code]);
  const prs = useResource(() => api.prs({ status: "open" }).then((ls) => ls.filter((l) => l.material?.id === code)), [code]);
  useEffect(() => { window.scrollTo({ top: 0 }); }, [code]);
  if (m.error) return m.error.startsWith("404") ? <EmptyState>No material {code} in the master.</EmptyState> : <LoadError what={`material ${code}`} retry={invalidate} />;
  if (!m.data) return <LoadingRows n={4} />;
  const d = m.data;
  const atSite = <T extends PoLine | PrLine>(ls: T[] | undefined) => (ls ?? []).filter((l) => !site || l.project?.id === site);
  const openPos = atSite(pos.data).sort((a, b) => (a.delivery_date ?? "9999").localeCompare(b.delivery_date ?? "9999"));
  const openPrs = atSite(prs.data).sort((a, b) => (a.needed_by ?? "9999").localeCompare(b.needed_by ?? "9999"));
  const newest = d.history.length ? d.history[d.history.length - 1] : null;
  const siteRate = site ? d.by_site.find((s) => s.project.id === site) : null;
  const vendors = [...(d.by_vendor as unknown as ByVendor[])].sort((a, b) => b.last_date.localeCompare(a.last_date));
  const used = new Set([...d.by_site.map((s) => s.project.id), ...(d.where_used as unknown as { project: string }[]).map((w) => w.project)]);
  return (
    <div className="lk-card">
      <div className="lk-top">
        <h2>{d.description}</h2>
        <p>{d.code} · {d.base_uom}{d.lead_days != null ? ` · ${d.lead_days} days' lead` : ""}</p>
        <div className="lk-site"><ProjectPicker label="Site" projects={projects.list} value={site} onChange={onSite} only={(p) => used.has(p.ref.id)} /></div>
      </div>
      <dl className="lk-figs">
        <div><dt>{siteRate ? `Last rate at ${siteRate.project.label}` : "Last PO rate"}</dt>
          <dd>{siteRate ? rate(siteRate.last_rate, d.base_uom) : newest ? rate(newest.rate, d.base_uom) : "—"}
            <small>{siteRate ? `${day(siteRate.last_date)} · ${siteRate.vendor}` : newest ? `${day(newest.date)} · ${newest.vendor}` : "no PO on file"}</small></dd></div>
        <div><dt>Open on POs</dt><dd>{qty(openPos.reduce((s, l) => s + l.open_qty, 0), d.base_uom)}<small>{plural(openPos.length, "line")}{site ? " at this site" : ""}</small></dd></div>
        <div><dt>In open PRs</dt><dd>{qty(openPrs.reduce((s, l) => s + l.qty, 0), d.base_uom)}<small>{plural(openPrs.length, "line")}{site ? " at this site" : ""}</small></dd></div>
      </dl>
      <Block title="Open PO lines" count={openPos.length}>
        {pos.loading && !pos.data ? <LoadingRows n={2} /> : openPos.length === 0 ? <p className="rc-note">None open{site ? " for this site" : ""}.</p> : (
          <ul className="lk-list">
            {openPos.map((l) => (
              <li key={l.ref.id}><Link to={lineTo("po", l.ref.id)}>
                <span><b>{qty(l.open_qty, l.uom)}</b> open · {l.vendor.label}</span>
                <small>{l.project?.label ?? "no project"} · PO {l.ref.id} · {dueText(l)}</small>
              </Link></li>
            ))}
          </ul>
        )}
      </Block>
      <Block title="Open PR lines" count={openPrs.length}>
        {prs.loading && !prs.data ? <LoadingRows n={2} /> : openPrs.length === 0 ? <p className="rc-note">None open{site ? " for this site" : ""}.</p> : (
          <ul className="lk-list">
            {openPrs.map((l) => (
              <li key={l.ref.id}><Link to={lineTo("pr", l.ref.id)}>
                <span><b>{qty(l.qty, l.uom)}</b> · {l.project?.label ?? "no project"}</span>
                <small>PR {l.ref.id} · needed by {day(l.needed_by)}{l.age_days != null ? ` · ${l.age_days} days open` : ""}</small>
              </Link></li>
            ))}
          </ul>
        )}
      </Block>
      <Block title="Vendors" count={vendors.length} note={vendors.length ? "Who has supplied it on a PO, the most recent first." : undefined}>
        {vendors.length === 0 ? <p className="rc-note">No PO on file, so no vendor yet.</p> : (
          <ul className="lk-list">
            {vendors.map((v) => (
              <li key={v.id}><Link to={`/vendors/${encodeURIComponent(v.id)}`}>
                <span><b>{v.vendor}</b> · {v.id}</span>
                <small>last {rate(v.last, d.base_uom)} on {day(v.last_date)} · {plural(v.lines, "PO line")}</small>
              </Link></li>
            ))}
          </ul>
        )}
      </Block>
      <p className="lk-more"><Link className="ds-btn" to={`/materials/${encodeURIComponent(d.code)}`}>Open the material page</Link></p>
    </div>
  );
}

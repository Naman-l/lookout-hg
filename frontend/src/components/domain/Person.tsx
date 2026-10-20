import { Users } from "lucide-react";
import { Tip } from "./Tip";

const first = (name: string) => name.trim().split(/\s+/)[0];
const initials = (name: string) => name.trim().split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase();

/** A person: a grey avatar with initials and the first name; `label` overrides when two people share one. */
export function Person({ name, label }: { name: string; label?: string }) {
  return <span className="dm-person" title={name}><i className="dm-avatar" aria-hidden>{initials(name)}</i><span className="dm-name">{label ?? first(name)}</span></span>;
}

/** Up to three people by first name (a shared first name adds the last initial); four or more become one count chip that names them on hover. */
export function People({ names, max = 3, noun = "people" }: { names: string[]; max?: number; noun?: string }) {
  const uniq = [...new Set(names)];
  if (uniq.length === 0) return <span className="dm-rel">nobody</span>;
  if (uniq.length > max) {
    return <Tip tip={uniq.join(", ")}><span className="dm-chip dm-count"><Users size={14} strokeWidth={1.5} aria-hidden />{uniq.length} {noun}</span></Tip>;
  }
  const firsts = uniq.map(first);
  const label = (n: string) => {
    const f = first(n);
    if (firsts.filter((x) => x === f).length < 2) return f;
    const rest = n.trim().split(/\s+/).slice(1).join(" ");
    return rest ? `${f} ${rest[0]}.` : f;
  };
  return <span className="dm-people">{uniq.map((n) => <Person key={n} name={n} label={label(n)} />)}</span>;
}

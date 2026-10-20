import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

/** A buyer Lookout knows, from the buyers table (/api/people). */
export type Person = { name: string; initials: string; note?: string };

type Ctx = { me: string | null; setMe: (name: string) => void; clear: () => void; people: Person[]; ready: boolean; choosing: boolean; choose: (on?: boolean) => void };
const MeCtx = createContext<Ctx>({ me: null, setMe: () => {}, clear: () => {}, people: [], ready: false, choosing: false, choose: () => {} });

const KEY = "lookout.me";
const read = (): string | null => { try { return localStorage.getItem(KEY); } catch { return null; } };
const write = (v: string | null) => { try { if (v) localStorage.setItem(KEY, v); else localStorage.removeItem(KEY); } catch { /* private mode: the choice lasts this visit */ } };

export const initials = (name: string) => name.split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();

async function loadPeople(): Promise<Person[]> {
  const people = await fetch("/api/people").then((r) => (r.ok ? (r.json() as Promise<{ name: string; categories: string[]; open_lines: number }[]>) : []), () => []);
  return people.map((p) => ({
    name: p.name,
    initials: initials(p.name),
    note: [p.categories.slice(0, 3).join(", "), `${p.open_lines} open lines`].filter(Boolean).join(" · "),
  }));
}

/** Who is using Lookout: chosen once, remembered on this computer, sent as the person on every approval. No sign-in. */
export function MeProvider({ children }: { children: ReactNode }) {
  const [me, set] = useState<string | null>(read);
  const [people, setPeople] = useState<Person[]>([]);
  const [ready, setReady] = useState(false);
  const [choosing, setChoosing] = useState(false);
  const choose = useCallback((on = true) => setChoosing(on), []);
  useEffect(() => { loadPeople().then((p) => { setPeople(p); setReady(true); }); }, []);
  // A remembered name that is no longer a buyer is dropped, so nobody signs as a stranger.
  useEffect(() => { if (ready && me && people.length && !people.some((p) => p.name === me)) { write(null); set(null); } }, [ready, me, people]);
  const setMe = useCallback((name: string) => { write(name); set(name); }, []);
  const clear = useCallback(() => { write(null); set(null); }, []);
  const value = useMemo(() => ({ me, setMe, clear, people, ready, choosing, choose }), [me, setMe, clear, people, ready, choosing, choose]);
  return <MeCtx.Provider value={value}>{children}</MeCtx.Provider>;
}

export const useMe = () => useContext(MeCtx);

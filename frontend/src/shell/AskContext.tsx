import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { api } from "../api/client";
import { useMe } from "../api/useMe";
import { NO_AGENT } from "../ui/copy";
import type { EntityRef } from "../api/types";

export type Asked = { runId: string; question: string };
type Example = { question: string; context?: EntityRef | null };
type Ctx = {
  context: EntityRef | null; set: (c: EntityRef | null) => void;
  open: boolean; setOpen: (o: boolean) => void;
  about: string; thread: Asked[]; err: string | null;
  /** what a question is about: this page's record, or everything in the company */
  scope: "page" | "all"; setScope: (s: "page" | "all") => void;
  /** null until the server says: a key or LOOKOUT_LIVE=1 on the server makes it true; a refused ask makes it false. */
  connected: boolean | null; examples: Example[];
  send: (text: string, ctx?: EntityRef | null) => Promise<boolean>;
  /** show a run that already exists (one a screen started itself) in the answer panel: the question as asked, then the run streaming and laid out */
  openRun: (runId: string, question: string) => void;
  /** open the panel with a question started in the composer, for the buyer to finish and send (the case page's "Ask for another option", "Ask for changes") */
  prefill: string; openWith: (text: string) => void; takePrefill: () => void;
};
const AskCtx = createContext<Ctx>({ context: null, set: () => {}, open: false, setOpen: () => {}, about: "Lookout", thread: [], err: null, scope: "page", setScope: () => {}, openRun: () => {}, prefill: "", openWith: () => {}, takePrefill: () => {}, connected: null, examples: [], send: async () => false });

const SCOPE: [string, string][] = [["/approvals", "Approvals"], ["/inbox", "Inbox"], ["/activity", "Agent runs"], ["/data", "Data"], ["/suppliers", "Suppliers"], ["/parts", "Parts"], ["/orders", "Orders"], ["/forecast", "Forecast"], ["/more", "Lookout"], ["/shelf", "this part"], ["/design", "the design system"]];
const scopeOf = (path: string) => (path === "/" ? "Today" : SCOPE.find(([p]) => path.startsWith(p))?.[1] ?? "Lookout");

/** What the buyer is looking at, and the one conversation about it: the box at the foot and the panel beside the page both read this. */
export function AskProvider({ children }: { children: ReactNode }) {
  const { me } = useMe();
  const where = useLocation().pathname;
  const [context, set] = useState<EntityRef | null>(null);
  const [open, setOpen] = useState(false);
  const [thread, setThread] = useState<Asked[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [refused, setRefused] = useState(false);
  const [scope, setScope] = useState<"page" | "all">("page");
  const [examples, setExamples] = useState<Example[]>([]);
  const about = context ? (context.label ?? context.id) : scopeOf(where);
  const [forWhat, setForWhat] = useState(about);

  // Closing is final for that subject; moving to another page starts a new thread.
  useEffect(() => { if (about !== forWhat) { setThread([]); setOpen(false); setErr(null); setScope("page"); setForWhat(about); } }, [about, forWhat]);
  useEffect(() => { api.askExamples().then(setExamples).catch(() => setExamples([])); }, []);
  // Without a live agent, say so before the first question and offer the examples that have saved answers.
  useEffect(() => { api.health().then((h) => { if (!h.agent_live) setRefused(true); }).catch(() => {}); }, []);

  const send = useCallback(async (text: string, ctx: EntityRef | null = scope === "all" ? null : context) => {
    const question = text.trim();
    if (!question) return false;
    setErr(null);
    try {
      const r = await api.ask(question, ctx, me ?? "", thread.length ? thread[thread.length - 1].runId : null);
      setThread((t) => [...t, { runId: r.run_id, question }]); setOpen(true); setRefused(false);
      return true;
    } catch (e) {
      const none = (e as Error).message === "no-model";
      if (none) setRefused(true);
      setErr(none ? NO_AGENT : "Ask could not be reached. Try again.");
      return false;
    }
  }, [context, me, scope, thread]);

  const [prefill, setPrefill] = useState("");
  const openWith = useCallback((text: string) => { setPrefill(text); setOpen(true); }, []);
  const takePrefill = useCallback(() => setPrefill(""), []);
  const openRun = useCallback((runId: string, question: string) => { setThread((t) => (t.some((x) => x.runId === runId) ? t : [...t, { runId, question }])); setOpen(true); }, []);

  return <AskCtx.Provider value={{ context, set, open, setOpen, about, thread, err, scope, setScope, connected: refused ? false : null, examples, send, openRun, prefill, openWith, takePrefill }}>{children}</AskCtx.Provider>;
}

export const useAskState = () => useContext(AskCtx);

/** A screen about one record calls this; leaving the screen clears it. `undefined` leaves the context as it is (a part embedded in a page that owns it). */
export function useAskContext(ref: EntityRef | null | undefined) {
  const { set } = useAskState();
  const key = ref === undefined ? "keep" : ref ? `${ref.type}:${ref.id}:${ref.label ?? ""}` : "";
  useEffect(() => {
    if (ref === undefined) return;
    set(ref);
    return () => set(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
}

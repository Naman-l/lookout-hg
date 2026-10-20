import { useCallback, useEffect, useRef, useState } from "react";

/* Web Speech: Safari tabs and Chrome have it; an installed iPhone app may not work, so typing always stays. */
type Rec = { lang: string; interimResults: boolean; continuous: boolean; start(): void; stop(): void; abort(): void; onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null; onend: (() => void) | null; onerror: ((e: { error: string }) => void) | null };
type RecCtor = new () => Rec;
const ctor = (): RecCtor | null => {
  const w = window as unknown as { SpeechRecognition?: RecCtor; webkitSpeechRecognition?: RecCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
};

/** Hold to speak: `start` on press, `stop` on release. `onText` gets the words as they come; `onDone` gets the final words. */
export function useVoice(onText: (t: string) => void, onDone: (t: string) => void) {
  const supported = typeof window !== "undefined" && ctor() !== null;
  const [listening, setListening] = useState(false);
  const rec = useRef<Rec | null>(null);
  const said = useRef("");
  const cbs = useRef({ onText, onDone });
  cbs.current = { onText, onDone };

  const start = useCallback(() => {
    const C = ctor();
    if (!C || rec.current) return;
    const r = new C();
    r.lang = "en-US"; r.interimResults = true; r.continuous = false;
    said.current = "";
    r.onresult = (e) => {
      said.current = Array.from(e.results).map((x) => x[0].transcript).join(" ").trim();
      cbs.current.onText(said.current);
    };
    r.onerror = () => { /* denied or no speech: the typed box is still there */ };
    r.onend = () => { rec.current = null; setListening(false); if (said.current) cbs.current.onDone(said.current); };
    rec.current = r;
    setListening(true);
    try { r.start(); } catch { rec.current = null; setListening(false); }
  }, []);
  const stop = useCallback(() => { rec.current?.stop(); }, []);
  useEffect(() => () => rec.current?.abort(), []);
  return { supported, listening, start, stop };
}

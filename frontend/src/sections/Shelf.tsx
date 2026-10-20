import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ScanLine, X } from "lucide-react";

/** The barcode scan is parked: the entry is hidden, the code stays (Khalid: hide or fold, never rip out). */
const SCAN_ENTRY = false;
import { Button, Field, Notice, PageHeader, Row, Skeleton } from "../ds";
import { api } from "../api/client";
import { useResource } from "../api/useResource";

/* Barcode reading exists only on some browsers (Chrome on Android, not iPhone Safari): the scan button is shown only where it works. */
type Detector = { detect(v: HTMLVideoElement): Promise<{ rawValue: string }[]> };
const detectorCtor = () => (window as unknown as { BarcodeDetector?: new () => Detector }).BarcodeDetector;
const canScan = () => typeof window !== "undefined" && !!detectorCtor() && !!navigator.mediaDevices?.getUserMedia;

const norm = (s: string) => s.trim().toUpperCase().replace(/\s+/g, "");

/** Part at the shelf: type a part number, or scan it, and land on that part's facts. */
export function Shelf() {
  const nav = useNavigate();
  const parts = useResource(api.parts);
  const [q, setQ] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const list = parts.data ?? [];
  const typed = norm(q);
  const hits = typed.length >= 2 ? list.filter((p) => p.ref.id.includes(typed) || p.description.toUpperCase().includes(q.trim().toUpperCase())).slice(0, 8) : [];

  const open = (value: string) => {
    const id = norm(value);
    const exact = list.find((p) => p.ref.id === id) ?? (hits.length === 1 ? hits[0] : undefined);
    if (exact) nav(`/parts/${encodeURIComponent(exact.ref.id)}`);
    else setNote(`No part "${value.trim()}" on file. Check the number and try again.`);
  };
  const submit = (e: FormEvent) => { e.preventDefault(); setNote(null); open(q); };

  return (
    <>
      <PageHeader title="Part at the shelf" meta="Type a part number, or scan the label, to see what is open, what it costs and who supplies it." />
      <form className="shelf" onSubmit={submit}>
        <Field aria-label="Part number" placeholder="Part number" autoFocus autoCapitalize="characters" autoCorrect="off" spellCheck={false}
          value={q} onChange={(e) => { setQ(e.target.value); setNote(null); }} />
        <div className="ds-actions">
          <Button variant="primary" type="submit" disabled={!typed}>Show part</Button>
          {SCAN_ENTRY && canScan() && <Button aria-label="Scan a barcode" onClick={() => setScanning(true)}><ScanLine size={18} strokeWidth={1.6} /> Scan</Button>}
        </div>
      </form>
      {note && <Notice tone="risk">{note}</Notice>}
      {parts.loading && <Skeleton width={280} />}
      {hits.map((p) => <Row key={p.ref.id} to={`/parts/${encodeURIComponent(p.ref.id)}`} title={<><span className="pn">{p.ref.id}</span> {p.description}</>} sub={p.category} />)}
      {scanning && <Scanner onCode={(c) => { setScanning(false); setQ(c); setNote(null); open(c); }} onClose={() => setScanning(false)} onFail={() => { setScanning(false); setNote("The camera is not available. Type the number instead."); }} />}
    </>
  );
}

function Scanner({ onCode, onClose, onFail }: { onCode: (c: string) => void; onClose: () => void; onFail: () => void }) {
  const video = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    let stream: MediaStream | null = null, timer = 0, live = true;
    const Detector = detectorCtor()!;
    navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } }).then(
      async (s) => {
        if (!live) { s.getTracks().forEach((t) => t.stop()); return; }
        stream = s;
        const v = video.current!; v.srcObject = s; await v.play().catch(() => {});
        const d = new Detector();
        timer = window.setInterval(async () => {
          const found = await d.detect(v).catch(() => []);
          if (found[0]?.rawValue) { window.clearInterval(timer); onCode(found[0].rawValue); }
        }, 250);
      },
      () => onFail(),
    );
    return () => { live = false; window.clearInterval(timer); stream?.getTracks().forEach((t) => t.stop()); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <div className="scanner" role="dialog" aria-label="Scan a barcode">
      <video ref={video} playsInline muted />
      <button type="button" className="btn" onClick={onClose}><X size={16} strokeWidth={1.6} /> Close</button>
    </div>
  );
}

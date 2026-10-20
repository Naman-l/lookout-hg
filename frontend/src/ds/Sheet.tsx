import { useEffect, useRef, type ReactNode } from "react";

/** A full-height sheet over the page, for a phone: it owns the scrolling while open, Esc or Done closes it and focus goes back to where it was. */
export function Sheet({ title, hint, onClose, children }: { title: string; hint?: string; onClose: () => void; children: ReactNode }) {
  const done = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    const lock = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    done.current?.focus();
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", key);
    return () => { window.removeEventListener("keydown", key); document.body.style.overflow = lock; before?.focus?.(); };
  }, [onClose]);
  return (
    <>
      <div className="dim" onClick={onClose} aria-hidden />
      <div className="sheetm" role="dialog" aria-modal="true" aria-label={title}>
        <i className="grab" aria-hidden />
        <div className="sh"><b>{title}</b>{hint && <span className="muted">{hint}</span>}<button type="button" ref={done} onClick={onClose}>Done</button></div>
        <div className="shb">{children}</div>
      </div>
    </>
  );
}

import { useId, type ReactNode } from "react";

/** A hover and focus definition: the trigger is focusable and points at the tooltip, so a keyboard user gets the same words. */
export function Tip({ tip, children, tabbable = true, inline }: { tip: string; children: ReactNode; tabbable?: boolean; inline?: boolean }) {
  const id = useId();
  return (
    <span className={`dm-tipwrap${inline ? " inline" : ""}`} tabIndex={tabbable ? 0 : undefined} aria-describedby={id}>
      {children}
      <span role="tooltip" id={id} className="dm-tip">{tip}</span>
    </span>
  );
}

import { useLayoutEffect, useRef, useState } from "react";

/** One row, always: does a bar's full form fit the width it has? `box` is the space the bar may take; `full` is the full form,
 * kept in the layout (hidden when it does not fit) so its natural width is measured on every resize. The caller renders a
 * compact form (one menu) when `fits` is false, so a bar never wraps to a second row or scrolls sideways. `extra` is width the bar needs beside the full form (a search box). */
export function useFits(extra = 0) {
  const box = useRef<HTMLDivElement | null>(null);
  const full = useRef<HTMLDivElement | null>(null);
  const [fits, setFits] = useState(true);
  useLayoutEffect(() => {
    const b = box.current, f = full.current;
    if (!b || !f) return;
    const check = () => setFits(f.scrollWidth + extra <= b.clientWidth + 1);
    check();
    const ro = new ResizeObserver(check);
    ro.observe(b); ro.observe(f);
    return () => ro.disconnect();
  }, []);
  return { box, full, fits };
}

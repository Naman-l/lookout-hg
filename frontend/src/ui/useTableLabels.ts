import { useEffect } from "react";

/** On a phone every table becomes rows. The CSS needs each cell to know its column's name, so copy the header text onto the cells. */
function label(table: HTMLTableElement) {
  const heads = [...table.querySelectorAll<HTMLElement>("thead th")].map((h) => ((h.querySelector(".who") ?? h).textContent ?? "").trim());
  if (heads.length === 0) return;
  table.querySelectorAll("tbody tr").forEach((tr) => {
    [...tr.children].forEach((cell, i) => { if (heads[i] && cell.getAttribute("data-label") !== heads[i]) cell.setAttribute("data-label", heads[i]); if (cell.textContent?.trim() === "—") cell.setAttribute("data-empty", ""); });
  });
}

export function useTableLabels(root: () => HTMLElement | null) {
  useEffect(() => {
    const el = root();
    if (!el) return;
    const run = () => el.querySelectorAll("table").forEach((t) => label(t as HTMLTableElement));
    run();
    const mo = new MutationObserver(run);
    mo.observe(el, { childList: true, subtree: true });
    return () => mo.disconnect();
  }, [root]);
}

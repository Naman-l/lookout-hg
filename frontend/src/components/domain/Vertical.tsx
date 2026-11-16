/** The five verticals, always in the same order and colour: Roads, Railway, BESS, Solar, T&D. One line icon each (road, rail, battery, sun, tower). */
export const VERTICALS = [
  { id: "roads", name: "Roads", short: "Roads" },
  { id: "railway", name: "Railway", short: "Rly" },
  { id: "bess", name: "BESS", short: "BESS" },
  { id: "solar", name: "Solar", short: "Solar" },
  { id: "td", name: "T&D", short: "T&D" },
] as const;
export type VerticalId = (typeof VERTICALS)[number]["id"];
export const verticalName = (id?: string | null) => VERTICALS.find((v) => v.id === id)?.name ?? id ?? "";

const PATHS: Record<VerticalId, string> = {
  roads: "M8 3 6 21M16 3l2 18M12 4v3M12 10v3M12 16v3",
  railway: "M7 3v18M17 3v18M5 6h14M5 10h14M5 14h14M5 18h14",
  bess: "M5 7h13v11H5zM18 10h2v5h-2M9 10l-1.5 3h3L9 16",
  solar: "M12 8a4 4 0 1 1 0 8 4 4 0 0 1 0-8M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1",
  td: "M12 2 7 22M12 2l5 20M8.5 9h7M7.4 14h9.2M6 6h12M9 22h6",
};

export function VerticalIcon({ id, size = 16, on = true, title }: { id: string; size?: number; on?: boolean; title?: string }) {
  const p = PATHS[id as VerticalId];
  if (!p) return null;
  return (
    <svg className={`vert-ic${on ? ` v-${id}` : ""}`} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round"
      strokeLinejoin="round" role={title ? "img" : undefined} aria-label={title} aria-hidden={title ? undefined : true}>
      {title && <title>{title}</title>}
      <path d={p} />
    </svg>
  );
}

import { CalendarClock, CalendarX } from "lucide-react";
import { shortDate } from "../../ui/format";

const DAY = 86_400_000;
const utc = (iso: string) => { const [y, m, d] = iso.split("-").map(Number); return Date.UTC(y, m - 1, d); };

/** Whole days from the data date to `date`; negative once it has passed. */
export const daysBetween = (asOf: string, date: string) => Math.round((utc(date) - utc(asOf)) / DAY);

const words = (n: number) => (n === 0 ? "on the data date" : n === 1 ? "in 1 day" : n === -1 ? "1 day past" : n > 0 ? `in ${n} days` : `${-n} days past`);

/** A date counted from the data date, never the clock: neutral, amber within 7 days, red once past. Colour comes with an icon and the words. */
export function DateDue({ date, asOf, daysLeft }: { date: string | null | undefined; asOf?: string; daysLeft?: number | null }) {
  if (!date) return <span className="dm-date">—</span>;
  const n = daysLeft ?? (asOf ? daysBetween(asOf, date) : null);
  const tone = n == null ? undefined : n < 0 ? "red" : n <= 7 ? "amber" : undefined;
  return (
    <span className="dm-date" data-tone={tone}>
      {tone === "red" && <CalendarX size={14} strokeWidth={1.75} aria-hidden />}
      {tone === "amber" && <CalendarClock size={14} strokeWidth={1.75} aria-hidden />}
      <b>{shortDate(date)}</b>
      {n != null && <span className="dm-rel">{words(n)}</span>}
    </span>
  );
}

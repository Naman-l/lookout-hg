import type { ActionItem } from "../api/types";

/** A case's short name, as list cells and robot pages say it (Records FINAL §0): the title up to its first colon, without the "(on time …)" aside
 * or a trailing ", with …". Every title on Today is written cause first, so this is the name a buyer uses for the case. */
export function caseShort(i: Pick<ActionItem, "title">): string {
  return i.title.split(":")[0].replace(/\s*\(on time[^)]*\)/, "").replace(/, with .*$/, "").trim();
}

/** Team lists rather than one cause: they hold many records and go after the cases of their own. */
export const isRollup = (key: string) => key === "deadline:chase" || key === "deadline:quotes" || key === "tariff:all" || key.startsWith("unknown:");

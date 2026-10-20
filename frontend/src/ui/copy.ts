/** Words used in more than one place, so a buyer meets the same sentence everywhere. */
export const NO_AGENT = "The agent is not connected.";
export const isNoAgent = (s: string | null | undefined) => !!s && s.startsWith(NO_AGENT);

/** Two different dates, two words: "past due" is the PO-date meaning (Action list, Orders, chase); "late on the supplier's latest date" is the readiness meaning (the supplier's own, revised date has passed). A ruling changes one line here. */
export const PAST_DUE = "past due";
export const LATE_ON_LATEST = "late on the supplier's latest date";
export const LATE_CHIP = "late";

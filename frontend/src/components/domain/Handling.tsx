export type HandlingKey = "fixed" | "inferred" | "flagged" | "linked" | "unknown" | "dropped";
const WORDS: Record<HandlingKey, { word: string; meaning: string }> = {
  fixed: { word: "Fixed", meaning: "Cleaned to one form; the raw value is kept" },
  inferred: { word: "Estimated", meaning: "Filled in from other records; marked as estimated" },
  flagged: { word: "Raised", meaning: "Left as it is and raised for a person to decide" },
  linked: { word: "Linked", meaning: "Joined to the record it duplicates; both kept" },
  unknown: { word: "Left blank", meaning: "Not guessed; someone has to answer" },
  dropped: { word: "Dropped", meaning: "An exact repeat removed, with the row it repeats recorded" },
};
/** The API's verbs (fix, infer, flag, link, drop, leave) and the cleaned-up ones (fixed, ...) are the same six things. */
const ALIAS: Record<string, HandlingKey> = { fix: "fixed", infer: "inferred", flag: "flagged", link: "linked", drop: "dropped", leave: "unknown" };

/** What was done about a piece of data, as one plain word (FINAL 09; one vocabulary app-wide): Fixed · Linked · Estimated · Dropped · Raised · Left blank.
 * The meaning is the hover; for Estimated and Dropped the hover is the issue's own rule (how, or why), when the caller has it. */
export function Handling({ how, rule }: { how: string; rule?: string | null }) {
  const k = (WORDS[how as HandlingKey] ? how : ALIAS[how]) as HandlingKey | undefined;
  const h = k ? WORDS[k] : null;
  if (!h) return <span className="dm-how">{how}</span>;
  return <span className="dm-how" title={(k === "inferred" || k === "dropped") && rule ? rule : h.meaning}>{h.word}</span>;
}

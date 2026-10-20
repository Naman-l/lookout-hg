export type Handling = "fixed" | "inferred" | "flagged" | "linked" | "unknown" | "dropped";
export interface Issue { count: number; text: string; handling: Handling }

const LINE = /^(\d[\d,]*)\s+(.*)\s\((fixed|inferred|flagged|linked|unknown|dropped)\)$/s;

/** The server writes each issue as "<count> <what> (<handling>)", the what cut at a fixed length. Split it into its three parts; a what that was cut inside a bracket loses its partial last word and ends in an ellipsis. */
export function parseIssue(line: string): Issue | null {
  const m = LINE.exec(line.trim());
  if (!m) return null;
  let text = m[2].trim();
  const open = (text.match(/\(/g) ?? []).length, shut = (text.match(/\)/g) ?? []).length;
  if (open > shut) text = `${text.replace(/[\s,;]*[^\s,;(]*$/, "").replace(/[\s,;(]+$/, "")}…`;
  return { count: Number(m[1].replace(/,/g, "")), text, handling: m[3] as Handling };
}

/** A line that does not parse is kept whole, as an issue with no count and no handling, never dropped. */
export const parseIssues = (lines: string[]): (Issue | { raw: string })[] => lines.map((l) => parseIssue(l) ?? { raw: l });

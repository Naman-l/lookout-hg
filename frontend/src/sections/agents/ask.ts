import type { EntityRef } from "../../api/types";

/** Ask (FINAL 08 D): the words around a question. Pure, so it is unit-tested. */

/** The scope chip's name: a case's title up to its colon ("<Supplier> fire"); any other page as it is. */
export const shortAbout = (about: string) => about.split(": ")[0].replace(/\s*\(on time[^)]*\)/, "").trim();

type Example = { question: string; context?: EntityRef | null };

/** The recorded questions about what is on screen first: the same record, then those that name a word of its short name (a supplier, a part id), then the rest, in their order. */
export function rankExamples<T extends Example>(examples: T[], context: EntityRef | null, about: string): T[] {
  const words = shortAbout(about).split(/[\s,·]+/).filter((w) => w.length > 3 && /^[A-Z0-9]/.test(w));
  const score = (x: T) => (context && x.context?.id === context.id ? 0 : words.some((w) => x.question.includes(w)) ? 1 : 2);
  return examples.map((x, i) => ({ x, i, s: score(x) })).sort((a, b) => a.s - b.s || a.i - b.i).map((y) => y.x);
}

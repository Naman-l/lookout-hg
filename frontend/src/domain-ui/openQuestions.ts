/** "Still open", as a buyer reads it (BUYER R2 #3/#4): each question names its part or PO line and who answers it.
 * The run's own question text is preferred to its short label ("country of origin" alone says nothing); a question that names
 * no id (a guess, "these parts") and the workflow-phase template ("Where PO-1/1 is in: quoted, acknowledged, …") are left out,
 * and the same question asked twice is shown once. */
export type OpenQuestion = { what: string; question?: string | null; owner?: string | null };
export type NamedQuestion = { text: string; owner: string | null };

const NAMES_ID = /\b[A-Z]{2,}-\d{2,}/;      // a PO line, an order or a part id
const PHASE_TEMPLATE = /\bis in:\s/;

export function namedQuestions(qs: OpenQuestion[]): NamedQuestion[] {
  const out: NamedQuestion[] = [];
  const seen = new Set<string>();
  for (const q of qs) {
    if (PHASE_TEMPLATE.test(q.what)) continue;
    const text = (q.question || q.what || "").trim();
    if (!NAMES_ID.test(text)) continue;
    const key = text.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ text, owner: q.owner ? q.owner[0].toUpperCase() + q.owner.slice(1) : null });
  }
  return out;
}

/** How many a list shows before "+N more". */
export const SHOWN = 3;

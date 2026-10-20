import type { Action } from "../api/types";
import { humanize } from "./format";

const VERB: Record<Action["type"], string> = {
  supplier_request: "Request to", supplier_alias: "Link records for",
  note: "Note",
};
const PO = /\b(?:HPO-\d{2}-\d{5}|PO-\d{5})(?: ?\/ ?\d+)?\b/g;
const PO_RUN = /,?\s*(?:HPO-\d{2}-\d{5}|PO-\d{5})(?:\s*(?:\/|and|,)\s*(?:HPO-\d{2}-\d{5}|PO-\d{5}|\d{3,5}|line \d+))*(?:\s+line \d+)?(?:\s*\([^)]*\))?/g;
const QUOTE_NO = /\s*\bQ-[A-Z]{2}-\d\d-\d{4}\b/g;

/** A subject for a list: no PO numbers or quote numbers, and how many orders it covers instead. */
const plain = (text: string): string => {
  const orders = new Set((text.match(PO_RUN) ?? []).flatMap((m) => m.match(/\d{5}/g) ?? [])).size;
  const t = text.replace(PO_RUN, "").replace(QUOTE_NO, "").replace(/\s{2,}/g, " ").replace(/\s+([,.:])/g, "$1").replace(/^[,:\s]+|[,:\s]+$/g, "").replace(/\bof open POs\b/, "of open orders");
  return orders ? `${t} · ${orders} ${orders === 1 ? "order" : "orders"}` : t;
};

/** A draft in the buyer's words: "Request to Acme: revised promise dates", its PO lines kept apart as tags. */
export function describeAction(a: Action, nameOf?: (id: string) => string | undefined): { title: string; rest: string; poLines: string[] } {
  const subject = a.subject ?? "";
  const poLines = Array.from(new Set(subject.match(PO) ?? []));
  const colon = subject.indexOf(":");
  const note = a.type === "note";
  const rest = note ? "" : poLines.length && colon >= 0 ? subject.slice(colon + 1).trim() : poLines.length ? "" : subject;
  const who = a.target?.label ?? (a.target ? nameOf?.(a.target.id) ?? "" : "");
  const title = note ? subject || (a.body ?? "").replace(/\s+/g, " ").trim() || VERB[a.type] : `${VERB[a.type]} ${who}`.trim();
  return { title: humanize(title), rest: humanize(plain(rest)), poLines };
}

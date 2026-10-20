import type { MessageMatch } from "../../api/types";

const FIELD: Record<string, string> = { subject: "Subject", body: "Message", from: "From", sender: "From", facts: "Fact", part: "Part", po_line: "PO line" };

/** Where a search matched: the field, then the snippet with the matched words marked. A span outside the snippet marks nothing. */
export function Match({ x }: { x: MessageMatch }) {
  const a = x.start, b = x.end;
  const ok = Number.isInteger(a) && Number.isInteger(b) && a >= 0 && b > a && b <= x.snippet.length;
  return <>{FIELD[x.field] ?? x.field}: …{ok ? <>{x.snippet.slice(0, a)}<mark className="ib-hit">{x.snippet.slice(a, b)}</mark>{x.snippet.slice(b)}</> : x.snippet}…</>;
}

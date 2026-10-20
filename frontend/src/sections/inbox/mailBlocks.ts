/** A mail body cut into blocks without moving a character: prose to reflow, or text whose spacing carries meaning (an aligned table, an indented list, a signature). Offsets are into the original body, so entity spans still land in their place (a reflowed newline becomes one space of the same length). */
export interface Block { start: number; end: number; kind: "prose" | "pre" }

const GAP = /\S {2,}\S/;            // two or more spaces between words: a column
const SIGN = /^(best|kind|warm|with)?\s*(regards|wishes|sincerely|thanks|thank you|cheers|mit freundlichen|atentamente|saludos|cordialement)\b/i;

function kind(lines: string[], afterSign: boolean): "prose" | "pre" {
  if (afterSign) return "pre";
  const aligned = lines.filter((l) => GAP.test(l) || /^\s{2,}\S/.test(l)).length;
  if (aligned >= 2 || (lines.length > 1 && aligned === lines.length)) return "pre";
  if (lines.length >= 2 && lines.length <= 5 && lines.every((l) => l.length < 42 && !/[.!?]$/.test(l.trim()))) return "pre"; // an address or a signature block
  return "prose";
}

export function mailBlocks(body: string): Block[] {
  const out: Block[] = [];
  const re = /\n{2,}/g;
  let from = 0, afterSign = false;
  const push = (a: number, b: number) => {
    if (b <= a) return;
    const lines = body.slice(a, b).split("\n");
    if (SIGN.test(lines[0].trim()) && lines.length <= 2) afterSign = true;
    out.push({ start: a, end: b, kind: kind(lines, afterSign) });
  };
  for (let m = re.exec(body); m; m = re.exec(body)) { push(from, m.index); from = m.index + m[0].length; }
  push(from, body.length);
  return out;
}

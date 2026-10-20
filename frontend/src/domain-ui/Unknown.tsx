import type { Unknown } from "../api/types";

/** A fact the data does not hold: never a zero, a dash or a blank. */
export function UnknownValue({ u }: { u: Unknown }) {
  return (
    <span className="unknown" title={u.question}>
      unknown<span className="unknown-owner">· ask {u.owner}</span>
    </span>
  );
}

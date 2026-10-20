import { useState } from "react";
import { Handling as HandlingWord } from "../../components/domain";
import { parseIssues } from "./model";


/** One file's issues as a table: how many rows, what was wrong, what was done about it. Collapsed after `limit`. */
export function IssueTable({ file, lines, limit = 5 }: { file: string; lines: string[]; limit?: number }) {
  const [all, setAll] = useState(false);
  const rows = parseIssues(lines);
  const shown = all ? rows : rows.slice(0, limit);
  if (rows.length === 0) return <p className="im-none">No issues found in {file}.</p>;
  return (
    <div className="dm-tablewrap">
      <table className="dm-table im-table">
        <caption className="dm-sr">Issues found in {file}</caption>
        <thead><tr><th scope="col" className="dm-num">Rows</th><th scope="col">What was wrong</th><th scope="col">What was done</th></tr></thead>
        <tbody>
          {shown.map((r, n) => "raw" in r
            ? <tr key={n}><td className="dm-num">—</td><td colSpan={2}>{r.raw}</td></tr>
            : (
              <tr key={n}>
                <td className="dm-num">{r.count.toLocaleString("en-US")}</td>
                <td className="im-what">{r.text}</td>
                <td><HandlingWord how={r.handling} /></td>
              </tr>))}
        </tbody>
      </table>
      {rows.length > limit && <button type="button" className="dm-more" aria-expanded={all} onClick={() => setAll(!all)}>{all ? "Show fewer" : `Show ${rows.length - limit} more`}</button>}
    </div>
  );
}

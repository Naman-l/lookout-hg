/** What a running agent is doing, on one line of fixed height: the text is cut with an ellipsis, the full text is the hover title, and the block never grows or shrinks. */
export function StatusLine({ text, note, className = "" }: { text: string; note?: string; className?: string }) {
  return <p className={`status-line ${className}`.trim()} role="status" title={text}><span className="pulse" /><span className="sl-t">{text}</span>{note && <small>{note}</small>}</p>;
}

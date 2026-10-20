/** A page that could not load (FINAL 09 §5): one ink line and Try again. Not red: a load error is not a danger to a decision. No box. */
export function LoadError({ what, retry, busy = false }: { what: string; retry?: () => void; busy?: boolean }) {
  return (
    <p className="ds-loaderr" role="alert">
      <b>Couldn't load {what}.</b>
      {retry && <button type="button" onClick={retry} disabled={busy}>Try again</button>}
    </p>
  );
}

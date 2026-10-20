import { NotFound } from "../ds";

/** The catch-all route: the shared not-found page. */
export function Placeholder({ title, line }: { title: string; line: string }) {
  return <NotFound title={title} line={line} />;
}

import { EntityText, cleanEntities, guardSuspect, type Entity } from "../../components/domain";
import { mailBlocks } from "./mailBlocks";

/** The message as received: prose reflowed into paragraphs in the body font; tables, lists and signatures keep their spacing in monospace. Lines the changes rest on are marked in the monospace blocks. */
export function MailBody({ body, highlights, entities, suspect }: { body: string; highlights: string[]; entities?: Entity[]; suspect: boolean }) {
  const spans = cleanEntities(body, suspect ? guardSuspect(entities) : entities);
  return (
    <div className="ml">
      {mailBlocks(body).map((b) => {
        const text = body.slice(b.start, b.end);
        const inside = spans.filter((e) => e.start >= b.start && e.end <= b.end).map((e) => ({ ...e, start: e.start - b.start, end: e.end - b.start }));
        if (b.kind === "prose") return <p key={b.start} className="ml-p"><EntityText text={text.replace(/\n/g, " ")} entities={inside} /></p>;
        const marked = highlights.some((h) => text.includes(h));
        return <pre key={b.start} className={`ml-pre${marked ? " marked" : ""}${/\S {2,}\S/.test(text) ? " tab" : ""}`}>{inside.length ? <EntityText text={text} entities={inside} /> : text}</pre>;
      })}
    </div>
  );
}

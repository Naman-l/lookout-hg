import "./domain.css";

/* The domain components (UI-STANDARD §7): one component per kind of thing, the same on every screen. */
export { Person, People } from "./Person";
export { Money, moneyText, type MoneyIn } from "./Money";
export { DateDue, daysBetween } from "./DateDue";
export { TrustBadge, TrustBadges, REASONS } from "./TrustBadge";
export { Handling, type HandlingKey } from "./Handling";
export { Term, GLOSSARY } from "./Term";
export { EntityText, EntityLines, MARKERS, guardSuspect, Points, sentenceRanges, InlineEntity, cleanEntities, type Entity, type EntityType } from "./EntityText";
export { Tip } from "./Tip";
export { VERTICALS, VerticalIcon, verticalName, type VerticalId } from "./Vertical";

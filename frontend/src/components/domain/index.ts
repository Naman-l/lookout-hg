import "./domain.css";

/* The domain components (UI-STANDARD §7): one component per kind of thing, the same on every screen. */
export { Part } from "./Part";
export { Supplier, type SupplierTrust } from "./Supplier";
export { PoLine, PoLineTable, poLineNumber, type PoLineIn } from "./PoLine";
export { Person, People } from "./Person";
export { Money, moneyText, type MoneyIn } from "./Money";
export { DateDue, daysBetween } from "./DateDue";
export { Stage, type StageKey } from "./Stage";
export { TrustBadge, TrustBadges, REASONS } from "./TrustBadge";
export { ProblemKind, ProblemLegend, KINDS, kindOfGroup, type Kind } from "./ProblemKind";
export { ItemLink } from "./ItemLink";
export { Handling, type HandlingKey } from "./Handling";
export { Term, GLOSSARY } from "./Term";
export { EntityText, EntityLines, MARKERS, guardSuspect, Points, sentenceRanges, InlineEntity, cleanEntities, type Entity, type EntityType } from "./EntityText";
export { Tip } from "./Tip";
export { RobotDrawing, RobotIcon, robotKey, useRobots, type Robot } from "./Robot";

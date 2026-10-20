import type { ActionItem } from "../api/types";

/** The buyer's words for the contract's enums (FIELD.md). */
export type Group = ActionItem["group"] | "trust";
export const GROUP_LABEL: Record<Group, string> = {
  disruption: "Supplier can't deliver", deadline: "Deadline", tariff: "New import duty", unknown: "Open question", trust: "Held message", // the plain names of UI-STANDARD §7
};
export const SEVERITY_LABEL: Record<ActionItem["severity"], string> = { high: "High", medium: "Medium", low: "Low" };
export const dotClass = (s: ActionItem["severity"]) => (s === "medium" ? "med" : s);

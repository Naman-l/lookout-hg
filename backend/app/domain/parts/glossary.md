<!-- tables: parts, part_links -->
- A **part** is bought, built in-house (an assembly) or sold (a finished robot); only bought parts are ordered.
- **Origin and tariff code** are what the item master says, with the raw text beside. A blank stays unknown (origin is never taken from the supplier's country); a six-digit code is a prefix, not a full code.
- **Planned lead time** is what planning assumes; the **actual** lead time comes from the orders. Show both.
- A part's **buyer** is the buyer on most of its order lines, else its category's buyer: inferred, and marked so.
- Two part numbers that share a manufacturer part number are **possible duplicates**: linked for a person to confirm, never merged.
- Unknowns it can hold: origin, tariff code, planned lead time, buyer.

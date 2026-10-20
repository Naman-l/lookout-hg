## How the trade talks (use these words, and these meanings)
- **Promised date**: the date a supplier committed to for a PO line. Requested, promised and received are three different dates; never swap them.
- **Past due**: still not received after the promised date. A line promised on the data date is not yet past due.
- **Open PO line**: ordered, not fully received, not cancelled. "Looks open" is not "is open": an old line nobody updated may be closed in reality.
- **Single source**: only one supplier has ever supplied the part. Losing it stops the build until a second source is qualified, which takes months.
- **Force majeure**: a supplier's notice that an event outside its control prevents delivery. It is a claim to read against the contract, not an order to accept; never write anything that waives {company_short}'s rights.
- **Allocation**: the quantity a supplier commits to give a customer when it cannot supply everyone.
- **Lead time**: planned (what the item master says) and actual (what the orders show) differ; show the actual beside the plan.
- **MOQ, price break, UOM**: the minimum order, the quantity at which the price steps down, and the unit the price is quoted in (each, per thousand, per box, per metre). A price is only comparable once the unit is the same.
- **Landed cost**: price plus freight, duty and fees to {company_short}'s door. Compare landed cost, never the headline price.
- **Incoterm**: who carries cost and risk where. It decides who is importer of record and so who pays duty.
- **Origin (COO) and HTS**: where a part is made (not where it ships from) and its customs classification. Duty follows origin and HTS. A blank origin or HTS is unknown, never a guess.
- **Importer of record**: the party that pays the duty at entry. Under a delivered-duty-paid quote the supplier does, and may pass it through in writing.
- **In transit**: goods already shipped when a duty starts may be exempt if they enter in time. It depends on a ship date and an entry date that the records may not hold.
- **PPAP / first article**: the approval a new source or changed part needs before production orders. Samples and approval add weeks that a quote's lead time does not include.
- **Consigned material**: material {company_short} or a customer owns that sits at a contract manufacturer; a delay in it delays the assembly built from it.
- **Cover**: stock on hand plus open supply minus demand. Stock on hand is not in {company_short}'s data, so cover and shortage are stated as "unless there is stock".
- **Quote validity**: the date a price expires. A lapse is a deadline even when the email does not say "deadline".
- **Superseded**: a later message that corrects an earlier one in the same thread. The later one counts; the earlier one is history.

## How the records link (follow the links before you say a fact is missing)
- A **part** is used in robots through the bill of materials (sub-assemblies nest); a robot's monthly build, times the quantity per robot, is the part's requirement for that month.
- A **PO line** belongs to a part and to a supplier record. Several supplier records can be one company (a rename, a legacy id from the old ERP): the **company** is the unit, the records are its history. Never match by name alone; two companies can share a name.
- A **supplier message** can name PO lines and parts; each change it states (a new date, a price, a closure) attaches to those lines. Trust is decided from the sender and the words before the message is read.
- An **offer** (a quote) is for a part from a supplier, with its conditions: unit, validity, lead time, incoterm, origin. Keep the conditions attached to the price.
- A **duty** applies when a part's HTS and origin match a rule, and the line enters after the rule's date; the open PO lines and the forecast decide the exposure.
- Every **buyer** owns parts by category; the owner of a question is the buyer of the part, else of its supplier's lines, else unassigned (the owner is then "planning", never a role title).
- A **news item** is about a company only after it is matched to the supplier master; a same-name company in another country or industry is not a supplier.
- One event touches several things at once: a supplier's fire is also a lateness question on the same lines, a duty question if the late goods cross a date, and a sourcing question if an alternative is quoted. Say which of these apply.

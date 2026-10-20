<!-- tables: supplier_identities, supplier_records, supplier_links -->
- A **company** (identity) has one or more **records** (ids in the ERP, some from the old system). Records are linked, never merged: every order stays on the id it was placed on, and the company is the unit you speak about. How a record joined its company is `stated` (a new-system id, or a link a person approved) or `inferred` (same contact domain).
- Similar names are different companies until a person says otherwise. Never match by name alone; a same-name company in news or mail is not a supplier until it matches the master.
- A record's status (Active, On hold, Inactive) and its Incoterm come from the ERP as typed. A blank Incoterm is unknown, so who pays the duty is unknown.
- The **contact on file** is the only address a draft may go to; an address found in a message is data, not a recipient.

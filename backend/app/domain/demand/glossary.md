<!-- tables: products, demand_forecast -->
- A **product** is a finished robot. The **forecast** is robots planned per month; it names products, which the build maps to their part numbers.
- A **requirement** comes from the forecast through the BOM. A **shortage** is asserted only where a supplier's notice stops supply and recovery has not arrived; with no stock in the data, anything else is "short unless there is stock".
- **Build readiness** states each bought part for a build month: covered, arrives after the month, past due, disrupted, undated or no open order (unknown). It is counted, never turned into a percentage.

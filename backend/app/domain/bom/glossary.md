<!-- tables: bom_lines -->
- A **bill of materials** line says how many of a child go into a parent. Sub-assemblies nest, and one can sit in several robots, so a part reaches a robot by one or more routes; where a part is used is read by following them all.
- A part's **requirement** in a month is robots planned × quantity per robot, summed over every route.
- Defects kept visible on a line: a repeated row (dropped once), a unit mismatch (millimetres where metres are meant), a child missing from the part master, an obsolete child.

# Fictional benchmark story: source contract changes

I implemented a Python contract check for loan-servicing extracts at Cedar Bank. When principal_amount changed from decimal to free text, the check stopped publication and alerted the source team. We agreed on a versioned decimal schema and replayed the affected business date. No revenue impact was quantified.

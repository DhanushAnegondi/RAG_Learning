# SQL review worksheet: {{query/model}}
Copy beside the model/test plan. Use the actual dialect; this is not executable SQL.

Engine/version and dialect: {{pin}}
Driving grain and key: {{definition}}
Expected join cardinalities: {{relationships}}
Time interval/timezone: {{half-open bounds and conversion}}
NULL and decimal policies: {{rules}}
Dedup order and tie-breaker: {{columns}}
Window frame intent: {{whole partition/running/bounded}}

| Fixture | Independently expected rows/totals | Comparison semantics | Command | Actual evidence |
|---|---|---|---|---|
| Tied ordering values | {{rows}} | {{multiset/order}} | {{command}} | unrun |
| NULL and unmatched join | {{rows}} | {{semantics}} | {{command}} | unrun |
| Duplicate row / rerun | {{rows}} | {{multiplicity preserved/removed}} | {{command}} | unrun |
| Exact time boundary | {{rows}} | {{semantics}} | {{command}} | unrun |

Plan command, data size and execution side effects: {{details}}
Performance observations: unmeasured

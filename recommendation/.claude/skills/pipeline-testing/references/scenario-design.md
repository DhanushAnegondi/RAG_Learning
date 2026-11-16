# Scenario design and fixture boundaries

Checked: 2026-11-09. Sources: [pytest fixtures](https://docs.pytest.org/en/stable/how-to/fixtures.html), [pytest exit codes](https://docs.pytest.org/en/stable/reference/exit-codes.html). Scenario priorities and data-engineering cases below are local guidance.

## Design a defect-catching check

Begin with the observable contract and hand-derived expected records. Choose fixtures that distinguish plausible wrong implementations: duplicate input with conflicting values, equal timestamps with different ordering keys, an empty batch, or a retry after only part of a write completed. Do not compute expected rows by calling the transformation being tested.

Use narrow fixture scope for mutable state and explicit teardown. A broader fixture is appropriate for expensive immutable setup, but shared mutable tables can make results depend on execution order. Integration checks must exercise the target engine when its transaction, SQL dialect or storage semantics matter.

## Pitfalls and adaptation

No collected tests is a distinct pytest outcome, not a pass. Report skips and expected failures alongside failures, and verify that the selected command collects the intended files. Pin engine/tool versions through the project rather than assuming the moving stable documentation matches them. Choose relevant scenarios and mark genuine N/A with a reason; do not invent deletes or ordering contracts the source does not supply.

# Claim-to-evidence discipline

Checked: 2026-11-09. [pytest exit codes](https://docs.pytest.org/en/stable/reference/exit-codes.html) distinguishes passed tests, failures, interruption, errors and no collection. The claim ledger is a local harness convention that applies to tools beyond pytest.

## Establish the claim's boundary

Apply [workflow policy](../../apiv-method/references/workflow-policy.md) for tier and evidence validity. Prior evidence remains usable only for unchanged relevant scope, dependencies and environment with trustworthy provenance; turn boundaries alone do not invalidate it. Required independent checks and explicit fresh sprint exits rerun.

Write the precise outcome before selecting its check. “Parser accepts valid metadata and rejects malformed inputs” needs both controls; “pipeline recovers after restart” needs actual recovery and reconciliation. A syntax check cannot establish either service behavior or independent review.

Record revision, command, environment, exit code, selected scope and result. Read the whole output, including skips and warnings. Verify that the intended tests were collected. A wrapper that discards the underlying exit status can make a broken command appear green; inspect the wrapper when evidence conflicts.

## Pitfalls and customization

Do not promote a historical run after connected files change. Do not turn unavailable environments into “not applicable.” Use the target project's full required checks and distinguish unrelated pre-existing failures from new ones with evidence. Customize claim wording and acceptance thresholds to the contract; keep missing proof visible in the handoff.

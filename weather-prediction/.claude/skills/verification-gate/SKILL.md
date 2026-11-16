---
name: verification-gate
description: "Validate evidence provenance and scope before reporting an outcome, a metric or closing a gate. Use before completion claims, handoffs, commits, PRs and README numbers."
---

# Verification gate

Evidence validity follows [workflow policy](../apiv-method/references/workflow-policy.md): revision, dependencies, environment, command, time, result and scope. It does not depend on the conversation turn.

## Before claiming an outcome

1. State the precise claim and the acceptance criterion it satisfies.
2. Inspect the actual artifact (diff, output file, trace), not a worker summary.
3. Run missing or invalidated checks. Reuse evidence only when relevant inputs, dependencies and environment are unchanged.
4. Read command output, exit status, collected/skipped counts and covered scope. N/A needs a reason; unavailable or failed is not N/A.
5. Tie the claim to the evidence and disclose limits.

## Proof boundaries

| Claim | Evidence needed |
|---|---|
| Tests pass | Intended scope collected; exit status 0; no hidden skips. Offline suite also run with `NVIDIA_API_KEY` unset. |
| Bug fixed | Reproduced failure, then passing regression test. |
| Metric improved (hit@k, correctness, recovery rate) | Eval run on the same corpus and eval set for both systems; result file path, models, commit, corpus hash recorded. |
| Idempotent indexing | Second run with no change makes zero embedding calls and leaves the index identical. |
| Degrades gracefully | Fault injected, run finished without crash, `degraded` and `errors` reported. |
| Independent review passed | A separate reviewer returned `VERDICT: PASS` on the actual diff. |

No number goes into a README or RESULTS.md without a recorded run. Planned, executed, inferred and measured stay labelled apart.

Read [claim evidence](references/claim-evidence.md) for pitfalls. Use the [claim ledger](assets/templates/claim-ledger.md) when a tracked evidence map helps.

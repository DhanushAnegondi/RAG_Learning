# Workflow policy

APIV is the single workflow: Align, Plan, Implement, Verify, Learn.

## Precedence

1. Runtime restrictions and user instructions.
2. Project constraints (offline tests, provider, clean repo) and named exit checks.
3. This policy for process depth, delegation and evidence.
4. Skills and role guidance, read within the selected tier.

Tier selection never waives secret handling or approval boundaries.

## Route before implementing

Classify by impact, uncertainty and reversibility, not file count. Promote if a High trigger appears; never demote to dodge a check.

| Tier | Use when | Minimum process and evidence |
|---|---|---|
| Low | Localized, reversible doc or mechanical fix, no behavior change | Inspect, edit, run a focused check, read the diff, note the outcome. No tickets. |
| Standard | Ordinary feature or refactor, understood boundaries | Short acceptance plan; tests incl. failure cases; review of the real diff; record result and limits. One agent may do it. |
| High | Public interface change; prompt, model, retrieval or routing change; persistent index format; secret or deploy boundary; any claim of measured improvement | Tracked spec; dependency-ordered tickets; separate builder and reviewer; offline suite plus eval run; explicit acceptance evidence. |

High work: keep detailed tickets to the current slice. Self-review does not satisfy independent review. If a reviewer or tool is unavailable, record it and leave that gate open.

## Evidence validity and reuse

Record: revision or file digests, dependency versions, config and environment, command, time, result, covered scope. For evals add: system under test, models, corpus hash, eval-set hash, seed. A worker summary or green status alone proves nothing.

Reuse evidence only when inputs, dependencies and environment are unchanged and provenance is trusted. Rerun when code, config, corpus, eval set or models change, when provenance is unclear, or when independent validation requires its own run.

N/A means the check does not apply, with a reason. A failed or unavailable check is not N/A. Keep failed history. Never report a gate passed without its evidence.

## Capture selection

Make diagrams or tables when topology or results benefit from them, or when asked. Keep source and provenance with each capture. Documentation edits alone need no images.

## Logging

Record tier and reason, decisions, failures, actual checks and handoff limits in proportion to the work. Keep logs out of the repo tree unless they are curated deliverables.

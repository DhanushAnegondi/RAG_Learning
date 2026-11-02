# Evidence-check tuning comparison — 2026-11-01

Compared original V2 with a quote-backed second check. Both runs used the same NVIDIA embedding
and Bolt E4B chat models, confirmed-source filters, and revised fictional corpus. V1 fast-mode
coverage is included for context. Each result is one live run; model outputs can vary.

| Questions | V1 fast | Original V2 | V2 with recheck |
|---|---:|---:|---:|
| Development: supported accepted | 18/18 | 15/18 | 17/18 |
| Development: unsupported rejected | 0/9 | 9/9 | 9/9 |
| Remaining: supported accepted | 12/12 | 9/12 | 11/12 |
| Remaining: unsupported rejected | 0/9 | 9/9 | 9/9 |
| Total: supported accepted | 30/30 | 24/30 | 28/30 |
| Total: unsupported rejected | 0/18 | 18/18 | 18/18 |

All four runs had zero API errors; the two recheck runs had zero recheck errors. V1 fast mode
counts any returned document as coverage. V2 selects reviewed passages and uses a model to assess
coverage; the recheck can override an insufficient decision only with an exact quote from a
selected passage. An exact quote proves text exists, not that it supports the requested claim.

The six supported fixture documents originally had headings describing the stories as fictional.
Those headings may have caused the model to treat simulated facts as explicitly untrue. They were
changed to neutral project headings; all fixture content remains fictional, as stated in the
benchmark README. Original V2 and recheck V2 were rerun against these same revised files, so these
figures must not be directly compared with the earlier test on the original fixtures.

The remaining questions had been inspected in a prior evaluation, so they are not a pristine
holdout. This measures source selection and coverage decisions, not final answer factuality,
performance on personal sources, or a guaranteed reduction in unsupported claims. The recheck adds
an extra model call on some questions. The next evaluation should use new, independently reviewed
questions and score individual generated claims as well as wrong-employer and unsupported-metric cases.

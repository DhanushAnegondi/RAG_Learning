# Fictional regression benchmark

48 questions: 30 supported and 18 unsupported. `split` marks dev and holdout paraphrases/negatives.
See [COVERAGE-RESULTS.md](COVERAGE-RESULTS.md) for the live coverage comparison.
See [TUNING-RESULTS.md](TUNING-RESULTS.md) for the subsequent checker comparison using revised fixture headings.
All employers, stories, claims and metrics in `fixtures/` are fictional. They must never be used
as candidate resume or interview evidence. A fixture's `confirmed` label means it is authoritative
inside this fictional test universe only.

Run `python -m copilot.cli evaluate` to validate the set without API calls.
See `../docs/TESTING.md` for live retrieval comparisons and optional generated-answer comparisons.
The set tests source selection, missing evidence, ownership boundaries, wrong-employer premises and
exclusion of synthetic/draft/unverified sources. It does not yet label each individual answer claim
or test multi-turn conversations. Results/indexes stay in ignored `results/`.

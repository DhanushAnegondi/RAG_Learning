# Sprint 01 ponytail review

Two independent reviewers (Sonnet agents, read-only) ran `ponytail-review`: one on code, one on
tests. Both returned VERDICT: FAIL. Every finding below is fixed, deferred with a reason, or
rejected with a reason. Evidence: `run/red-review.out` (new tests failing first, 66 cases),
`run/green.out`, `run/check.out`, `run/mutation.out`.

## Code review (VERDICT: FAIL -> fixed)

Passed as reviewed: no test-window leakage, no row dropped for missing data, fill flags mark
exactly the filled rows, scope arithmetic adds up, Recall / NDCG hand-checkable, same users and
candidates for every method, Telugu rows restricted to Telugu films for the baseline too.

| # | Finding | Outcome |
|---|---|---|
| 1 | "Naive" fill in the hidden-value check was one global median and one genre guess, so the fill looked about 3x better than it is | Fixed: naive = the film's language median (runtime, year) or the language's three most common genres, same number of guesses as the fill. `clean.masked_fill_check`; test `test_masked_check_scores_fills_and_a_fair_naive_fill` |
| 2 | Findings named "Best: popularity" on a 0.0025 recall gap, printed "hard to beat" as fixed text, and limits said "within noise" with nothing measured | Fixed: a winner is named only when it leads on Recall and NDCG and by at least 0.005 recall, otherwise "no clear winner"; the like-spread sentence states only the top film and its share; limits print the measured Telugu user and film counts. `pipeline.findings`, `_verdict`, `limit_notes`; 10 `test_findings_*` tests |
| 3 | `cmd \| tee file` in the Makefile returned tee's exit code, so a failing test run looked green | Fixed: `SHELL := bash`, `.SHELLFLAGS := -o pipefail -c`. Checked by hand: a failing piped command now exits non-zero |
| 4 | Blend scaled each part by the best candidate including films the user had already seen | Fixed: scale = best UNSEEN candidate; `blend(parts, weights, candidates, seen)`. Tests `test_blend_scales_by_the_best_unseen_candidate`, `test_the_blend_scale_ignores_a_seen_film_with_the_top_score` |
| 5 | Candidates included films not released yet | Fixed with a changed rule: a film is left out only when released on or after the END of the evaluation window (it cannot have a rating inside it). Films released inside the window stay, because recommending a new release is a real cold-start case. Films with no date stay. Counts are printed as a finding. `pipeline.released_before` |
| 6 | Popularity baseline counted likes from a 1-in-8 user sample | Fixed: `sql/marts/06_mart_like_counts.sql` counts likes before each cutoff over all users; item-item similarity still uses the sample (stated in limits) |
| 7 | Hidden-value check let earlier fills count as observed values | Fixed: every earlier fill is blanked before refilling. Test `test_masked_check_fills_see_observed_values_only` |
| 8 | Filled genres fed the similarity vectors (29 films shared a placeholder genre) | Fixed: the genre block uses observed genres only; filled genres stay for display. Test `test_filled_genres_are_not_a_similarity_signal` |
| 9 | Dedup kept the most complete copy, then applied the vote floor to it: 14 English films with a copy above the floor were cut | Fixed: `max_imdb_votes` over all copies of an id feeds the floor and the scope audit. Checked on the real warehouse after the rerun: 0 English ids have a copy above the floor and a kept copy below it, and the kept count is unchanged (34,122), so the reviewer's count of 14 did not reproduce. The rule is kept because it is the correct one and is tested |
| 10 | Two MovieLens ids for one film: the later rating replaced the earlier one, so 414 already-seen pairs could count as test hits | Fixed: the earliest rating and its time are kept; same-second ties go to the lower MovieLens id |
| 11 | `blend` crashed on an empty candidate set; zero-score films were returned as recommendations in index order | Fixed: empty set raises a named error; a slot with score <= 0 is not a recommendation (`top_k`) |
| 12 | Telugu blend weights chosen on 68 validation users, no minimum | Fixed: `Settings.min_validation_users = 30`; below it the Telugu shelf uses the all-films weights and the page says so. Validation user counts are printed next to the weights |
| 13 | The commands list on the page is a fixed list | Rejected: it is the list of commands to reproduce the sprint, and each one's captured output is shown beside it on the page. A missing output file is visible there |
| 14 | "4,405 repeated ids" was the count of extra rows; duplicates called "outside scope" | Fixed: wording is "extra copies of an id", counted apart from scope cuts |
| 15 | A gzip-encoded download would fail the length check and burn all retries | Fixed: the length check is skipped when `Content-Encoding` is set. Test `test_download_of_an_encoded_body_skips_the_length_check` |
| Lean | Dead code: `clean.missing_report`, `pipeline.pct`, unused `staged` argument, misleading `build_marts` defaults | Fixed: deleted; `build_marts` parameters are required |

## Test review (VERDICT: FAIL -> fixed)

Passed as reviewed: expectations are hand-derived (NDCG, neighbour cosine, shrunk score, audit
counts, blend, feature norms re-derived by the reviewer); no mirror assertions.

| # | Finding | Outcome |
|---|---|---|
| 1 | Dedup tie-break untested, and not deterministic: two copies equal on the ranked columns gave a different winner by load order (real bug) | Fixed: the order now covers every column. `test_dedup_tie_never_depends_on_the_order_rows_were_loaded` (13 cases), completeness-beats-votes and votes-then-title tests |
| 2 | Mutant "Unknown counts as a person" survived although the catalog said killed | Fixed: `test_literal_unknown_person_without_a_flag_is_not_a_similarity_signal`; `mutation.out` and `green.out` now exist |
| 3 | Filled-genre rule had no test (real bug, code finding 8) | Fixed, see code 8 |
| 4 | Validation / test wiring lived in `main`, untested: the headline leakage rule had no test | Fixed: wiring moved to `pipeline.eval_windows`, `choose_shelf_weights`, `score_test`. Tests `test_validation_window_never_sees_a_test_window_rating`, `test_blend_weights_are_chosen_on_validation_data_only`, boundary mutants on every cutoff |
| 5 | Item-item tests used symmetric matrices; a transposed product passed | Fixed: asymmetric matrix test |
| 6 | `seen` equalled `profile` in every fixture | Fixed: `test_evaluate_never_recommends_a_film_the_user_rated_and_disliked` |
| 7 | A zero-weight part nobody else used raised KeyError (real bug) | Fixed: weight checked before the lookup; test |
| 8 | Fixtures with equal similarities hid the vote weighting, k, the three-genre cap, tie order, the runtime language step, the per-language vote weight and the keyword cap | Fixed: nine tests in `test_clean.py`, each with a mutant |
| 9 | SQL rules untested: English null votes, blank text fields, 7 of 10 audit columns, `missing_after` > 0, coverage median | Fixed: five tests in `test_sql.py`. The "latest rating wins" test became "earliest rating wins" (code 10) |
| 10 | Repeated (user, film) pair and out-of-catalogue test ratings untested; `fit_collaborative` counted a repeated like twice (real bug) | Fixed: tests and a one-line guard |
| 11 | Ingest and warehouse edges: no Content-Length, retries exhausted, cut mid-stream, memory cap settings, snapshot order, repeated zip member | Fixed: seven tests |
| 12 | `bridge_table` k and similarity, `fill_examples`, `findings` fixed text ("dropped 0 rows"), `weight_grid` order, `scripts/recommend.py::find`, charts | Fixed: tests added; "dropped" is now computed from staged and cleaned row counts. `scripts/build_diagram.py` stays untested: deferred, it only reads captured files and its output is inspected by eye each sprint |
| 13 | Hidden-value check: year, naive and per-language outputs unasserted; seed could be ignored | Fixed: three tests, second seed |
| 14 | Error paths and keyword fallback untested | Fixed: four tests |
| 15 | Dead code with a test | Fixed: deleted |
| 16 | CATALOG.md did not match the tests on disk (15 missing, 5 phantom rows, stale text) | Fixed: catalog regenerated from the files on disk and cross-checked against `pytest --collect-only` |
| 17 | RED evidence weaker than the catalog claimed | Fixed: the catalog says what each RED file proves and no more; 57 tests carry `mutant` (no RED file, mutation run is their proof) |
| 18 | Mutation list: one survivor, many rules with no mutant | Fixed: 194 mutants after cycle 1 (196 after cycle 2), all killed. The first full run had 12 survivors; tests were strengthened; two bad mutants (one equivalent, one no-op) were dropped or rewritten |
| 19 | Smaller pins: pair key above 2^20, report escaping, multi-assert tests, empty inputs | Partly fixed: pair-key and escaping tests added. Deferred: splitting the multi-assert tests, and tests for empty inputs (the reviewer probed them and found no crash) |

Found by the new tests, not by a reviewer: `like_spread` summed in float32 and printed shares
such as 33.29999923706055 (now float64); `make test` printed no "N passed" line into `green.out`.

## Re-review of the changed parts (cycle 2, VERDICT: FAIL -> fixed)

A third Sonnet reviewer (read-only) checked only the behavior the fixes changed. Passed: blend
scaling and `top_k` edge cases, every window cutoff and like-count column, weights from
validation only, same users and candidates for every method, dedup total order, scope audit
arithmetic, observed-only genre block, the fair naive fill.

| # | Finding | Outcome |
|---|---|---|
| 1 | MEDIUM: the 0.005 winner margin ignored the user count, so "Best:" could be printed on a slice of 40 users where one hit moves recall more than that | Fixed: margin = max(0.005, 1/sqrt(users)), printed in the sentence. RED in `run/red-review2.out`; test `test_a_small_slice_needs_a_recall_lead_of_one_over_root_users`; two mutants. It is a rough guard, not a significance test |
| 2 | LOW: "Rating evidence is uneven" printed whatever the numbers were | Fixed: the sentence now only states the counts |
| 3 | LOW: "2024 snapshot" and "October 2023" in the limits are fixed text | Kept: both are facts about the source files, not results of the run |

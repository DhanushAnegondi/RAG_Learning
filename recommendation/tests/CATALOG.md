# Test catalog

All tests run offline (frames built in `conftest.py`, a fake HTTP session, in-memory DuckDB fed
from files written to `tmp_path`). One row per test function on disk (`pytest --collect-only`
lists the same names; `test_dedup_tie_never_depends_on_the_order_rows_were_loaded` is one row for
13 parametrised cases). Evidence lives in `results/sprint-01/run/`.

What each RED file proves, and no more:

- `red-collect.out`: the first seven test files run before any `src/cinebridge` module existed.
  Seven collection errors. It proves the order of work (tests first). It does not prove that any
  test can fail for a behavioral reason.
- `red-split.out`: three split / model-ratings SQL tests failing because their SQL step did not
  exist yet (a missing keyword argument). It proves the signature only.
- `red-realrun.out`: 21 tests failing before the four real-run fixes, mostly because function
  signatures changed (missing attribute, wrong arguments). Some also fail on a changed value.
- `red-review.out`: the tests written for review cycle 1 run before the fixes: 66 failing tests.
  Most are behavioral (a wrong value or a missing rule); a few fail on a changed signature.
  Tests that already passed then (guards for behavior that already worked, and new coverage of
  old code) carry `mutant`.
- `red-review2.out`: the user-count margin test of review cycle 2 failing before the fix
  (a behavioral failure: "Best:" printed on 40 users).
- `mutation.out` (`make mutate`): the behavioral proof for every row. Each mutant breaks one rule
  on purpose and the run stops at the first failing test. The third column lists the mutants
  that test failed first; a test can kill more mutants than it is listed for, but the file
  shows only the first failing test.
- `green.out` (`make test`).

RED column: every RED file in which that test is seen failing. `collect` = red-collect.out,
`split` = red-split.out, `realrun` = red-realrun.out, `review` = red-review.out, `review2` = red-review2.out, `mutant` = no
RED file shows it failing; its behavioral proof is the mutation run only.

| Test | Behavior | Mutants it failed first (mutation.out) | Layer | Sprint | RED | GREEN |
|---|---|---|---|---|---|---|
| test_clean::test_no_row_is_dropped_and_order_is_kept | same ids, same order | people left missing | unit | 01 | collect | yes |
| test_clean::test_filled_columns_have_no_missing_values | no null or blank in the 10 filled columns or score | - | unit | 01 | collect | yes |
| test_clean::test_observed_values_are_not_changed | real values untouched | - | unit | 01 | collect | yes |
| test_clean::test_flags_mark_exactly_the_filled_rows | `<col>_filled` == was missing, bool | - | unit | 01 | collect | yes |
| test_clean::test_input_frame_is_not_mutated | caller's frame unchanged | - | unit | 01 | collect | yes |
| test_clean::test_title_falls_back_to_original_title_then_to_a_label | Telugu-script original title, else "Untitled id" | title ignores the original title | unit | 01 | collect | yes |
| test_clean::test_year_is_the_language_median_of_observed_years | median per language, int | year filled with mean; year ignores language; unrelated films count as neighbours | unit | 01 | collect, realrun | yes |
| test_clean::test_year_comes_from_films_sharing_cast_before_the_language_median | year filled from the median of films sharing cast; lonely film gets the language median | year ignores similar films; similar films' year averaged, not the median | unit | 01 | realrun | yes |
| test_clean::test_a_filled_number_is_rounded_not_truncated | median 2017.5 fills as 2018, not 2017 | filled number truncated, not rounded | unit | 01 | mutant | yes |
| test_clean::test_year_with_no_observed_value_in_the_language_uses_all_films | fallback to all films | - | unit | 01 | collect, realrun | yes |
| test_clean::test_year_with_nothing_observed_raises | nothing to fill from raises | - | unit | 01 | collect, realrun | yes |
| test_clean::test_runtime_uses_language_and_first_genre_when_the_group_is_big_enough | group median; thin group -> language; no language data -> all | runtime from a too-small group; runtime ignores genre | unit | 01 | collect | yes |
| test_clean::test_runtime_medians_ignore_other_languages | Telugu fill from Telugu runtimes | - | unit | 01 | collect | yes |
| test_clean::test_genres_come_from_the_most_similar_films | neighbours by shared director vote | weak genre votes kept | unit | 01 | collect | yes |
| test_clean::test_genres_keep_every_genre_with_at_least_half_the_top_vote | half-of-top rule, hand-counted | - | unit | 01 | collect | yes |
| test_clean::test_genres_fall_back_to_the_language_favourite_when_nothing_is_similar | zero-similarity film gets language favourite | - | unit | 01 | collect | yes |
| test_clean::test_overview_is_built_from_the_film_s_own_fields | exact sentence; no "Unknown" in it | cast left out of built overview; built overview lists the whole cast; tagline left out of built overview | unit | 01 | collect | yes |
| test_clean::test_keywords_are_drawn_from_the_film_s_own_overview | top words of own overview; observed keywords kept | - | unit | 01 | collect | yes |
| test_clean::test_keywords_for_a_filled_overview_come_from_genres | built overview is not mined for keywords | keywords drawn from a built overview | unit | 01 | collect | yes |
| test_clean::test_people_get_a_placeholder_and_a_flag | "Unknown" + flags | - | unit | 01 | collect | yes |
| test_clean::test_score_shrinks_low_vote_films_toward_the_language_mean | score formula hand-computed; no-vote film = mean | score not shrunk | unit | 01 | collect | yes |
| test_clean::test_score_uses_each_language_s_own_mean | Telugu mean for Telugu films | rating mean ignores language | unit | 01 | collect | yes |
| test_clean::test_masked_check_scores_fills_and_a_fair_naive_fill | hidden rows fixed by hand (first of each language); fill error and the naive language-median / top-3-genres error asserted per column and language, plus metric text and row order | mask size wrong; naive fill uses one median for all languages; naive genre guess gets one genre, the fill gets three; naive genre guess sees the hidden rows; naive genre guess takes the rarest genres | unit | 01 | review | yes |
| test_clean::test_masked_check_fills_see_observed_values_only | values the pipeline filled earlier (flag set, extreme 999) are treated as missing and never scored | earlier fills treated as observed in the masked check; fill error doubled | unit | 01 | review | yes |
| test_clean::test_masked_check_is_repeatable_for_a_seed_and_follows_it | same seed gives the same table; another seed hides other films | masked check ignores its seed | unit | 01 | mutant | yes |
| test_clean::test_clean_refuses_to_return_fewer_rows | a fill that drops a row raises CleanError | dropped-row guard off | unit | 01 | mutant | yes |
| test_clean::test_clean_refuses_to_return_a_gap | a fill that leaves nulls raises CleanError | leftover-gap guard off | unit | 01 | mutant | yes |
| test_clean::test_genre_votes_are_weighted_by_similarity | genre votes weighted by similarity (0.735 vs 0.176 + 0.176), not head count | genre votes counted, not weighted by similarity | unit | 01 | mutant | yes |
| test_clean::test_only_the_k_nearest_films_vote_for_genres | k=1 lets only the nearest film vote; k=3 lets all three (Comedy, Thriller) | all neighbours vote, not the k nearest | unit | 01 | mutant | yes |
| test_clean::test_a_film_gets_at_most_three_genres_and_ties_go_alphabetically | four genres tie on one vote: the first three alphabetically are kept | genre cap off | unit | 01 | mutant | yes |
| test_clean::test_year_uses_only_the_k_nearest_films | k=2 of three equally similar films: median of the first two years | year uses every similar film, not the k nearest | unit | 01 | mutant | yes |
| test_clean::test_runtime_thin_group_falls_back_to_the_language_median_not_the_global_one | thin (language, genre) group uses the Telugu median 165, not the all-film median 100 | runtime thin group uses the all-film median, not the language's | unit | 01 | mutant | yes |
| test_clean::test_score_weight_is_the_median_votes_of_the_film_s_own_language | score shrink weight m is the film's language median votes | vote weight ignores language | unit | 01 | mutant | yes |
| test_clean::test_language_favourite_tie_goes_to_the_alphabetically_first_genre | zero-similarity film in a language where two genres tie gets Action, not Drama | language favourite tie goes to the last genre | unit | 01 | mutant | yes |
| test_clean::test_keywords_keep_only_the_top_n_words | six equally weighted words, top_n=5: first five alphabetically | keyword count not capped | unit | 01 | mutant | yes |
| test_clean::test_keywords_fall_back_to_genres_when_the_overview_has_no_usable_words | an overview of only stop words yields genre keywords | - | unit | 01 | mutant | yes |
| test_clean::test_fills_refuse_when_nothing_is_observed_to_fill_from | genres, runtime and rating raise CleanError when no value is observed | - | unit | 01 | mutant | yes |
| test_clean::test_overview_needs_genres_to_be_filled_first | fill_overview raises if a film still has no genres | - | unit | 01 | mutant | yes |
| test_clean::test_keywords_need_genres_when_there_is_no_overview_to_mine | fill_keywords raises if neither overview nor genres can supply words | - | unit | 01 | mutant | yes |
| test_evaluate::test_split_is_strict_at_the_cutoff | train < cutoff <= test | cutoff rating leaks into train; test split is the train split | unit | 01 | collect | yes |
| test_evaluate::test_window_keeps_start_and_leaves_out_end | half-open window | window end included; window start excluded | unit | 01 | collect | yes |
| test_evaluate::test_user_matrices_split_likes_seen_and_later_likes | profile, seen, relevant; unknown film ignored | already-rated film counts as a hit; profile built from every rated film | unit | 01 | collect | yes |
| test_evaluate::test_user_matrices_need_enough_liked_films_in_the_profile | min_profile; 4.0 is a like | like boundary; thin profiles tested | unit | 01 | collect | yes |
| test_evaluate::test_recall_and_ndcg_by_hand | recall 2/3, NDCG by hand | hit rate counts hits, not users | unit | 01 | collect | yes |
| test_evaluate::test_ndcg_ideal_is_capped_by_the_number_of_relevant_items | one relevant item at rank 1 = NDCG 1 | NDCG ideal not capped | unit | 01 | collect | yes |
| test_evaluate::test_unfilled_slots_never_count_as_hits | padded slot ignored | unfilled slot counts as a hit | unit | 01 | collect | yes |
| test_evaluate::test_evaluate_reports_each_method_on_the_same_users | same users per method; hand-computed means | seen items recommended; worst items first; recall divided by min(relevant, k) | unit | 01 | collect, realrun | yes |
| test_evaluate::test_slice_limits_candidates_and_hits_for_every_method | Telugu slice: only Telugu films recommended | slice candidates ignored | unit | 01 | collect, realrun | yes |
| test_evaluate::test_slice_user_mask_and_users_without_a_relevant_item_are_left_out | user filter; no-relevant users excluded | slice user filter ignored; hits outside the slice count; users counted over everyone | unit | 01 | collect, realrun | yes |
| test_evaluate::test_evaluate_blends_parts_with_the_given_weights | 0.6 a + 0.4 b ranks like a; 0.4 a + 0.6 b ranks like b; hand-computed | method weights ignored | unit | 01 | realrun | yes |
| test_evaluate::test_evaluate_gives_the_same_answer_in_small_batches | batch size does not change results | - | unit | 01 | collect, realrun | yes |
| test_evaluate::test_choose_weights_picks_the_best_blend_and_reports_every_candidate | best recall wins; the table lists every grid entry with users and recall | - | unit | 01 | realrun | yes |
| test_evaluate::test_choose_weights_tie_goes_to_the_first_grid_entry | tie on recall goes to the first entry | weight tie goes to the last grid entry | unit | 01 | realrun | yes |
| test_evaluate::test_choose_weights_scores_only_users_with_a_relevant_candidate | users with no relevant film on the shelf are not scored | weights tuned on users outside the shelf | unit | 01 | realrun | yes |
| test_evaluate::test_choose_weights_with_nobody_to_score_returns_the_first_entry | no scorable user: first entry, zero users, no crash | - | unit | 01 | realrun | yes |
| test_evaluate::test_a_repeated_user_film_pair_is_still_one_entry | a user-film pair rated twice is one cell in profile, seen and relevant | a repeated rating counts twice | unit | 01 | mutant | yes |
| test_evaluate::test_test_ratings_of_films_outside_the_catalogue_are_ignored | a test-window like of a film not in the catalogue is not a hit | test ratings of films outside the catalogue kept | unit | 01 | mutant | yes |
| test_evaluate::test_pair_key_keeps_film_ids_above_two_to_the_twenty_apart | film ids above 2**20 do not collide with another user's pair | pair key collides for large film ids | unit | 01 | mutant | yes |
| test_evaluate::test_recall_divides_by_every_relevant_item_not_by_k | 2 hits of 4 relevant = 0.5 with k=2 | - | unit | 01 | mutant | yes |
| test_evaluate::test_hit_rate_counts_a_user_once_however_many_hits | three hits count one user | - | unit | 01 | mutant | yes |
| test_evaluate::test_a_zero_weight_part_that_no_method_uses_is_not_scored | a part with weight 0 in every method is not looked up | blend looks up a part whose weight is zero; evaluate scores a part with zero weight | unit | 01 | review | yes |
| test_evaluate::test_a_slice_nobody_qualifies_for_reports_nan_not_zero | zero qualifying users gives NaN recall, not 0 | - | unit | 01 | mutant | yes |
| test_evaluate::test_users_count_only_those_with_a_relevant_item_in_the_slice | users column counts users with a relevant film on the shelf | - | unit | 01 | mutant | yes |
| test_evaluate::test_evaluate_never_recommends_a_film_the_user_rated_and_disliked | seen (every rated film) differs from profile (liked): evaluate and choose_weights hide the disliked film | evaluate hides liked films, not every rated film; weights tuned hiding liked films, not every rated film | unit | 01 | mutant | yes |
| test_evaluate::test_the_blend_scale_ignores_a_seen_film_with_the_top_score | a seen film with a huge score does not set the scale; film 2 wins as a hit | blend scaled by a seen film; blend scaled over all films, not the shelf; weights scaled by liked films, not every rated film | unit | 01 | review | yes |
| test_evaluate::test_a_zero_score_pick_is_not_a_hit | all scores zero: no recommendation, so no hit | zero-score slot counts as a recommendation | unit | 01 | review | yes |
| test_features::test_a_film_with_every_field_is_unit_length_and_a_film_with_gaps_is_shorter | full film has length 1; film without text has sqrt(0.72 / 1.72) | every row rescaled to length 1 (gaps rewarded) | unit | 01 | realrun | yes |
| test_features::test_a_film_with_gaps_does_not_outrank_a_fuller_match | genre-only film matches at 0.36 / 1.72, below a fuller match | - | unit | 01 | realrun | yes |
| test_features::test_shared_director_makes_films_more_alike | people are a signal | - | unit | 01 | collect | yes |
| test_features::test_unknown_people_are_not_a_similarity_signal | two "Unknown" directors: cosine 0 | - | unit | 01 | collect | yes |
| test_features::test_filled_overview_and_keywords_are_not_a_similarity_signal | built text ignored | filled text counts as signal | unit | 01 | collect | yes |
| test_features::test_language_is_not_a_wall_between_similar_films | en and te films with alike plots score > 0.3 | - | unit | 01 | collect | yes |
| test_features::test_only_the_first_five_cast_names_count | top-5 cast | whole cast list used | unit | 01 | collect | yes |
| test_features::test_a_film_with_no_usable_fields_gets_a_zero_vector | zero row, no NaN | - | unit | 01 | collect | yes |
| test_features::test_genres_can_be_left_out | include_genres=False | - | unit | 01 | collect | yes |
| test_features::test_literal_unknown_person_without_a_flag_is_not_a_similarity_signal | directors and cast 'Unknown' with no _filled column: cosine 0 | Unknown counts as a person | unit | 01 | mutant | yes |
| test_features::test_filled_genres_are_not_a_similarity_signal | two language-favourite genres do not match each other or an observed film; the genre text stays | filled genres count as signal | unit | 01 | review | yes |
| test_features::test_observed_genres_still_match_when_another_row_was_filled | observed genres match; the flagged row does not | - | unit | 01 | review | yes |
| test_ingest::test_download_writes_file_and_sets_timeout | body streamed to dest, timeout set | - | unit | 01 | collect | yes |
| test_ingest::test_download_skips_existing_file_without_a_request | landed file is reused | existing file refetched | unit | 01 | collect | yes |
| test_ingest::test_download_retries_server_error_then_succeeds | 503 and 429 retried, waits 1s then 2s | 429 not retried; no growing wait between retries | unit | 01 | collect | yes |
| test_ingest::test_download_retries_connection_error | dropped connection retried | connection error not retried | unit | 01 | collect | yes |
| test_ingest::test_download_client_error_fails_fast | 404 raises at once, no file | - | unit | 01 | collect | yes |
| test_ingest::test_download_truncated_body_is_not_kept | short body retried, then raises, no file left | short download kept; partial file left behind | unit | 01 | collect | yes |
| test_ingest::test_download_without_a_content_length_header_keeps_the_file | no Content-Length header: body kept after one request | download without a length header never succeeds | unit | 01 | mutant | yes |
| test_ingest::test_download_of_an_encoded_body_skips_the_length_check | Content-Encoding gzip: length mismatch is expected, file kept | length checked on an encoded body | unit | 01 | review | yes |
| test_ingest::test_download_gives_up_after_the_last_attempt_without_a_final_wait | three 503s: waits 1s, 2s only; no file left | wait after the last attempt | unit | 01 | mutant | yes |
| test_ingest::test_download_cut_off_mid_stream_leaves_no_part_file | connection dropped mid-body: retried, no .part file left | - | unit | 01 | mutant | yes |
| test_ingest::test_download_cut_off_on_every_attempt_leaves_nothing_behind | every attempt drops: IngestError, folder empty | - | unit | 01 | mutant | yes |
| test_ingest::test_extract_movielens_takes_only_ratings_and_links | exact-name members only, fixed output names | loose zip member match | unit | 01 | collect | yes |
| test_ingest::test_extract_movielens_keeps_the_first_of_a_repeated_member | a second ratings.csv in the zip does not overwrite the first | a repeated zip member overwrites the first | unit | 01 | mutant | yes |
| test_ingest::test_extract_movielens_missing_member_raises | missing links.csv raises | - | unit | 01 | collect | yes |
| test_pipeline::test_collaborative_fit_uses_only_sampled_users_likes_before_the_cutoff | item-item neighbours see only sampled users' likes before the cutoff (an unsampled user's likes, dislikes and later ratings are ignored) | cosine without the square root; collaborative fit sees the future; collaborative fit uses unsampled users; dislikes counted as likes | unit | 01 | review | yes |
| test_pipeline::test_collaborative_fit_counts_a_repeated_like_once | a user-film like twice is one like: similarity 1.0, not 1.22 | a repeated like counts twice | unit | 01 | review | yes |
| test_pipeline::test_popularity_vector_is_aligned_to_the_film_order_and_reads_the_asked_column | mart like counts aligned to film order; missing film is 0; float32; column chosen | unliked film gets a like | unit | 01 | review | yes |
| test_pipeline::test_parts_score_in_film_order | three scorers in film order | - | unit | 01 | realrun | yes |
| test_pipeline::test_weight_grid_covers_the_simplex_content_first | step 0.5 grid: the six entries in exact order | weight grid no longer content-first; weight grid no longer item-item-first within a content level | unit | 01 | realrun | yes |
| test_pipeline::test_weight_grid_of_a_quarter_has_fifteen_blends_that_each_sum_to_one | step 0.25: 15 entries summing to 1 | - | unit | 01 | mutant | yes |
| test_pipeline::test_released_before_keeps_unknown_dates_and_films_released_inside_the_window | release on or after the end excluded; null date and earlier dates kept | films with no release date dropped from the candidates; film released on the window end stays a candidate | unit | 01 | review | yes |
| test_pipeline::test_validation_window_never_sees_a_test_window_rating | validation profile, seen, relevant and item-item fit hold nothing from the validation or test window beyond their cutoffs | validation profile includes validation-window likes; validation scored on test-window likes; validation neighbours fitted on the validation window | unit | 01 | review | yes |
| test_pipeline::test_test_window_profile_and_seen_include_the_validation_window_but_not_test_ratings | test profile and seen include the validation-window like; relevant is the test-window like; neighbours from before test_start | test profile misses the validation window; test neighbours fitted before the validation window only | unit | 01 | review | yes |
| test_pipeline::test_popularity_comes_from_the_like_count_column_of_each_window | validation uses likes_before_val, test uses likes_before_test | validation popularity counts likes up to the test cutoff | unit | 01 | review | yes |
| test_pipeline::test_candidates_drop_films_released_on_or_after_each_window_end | candidate masks and excluded counts per window, boundary days included | validation candidates use the test window end; test candidates use the validation window end | unit | 01 | review | yes |
| test_pipeline::test_blend_weights_are_chosen_on_validation_data_only | weights follow the validation window even when the test window would pick another blend | blend weights chosen on the test window; shelf with exactly the minimum users falls back | unit | 01 | review | yes |
| test_pipeline::test_weights_ignore_films_that_cannot_be_hits_in_the_validation_window | weights judged on candidates only; the unreleased most-popular film is skipped | Telugu shelf weights ignore the window mask; all-films weights ignore the window mask | unit | 01 | mutant | yes |
| test_pipeline::test_a_shelf_with_too_few_validation_users_uses_the_all_films_weights | Telugu shelf with 1 < 2 validation users borrows the all-films weights and says so | thin Telugu shelf keeps its own weights | unit | 01 | review | yes |
| test_pipeline::test_test_scoring_uses_the_test_candidates_and_each_shelf_s_own_weights | test candidates mask (also on the Telugu shelf), hybrid weights per shelf, first-time slice | test candidates ignore the window mask; Telugu test candidates ignore the window mask; Telugu hybrid uses the all-films weights; all-films hybrid uses the Telugu weights; first-time slice takes the users with Telugu history | unit | 01 | review | yes |
| test_pipeline::test_bridge_table_recommends_only_the_other_language | bridge rows are other-language only | bridge ignores the language filter; bridge stays in the seed language | unit | 01 | mutant | yes |
| test_pipeline::test_bridge_table_lists_a_repeated_title_once | repeated title listed once | bridge lists a repeated title twice | unit | 01 | mutant | yes |
| test_pipeline::test_bridge_table_lists_at_most_k_films_with_a_hand_derived_similarity | k=2 of three equal matches; similarity 0.791 = (1 + 0.36) / 1.72 | bridge lists more than k films; bridge similarity rounded to one decimal | unit | 01 | mutant | yes |
| test_pipeline::test_like_spread_counts_shelf_likes_most_liked_first | shelf likes, shares and cumulative shares, most-liked first, top limit | like spread counts films outside the shelf | unit | 01 | mutant | yes |
| test_pipeline::test_like_spread_rounds_to_one_decimal | shares 33.3 / 66.7 as plain floats | - | unit | 01 | review | yes |
| test_pipeline::test_like_spread_with_no_likes_is_an_empty_table | empty table keeps its columns | - | unit | 01 | mutant | yes |
| test_pipeline::test_fill_examples_lists_the_gappiest_telugu_films_and_marks_filled_values | five-gap film first, ties by votes then id; English film left out; (filled) marks | fill examples list the fullest films first; fill examples do not mark filled genres | unit | 01 | review | yes |
| test_pipeline::test_findings_are_built_from_the_tables_they_describe | catalogue, fill, rating-evidence, per-slice Recall and NDCG sentences carry the table numbers; empty slice says nothing measured | - | unit | 01 | realrun, review | yes |
| test_pipeline::test_findings_name_a_winner_only_with_the_best_recall_and_ndcg_and_a_clear_lead | winner needs best recall, best NDCG and a 0.005 lead; every method still listed | a best method named with no recall lead; a best method named without leading on NDCG | unit | 01 | review | yes |
| test_pipeline::test_a_recall_lead_of_exactly_the_margin_counts_even_with_float_noise | 0.102 - 0.097 (0.00499999) counts as a 0.005 lead | winner margin hit by float noise | unit | 01 | review | yes |
| test_pipeline::test_a_small_slice_needs_a_recall_lead_of_one_over_root_users | margin = max(0.005, 1/sqrt(users)): 40 users need 0.158, 10,000 need 0.01; a lead of exactly the margin counts | winner margin ignores how few users a slice has; a lead of exactly the margin does not count | unit | 01 | review2 | yes |
| test_pipeline::test_a_tie_on_the_best_recall_is_no_clear_winner | equal best recall: no winner | - | unit | 01 | review | yes |
| test_pipeline::test_findings_state_only_measured_facts_about_the_like_spread | top film, its share, top-3 share, distinct films; no unmeasured claim | - | unit | 01 | review | yes |
| test_pipeline::test_findings_with_no_telugu_likes_leave_the_spread_sentence_out | empty spread: no sentence | - | unit | 01 | review | yes |
| test_pipeline::test_findings_compute_dropped_rows_and_report_what_is_still_missing | dropped rows = staged - cleaned; still-missing count from the audit | dropped rows hard-coded; still-missing count hard-coded | unit | 01 | review | yes |
| test_pipeline::test_findings_describe_duplicates_as_extra_copies_not_scope | duplicate ids worded as extra copies; adult and floor counts shown | - | unit | 01 | review | yes |
| test_pipeline::test_findings_say_how_many_films_each_window_left_out_of_the_candidates | validation and test exclusion counts on the page | excluded counts swapped on the page | unit | 01 | review | yes |
| test_pipeline::test_findings_print_validation_users_next_to_each_shelf_s_weights | validation user count next to each shelf's weights | validation users not shown next to the weights | unit | 01 | review | yes |
| test_pipeline::test_findings_say_when_the_telugu_shelf_fell_back_to_the_all_films_weights | fallback sentence names the users and the minimum | fallback not announced | unit | 01 | review | yes |
| test_pipeline::test_limits_state_the_measured_telugu_counts_and_the_vote_snapshot | limits carry measured Telugu counts, the 2024 vote snapshot, sample and popularity wording | vote-floor snapshot limit missing; Telugu test user count not measured | unit | 01 | review | yes |
| test_pipeline::test_chart_missing_writes_a_png | chart_missing writes a PNG | - | unit | 01 | mutant | yes |
| test_pipeline::test_chart_eval_writes_a_png | chart_eval writes a PNG | - | unit | 01 | mutant | yes |
| test_pipeline::test_chart_fill_quality_writes_a_png | chart_fill_quality writes a PNG | - | unit | 01 | mutant | yes |
| test_recommend::test_popularity_counts_likes_per_item | like counts | - | unit | 01 | collect | yes |
| test_recommend::test_item_neighbors_is_cosine_of_shared_likes | cosine by hand; zero diagonal; no-like item safe | item is its own neighbour | unit | 01 | collect | yes |
| test_recommend::test_item_neighbors_shrink_pulls_thin_evidence_down | shrink in the denominator | - | unit | 01 | collect | yes |
| test_recommend::test_item_neighbors_keeps_only_the_top_n_per_item_and_blocks_agree | top-n kept; block size does not change values | every neighbour kept, not the top n; neighbour block offset lost | unit | 01 | collect | yes |
| test_recommend::test_cf_scores_read_row_i_as_the_neighbours_of_liked_item_i | asymmetric neighbour matrix: liked item i reads row i | item-item score reads neighbours in the wrong direction | unit | 01 | mutant | yes |
| test_recommend::test_content_scores_are_cosine_to_the_mean_liked_vector | cosine to taste vector; empty profile = 0 | taste vector not normalised | unit | 01 | collect | yes |
| test_recommend::test_blend_endpoints_and_row_scaling | alpha 0/1/0.5; no-signal row keeps content order | blend without scaling | unit | 01 | collect, realrun, review | yes |
| test_recommend::test_blend_scales_each_part_inside_the_candidate_set | scaling by the best candidate, not the best film overall | - | unit | 01 | realrun, review | yes |
| test_recommend::test_blend_scales_by_the_best_unseen_candidate | a seen film does not set the scale: [0.75, 0.75] for the two unseen films | - | unit | 01 | review | yes |
| test_recommend::test_blend_of_a_user_who_has_seen_every_candidate_is_zero_not_nan | all candidates seen: zeros | - | unit | 01 | review | yes |
| test_recommend::test_blend_rejects_bad_weights | negative or zero-sum weights raise; unknown part raises KeyError | - | unit | 01 | realrun, review | yes |
| test_recommend::test_blend_with_no_candidate_raises | empty candidate set raises ValueError | blend accepts an empty candidate set | unit | 01 | review | yes |
| test_recommend::test_blend_does_not_look_up_a_part_whose_weight_is_zero | weight 0 is skipped before the part is looked up | - | unit | 01 | review | yes |
| test_recommend::test_top_k_skips_seen_items_and_items_outside_the_candidates | seen and non-candidates excluded; input untouched | - | unit | 01 | collect | yes |
| test_recommend::test_top_k_breaks_ties_by_item_order | deterministic ties | - | unit | 01 | collect | yes |
| test_recommend::test_top_k_marks_slots_it_could_not_fill | shape (users, k); valid=False padding | - | unit | 01 | collect | yes |
| test_recommend::test_top_k_zero_score_slot_is_not_a_recommendation | zero-score slots are valid=False | - | unit | 01 | review | yes |
| test_recommend::test_top_k_ties_go_to_the_lower_index_on_a_long_list | 60 tied scores: indexes 0-4 | top-k ties not deterministic | unit | 01 | mutant | yes |
| test_recommend::test_similar_items_ties_go_to_the_lower_index_on_a_long_list | 60 tied films: ids 1-5 | seed film returned as its own match; bridge ties not deterministic | unit | 01 | mutant | yes |
| test_recommend::test_similar_items_ranks_within_candidates_and_leaves_out_the_seed | bridge lookup: candidates only, no seed, no zero matches | - | unit | 01 | collect | yes |
| test_recommend_script::test_an_exact_title_beats_a_higher_voted_partial_match | exact title match wins over votes | - | unit (scripts) | 01 | mutant | yes |
| test_recommend_script::test_without_an_exact_match_the_best_known_film_containing_the_text_wins | contains-match picks the highest-voted film that contains the text | - | unit (scripts) | 01 | mutant | yes |
| test_recommend_script::test_a_telugu_script_original_title_matches | Telugu-script original title is matched | - | unit (scripts) | 01 | mutant | yes |
| test_recommend_script::test_regex_characters_in_the_query_are_literal | regex characters in the query are literal | - | unit (scripts) | 01 | mutant | yes |
| test_recommend_script::test_a_missing_original_title_does_not_break_the_search | null original_title is tolerated | - | unit (scripts) | 01 | mutant | yes |
| test_recommend_script::test_no_match_returns_none | no match returns None | - | unit (scripts) | 01 | mutant | yes |
| test_report::test_page_lists_sprints_newest_first_with_natural_order | sprint-10 above sprint-9 | sprints oldest first; sprint-10 sorted below sprint-9 | unit | 01 | collect | yes |
| test_report::test_page_shows_terminal_output_and_csv_cells_escaped | output, cells, findings escaped | terminal output not escaped | unit | 01 | collect | yes |
| test_report::test_page_keeps_telugu_script | Telugu text survives, utf-8 declared | - | unit | 01 | collect | yes |
| test_report::test_page_shows_table_schema_count_and_sample | snapshots rendered in table_order | - | unit | 01 | collect | yes |
| test_report::test_page_embeds_charts_and_caption_titles | charts inline, captions used | - | unit | 01 | collect | yes |
| test_report::test_page_escapes_review_limits_commands_and_caption_text | review.md, limits, commands, scripts and caption text are HTML-escaped | commands not escaped; limits not escaped; review notes not escaped; caption notes not escaped | unit | 01 | mutant | yes |
| test_sql::test_load_movies_keeps_only_english_and_telugu | raw holds en + te only | other languages landed | integration (DuckDB) | 01 | collect | yes |
| test_sql::test_load_movies_rerun_gives_same_rows | full refresh is idempotent | - | integration | 01 | collect | yes |
| test_sql::test_staging_keeps_telugu_below_the_english_vote_floor | Telugu films kept at 3 or null votes; English cut at 999 | Telugu films cut by the English vote floor | integration | 01 | collect | yes |
| test_sql::test_staging_excludes_adult_titles_and_treats_null_adult_as_not_adult | adult out; null flag = not adult | adult titles kept; null adult flag drops the film | integration | 01 | collect | yes |
| test_sql::test_staging_dedup_keeps_the_most_complete_row | repeated id keeps the fullest copy | dedup keeps the emptiest copy | integration | 01 | collect | yes |
| test_sql::test_staging_cuts_an_english_film_with_no_votes | English film with NULL votes is cut | - | integration (DuckDB) | 01 | mutant | yes |
| test_sql::test_vote_floor_looks_at_the_highest_vote_count_among_the_copies_of_an_id | film kept when another copy clears the floor; kept row keeps its own votes; audit agrees | vote floor reads the kept copy only; vote floor reads the lowest copy; scope audit counts the vote floor on the kept copy; duplicates not counted | integration (DuckDB) | 01 | review | yes |
| test_sql::test_dedup_completeness_beats_votes_and_title | completeness first, both load orders | - | integration (DuckDB) | 01 | mutant | yes |
| test_sql::test_dedup_equal_completeness_goes_to_more_votes_then_to_title | then votes, then title, both orders | dedup keeps the least-voted copy; dedup title tie-break reversed | integration (DuckDB) | 01 | mutant | yes |
| test_sql::test_dedup_tie_never_depends_on_the_order_rows_were_loaded | 13 parametrised columns: copies differing only there rank the same in either load order | dedup tie-break on imdb_id dropped; dedup tie-break on genres dropped; dedup tie-break on popularity dropped | integration (DuckDB) | 01 | review | yes |
| test_sql::test_dedup_tie_between_an_adult_and_a_non_adult_copy_keeps_the_non_adult_one | adult flag is the last tie-break | dedup tie-break on the adult flag dropped | integration (DuckDB) | 01 | review | yes |
| test_sql::test_every_blank_text_field_becomes_null | blank title, original_title, tconst, tagline, status become NULL | blank title treated as real; blank original title treated as real; blank IMDb id treated as real; blank tagline treated as real; blank status treated as real | integration (DuckDB) | 01 | mutant | yes |
| test_sql::test_staging_turns_blanks_zero_runtime_and_bad_dates_into_null_but_keeps_the_row | blanks, 0 runtime, bad date become null; row stays | zero runtime treated as real; blank overview treated as real | integration | 01 | collect | yes |
| test_sql::test_staging_reads_release_year_from_the_date | year from date | - | integration | 01 | collect | yes |
| test_sql::test_scope_audit_counts_add_up | landed, duplicates, adult, below floor, kept by language | scope audit counts Telugu films under the floor | integration | 01 | collect | yes |
| test_sql::test_ratings_map_to_tmdb_ids_and_drop_out_of_scope_movies | MovieLens id -> TMDB id; unknown or null ids dropped | out-of-scope ratings kept | integration | 01 | collect | yes |
| test_sql::test_two_movielens_ids_for_one_film_keep_the_earliest_rating_and_its_time | earliest rating and its time kept whether the later one is higher or lower | latest rating kept, not the earliest | integration (DuckDB) | 01 | review | yes |
| test_sql::test_two_movielens_ids_rated_at_the_same_second_keep_the_lower_movielens_id | same-second tie goes to the lower id in both file orders | same-second tie goes to the higher MovieLens id | integration (DuckDB) | 01 | review | yes |
| test_sql::test_ratings_rerun_gives_same_rows | ratings load idempotent | link table not refreshed | integration | 01 | collect | yes |
| test_sql::test_missing_audit_reports_every_column_with_its_own_counts_and_a_gap_left_after | all 10 columns per language with different counts, pct, and missing_after > 0 for an unfilled gap | audit counts the wrong flag; audit reads the wrong column before cleaning; audit never sees a year left missing; audit never sees genres left missing; audit votes flag reads the rating flag | integration (DuckDB) | 01 | review | yes |
| test_sql::test_write_clean_refuses_a_frame_that_lost_or_gained_rows | cleaned frame must match staged row count | row-count guard off | integration | 01 | collect | yes |
| test_sql::test_write_clean_refuses_a_frame_with_different_ids | cleaned frame must hold the staged ids | id guard off | integration | 01 | collect | yes |
| test_sql::test_rating_coverage_counts_films_ratings_likes_and_the_median_by_language | films, rated films, ratings, likes and median_ratings_per_rated_film | coverage median not computed; like rating never passed to the marts | integration (DuckDB) | 01 | review | yes |
| test_sql::test_rating_coverage_uses_the_like_rating_it_is_given | like_rating 3.5 moves the like counts | coverage ignores the like rating setting | integration (DuckDB) | 01 | review | yes |
| test_sql::test_like_counts_cut_at_validation_start_and_test_start_for_every_user | likes strictly before each cutoff, all users, at like_rating 3.5; unrated film has no row | like counts ignore the like rating setting; like count at the validation cutoff included; like count at the test cutoff included; validation like count uses the test cutoff | integration (DuckDB) | 01 | review | yes |
| test_sql::test_snapshot_reports_schema_count_and_sample | snapshot for results page | - | integration | 01 | collect | yes |
| test_sql::test_snapshot_rejects_unknown_table | table name allowlist | - | unit | 01 | collect | yes |
| test_sql::test_split_cutoffs_count_back_whole_months_from_the_last_rating_day | test_start and val_start from last rating day | test cutoff uses the wrong window | integration | 01 | split, review | yes |
| test_sql::test_model_ratings_keep_sampled_users_and_users_active_after_validation_start | sampled users + late users, all their ratings, flags | sampled users dropped | integration | 01 | split, review | yes |
| test_sql::test_model_ratings_boundary_rating_exactly_at_validation_start_counts_as_late | boundary is inclusive | validation boundary rating lost | integration | 01 | split, review | yes |
| test_sql::test_snapshot_sample_is_the_lowest_rows_not_insertion_order | sample ordered by all columns | snapshot sample in insertion order | integration (DuckDB) | 01 | mutant | yes |
| test_sql::test_a_file_warehouse_gets_a_memory_cap_a_spill_folder_and_unordered_inserts | memory limit, temp directory and preserve_insertion_order on a file database | memory cap not set; spill folder not set; insertion order preserved (memory) | integration (DuckDB) | 01 | mutant | yes |
| test_sql::test_an_in_memory_warehouse_keeps_duckdb_defaults | an in-memory database keeps preserve_insertion_order on | - | integration (DuckDB) | 01 | mutant | yes |

## Not covered

- `pipeline.main` end to end (network, 440 MB of data): proven by the captured real run in
  `results/sprint-01/run/pipeline.out`, not by a test. That includes which window dictionary
  `main` hands to `choose_shelf_weights` and `score_test` (both functions select their window
  themselves and are tested), the printed progress lines, and the CSV, JSON and meta writes.
- `scripts/build_diagram.py`: generates the architecture page for the stack-diagram skill and
  has no logic of its own to assert; it is rendered and checked by eye (`make diagram`).
- `scripts/recommend.py::main` (argument parsing, DuckDB read, printing); its title lookup `find`
  is tested.
- Chart appearance: the three charts are only checked to write a non-trivial PNG; their look is
  checked by eye on the rendered page.
- Fill quality on real data is measured (`04_fill_quality.csv`), not asserted against a threshold.
- Real-data speed and memory: the DuckDB memory cap and spill settings are asserted, their effect
  on the 32M-row run is shown only by the real run.

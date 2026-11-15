# Test catalog

All tests run offline (fixtures, fake HTTP session, in-memory DuckDB). RED = seen failing before
the code existed; evidence in `results/sprint-01/run/red*.out`. GREEN in `green.out`.
Mutation evidence in `mutation.out` (`make mutate`).

| Test | Behavior | Break it catches | Layer | Sprint | RED | GREEN |
|---|---|---|---|---|---|---|
| test_ingest::test_parse_daily_keeps_rows_and_nulls_as_nan | daily payload -> typed frame | null max dropped or turned into 0 | unit | 01 | red.out | yes |
| test_ingest::test_parse_previous_runs_goes_wide_to_long_by_lead_and_drops_nulls | previous_dayN -> lead N | lead mislabelled (mutation: lead+1 killed) | unit | 01 | red.out | yes |
| test_ingest::test_parse_previous_runs_missing_lead_column_raises | requested lead must exist | lead silently missing | unit | 01 | red.out | yes |
| test_ingest::test_parse_daily_without_daily_block_raises | malformed payload | empty frame instead of error | unit | 01 | red.out | yes |
| test_ingest::test_fetch_json_retries_transient_then_succeeds | 503 retried, timeout passed | no retry / no timeout | unit | 01 | red.out | yes |
| test_ingest::test_fetch_json_does_not_retry_client_error | 4xx fails fast | 4xx retried (mutation killed) | unit | 01 | red.out | yes |
| test_ingest::test_fetch_json_gives_up_after_retries | bounded retries | unbounded loop, swallowed error | unit | 01 | red.out | yes |
| test_ingest::test_fetch_json_error_body_with_200_raises | `{"error": true}` is an error | error body used as data | unit | 01 | red.out | yes |
| test_sql::test_load_is_idempotent_and_replaces_changed_rows | rerun = same rows; corrections replace | duplicate rows on rerun | integration (DuckDB) | 01 | red.out | yes |
| test_sql::test_load_duplicate_key_in_one_batch_fails_loudly | dup keys in a batch raise | silent collapse (found a real DuckDB behavior; guard added) | integration | 01 | red.out | yes |
| test_sql::test_load_rejects_unknown_table | table allowlist | SQL identifier injection | unit | 01 | red.out | yes |
| test_sql::test_published_daily_uses_full_days_only | 24-hour days only; max/min right | partial day kept (mutation killed) | integration | 01 | red.out | yes |
| test_sql::test_forecast_error_sign_is_forecast_minus_actual | error = forecast - actual | sign flip (mutation killed) | integration | 01 | red.out | yes |
| test_sql::test_forecast_error_excludes_days_without_actuals | inner join only | left join with null actuals (mutation killed) | integration | 01 | red.out | yes |
| test_sql::test_error_by_lead_metrics_hand_computed | bias, MAE, shares, worst miss | wrong aggregation | integration | 01 | red.out | yes |
| test_sql::test_snapshot_reports_schema_count_and_sample | snapshot for results page | lost counts or types | integration | 01 | red.out | yes |
| test_models::test_seasonal_features_shape_and_quarter_turn | annual cycle scaling | wrong day-of-year scale (period assert removed: was vacuous, review 13) | unit | 01 | red.out | yes |
| test_models::test_climatology_recovers_season_and_trend | trend extrapolates | missing trend term | unit | 01 | red.out | yes |
| test_models::test_anomaly_decay_learns_geometric_ratio | decay per lead | wrong lag | unit | 01 | red.out | yes |
| test_models::test_split_by_date_is_strict | no leakage at test start | boundary row in train (mutation killed) | unit | 01 | red.out | yes |
| test_models::test_interval_coverage_inclusive_bounds | bounds inclusive | off-by-bound | unit | 01 | red.out | yes |
| test_models::test_corrector_removes_constant_warm_bias | +2 C bias corrected | bias survives | unit | 01 | red.out | yes |
| test_models::test_corrector_keeps_raw_when_forecast_is_unbiased | raw kept unless 2% better | noise-driven overfit (mutation killed) | unit | 01 | red-min-gain.out | yes |
| test_models::test_corrector_intervals_cover_about_80_percent | p10-p90 calibrated | band too narrow/wide | unit | 01 | red.out | yes |
| test_models::test_corrector_rejects_unseen_lead | unknown lead raises | silent prediction | unit | 01 | red.out | yes |
| test_models::test_outlook_blends_short_and_long_range | leads 1-7 corrected, 8-30 clim+anomaly | wrong source per lead | unit | 01 | red.out | yes |
| test_models::test_long_range_backtest_hand_computed | origin and lead alignment | misaligned anomaly | unit | 01 | red-backtest.out | yes |
| test_models::test_corrector_band_reflects_most_recent_year | band follows current error regime | stale-year band (mutation killed) | unit | 01 | red-recent-band.out | yes |
| test_report::test_page_lists_sprints_newest_first | newest sprint first | order flipped (mutation killed) | unit | 01 | red.out | yes |
| test_report::test_page_shows_terminal_output_verbatim_and_escaped | output verbatim, escaped | HTML injection (mutation killed) | unit | 01 | red.out | yes |
| test_report::test_page_shows_table_schema_count_and_sample | snapshots rendered | lost count/types/sample | unit | 01 | red.out | yes |
| test_review_fixes::test_fetch_json_retries_gateway_error_with_html_body | review fix | Fails if a 502 with a non-JSON body escapes as JSONDecodeError instead of a retry | unit/integration | 01-review | red-review.out or mutation.out | yes |
| test_review_fixes::test_fetch_json_retries_429_with_exponential_backoff | review fix | Fails if rate limiting (429) is not retried or the first backoff is not 1 second | unit/integration | 01-review | red-review.out or mutation.out | yes |
| test_review_fixes::test_fetchers_send_location_timezone_and_variables | review fix | Fails if timezone, lead variable names or forecast_days are dropped from requests | unit/integration | 01-review | red-review.out or mutation.out | yes |
| test_review_fixes::test_fetch_all_on_new_years_day_never_requests_an_inverted_range | review fix | Fails if on 1 January the loop asks for 2027-01-01..2026-12-31 (API answers 400) | unit/integration | 01-review | red-review.out or mutation.out | yes |
| test_review_fixes::test_sql_keeps_cities_and_leads_apart | review fix | Fails if a group by or join drops city or lead_days and mixes their errors | unit/integration | 01-review | red-review.out or mutation.out | yes |
| test_review_fixes::test_error_by_lead_rmse_and_quantiles_hand_computed | review fix | Fails if rmse or the p10/p90 error columns are computed wrongly | unit/integration | 01-review | red-review.out or mutation.out | yes |
| test_review_fixes::test_actual_with_null_max_is_dropped_end_to_end | review fix | Fails if a parsed null max reaches the marts (staging null filter removed) | unit/integration | 01-review | red-review.out or mutation.out | yes |
| test_review_fixes::test_every_loader_is_idempotent_and_rejects_duplicate_batches | review fix | Fails if any loader duplicates on rerun or silently collapses duplicate keys | unit/integration | 01-review | red-review.out or mutation.out | yes |
| test_review_fixes::test_live_forecasts_from_different_issue_days_both_survive | review fix | Fails if issued_on drops out of the key and a new forecast overwrites yesterday's | unit/integration | 01-review | red-review.out or mutation.out | yes |
| test_review_fixes::test_snapshot_rejects_unknown_table | review fix | Fails if snapshot formats an unchecked table name into SQL | unit/integration | 01-review | red-review.out or mutation.out | yes |
| test_review_fixes::test_outlook_seam_between_day_7_and_day_8 | review fix | Fails if lead 7 is not corrected, lead 8 uses the wrong decay or quantile, or bands drop | unit/integration | 01-review | red-review.out or mutation.out | yes |
| test_review_fixes::test_outlook_refuses_missing_published_forecast | review fix | Fails if missing published days silently turn the week into climatology | unit/integration | 01-review | red-review.out or mutation.out | yes |
| test_review_fixes::test_recent_anomaly_uses_contiguous_window_and_checks_age | review fix | Fails if the anomaly is stale, skips a gap, or averages the wrong days | unit/integration | 01-review | red-review.out or mutation.out | yes |
| test_review_fixes::test_corrector_with_too_little_history_fails_loudly | review fix | Fails if 60 days of history silently produce an untested model | unit/integration | 01-review | red-review.out or mutation.out | yes |
| test_review_fixes::test_corrector_band_always_contains_prediction | review fix | Fails if one-signed residuals give a band that excludes the prediction (clamp removed) | unit/integration | 01-review | red-review.out or mutation.out | yes |
| test_review_fixes::test_anomaly_decay_with_three_day_window_hand_computed | review fix | Fails if the window is centred or allows partial windows | unit/integration | 01-review | red-review.out or mutation.out | yes |
| test_review_fixes::test_residual_quantiles_on_ten_residuals | review fix | Fails if the requested quantiles are ignored | unit/integration | 01-review | red-review.out or mutation.out | yes |
| test_review_fixes::test_evaluate_long_never_learns_from_the_test_window | review fix | Fails if climatology, decay or bands see test-window data (a +10 C jump there) | unit/integration | 01-review | red-review.out or mutation.out | yes |
| test_review_fixes::test_evaluate_short_never_learns_from_the_test_window | review fix | Fails if the corrector's chosen method or band changes when only test actuals change | unit/integration | 01-review | red-review.out or mutation.out | yes |
| test_review_fixes::test_long_range_bands_are_out_of_sample | review fix | Fails if bands come from residuals of the same rows the climatology was fit on | unit/integration | 01-review | red-review.out or mutation.out | yes |
| test_review_fixes::test_short_range_findings_report_kept_raw_and_worst_lead | review fix | Fails if findings claim a correction where raw was kept, or hide the worst regression | unit/integration | 01-review | red-review.out or mutation.out | yes |
| test_review_fixes::test_report_orders_sprint_10_above_sprint_9 | review fix | Fails if sprints sort as text, putting sprint-9 above sprint-10 | unit/integration | 01-review | red-review.out or mutation.out | yes |
| test_review_fixes::test_report_escapes_findings_and_csv_cells_and_embeds_charts | review fix | Fails if findings or CSV cells inject HTML, or charts are not embedded | unit/integration | 01-review | red-review.out or mutation.out | yes |
| test_review_fixes::test_seasonal_features_hand_values | review fix | Fails if the yearly period or harmonic order is wrong (values computed by hand) | unit/integration | 01-review | red-review.out or mutation.out | yes |
| test_review_fixes::test_share_off_counts_an_error_of_exactly_3c | review fix | Fails if 'off by 3 C or more' excludes an error of exactly 3 C (>= became >) | unit/integration | 01-review | red-review.out or mutation.out | yes |

Not covered, with reason:
- Live HTTP against Open-Meteo: exercised only by `make run` (`pipeline.out`). That run is
  evidence for the results page, not a test; it asserts nothing.
- `pipeline.main`, `charts`, `write_meta`: no test; `date.today()` is not injected yet.
- Train cut by issue date (lead-aware) is not implemented, so not tested; stated as a limit.
- GBM candidate predictions: only exercised through CV selection.
- Schema drift beyond a missing lead column (extra or renamed payload fields, arrays shorter
  than `time`): untested. Property tests (`hypothesis`) on parsers: not written this sprint.
- RED for the original 31 tests is stub `NotImplementedError` (signature-level); behavioral RED
  exists for the review tests and the three later additions (`red-*.out`).

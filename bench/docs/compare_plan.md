# Benchmark Comparison Plan (Full Sweep + Scalability)

## Objective

Compare n8n vs `rag_service` across the full valid operating range using isolated child batches and a parent comparison cohort.

The overall winner should reflect operating quality and reliability across the sweep, not only a few best-case frontier points.

## Inputs

- Boundary audit acts as a validity precondition for interpretable thesis comparisons; it is not itself part of the performance comparison dataset.
- `bench/results/compare_*/pair_plan.json`
- `bench/results/compare_*/analysis/pair_validation.json`
- `bench/results/compare_*/analysis/pair_comparison.json`
- `bench/results/compare_*/analysis/sweep_points_agg.csv`
- `bench/results/compare_*/analysis/knee_report.json`
- child `bench/results/run_*/manifest.json` files referenced by the pair plan

## Validity Before Comparison

Only compare points that are scientifically usable:

- base validity (`point_valid=true`): measure window present, loadgen validity (`dropped_iterations == 0` and `vus_max < cap`), and prompt-mix validity
- pair-valid shared RPMs: offered RPM values where both systems have a valid parent aggregated point for the same `prompt_set` after joining isolated child batches by pair repetition
- timeout non-compliance is **not** an exclusion from the primary comparison; it remains a negative operating outcome and must be counted in `timeout_rate`

Invalid points must be reported from `analysis/invalid_points.csv` and excluded from winner decisions, best-tradeoff summaries, and knee classification.

Internal smoke validity checks are not part of the thesis comparison outcome and must not be reported as benchmark results.

## Primary Comparison: Full-Sweep Operating Quality

Use all pair-valid shared RPMs from the parent `analysis/sweep_points_agg.csv`.

At each shared valid RPM, compare:

- `throughput_success_rps_mean` (higher is better)
- `latency_p95_s_mean` (lower is better)
- `timeout_rate_mean` (lower is better)
- `error_rate_total_mean` (lower is better)

Also report, but do not use as the main winner rule:

- `error_rate_non_timeout_mean`

For the full sweep, report:

- per-RPM side-by-side values for both systems
- win/loss/tie counts across shared valid RPMs for each primary metric
- median per-RPM difference for each primary metric
- validity coverage summary: valid RPM count, shared valid RPM count, and invalid-point count by reason

## Secondary Scalability Summaries

Use these to interpret scaling limits and operating regimes. Do not use them alone to declare the overall winner.

- Best-tradeoff shape: all valid `on_best_tradeoff_p95=true` points, plotted as `throughput_success_rps_mean` vs `latency_p95_s_mean`
- Sustainability: `sustainable_throughput_success_rps`, `last_good_rpm`, `first_bad_rpm`, `first_bad_reasons`

No tier-based operating classes are used in this benchmark. The scientific conclusion is drawn from the full-sweep comparison across shared valid RPMs.

## Winner-Decision Rule

Declare a system `better_overall` only if all of the following hold:

1. It has no worse validity coverage than the other system.
2. It wins both primary reliability metrics across shared valid RPMs:
   - lower `timeout_rate_mean` at more shared valid RPMs
   - lower `error_rate_total_mean` at more shared valid RPMs
3. It also wins at least one primary performance metric across shared valid RPMs:
   - higher `throughput_success_rps_mean`, or
   - lower `latency_p95_s_mean`
4. It is not worse on `sustainable_throughput_success_rps`.

If no system satisfies all conditions, report `trade_off_not_single_winner`.
This is a valid final scientific outcome, not a runner failure by itself.

Use these conclusion labels consistently in JSON outputs:

- `better_overall`: the full rule above is satisfied
- `more_reliable_across_tested_range`: reliability wins, but the full rule does not
- `more_scalable_before_knee`: sustainability wins, but the full rule does not
- `trade_off_not_single_winner`: results split across operating quality and scalability summaries

## Reliability Reporting

Always show reliability beside performance, not as an appendix-only afterthought:

- `timeout_rate`
- `error_rate_total`
- `error_rate_non_timeout`
- failure taxonomy rates (429/5xx/non-200/contract/empty/citation/parse/transport)

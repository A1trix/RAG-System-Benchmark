# Benchmark Metrics and Outputs

## k6 Summaries

- Per run summary: `bench/results/run_*/<run_id>.json`
- Frontier run ids: `arrival-{endpoint}-{prompt_set}-{rpm}rpm-rep{N}-{timestamp}-{cache}`

## Measure-Window Metrics (Primary)

Emitted by `bench/k6/rag.js` and `bench/k6/n8n.js` during scenario `measure` only:

- `latency_measure_ms` (Trend, successful requests)
- `attempts_measure` (Counter)
- `successes_measure` (Counter)
- `timeouts_measure` (Counter)
- `errors_total_measure` (Counter)
- `errors_non_timeout_measure` (Counter)

Failure diagnostics:

- `http_429_measure`, `http_5xx_measure`, `http_non_200_measure`
- `contract_fail_measure`, `empty_answer_measure`, `citation_missing_measure`, `json_parse_fail_measure`
- `transport_error_non_timeout_measure`

Derived in sweep analysis:

- `throughput_success_rps = successes / measure_seconds`
- `throughput_attempt_rps = attempts / measure_seconds`
- `timeout_rate = timeouts / attempts`
- `error_rate_total = errors_total / attempts`
- `error_rate_non_timeout = errors_non_timeout / attempts`

In this benchmark, each tested RPM produces one measured result for a system. When those results are plotted as throughput vs latency, the frontier is the set of best results we actually saw: results where no other valid result gives both more throughput and lower latency at the same time.

Example:

- If Point A is `2.0 rps` at `8s p95` and Point B is `2.0 rps` at `12s p95`, Point B is dominated by Point A.
- If Point C is `3.0 rps` at `14s p95`, both Point A and Point C can be on the frontier because each is a different best trade-off.

## Prompt-Mix Metrics

Primary prompt-mix validity signal:

- `attempts_measure_prompt{prompt_id:*}`

Default fallback when prompt-tagged attempts are missing:

- deterministic reconstruction from `prompt_order_<run_id>.json` + `attempts_measure_count` (arrival-global scheduler)
- disable fallback with `BENCH_SWEEP_REQUIRE_PROMPT_TAGS=1`

Additional prompt-tagged diagnostics (not required for prompt-mix validity):

- `successes_measure_prompt{prompt_id:*}`
- `timeouts_measure_prompt{prompt_id:*}`
- `errors_non_timeout_measure_prompt{prompt_id:*}`

## Run Windows Metadata

`bench/results/run_*/runs.jsonl` includes (per run):

- identity: `run_id`, `run_tag`, `endpoint`, `prompt_set`, `summary_file`
- timing: `start`, `end`, `duration`, `settle_seconds`, `measure_seconds`
- loadgen cap: `vus` (configured `K6_ARR_MAX_VUS`)
- `vus_cap` in reports means the configured k6 maximum number of virtual users for that run (`K6_ARR_MAX_VUS`, also called `maxVUs`). The validity check `vus_max < vus_cap` confirms k6 did not hit its VU ceiling while trying to sustain the requested arrival rate.
- derived fields from `k6_summary_report.py` (checks/http/latency/requests)

## Sweep Analysis Outputs

Written under `bench/results/run_*/analysis/`:

- `sweep_points.csv`
- `sweep_points_agg.csv` (main table for full-sweep comparison over valid points)
- `knee_report.json`, `knee_report.md`
- `invalid_points.csv`
- `prompt_mix_report.md`
- plots: `throughput_vs_p95`, `timeout_rate_vs_throughput`, `error_rate_vs_throughput`, plus diagnostic plots

Fresh benchmark-owned analysis artifacts use the current p95-only latency schema.

Notable provenance fields in `sweep_points.csv`:

- `prompt_mix_source` (`tagged`, `scheduler_fallback`, `unverifiable`)
- `timeouts_measure_source`, `errors_total_measure_source`, `errors_non_timeout_measure_source` (`metric`, `implicit_zero`, `missing`)

Current schema notes:

- `sweep_points.csv` includes latency fields for `latency_p50_s` and `latency_p95_s`.
- `sweep_points_agg.csv` includes `on_best_tradeoff_p95` together with the current throughput, error, timeout, and latency aggregates.
- `knee_report.json` and `knee_report.md` report timeout, p95, and total-error knee information only.

## Analysis Scripts (bench/helpers/analysis/)

- `analyze_sweep.py`
  - Public CLI entrypoint for sweep analysis.
  - Delegates to the internal package `bench/helpers/analysis/sweep_analysis/`.
  - Stable command surface for isolated child-batch analysis, smoke validity, and parent synthetic sweep analysis.
  - Primary analysis for sweep runs: reads k6 arrival summaries (`arrival-*.json`) + `runs.jsonl` and computes rep-level + point-level tables.
  - Enforces scientific validity gates (loadgen, prompt-mix, measure activity), computes Pareto frontier membership and knee detection.
  - Emits `sweep_points*.csv`, `invalid_points.csv`, `prompt_mix_report.md`, `knee_report.*`, and plots.
  - Used for the smoke validity gate (`--enforce-validity`) and final sweep analysis.
  - The generic sweep-analysis pipeline follows the current p95-only latency contract for fresh benchmark-owned artifacts.

- `sweep_analysis/`
  - Internal implementation package behind `analyze_sweep.py`.
  - Module layout:
    - `config.py`: CLI/parser construction and defaults
    - `discovery.py`: summary discovery, run indexing, and tag filters
    - `rep_analysis.py`: per-summary extraction into rep-level rows
    - `prompt_mix.py`: prompt-order fallback and prompt-mix validation
    - `aggregation.py`: point aggregation, invalid rows, and best-tradeoff tagging
    - `knee.py`: knee detection and sustainability summaries
    - `reports.py`: CSV/JSON/Markdown outputs and console reporting
    - `plots.py`: plot generation and plotting data preparation
    - `pipeline.py`: end-to-end analysis orchestration
    - `metrics.py`, `stats.py`, `io_utils.py`, `types.py`: shared helpers and core types

- `sweep_decision.py`
  - Lightweight prereg evaluator for the parent isolated comparison cohort.
  - Consumes parent comparison artifacts (`analysis/sweep_points_agg.csv`, `analysis/knee_report.json`, `analysis/pair_validation.json`) and produces a compact decision summary.

- `prereg_decision.py`
  - Stable prereg decision entrypoint used by the runner.
  - Loads `bench/preregistration.json`, checks compatibility with the supported prereg decision contract, and dispatches to `sweep_decision.py`.
  - Emits a compact thesis-batch decision JSON including prereg id/schema version, prompt set, shared valid RPMs, conclusion label, and winner summary.

- `validate_thesis_batch.py`
  - Child-batch artifact validator for hard-gate checks after isolated endpoint runs.
  - Requires `sweep_primary` runs to be present in `runs.jsonl`.

- `validate_thesis_pair.py`
  - Parent-cohort validator for isolated rag/n8n pair comparisons.
  - Requires paired child batches, matching prereg/audit inputs, and alternating order by repetition.

- `compare_isolated_batches.py`
  - Builds parent comparison artifacts from isolated child-batch analyses.
  - Emits parent `analysis/sweep_points*.csv`, `analysis/knee_report.*`, and `analysis/pair_comparison.*` artifacts.

- `analyze_timeouts.py` (optional diagnostics)
  - Correlates `rag-pipeline.log` request durations with per-request timing breakdown from `timings-rag.jsonl`.
  - Emits `analysis/slow_requests.csv` (top-N slowest requests) to identify likely bottlenecks (queue/retrieval/LLM/post/overhead).
  - Only relevant for optional profiling and timing-capture runs; not part of the thesis benchmark result set.

- `dropped_iterations_report.py` (optional diagnostics)
  - Diagnoses why k6 dropped arrivals (`dropped_iterations`) for a run folder and suggests next actions (e.g., VU cap hit vs latency pressure).
  - Emits `analysis/dropped_iterations_report.csv` and `analysis/dropped_iterations_report.md`.

## Other Batch Artifacts

- `manifest.json`, `docker_images.json`
- `source_fingerprint.json`
- `db_fingerprint_pre.json`, `db_fingerprint_post.json`
- `boundary_audit_report.json` (required/validated when `BENCH_REQUIRE_BOUNDARY_AUDIT=1`; validates model/workflow boundary, not performance)
- `thesis_batch_validation.json` (emitted when thesis-batch validation step is enabled)

Parent isolated comparison artifacts:

- `pair_plan.json`
- `analysis/pair_validation.json`
- `analysis/pair_comparison.json`, `analysis/pair_comparison.csv`, `analysis/pair_comparison.md`
- parent `analysis/sweep_points.csv`, `analysis/sweep_points_agg.csv`, `analysis/knee_report.json`, `analysis/knee_report.md`

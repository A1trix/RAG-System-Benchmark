# Benchmark Preregistration (Boundary Audit + Isolated Paired Primary Sweep)

This preregistration defines the primary evaluation regime, metrics, and decision rules for the thesis benchmark comparing n8n vs the Python RAG service.

## Systems

- n8n webhook-based agentic RAG workflow
- Python FastAPI-based agentic RAG service (`rag_service`)

## Primary Result (Headline)

The headline result is the full-sweep operating-quality comparison over pair-valid shared load points.

- Pair-valid shared point: same `offered_rpm`, same `prompt_set`, and all planned pair repetitions valid for both systems across isolated child batches
- Primary comparison metrics:
  - `throughput_success_rps` (higher is better)
  - `latency_p95_s` (lower is better)
  - `timeout_rate` (lower is better)
  - `error_rate_total` (lower is better)
- Supporting metrics:
  - `error_rate_non_timeout`

We report per-RPM side-by-side values, win/loss/tie counts across shared valid points, and median per-RPM differences for the primary metrics.

A system is declared better overall only if it has no worse validity coverage, wins both reliability metrics (`timeout_rate` and `error_rate_total`) across shared valid points, wins at least one primary performance metric (`throughput_success_rps` or `latency_p95_s`), and is not worse on sustainable throughput. Otherwise the result is reported as a trade-off rather than a single overall winner.

## Secondary Scalability Summaries

We also report the empirical throughput-latency frontier and knee / sustainable throughput as secondary scalability summaries:

- X axis: achieved throughput in the measure window, `throughput_success_rps = successes / measure_seconds`
- Y axis (primary): end-to-end latency p95 in the measure window

We report the empirical frontier (best observed trade-off points) and compare systems by the shape and stability of this frontier. The frontier is used to describe scalability trade-offs under load; it is not the sole winner-decision rule.

## Benchmark Structure (Constant-Arrival-Rate)

The thesis benchmark cohort consists of a boundary audit followed by isolated child batches and a parent comparison step.

Boundary audit:

- Executed before performance runs with a separate non-evaluation prompt set
- Purpose: verify model boundary, workflow boundary, and locked sampling parameters (temperature, top_p, max_completion_tokens) relevant to the final performance comparison
- Not part of latency/throughput analysis

In the machine-readable preregistration (`bench/preregistration.json`), the boundary audit is encoded as a required precondition for interpretable thesis runs. Internal smoke checks are not part of the preregistered thesis decision basis.

Primary sweep (child-batch target regime):

- Offered load points: 10..100 RPM in steps of 10 RPM
- Settle: 180s
- Measure: 720s
- Child-batch repetitions: 1
- Paired thesis repetitions: 3 (executed via `bench/run_compare_pair.sh`)

Each child load point of the primary sweep is a single k6 run with two internal windows:

- Settle window: reach steady state (excluded from primary analysis)
- Measure window: included in all reported metrics

Prompt scheduling (sweep track):

- The harness sets `K6_PROMPT_SCHEDULER=arrival_global` for all sweep runs.
- Rationale: in `constant-arrival-rate` mode k6 dynamically allocates VUs; prompt selection must not depend on `__VU` or prompt mix can differ between systems.

Execution note:

- `run_all.sh` is a single-endpoint child-batch runner and requires `BENCH_TARGET_ENDPOINT=rag|n8n`.
- `run_compare_pair.sh` is the thesis-grade compare runner and alternates child-batch order by repetition.
- This preregistration defines target defaults for thesis-grade runs; verify realized values in parent and child manifests before drawing final conclusions.
- The preregistered final prompt file is `scope.prompts_path = /bench/prompts.json` and must match the realized manifests.
- Internal smoke validity checks may exist as runner safeguards, but they are not part of the thesis benchmark decision basis.

## Measure-Only Metric Definitions

All metrics below are computed strictly within the measure window and are produced by the k6 scripts via custom measure-only metrics:

- `attempts`: total request attempts (`attempts_measure.count`)
- `successes`: successful requests (`successes_measure.count`)
- `throughput_success_rps = successes / measure_seconds`
- `throughput_attempt_rps = attempts / measure_seconds`
- `timeout_rate = timeouts / attempts` where `timeouts = timeouts_measure.count`
- `error_rate_total = errors_total / attempts` where `errors_total = errors_total_measure.count`
- `error_rate_non_timeout = errors_non_timeout / attempts` where `errors_non_timeout = errors_non_timeout_measure.count`
- Latency on successful requests only, from `latency_measure_ms` Trend:
  - p50/p95 (converted ms -> seconds)

Reporting note: `timeout_rate` and `error_rate_total` are always reported separately and are not folded into a single "success" metric.

## Validity Gates

Timeout compliance (hard, per-rep and per-point):

- Per repetition pass rule: `timeout_rate <= 1.0%` (0.01)
- Per point pass rule: all 3 reps at that offered RPM must pass; otherwise the point is non-compliant
- Non-compliant points remain in the primary full-sweep comparison as poor reliability outcomes; they can trigger the knee.

Load-generator validity gate (open-loop correctness):

- A repetition is loadgen-valid only if:
  - measure-window `dropped_iterations.count == 0`, and
  - measure-window `vus_max < maxVUs` (k6 did not hit its configured VU cap)
- A point is loadgen-valid only if all repetitions are loadgen-valid.
- Loadgen-invalid points are reported transparently but excluded from the primary winner decision, best-tradeoff summaries, and knee classification.

Prompt-mix validity gate (workload equality):

- Primary prompt-mix evidence is prompt-tagged attempt counters (`attempts_measure_prompt{prompt_id:...}`) in the measure window.
- Default fallback (when tagged subseries are absent): reconstruct prompt attempt counts from deterministic `arrival_global` scheduling using `prompt_order_<run_id>.json` and `attempts_measure_count`.
- Strict mode: set `BENCH_SWEEP_REQUIRE_PROMPT_TAGS=1` to require direct tagged prompt counters (no fallback).
- A repetition passes prompt-mix validity only if attempt counts across prompts are balanced (max-min <= 1 across prompts in the measure window).
- A point passes prompt-mix validity only if all repetitions pass.
- Prompt-mix-invalid points are reported transparently but excluded from the primary winner decision, best-tradeoff summaries, and knee classification.

Optional non-timeout error gate (disabled by default):

- `analyze_sweep.py` supports an additional non-timeout error compliance threshold (`--error-non-timeout-max`).
- `analyze_sweep.py` is the stable entrypoint; implementation details now live in `bench/helpers/analysis/sweep_analysis/` without changing the analysis contract.
- This gate is not part of the default preregistered decision path unless explicitly enabled for a run.

## Knee Rules (Secondary Scalability)

For scalability interpretation, we define sustainability as the maximum throughput before the latency knee.

Stage 1 points are ordered by increasing offered RPM.

The knee is the first Stage 1 point classified as "bad" by any of:

- Timeout non-compliance (per-point rule above)
- Error-rate knee: sharp slope change in `error_rate_total` over increasing offered RPM (piecewise regression)
- Latency knee: sharp slope change in p95 over increasing offered RPM (piecewise regression)

The sustainable throughput is the achieved throughput at the last good Stage 1 point immediately before the first bad point.

## Machine-Readable Preregistration

Machine-readable preregistration lives at `bench/preregistration.json`.

It encodes the thesis-relevant decision contract for the primary sweep comparison, the supporting scalability summaries, the reporting gates, and the required boundary-audit precondition. Internal smoke validation is not part of this preregistered thesis decision basis.

The benchmark manifest should record the preregistration id, schema version, and artifact hash so later analysis can prove which prereg contract was in effect for a given batch.

A thesis-valid child batch must contain `sweep_primary` runs for exactly one target endpoint. Internal smoke checks do not satisfy this condition. Final thesis comparison requires a parent isolated-pair cohort rather than one mixed run directory.

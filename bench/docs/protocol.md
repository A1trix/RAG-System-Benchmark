# Benchmark Protocol (Boundary Audit + Isolated Paired Primary Sweep)

## Scope

This benchmark compares two end-to-end RAG systems:

- n8n webhook-based workflow
- Python FastAPI `rag_service` (`/query`)

The harness uses open-loop `constant-arrival-rate` runs across a sweep.

Comparative conclusions come from the shared valid points in the sweep. Frontier and knee artifacts are supporting scalability summaries, not the sole basis for deciding which system performs better overall.

## Load Design

Each offered-load point is a single k6 run with two scenarios:

- `settle` (excluded from analysis)
- `measure` (included in analysis)

Configured by:

- `K6_ARR_RATE` (offered RPM)
- `K6_ARR_TIME_UNIT` (default `1m`)
- `K6_SETTLE_SECONDS`, `K6_MEASURE_SECONDS`
- `K6_ARR_PREALLOCATED_VUS`, `K6_ARR_MAX_VUS`

Prompt scheduling is fixed to `K6_PROMPT_SCHEDULER=arrival_global` to avoid VU-allocation-induced prompt-mix drift.

Prompt-mix validation defaults to tagged prompt counters and falls back to deterministic reconstruction from `prompt_order_<run_id>.json` when tagged subseries are missing.

## Benchmark Structure

The thesis-relevant benchmark cohort consists of:
1. a boundary audit as methodological pre-check
2. isolated `rag` child batches
3. isolated `n8n` child batches
4. a parent-level pair comparison over the child analyses

### Execution (Step-by-Step)

This section describes the concrete thesis-relevant runner flow.

1. Run boundary audit
   - Load `bench/profiles/thesis_compare.env` first so the audit runs in validity mode.
   - Execute `bench/run_boundary_audit.sh` with a non-evaluation prompt set.
   - Verify model boundary, workflow boundary, and locked sampling parameters (temperature, top_p, max_completion_tokens).
   - Export `BENCH_BOUNDARY_AUDIT_REPORT_PATH` to the produced `boundary_audit_report.json` before the compare run.
2. Execute the isolated pair runner
   - Run `bench/run_compare_pair.sh`.
   - For each paired repetition, it alternates child-batch order by repetition.
3. Child-batch execution
   - `bench/run_all.sh` runs exactly one target endpoint (`BENCH_TARGET_ENDPOINT=rag|n8n`).
   - Each child batch recreates the benchmark stack, validates the boundary-audit attachment, and runs smoke/primary sweep analysis for that one endpoint only.
4. Parent-level pair validation
   - `validate_thesis_pair.py` checks that the isolated child batches are comparable: same prereg, same prompt path, same RPM lattice, same audit artifact, same DB fingerprint baseline, and alternating order by repetition.
5. Parent-level comparison
   - `compare_isolated_batches.py` combines the child sweep analyses into parent `analysis/sweep_points*.csv`, `analysis/knee_report.*`, and `analysis/pair_comparison.*` artifacts.
6. Parent prereg decision
   - `prereg_decision.py` evaluates the parent comparison cohort and emits `analysis/prereg_decision.json`.

Implementation note:

- The child runner may execute internal smoke validity checks before the primary sweep. These are technical safeguards and are not part of thesis result interpretation.
- Simultaneous mixed benchmarking of `rag` and `n8n` inside one run directory is no longer supported.

## Validity Rules

Applied on **measure-window** metrics:

- Timeout rate definition: `timeout_rate = timeouts_measure / attempts_measure`
- Timeout compliance: per-rep `timeout_rate <= 1.0%`; per-point requires all reps passing
- Loadgen validity:
  - `dropped_iterations{scenario:measure}.count == 0`
  - `vus_max < K6_ARR_MAX_VUS`
- Prompt-mix validity:
  - primary evidence from `attempts_measure_prompt{prompt_id:*}`
  - fallback reconstruction from `prompt_order_<run_id>.json` + `attempts_measure_count` when prompt tags are absent (unless `BENCH_SWEEP_REQUIRE_PROMPT_TAGS=1`)
  - balanced distribution (`max - min <= 1` per rep)
- Optional analysis-only gate (disabled by default): non-timeout error compliance via `analyze_sweep.py --error-non-timeout-max`.
- The low-level sweep-analysis pipeline uses timeout, p95, total error rate, and prompt/loadgen validity only.

Invalid points are reported and excluded from winner decisions plus frontier/knee summaries.

Runs where k6 records zero measure-window requests/iterations are kept in child `runs.jsonl` and reported as invalid points (they do not terminate the child batch unless strict mode is enabled).

## Hard Gates

- Dataset freeze: DB fingerprint must match pre/post batch.
- Boundary audit: required when `BENCH_REQUIRE_BOUNDARY_AUDIT=1`.

### Boundary Audit (What/Why)

The boundary audit exists to protect experimental validity: it verifies that both systems are operating under the same LLM and workflow boundary before you run the thesis performance benchmark and compare performance.

What it checks (high-level):

- Model boundary: both systems call the expected chat/embedding models and expose the locked sampling/token-limit evidence required by the thesis validator.
- Workflow boundary: the benchmark is targeting the intended n8n workflow and its OpenAI credentials/config are consistent.
- Parameter verification: both systems use the same locked sampling parameters (temperature, top_p, max_completion_tokens).

How it works:

- `bench/run_boundary_audit.sh` runs a small, sequential prompt set (not a load test).
- For n8n, the workflow is temporarily switched to the dedicated audit credential so OpenAI traffic is routed through the audit proxy and the harness can inspect the *observed* model/parameter usage.
- After the audit completes, the workflow is restored to the primary benchmark credential before the actual compare run.
- It writes a `boundary_audit_report.json` and the benchmark batch attaches/validates that report when `BENCH_REQUIRE_BOUNDARY_AUDIT=1`.

Snapshot note:

- `n8n_workflow_runtime_snapshot_audit.json` records the audit-phase workflow state while the audit credential is active.
- `n8n_workflow_runtime_snapshot.json` records the restored benchmark-phase workflow state used for later attachment validation.
- Different workflow hashes between those two files are expected when the credential state changes between audit and benchmark phases.

What it is not:

- It is not a performance benchmark and should not be mixed into latency/throughput results.

## Outputs

Child artifacts (`bench/results/run_*/`):

- `runs.jsonl`
- `manifest.json`
- `source_fingerprint.json`
- `db_fingerprint_pre.json`, `db_fingerprint_post.json`
- `boundary_audit_report.json` (required/validated when `BENCH_REQUIRE_BOUNDARY_AUDIT=1`)
- `analysis/sweep_points.csv`
- `analysis/sweep_points_agg.csv`
- `analysis/knee_report.json`, `analysis/knee_report.md`
- `analysis/invalid_points.csv`
- `analysis/prompt_mix_report.md`

Parent comparison artifacts (`bench/results/compare_*/`):

- `pair_plan.json`
- `manifest.json`
- `analysis/pair_validation.json`
- `analysis/pair_comparison.json`, `analysis/pair_comparison.csv`, `analysis/pair_comparison.md`
- `analysis/sweep_points.csv`
- `analysis/sweep_points_agg.csv` (main comparison table for valid shared points)
- `analysis/knee_report.json`, `analysis/knee_report.md`
- `analysis/invalid_points.csv`
- `analysis/prompt_mix_report.md`
- `analysis/prereg_decision.json`, `analysis/prereg_decision.txt`

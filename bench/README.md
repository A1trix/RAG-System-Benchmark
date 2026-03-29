# Benchmark Stack

## Overview

This harness benchmarks two end-to-end RAG systems in isolated child batches:

- n8n workflow endpoint
- FastAPI `rag_service` endpoint

For thesis-relevant runs, the workflow is:

1. run the boundary audit
2. run isolated child batches for `rag` and `n8n`
3. compare the two child batches at the parent level

`run_all.sh` is a single-endpoint child-batch runner only. The supported thesis-grade comparison entrypoint is `run_compare_pair.sh`. Running both systems simultaneously inside one benchmark batch is no longer supported.

Here, the frontier means the best results we actually saw in the benchmark. These are the results where you cannot get more throughput without also accepting more latency.

## Docs

- Protocol: `bench/docs/protocol.md`
- Metrics and outputs: `bench/docs/metrics.md`
- Comparison plan: `bench/docs/compare_plan.md`
- Preregistration: `bench/docs/preregistration.md`
- Final thesis checklist: `bench/docs/final_thesis_run_checklist.md`

The canonical final thesis profile is `bench/profiles/thesis_compare.env`.
It defines a primary sweep of `20..120 RPM` in `20 RPM` steps with `180s` settle,
`720s` measure, and `3` paired parent repetitions.

## Run Order (Thesis-Grade)

1. Configure required env in `bench/.env` (especially `N8N_WORKFLOW_ID`, `N8N_OPENAI_CREDENTIAL_ID`, `N8N_AUDIT_OPENAI_CREDENTIAL_ID`).
2. Load the final thesis profile:

```bash
set -a; source bench/profiles/thesis_compare.env; set +a
```

3. Run boundary audit:

```bash
./bench/run_boundary_audit.sh
```

4. On success, export the produced audit report path for the compare run:

```bash
export BENCH_BOUNDARY_AUDIT_REPORT_PATH=/absolute/path/to/boundary_audit_report.json
```

Boundary audit purpose: it verifies the model/workflow boundary and workload parity signals that make the final performance comparison scientifically interpretable.
During the boundary audit, the n8n workflow is temporarily switched to the dedicated audit credential so OpenAI traffic flows through the audit proxy and can be observed. After the audit, the workflow is restored to the normal benchmark credential before the compare run.
5. Run the isolated pair comparison batch:

```bash
./bench/run_compare_pair.sh
```

## Single-Endpoint Child Runs

`run_all.sh` requires `BENCH_TARGET_ENDPOINT=rag|n8n`.

```bash
BENCH_TARGET_ENDPOINT=rag ./bench/run_all.sh
BENCH_TARGET_ENDPOINT=n8n ./bench/run_all.sh
```

Smoke-only technical checks:

```bash
set -a; source bench/profiles/thesis_compare.env; set +a
BENCH_REQUIRE_BOUNDARY_AUDIT=0 BENCH_SWEEP_SMOKE_RPM_LIST=20 BENCH_TARGET_ENDPOINT=rag BENCH_SWEEP_STOP_AFTER_SMOKE=1 ./bench/run_all.sh
BENCH_REQUIRE_BOUNDARY_AUDIT=0 BENCH_SWEEP_SMOKE_RPM_LIST=20 BENCH_TARGET_ENDPOINT=n8n BENCH_SWEEP_STOP_AFTER_SMOKE=1 ./bench/run_all.sh
```

## What `run_all.sh` Does

- Starts a clean benchmark stack for one selected endpoint (`rag` or `n8n`)
- Verifies corpus/vector prerequisites
- Attaches and validates the boundary-audit artifact when `BENCH_REQUIRE_BOUNDARY_AUDIT=1`
- Executes the selected endpoint's smoke/primary sweep child batch
- May perform internal smoke validity checks before the primary sweep; these are runner safeguards and not part of thesis result interpretation
- Runs child-batch sweep analysis (`analyze_sweep.py`)
- Writes child manifest + fingerprints + validation artifacts

## What `run_compare_pair.sh` Does

- Creates a parent comparison cohort under `bench/results/compare_<timestamp>/`
- Alternates child-batch order by paired repetition (`rag -> n8n`, then `n8n -> rag`, ...)
- Runs `run_all.sh` once per child batch with `BENCH_TARGET_ENDPOINT=rag|n8n`
- Builds pair validation and pair comparison artifacts from the isolated child batches
- Runs parent prereg decision over the isolated pair comparison artifacts

## Sweep Analysis Code Layout

- CLI entrypoint `bench/helpers/analysis/analyze_sweep.py`
- Implementation for the analysis in `bench/helpers/analysis/sweep_analysis/`
- Package split by responsibility:
  - `config.py` CLI/parser defaults
  - `discovery.py`, `rep_analysis.py` input discovery and rep-level extraction
  - `prompt_mix.py` prompt-mix reconstruction and validation
  - `aggregation.py`, `knee.py`, `stats.py` aggregation, frontier, and knee logic
  - `reports.py`, `plots.py`, `io_utils.py` artifact writing and plotting
  - `pipeline.py` end-to-end orchestration used by the entrypoint

Fresh benchmark-owned analysis artifacts use the current p95-only latency schema.

## Key Config (in `bench/.env`)

- Child runner target: `BENCH_TARGET_ENDPOINT=rag|n8n`
- Primary sweep: `BENCH_SWEEP_PRIMARY_*`
- Internal smoke gate: `BENCH_SWEEP_SMOKE_*`, `BENCH_SWEEP_STOP_AFTER_SMOKE` (technical validation only; not thesis benchmark basis)
- Sweep thresholds: `BENCH_SWEEP_TIMEOUT_RATE_MAX`
- Prompt-mix strictness: `BENCH_SWEEP_REQUIRE_PROMPT_TAGS=0|1` (`0` uses scheduler fallback from `prompt_order_*.json` when tags are missing)
- Arrival executor capacity: `BENCH_ARRIVAL_PREALLOCATED_VUS`, `BENCH_ARRIVAL_MAX_VUS`, `BENCH_ARRIVAL_TIME_UNIT`
- Prompt set: `BENCH_PROMPTS_PATH` (must match the preregistered final prompt file for thesis runs)
- Reproducibility: `PROMPT_BASE_SEED`, `BENCH_CACHE_REGIME`
- Audit gating: `BENCH_REQUIRE_BOUNDARY_AUDIT`, `BENCH_BOUNDARY_AUDIT_REPORT_PATH`
- Pair runner: `BENCH_PAIR_REPS`, `BENCH_PAIR_ORDER_MODE`, `BENCH_PAIR_VALIDATE_STRICT`

## Outputs

Child batch in `bench/results/run_<timestamp>/`:

- Run core: `runs.jsonl`, `manifest.json`, `docker_images.json`
- Fingerprints: `source_fingerprint.json`, `db_fingerprint_pre.json`, `db_fingerprint_post.json`
- Runtime snapshots: `n8n_workflow_runtime_snapshot.json`, `n8n_constraints_validation.json`, `boundary_audit_report.json` (required/validated when `BENCH_REQUIRE_BOUNDARY_AUDIT=1`)
- Boundary-audit traceability: `n8n_workflow_runtime_snapshot_audit.json` captures the temporary audit-phase workflow state, while `n8n_workflow_runtime_snapshot.json` captures the restored benchmark-phase state used for later attachment validation
- Sweep analysis:
  - `analysis/sweep_points.csv`
  - `analysis/sweep_points_agg.csv`
  - `analysis/knee_report.json`, `analysis/knee_report.md`
  - `analysis/invalid_points.csv`
  - `analysis/prompt_mix_report.md`
  - frontier plots under `analysis/`
- Decisions/validation (conditional by run mode):
  - `thesis_batch_validation.json` (when thesis-batch validation step is enabled)

Parent comparison cohort in `bench/results/compare_<timestamp>/`:

- `pair_plan.json`
- `manifest.json`
- `analysis/pair_validation.json`
- `analysis/pair_comparison.json`
- `analysis/pair_comparison.csv`
- `analysis/pair_comparison.md`
- `analysis/sweep_points.csv`
- `analysis/sweep_points_agg.csv`
- `analysis/knee_report.json`, `analysis/knee_report.md`
- `analysis/invalid_points.csv`
- `analysis/prompt_mix_report.md`
- `analysis/prereg_decision.json`, `analysis/prereg_decision.txt` (when `BENCH_PREREG_EVAL=1`)

## Token Usage Measurement

This benchmark includes token usage tracking for correlation analysis with latency and efficiency comparison between RAG and n8n systems.

### Token Metrics

Three token usage metrics are captured per **successful request only** (during the measure window):

- **tokens_prompt**: Input/prompt tokens consumed
- **tokens_completion**: Output/completion tokens generated  
- **tokens_total**: Total tokens (prompt + completion)

These metrics enable:
- Correlation analysis between token usage and latency (p95)
- Efficiency comparison between RAG service and n8n workflow
- Per-request token consumption tracking for cost analysis

### Implementation

**RAG Service**: Token usage is extracted from the response JSON body fields (`prompt_tokens`, `completion_tokens`, `total_tokens`) and added to k6 Trend metrics on successful responses.

**n8n Workflow**: The OpenAI proxy intercepts all API calls and adds `X-Token-Prompt`, `X-Token-Completion`, and `X-Token-Total` headers to responses. k6 extracts these headers on successful requests.

**Configuration**: Token logging is enabled via `LOG_OPENAI_USAGE=true` (set in `bench/.env` and `bench/profiles/thesis_compare.env` for thesis runs).

### Output Location

Token usage metrics appear in:
- k6 JSON summary output (e.g., `tokens_total.avg`, `tokens_total.p(95)`)
- Analysis plots (token-latency correlation scatter plots)
- Aggregated CSV results (when using analysis pipeline)


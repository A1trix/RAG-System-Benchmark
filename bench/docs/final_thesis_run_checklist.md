# Final Thesis Run Checklist

## Contract Lock

- Use `bench/profiles/thesis_compare.env` as the canonical final thesis profile.
- Confirm the preregistered final regime is `10..100 RPM` in `10 RPM` steps, `180s` settle, `720s` measure, `3` paired repetitions, and warm cache.
- Confirm the preregistered final prompt file is `BENCH_PROMPTS_PATH=/bench/prompts.json`.
- Confirm thesis interpretation uses the current p95-only latency schema.
- Confirm fresh benchmark-generated artifacts and manifests follow the current schema.

## Preflight

- Verify required environment values in `bench/.env`, especially `N8N_WORKFLOW_ID`, `N8N_OPENAI_CREDENTIAL_ID`, and `N8N_AUDIT_OPENAI_CREDENTIAL_ID`.
- Load the final profile: `set -a; source bench/profiles/thesis_compare.env; set +a`.
- Run endpoint smoke validation for both endpoints with `BENCH_REQUIRE_BOUNDARY_AUDIT=0 BENCH_SWEEP_SMOKE_RPM_LIST=20 BENCH_TARGET_ENDPOINT=rag BENCH_SWEEP_STOP_AFTER_SMOKE=1 ./bench/run_all.sh` and `BENCH_REQUIRE_BOUNDARY_AUDIT=0 BENCH_SWEEP_SMOKE_RPM_LIST=20 BENCH_TARGET_ENDPOINT=n8n BENCH_SWEEP_STOP_AFTER_SMOKE=1 ./bench/run_all.sh`.
- Fix any smoke validity failures before continuing.
- Treat these smoke runs as technical preflight checks only; they are never part of thesis evidence.

## Boundary Audit

- Run `./bench/run_boundary_audit.sh` immediately before the final comparison cohort.
- Confirm the boundary audit uses the configured `BOUNDARY_AUDIT_PROMPT_COUNT=20` sample.
- Confirm the produced `boundary_audit_report.json` passes (validity mode - verifies models and parameters).
- Confirm the audit temporarily used the dedicated audit credential/proxy path and that the workflow was restored to the primary benchmark credential afterward.
- Export `BENCH_BOUNDARY_AUDIT_REPORT_PATH` to that fresh report before the comparison run.

## Final Comparison Run

- Run the thesis comparison entrypoint: `./bench/run_compare_pair.sh`.
- Do not treat internal smoke safeguards as thesis results.

## Required Pass Artifacts

- Parent `analysis/pair_validation.json` must have `pass=true`.
- Each child `thesis_batch_validation.json` must have `pass=true`.
- Parent and child manifests must match the preregistered RPM lattice, settle/measure windows, pair repetitions, prompt file, and boundary-audit requirement.
- Parent `analysis/prereg_decision.json` must show shared valid comparison points.
- Treat `n8n_workflow_runtime_snapshot_audit.json` as the audit-phase state and `n8n_workflow_runtime_snapshot.json` as the restored benchmark-phase state used for attachment validation.

## Interpretation Guardrails

- Base the thesis conclusion on throughput, p95 latency, timeout rate, and total error rate across shared valid RPMs.
- Treat `error_rate_non_timeout` and failure taxonomy as supporting diagnostics.
- A final outcome of `trade_off_not_single_winner` is scientifically valid and does not by itself invalidate the run.
- Do not use technical pilot runs or smoke runs in the thesis result set.

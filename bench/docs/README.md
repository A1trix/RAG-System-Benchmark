# Benchmark Docs

This folder contains the benchmark protocol and analysis documentation for the isolated child-batch + parent comparison workflow.
Current benchmark-owned analysis internals follow the current p95-only latency schema.

## Read Order

1. `bench/docs/protocol.md` (what is executed, child vs parent artifacts, validity)
2. `bench/docs/metrics.md` (outputs, paths, units, schemas)
3. `bench/docs/compare_plan.md` (how to compare isolated child batches and interpret metrics)
4. `bench/docs/preregistration.md` (thesis decision rules)
5. `bench/docs/final_thesis_run_checklist.md` (pre-flight and acceptance checklist for the real thesis run)

Machine-readable prereg:

- `bench/preregistration.json` (thesis decision contract + boundary-audit precondition)

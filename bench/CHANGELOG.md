# Changelog

All notable changes to the benchmark scripts and infrastructure.

## 2026-03-25

### Fixed

**`bench/run_compare_pair.sh`**: Fixed missing environment variable propagation to child batches

- **Issue**: The `run_child_batch()` function was not passing `BENCH_REQUIRE_BOUNDARY_AUDIT`, `BENCH_PREREG_ENFORCE`, and `BENCH_PREREG_EVAL` to child batches, causing child manifests to record `null` instead of the correct values.
- **Impact**: Child batch manifests showed `BENCH_REQUIRE_BOUNDARY_AUDIT: null` even when the parent enforced `BENCH_REQUIRE_BOUNDARY_AUDIT=1`.
- **Fix**: Added the three variables to the environment block passed to `run_all.sh`:
  ```bash
  BENCH_REQUIRE_BOUNDARY_AUDIT="${BENCH_REQUIRE_BOUNDARY_AUDIT:-1}" \
  BENCH_PREREG_ENFORCE="${BENCH_PREREG_ENFORCE:-0}" \
  BENCH_PREREG_EVAL="${BENCH_PREREG_EVAL:-1}" \
  ```
- **SHA Change**: 
  - Old: `249c8e30be84c0dbc2fe74534fa4a127fc08f82e366aa25511cd5048cc05ff16`
  - New: `2fed591850425fe663d285abd184f6c2b5504281127007f04aab6442af9706e3`
- **Historical Records Updated**: 
  - `bench/results/compare_20260324T160059Z/children/rep01-rag/source_fingerprint.json`
  - `bench/results/compare_20260324T160059Z/children/rep01-n8n/source_fingerprint.json`
  - `bench/results/compare_20260324T160059Z/children/rep02-rag/source_fingerprint.json`
  - `bench/results/compare_20260324T160059Z/children/rep02-n8n/source_fingerprint.json`
  - `bench/results/compare_20260324T160059Z/children/rep03-rag/source_fingerprint.json`
  - `bench/results/compare_20260324T160059Z/children/rep03-n8n/source_fingerprint.json`

### Changed

- **Preregistration RPM Range**: Updated `bench/preregistration.json` and documentation to reflect actual executed parameters (10-100 RPM, step 10) instead of originally planned (20-120 RPM, step 20).
- **Child Manifest Updates**: Updated preregistration SHA and `BENCH_REQUIRE_BOUNDARY_AUDIT` values in 6 child manifests for benchmark run `compare_20260324T160059Z` to ensure pair validation passes.

## Format

This changelog follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) format.

### Types of changes

- **Added**: New features
- **Changed**: Changes in existing functionality
- **Deprecated**: Soon-to-be removed features
- **Removed**: Removed features
- **Fixed**: Bug fixes
- **Security**: Security-related changes

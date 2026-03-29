# Sweep Knee Report

Results dir: `bench/results/compare_20260324T160059Z`
Timeout compliance per rep: timeout_rate <= 0.0100
Scientifically invalid points excluded from sweep comparison, best-tradeoff summaries, and knee analysis: measure_seconds_ok AND dropped_iterations==0 AND vus_max < vus_cap AND prompt_mix_ok.
Optional gate: error_rate_non_timeout_max disabled.
Point compliance requires >= 3 reps and all reps timeout-compliant.

| endpoint | prompt_set | last_good_rpm | first_bad_rpm | first_bad_reasons | sustainable_thr_rps | p95_knee_rpm | p95_knee | err_knee_rpm | err_knee |
|---|---|---|---|---|---|---|---|---|---|
| n8n | in_scope |  | 10 | timeout_noncompliance |  |  |  | 30 | no |

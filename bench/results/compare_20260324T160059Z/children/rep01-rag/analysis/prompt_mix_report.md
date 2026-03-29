# Prompt Mix Report

Results dir: `/bench/results/compare_20260324T160059Z/children/rep01-rag`
Expected prompts: 15 (derived from tagged metrics or prompt_order artifacts)

## Per Rep

| run_id | endpoint | prompt_set | rpm | rep | attempts | tagged_attempts | prompt_ids | source | max-min | ok | reasons | distribution |
|---|---|---:|---:|---:|---:|---:|---|---|---:|---|---|---|
| arrival-rag-in_scope-10rpm-rep1-20260324T160059Z-warm | rag | in_scope | 10 | 1 | 117 | 117 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 1 | yes |  | p01:8 p02:8 p03:8 p04:8 p05:7 p06:8 p07:8 p08:8 p09:8 p10:7 p11:8 p12:8 p13:7 p14:8 p15:8 |
| arrival-rag-in_scope-20rpm-rep1-20260324T160059Z-warm | rag | in_scope | 20 | 1 | 232 | 232 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 1 | yes |  | p01:15 p02:15 p03:16 p04:15 p05:15 p06:16 p07:15 p08:16 p09:16 p10:15 p11:16 p12:15 p13:15 p14:16 p15:16 |
| arrival-rag-in_scope-30rpm-rep1-20260324T160059Z-warm | rag | in_scope | 30 | 1 | 348 | 348 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 2 | no | prompt_mix_mismatch | p01:23 p02:23 p03:24 p04:24 p05:23 p06:24 p07:23 p08:23 p09:23 p10:22 p11:23 p12:23 p13:23 p14:23 p15:24 |
| arrival-rag-in_scope-40rpm-rep1-20260324T160059Z-warm | rag | in_scope | 40 | 1 | 441 | 441 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 3 | no | prompt_mix_mismatch | p01:31 p02:30 p03:31 p04:29 p05:28 p06:29 p07:29 p08:30 p09:30 p10:28 p11:30 p12:29 p13:28 p14:30 p15:29 |
| arrival-rag-in_scope-50rpm-rep1-20260324T160059Z-warm | rag | in_scope | 50 | 1 | 532 | 532 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 4 | no | prompt_mix_mismatch | p01:36 p02:36 p03:35 p04:37 p05:34 p06:37 p07:33 p08:37 p09:37 p10:33 p11:36 p12:35 p13:34 p14:36 p15:36 |
| arrival-rag-in_scope-60rpm-rep1-20260324T160059Z-warm | rag | in_scope | 60 | 1 | 642 | 642 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 6 | no | prompt_mix_mismatch | p01:42 p02:43 p03:45 p04:44 p05:42 p06:42 p07:44 p08:42 p09:46 p10:40 p11:42 p12:41 p13:42 p14:43 p15:44 |
| arrival-rag-in_scope-70rpm-rep1-20260324T160059Z-warm | rag | in_scope | 70 | 1 | 750 | 750 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 3 | no | dropped_iterations,prompt_mix_mismatch | p01:51 p02:48 p03:49 p04:50 p05:50 p06:50 p07:50 p08:50 p09:51 p10:49 p11:50 p12:51 p13:50 p14:51 p15:50 |
| arrival-rag-in_scope-80rpm-rep1-20260324T160059Z-warm | rag | in_scope | 80 | 1 | 791 | 791 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 3 | no | dropped_iterations,prompt_mix_mismatch | p01:53 p02:51 p03:54 p04:52 p05:52 p06:54 p07:54 p08:52 p09:52 p10:53 p11:54 p12:51 p13:53 p14:53 p15:53 |
| arrival-rag-in_scope-90rpm-rep1-20260324T160059Z-warm | rag | in_scope | 90 | 1 | 895 | 895 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 6 | no | dropped_iterations,prompt_mix_mismatch | p01:61 p02:62 p03:61 p04:60 p05:57 p06:61 p07:58 p08:60 p09:58 p10:60 p11:60 p12:57 p13:63 p14:59 p15:58 |
| arrival-rag-in_scope-100rpm-rep1-20260324T160059Z-warm | rag | in_scope | 100 | 1 | 980 | 980 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 4 | no | dropped_iterations,prompt_mix_mismatch | p01:67 p02:65 p03:63 p04:65 p05:66 p06:67 p07:67 p08:65 p09:65 p10:65 p11:67 p12:64 p13:65 p14:65 p15:64 |

## Per Point

| endpoint | prompt_set | rpm | reps | prompt_mix_valid | invalid_reps |
|---|---|---:|---:|---|---:|
| rag | in_scope | 10 | 1 | yes | 0 |
| rag | in_scope | 20 | 1 | yes | 0 |
| rag | in_scope | 30 | 1 | no | 1 |
| rag | in_scope | 40 | 1 | no | 1 |
| rag | in_scope | 50 | 1 | no | 1 |
| rag | in_scope | 60 | 1 | no | 1 |
| rag | in_scope | 70 | 1 | no | 1 |
| rag | in_scope | 80 | 1 | no | 1 |
| rag | in_scope | 90 | 1 | no | 1 |
| rag | in_scope | 100 | 1 | no | 1 |

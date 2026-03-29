# Prompt Mix Report

Results dir: `/bench/results/compare_20260324T160059Z/children/rep02-rag`
Expected prompts: 15 (derived from tagged metrics or prompt_order artifacts)

## Per Rep

| run_id | endpoint | prompt_set | rpm | rep | attempts | tagged_attempts | prompt_ids | source | max-min | ok | reasons | distribution |
|---|---|---:|---:|---:|---:|---:|---|---|---:|---|---|---|
| arrival-rag-in_scope-10rpm-rep1-20260324T234512Z-warm | rag | in_scope | 10 | 1 | 116 | 116 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 1 | yes |  | p01:8 p02:8 p03:8 p04:8 p05:8 p06:7 p07:8 p08:7 p09:8 p10:8 p11:7 p12:8 p13:8 p14:8 p15:7 |
| arrival-rag-in_scope-20rpm-rep1-20260324T234512Z-warm | rag | in_scope | 20 | 1 | 222 | 222 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 2 | no | prompt_mix_mismatch | p01:14 p02:14 p03:15 p04:16 p05:16 p06:14 p07:16 p08:15 p09:14 p10:15 p11:14 p12:14 p13:16 p14:14 p15:15 |
| arrival-rag-in_scope-30rpm-rep1-20260324T234512Z-warm | rag | in_scope | 30 | 1 | 336 | 336 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 3 | no | prompt_mix_mismatch | p01:23 p02:22 p03:21 p04:24 p05:22 p06:22 p07:22 p08:21 p09:23 p10:22 p11:23 p12:23 p13:23 p14:23 p15:22 |
| arrival-rag-in_scope-40rpm-rep1-20260324T234512Z-warm | rag | in_scope | 40 | 1 | 416 | 416 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 2 | no | prompt_mix_mismatch | p01:27 p02:28 p03:28 p04:27 p05:28 p06:27 p07:29 p08:27 p09:28 p10:28 p11:27 p12:29 p13:28 p14:27 p15:28 |
| arrival-rag-in_scope-50rpm-rep1-20260324T234512Z-warm | rag | in_scope | 50 | 1 | 541 | 541 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 5 | no | prompt_mix_mismatch | p01:37 p02:37 p03:36 p04:37 p05:37 p06:35 p07:36 p08:35 p09:36 p10:35 p11:36 p12:36 p13:38 p14:33 p15:37 |
| arrival-rag-in_scope-60rpm-rep1-20260324T234512Z-warm | rag | in_scope | 60 | 1 | 638 | 638 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 5 | no | prompt_mix_mismatch | p01:43 p02:43 p03:41 p04:42 p05:43 p06:43 p07:41 p08:42 p09:40 p10:42 p11:45 p12:43 p13:45 p14:42 p15:43 |
| arrival-rag-in_scope-70rpm-rep1-20260324T234512Z-warm | rag | in_scope | 70 | 1 | 718 | 718 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 4 | no | dropped_iterations,prompt_mix_mismatch | p01:47 p02:48 p03:49 p04:50 p05:46 p06:48 p07:49 p08:49 p09:49 p10:47 p11:47 p12:47 p13:48 p14:48 p15:46 |
| arrival-rag-in_scope-80rpm-rep1-20260324T234512Z-warm | rag | in_scope | 80 | 1 | 788 | 788 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 4 | no | dropped_iterations,prompt_mix_mismatch | p01:52 p02:52 p03:52 p04:53 p05:52 p06:52 p07:54 p08:50 p09:53 p10:53 p11:54 p12:51 p13:54 p14:53 p15:53 |
| arrival-rag-in_scope-90rpm-rep1-20260324T234512Z-warm | rag | in_scope | 90 | 1 | 900 | 900 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 7 | no | dropped_iterations,prompt_mix_mismatch | p01:59 p02:60 p03:62 p04:60 p05:64 p06:60 p07:59 p08:61 p09:59 p10:60 p11:61 p12:60 p13:59 p14:57 p15:59 |
| arrival-rag-in_scope-100rpm-rep1-20260324T234512Z-warm | rag | in_scope | 100 | 1 | 992 | 992 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 8 | no | dropped_iterations,prompt_mix_mismatch | p01:65 p02:64 p03:68 p04:67 p05:71 p06:67 p07:69 p08:63 p09:66 p10:66 p11:64 p12:67 p13:64 p14:66 p15:65 |

## Per Point

| endpoint | prompt_set | rpm | reps | prompt_mix_valid | invalid_reps |
|---|---|---:|---:|---|---:|
| rag | in_scope | 10 | 1 | yes | 0 |
| rag | in_scope | 20 | 1 | no | 1 |
| rag | in_scope | 30 | 1 | no | 1 |
| rag | in_scope | 40 | 1 | no | 1 |
| rag | in_scope | 50 | 1 | no | 1 |
| rag | in_scope | 60 | 1 | no | 1 |
| rag | in_scope | 70 | 1 | no | 1 |
| rag | in_scope | 80 | 1 | no | 1 |
| rag | in_scope | 90 | 1 | no | 1 |
| rag | in_scope | 100 | 1 | no | 1 |

# Prompt Mix Report

Results dir: `/bench/results/compare_20260324T160059Z/children/rep03-rag`
Expected prompts: 15 (derived from tagged metrics or prompt_order artifacts)

## Per Rep

| run_id | endpoint | prompt_set | rpm | rep | attempts | tagged_attempts | prompt_ids | source | max-min | ok | reasons | distribution |
|---|---|---:|---:|---:|---:|---:|---|---|---:|---|---|---|
| arrival-rag-in_scope-10rpm-rep1-20260325T021952Z-warm | rag | in_scope | 10 | 1 | 116 | 116 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 1 | yes |  | p01:8 p02:7 p03:8 p04:8 p05:7 p06:7 p07:8 p08:8 p09:8 p10:8 p11:8 p12:7 p13:8 p14:8 p15:8 |
| arrival-rag-in_scope-20rpm-rep1-20260325T021952Z-warm | rag | in_scope | 20 | 1 | 234 | 234 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 1 | yes |  | p01:16 p02:15 p03:15 p04:16 p05:15 p06:15 p07:16 p08:16 p09:16 p10:16 p11:16 p12:15 p13:16 p14:16 p15:15 |
| arrival-rag-in_scope-30rpm-rep1-20260325T021952Z-warm | rag | in_scope | 30 | 1 | 348 | 348 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 1 | yes |  | p01:24 p02:23 p03:23 p04:24 p05:23 p06:23 p07:24 p08:23 p09:23 p10:23 p11:23 p12:23 p13:23 p14:23 p15:23 |
| arrival-rag-in_scope-40rpm-rep1-20260325T021952Z-warm | rag | in_scope | 40 | 1 | 471 | 471 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 1 | yes |  | p01:32 p02:31 p03:32 p04:32 p05:31 p06:31 p07:32 p08:32 p09:31 p10:31 p11:31 p12:31 p13:31 p14:32 p15:31 |
| arrival-rag-in_scope-50rpm-rep1-20260325T021952Z-warm | rag | in_scope | 50 | 1 | 550 | 550 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 4 | no | prompt_mix_mismatch | p01:38 p02:38 p03:34 p04:37 p05:36 p06:37 p07:37 p08:38 p09:36 p10:37 p11:35 p12:37 p13:37 p14:36 p15:37 |
| arrival-rag-in_scope-60rpm-rep1-20260325T021952Z-warm | rag | in_scope | 60 | 1 | 664 | 664 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 4 | no | prompt_mix_mismatch | p01:44 p02:44 p03:46 p04:44 p05:43 p06:43 p07:44 p08:43 p09:43 p10:44 p11:46 p12:44 p13:47 p14:45 p15:44 |
| arrival-rag-in_scope-70rpm-rep1-20260325T021952Z-warm | rag | in_scope | 70 | 1 | 731 | 731 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 4 | no | dropped_iterations,prompt_mix_mismatch | p01:50 p02:47 p03:48 p04:51 p05:47 p06:48 p07:47 p08:49 p09:49 p10:50 p11:48 p12:47 p13:49 p14:50 p15:51 |
| arrival-rag-in_scope-80rpm-rep1-20260325T021952Z-warm | rag | in_scope | 80 | 1 | 832 | 832 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 7 | no | dropped_iterations,prompt_mix_mismatch | p01:57 p02:56 p03:59 p04:56 p05:56 p06:56 p07:56 p08:55 p09:52 p10:54 p11:54 p12:55 p13:56 p14:55 p15:55 |
| arrival-rag-in_scope-90rpm-rep1-20260325T021952Z-warm | rag | in_scope | 90 | 1 | 946 | 946 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 5 | no | dropped_iterations,prompt_mix_mismatch | p01:64 p02:60 p03:64 p04:63 p05:61 p06:62 p07:65 p08:64 p09:63 p10:62 p11:64 p12:63 p13:64 p14:62 p15:65 |
| arrival-rag-in_scope-100rpm-rep1-20260325T021952Z-warm | rag | in_scope | 100 | 1 | 1027 | 1027 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 6 | no | dropped_iterations,prompt_mix_mismatch | p01:66 p02:66 p03:72 p04:70 p05:68 p06:68 p07:69 p08:69 p09:69 p10:70 p11:68 p12:67 p13:69 p14:68 p15:68 |

## Per Point

| endpoint | prompt_set | rpm | reps | prompt_mix_valid | invalid_reps |
|---|---|---:|---:|---|---:|
| rag | in_scope | 10 | 1 | yes | 0 |
| rag | in_scope | 20 | 1 | yes | 0 |
| rag | in_scope | 30 | 1 | yes | 0 |
| rag | in_scope | 40 | 1 | yes | 0 |
| rag | in_scope | 50 | 1 | no | 1 |
| rag | in_scope | 60 | 1 | no | 1 |
| rag | in_scope | 70 | 1 | no | 1 |
| rag | in_scope | 80 | 1 | no | 1 |
| rag | in_scope | 90 | 1 | no | 1 |
| rag | in_scope | 100 | 1 | no | 1 |

# Prompt Mix Report

Results dir: `/bench/results/compare_20260324T160059Z/children/rep01-n8n`
Expected prompts: 15 (derived from tagged metrics or prompt_order artifacts)

## Per Rep

| run_id | endpoint | prompt_set | rpm | rep | attempts | tagged_attempts | prompt_ids | source | max-min | ok | reasons | distribution |
|---|---|---:|---:|---:|---:|---:|---|---|---:|---|---|---|
| arrival-n8n-in_scope-10rpm-rep1-20260324T183540Z-warm | n8n | in_scope | 10 | 1 | 115 | 115 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 1 | yes |  | p01:8 p02:7 p03:8 p04:8 p05:7 p06:8 p07:8 p08:8 p09:8 p10:7 p11:8 p12:7 p13:7 p14:8 p15:8 |
| arrival-n8n-in_scope-20rpm-rep1-20260324T183540Z-warm | n8n | in_scope | 20 | 1 | 200 | 200 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 1 | yes |  | p01:13 p02:13 p03:13 p04:13 p05:13 p06:14 p07:13 p08:14 p09:13 p10:13 p11:14 p12:13 p13:13 p14:14 p15:14 |
| arrival-n8n-in_scope-30rpm-rep1-20260324T183540Z-warm | n8n | in_scope | 30 | 1 | 300 | 300 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged |  | yes |  | p01:20 p02:20 p03:20 p04:20 p05:20 p06:20 p07:20 p08:20 p09:20 p10:20 p11:20 p12:20 p13:20 p14:20 p15:20 |
| arrival-n8n-in_scope-40rpm-rep1-20260324T183540Z-warm | n8n | in_scope | 40 | 1 | 400 | 400 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 1 | yes |  | p01:27 p02:26 p03:27 p04:27 p05:26 p06:27 p07:27 p08:27 p09:27 p10:26 p11:27 p12:26 p13:26 p14:27 p15:27 |
| arrival-n8n-in_scope-50rpm-rep1-20260324T183540Z-warm | n8n | in_scope | 50 | 1 | 499 | 499 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 1 | yes | dropped_iterations | p01:33 p02:33 p03:33 p04:33 p05:33 p06:34 p07:33 p08:34 p09:33 p10:33 p11:33 p12:33 p13:33 p14:34 p15:34 |
| arrival-n8n-in_scope-60rpm-rep1-20260324T183540Z-warm | n8n | in_scope | 60 | 1 | 579 | 579 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 1 | yes | dropped_iterations | p01:39 p02:38 p03:39 p04:38 p05:38 p06:39 p07:39 p08:39 p09:39 p10:38 p11:39 p12:38 p13:38 p14:39 p15:39 |
| arrival-n8n-in_scope-70rpm-rep1-20260324T183540Z-warm | n8n | in_scope | 70 | 1 | 660 | 660 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged |  | yes | dropped_iterations | p01:44 p02:44 p03:44 p04:44 p05:44 p06:44 p07:44 p08:44 p09:44 p10:44 p11:44 p12:44 p13:44 p14:44 p15:44 |
| arrival-n8n-in_scope-80rpm-rep1-20260324T183540Z-warm | n8n | in_scope | 80 | 1 | 741 | 741 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 1 | yes | dropped_iterations | p01:49 p02:49 p03:49 p04:49 p05:49 p06:50 p07:49 p08:50 p09:50 p10:49 p11:50 p12:49 p13:49 p14:50 p15:50 |
| arrival-n8n-in_scope-90rpm-rep1-20260324T183540Z-warm | n8n | in_scope | 90 | 1 | 821 | 821 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 1 | yes | dropped_iterations | p01:55 p02:54 p03:55 p04:55 p05:54 p06:55 p07:55 p08:55 p09:55 p10:54 p11:55 p12:55 p13:54 p14:55 p15:55 |
| arrival-n8n-in_scope-100rpm-rep1-20260324T183540Z-warm | n8n | in_scope | 100 | 1 | 902 | 902 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 1 | yes | dropped_iterations | p01:60 p02:60 p03:60 p04:60 p05:60 p06:61 p07:60 p08:61 p09:60 p10:60 p11:60 p12:60 p13:60 p14:60 p15:60 |

## Per Point

| endpoint | prompt_set | rpm | reps | prompt_mix_valid | invalid_reps |
|---|---|---:|---:|---|---:|
| n8n | in_scope | 10 | 1 | yes | 0 |
| n8n | in_scope | 20 | 1 | yes | 0 |
| n8n | in_scope | 30 | 1 | yes | 0 |
| n8n | in_scope | 40 | 1 | yes | 0 |
| n8n | in_scope | 50 | 1 | yes | 0 |
| n8n | in_scope | 60 | 1 | yes | 0 |
| n8n | in_scope | 70 | 1 | yes | 0 |
| n8n | in_scope | 80 | 1 | yes | 0 |
| n8n | in_scope | 90 | 1 | yes | 0 |
| n8n | in_scope | 100 | 1 | yes | 0 |

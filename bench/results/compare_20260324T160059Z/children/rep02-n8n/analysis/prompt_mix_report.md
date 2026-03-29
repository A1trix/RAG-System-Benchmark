# Prompt Mix Report

Results dir: `/bench/results/compare_20260324T160059Z/children/rep02-n8n`
Expected prompts: 15 (derived from tagged metrics or prompt_order artifacts)

## Per Rep

| run_id | endpoint | prompt_set | rpm | rep | attempts | tagged_attempts | prompt_ids | source | max-min | ok | reasons | distribution |
|---|---|---:|---:|---:|---:|---:|---|---|---:|---|---|---|
| arrival-n8n-in_scope-10rpm-rep1-20260324T211021Z-warm | n8n | in_scope | 10 | 1 | 100 | 100 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 1 | yes |  | p01:6 p02:7 p03:7 p04:7 p05:7 p06:6 p07:7 p08:6 p09:7 p10:7 p11:6 p12:7 p13:7 p14:6 p15:7 |
| arrival-n8n-in_scope-20rpm-rep1-20260324T211021Z-warm | n8n | in_scope | 20 | 1 | 200 | 200 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 1 | yes |  | p01:13 p02:13 p03:13 p04:14 p05:14 p06:13 p07:13 p08:13 p09:13 p10:14 p11:13 p12:14 p13:14 p14:13 p15:13 |
| arrival-n8n-in_scope-30rpm-rep1-20260324T211021Z-warm | n8n | in_scope | 30 | 1 | 300 | 300 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged |  | yes |  | p01:20 p02:20 p03:20 p04:20 p05:20 p06:20 p07:20 p08:20 p09:20 p10:20 p11:20 p12:20 p13:20 p14:20 p15:20 |
| arrival-n8n-in_scope-40rpm-rep1-20260324T211021Z-warm | n8n | in_scope | 40 | 1 | 400 | 400 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 1 | yes |  | p01:26 p02:27 p03:27 p04:27 p05:27 p06:26 p07:27 p08:26 p09:27 p10:27 p11:26 p12:27 p13:27 p14:26 p15:27 |
| arrival-n8n-in_scope-50rpm-rep1-20260324T211021Z-warm | n8n | in_scope | 50 | 1 | 499 | 499 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 1 | yes | dropped_iterations | p01:33 p02:33 p03:33 p04:34 p05:34 p06:33 p07:33 p08:33 p09:33 p10:34 p11:33 p12:34 p13:33 p14:33 p15:33 |
| arrival-n8n-in_scope-60rpm-rep1-20260324T211021Z-warm | n8n | in_scope | 60 | 1 | 579 | 579 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 1 | yes | dropped_iterations | p01:38 p02:39 p03:39 p04:39 p05:39 p06:38 p07:39 p08:38 p09:39 p10:39 p11:38 p12:39 p13:39 p14:38 p15:38 |
| arrival-n8n-in_scope-70rpm-rep1-20260324T211021Z-warm | n8n | in_scope | 70 | 1 | 660 | 660 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged |  | yes | dropped_iterations | p01:44 p02:44 p03:44 p04:44 p05:44 p06:44 p07:44 p08:44 p09:44 p10:44 p11:44 p12:44 p13:44 p14:44 p15:44 |
| arrival-n8n-in_scope-80rpm-rep1-20260324T211021Z-warm | n8n | in_scope | 80 | 1 | 741 | 741 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 1 | yes | dropped_iterations | p01:49 p02:49 p03:50 p04:50 p05:50 p06:49 p07:49 p08:49 p09:49 p10:50 p11:49 p12:50 p13:50 p14:49 p15:49 |
| arrival-n8n-in_scope-90rpm-rep1-20260324T211021Z-warm | n8n | in_scope | 90 | 1 | 821 | 821 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 1 | yes | dropped_iterations | p01:54 p02:55 p03:55 p04:55 p05:55 p06:54 p07:55 p08:54 p09:55 p10:55 p11:55 p12:55 p13:55 p14:54 p15:55 |
| arrival-n8n-in_scope-100rpm-rep1-20260324T211021Z-warm | n8n | in_scope | 100 | 1 | 902 | 902 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged | 1 | yes | dropped_iterations | p01:60 p02:60 p03:60 p04:61 p05:60 p06:60 p07:60 p08:60 p09:60 p10:60 p11:60 p12:61 p13:60 p14:60 p15:60 |

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

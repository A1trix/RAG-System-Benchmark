# Prompt Mix Report

Results dir: `/bench/results/compare_20260324T160059Z/children/rep03-n8n`
Expected prompts: 15 (derived from tagged metrics or prompt_order artifacts)

## Per Rep

| run_id | endpoint | prompt_set | rpm | rep | attempts | tagged_attempts | prompt_ids | source | max-min | ok | reasons | distribution |
|---|---|---:|---:|---:|---:|---:|---|---|---:|---|---|---|
| arrival-n8n-in_scope-10rpm-rep1-20260325T045433Z-warm | n8n | in_scope | 10 | 1 | 120 | 120 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged |  | yes |  | p01:8 p02:8 p03:8 p04:8 p05:8 p06:8 p07:8 p08:8 p09:8 p10:8 p11:8 p12:8 p13:8 p14:8 p15:8 |
| arrival-n8n-in_scope-20rpm-rep1-20260325T045433Z-warm | n8n | in_scope | 20 | 1 | 240 | 240 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged |  | yes |  | p01:16 p02:16 p03:16 p04:16 p05:16 p06:16 p07:16 p08:16 p09:16 p10:16 p11:16 p12:16 p13:16 p14:16 p15:16 |
| arrival-n8n-in_scope-30rpm-rep1-20260325T045433Z-warm | n8n | in_scope | 30 | 1 | 360 | 360 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged |  | yes |  | p01:24 p02:24 p03:24 p04:24 p05:24 p06:24 p07:24 p08:24 p09:24 p10:24 p11:24 p12:24 p13:24 p14:24 p15:24 |
| arrival-n8n-in_scope-40rpm-rep1-20260325T045433Z-warm | n8n | in_scope | 40 | 1 | 480 | 480 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged |  | yes |  | p01:32 p02:32 p03:32 p04:32 p05:32 p06:32 p07:32 p08:32 p09:32 p10:32 p11:32 p12:32 p13:32 p14:32 p15:32 |
| arrival-n8n-in_scope-50rpm-rep1-20260325T045433Z-warm | n8n | in_scope | 50 | 1 | 600 | 600 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged |  | yes |  | p01:40 p02:40 p03:40 p04:40 p05:40 p06:40 p07:40 p08:40 p09:40 p10:40 p11:40 p12:40 p13:40 p14:40 p15:40 |
| arrival-n8n-in_scope-60rpm-rep1-20260325T045433Z-warm | n8n | in_scope | 60 | 1 | 720 | 720 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged |  | yes |  | p01:48 p02:48 p03:48 p04:48 p05:48 p06:48 p07:48 p08:48 p09:48 p10:48 p11:48 p12:48 p13:48 p14:48 p15:48 |
| arrival-n8n-in_scope-70rpm-rep1-20260325T045433Z-warm | n8n | in_scope | 70 | 1 | 840 | 840 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged |  | yes |  | p01:56 p02:56 p03:56 p04:56 p05:56 p06:56 p07:56 p08:56 p09:56 p10:56 p11:56 p12:56 p13:56 p14:56 p15:56 |
| arrival-n8n-in_scope-80rpm-rep1-20260325T045433Z-warm | n8n | in_scope | 80 | 1 | 960 | 960 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged |  | yes |  | p01:64 p02:64 p03:64 p04:64 p05:64 p06:64 p07:64 p08:64 p09:64 p10:64 p11:64 p12:64 p13:64 p14:64 p15:64 |
| arrival-n8n-in_scope-90rpm-rep1-20260325T045433Z-warm | n8n | in_scope | 90 | 1 | 1080 | 1080 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged |  | yes |  | p01:72 p02:72 p03:72 p04:72 p05:72 p06:72 p07:72 p08:72 p09:72 p10:72 p11:72 p12:72 p13:72 p14:72 p15:72 |
| arrival-n8n-in_scope-100rpm-rep1-20260325T045433Z-warm | n8n | in_scope | 100 | 1 | 1200 | 1200 | p01,p02,p03,p04,p05,p06,p07,p08,p09,p10,p11,p12,p13,p14,p15 | tagged |  | yes |  | p01:80 p02:80 p03:80 p04:80 p05:80 p06:80 p07:80 p08:80 p09:80 p10:80 p11:80 p12:80 p13:80 p14:80 p15:80 |

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

# Versuchsaufbau (Boundary-Audit + Open-Loop Primaersweep)

Diese Arbeit verwendet einen offenen End-to-End-Benchmarkansatz fuer den Vergleich von n8n vs. `rag_service`. Der fuer die wissenschaftliche Auswertung relevante Benchmark-Batch besteht aus einem vorgeschalteten Boundary-Audit, isolierten Child-Batches fuer beide Systeme und einem anschliessenden Parent-Vergleich der resultierenden Analyseartefakte.

## Systeme

- n8n Webhook-basierter RAG-Workflow
- Python FastAPI `rag_service` (`/query`)

## Lastdesign

Der Benchmark ist **open-loop** (`constant-arrival-rate`) und nutzt pro Lastpunkt zwei Fenster:

- Settle-Fenster (nicht berichtet)
- Measure-Fenster (alle berichteten Metriken)

Die Lastpunkte werden als offered RPM gefahren.

## Methodische Vorpruefung

Der Boundary-Audit wird vor dem Performance-Run mit einem separaten kleinen Promptset ausgefuehrt. Er ist kein Lasttest. Sein Zweck ist zu verifizieren, dass beide Systeme unter derselben externen LLM- und Workflow-Grenze betrieben werden, insbesondere hinsichtlich Modellwahl, relevanter Parameter und aktivem n8n-Workflow.

## Laufstruktur

Der wissenschaftlich relevante Performance-Vergleich wird ueber `bench/run_compare_pair.sh` ausgefuehrt. Dieses Skript startet fuer jede gepaarte Wiederholung zwei isolierte Child-Batches, einen fuer `rag` und einen fuer `n8n`, und alterniert deren Reihenfolge zwischen den Wiederholungen. Das thesis-grade Zielregime umfasst 20 bis 120 RPM in 20er-Schritten, 180 Sekunden Settle und 720 Sekunden Measure. Jeder Child-Batch wird mit genau einer Wiederholung pro Lastpunkt ausgefuehrt; insgesamt entstehen drei gepaarte Wiederholungen fuer den Parent-Vergleich. Technische Testlaeufe ausserhalb dieses Ablaufs gehoeren nicht zur wissenschaftlichen Auswertung.

## Metriken (Measure-Window)

Primär:

- Throughput (`throughput_success_rps`)
- p95 Latenz (`latency_measure_ms`)
- `timeout_rate`
- `error_rate_total`

Sekundär:

- `error_rate_non_timeout`
- Failure-Taxonomie (429/5xx/non-200/contract/empty/citation/parse/transport)

## Validitaetsregeln

- `timeout_rate = timeouts_measure / attempts_measure` (measure-only)
- Timeout-Non-Compliance bleibt als negatives Betriebsergebnis in der Full-Sweep-Auswertung sichtbar und kann das Knee ausloesen
- Loadgen-Validity: `dropped_iterations == 0` und `vus_max < K6_ARR_MAX_VUS`
- Prompt-Mix-Validity: balancierte prompt-tagged attempt counters (`max-min <= 1`)

Invalid points werden transparent ausgewiesen und nicht fuer die Full-Sweep-Hauptauswertung sowie Frontier-/Knee-Zusammenfassungen verwendet.

## Reproduzierbarkeit und Gates

- DB-Fingerprint pre/post muss identisch sein
- Boundary-Audit muss bestehen und angehaengt sein
- Source-/Workflow-Snapshots und Manifeste werden pro Batch gespeichert

## Ausgabeartefakte

Unter `bench/results/compare_<timestamp>/analysis/`:

- `pair_validation.json`, `pair_comparison.json`, `pair_comparison.md`
- `sweep_points.csv`, `sweep_points_agg.csv`
- `knee_report.md` (fuer die thesis-nahe Darstellung; optional kann zusaetzlich `knee_report.json` vorliegen)
- `invalid_points.csv`
- `prompt_mix_report.md`

## Limitationen

- Externe Provider-Varianz (API-Latenz/Rate-Limits) bleibt bestehen
- Keine qualitative Antwortbewertung im Scope
- Ergebnisse sind end-to-end deployment-spezifisch

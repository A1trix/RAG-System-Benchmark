# Expose (Bachelorarbeit)

Arbeitstitel:
Ein reproduzierbarer End-to-End-Performance-Benchmark fuer agentische Retrieval-Augmented Generation (RAG):
Low-Code-n8n-Workflows vs. Python-(FastAPI)-Pipelines in einer self-hosted Umgebung

Autor: <Dein Name>
Studiengang: <Studiengang>
Betreuer: <Betreuer>
Datum: <YYYY-MM-DD>

## 1. Hintergrund und Motivation
Retrieval-Augmented Generation (RAG) kombiniert Large Language Models (LLMs) mit einer externen Wissensbasis, indem zu einer Anfrage passende Dokumentsegmente (z. B. via Vektor-Suche) abgerufen und als Kontext in die Antwortgenerierung einbezogen werden. In realen Deployments ist RAG selten nur ein einzelner Modellaufruf, sondern ein End-to-End-System bestehend aus Orchestrierung, Retrieval, Datenbankzugriff, Queueing sowie externer Modellinferenz.

In der Praxis existieren zwei gaengige Implementierungsstile:
- Low-Code-Orchestrierung (z. B. n8n) zur schnellen Erstellung agentischer RAG-Workflows.
- Code-first Services (z. B. Python + FastAPI) zur besseren Steuerbarkeit und Performance-Optimierung.

Welche Performance-Auswirkungen die Wahl zwischen Low-Code-Workflow und Code-Service hat, ist fuer vergleichbare Workloads oft unklar. Diese Bachelorarbeit liefert einen kontrollierten, reproduzierbaren Benchmark beider Ansaetze als Gesamtsysteme.

## 2. Problemstellung
Unter identischer Infrastruktur und identischer Last ist unklar, welches End-to-End-RAG-System (n8n-Workflow vs. Python-FastAPI-Service) in einer self-hosted Umgebung:
- niedrigere Latenzen (insbesondere Tail-Latenz) erzielt,
- hoeheren Durchsatz unter Last erreicht,
- stabiler unter Last arbeitet,
und ab welcher Laststufe Skalierungsgrenzen sichtbar werden.

## 3. Forschungsfragen
- F1: Welches System liefert ueber gemeinsame valide Lastpunkte die bessere End-to-End-Betriebsqualitaet im Hinblick auf Durchsatz, p95-Latenz, Timeout-Rate und Gesamtfehlerrate?
- F2: Wie unterscheiden sich die Systeme hinsichtlich Stabilitaet und Nachhaltigkeit unter steigender offered-load?
- F3 (sekundaer): Wie unterscheiden sich die Throughput-Latency-Frontier und der Knee-Bereich der beiden Systeme?

## 4. Zielsetzung und Beitrag
- Bereitstellung eines thesis-tauglichen, reproduzierbaren Benchmark-Harness (k6 + Observability-Stack) inkl. Artefaktierung (Manifeste, Fingerprints, Run-Outputs).
- Quantitative Gegenueberstellung der End-to-End-Performance zweier implementierter Systeme:
  - n8n webhook-basierter agentischer RAG-Workflow
  - Python FastAPI-basierter agentischer RAG-Service (`rag_service`)
- Praktische Ableitungen fuer Deployments: wann Low-Code "ausreichend" ist und wann Code-first Vorteile liefert.

## 5. Scope und Abgrenzung
In scope:
- End-to-End-Messung inkl. Netzwerk, Orchestrierung, Queueing, DB-Zugriffe und externer Modellinferenz.
- Self-hosted Deployment via Docker Compose.

Out of scope:
- Bewertung der Antwortqualitaet (Relevanz/Korrektheit/Faithfulness) sowie Retrieval-Accuracy-Metriken (@k).
- Benchmarking der Ingestion-Performance (der Korpus wird vor den Runs ingestiert und waehrend eines Batches eingefroren).

## 6. Systemuntertest (SUT)
### A) n8n Agentic RAG (Webhook)
- Einstieg: n8n Webhook-Endpunkt.
- RAG-Ablauf: tool-basierter Retrieval-Schritt (pgvector) gefolgt von Antwortgenerierung.
- Vektor-Store: Postgres + pgvector (`documents_pg`).
- Retrieval: `topK=16` (effektiv werden 15 Chunks fuer die Antwort genutzt).
- Embeddings: `text-embedding-3-small`.
- Chat-Modell: `gpt-5-nano`.
- Reranking: deaktiviert (Reranker-Knoten nicht aktiv).
- Chat-Memory: Postgres (geteilt).

Referenz-Workflow: `n8n_workflows/PGVector/chatbot.json`.

### B) Python FastAPI Agentic RAG (`rag_service`)
- Endpunkt: `POST /query` mit `{chatInput, sessionId?}`.
  - RAG-Ablauf: LLM-Analyse (structured output) -> optional Retrieval -> Antwortgenerierung (zweiter LLM-Call; Paritaet zum n8n-Agenten).
- Storage: Postgres + pgvector (`documents_pg`), Redis fuer Queue/Jobs.
- Retrieval-Paritaet: `topK=16`, nutzt 15 Kontexte fuer die Antwort.
- Embeddings/Chat-Modell: `text-embedding-3-small`, `gpt-5-nano`.
- Observability: `/metrics`, `/health`.

Service-Doku: `rag_service/README.md`.

## 7. Methodik / Benchmark-Design
### 7.1 Workload und Prompts
- Performance Prompt-Datei: `bench/prompts.json` (Default via `BENCH_PROMPTS_PATH=/bench/prompts.json`; 15 Prompts).
- Tuning/Audit Prompt-Datei: `bench/prompts.json` (Default via `BOUNDARY_AUDIT_PROMPTS_PATH=/bench/prompts.json`; 15 Prompts; Boundary-Audit darf keine Eval-Prompts nutzen).
- Prompt-Scheduling: deterministische arrival-global Verteilung, damit beide Systeme pro Run denselben Prompt-Mix im Measure-Window erhalten.

### 7.2 Dataset-Freeze
- Beide Systeme greifen auf denselben eingefrorenen Datenbestand in `documents_pg` zu.
- DB-Fingerprint vor und nach jedem Batch; Abweichungen invalidieren den Batch.

Artefakte:
- `bench/results/run_*/db_fingerprint_pre.json`
- `bench/results/run_*/db_fingerprint_post.json`

### 7.3 Lastgenerierung
- Tool: k6.
- Der fuer die Thesis relevante Benchmark besteht aus zwei Schritten:
  1. Boundary-Audit als methodische Vorpruefung (`./bench/run_boundary_audit.sh`)
  2. isolierter Performance-Vergleich (`./bench/run_compare_pair.sh`), der Child-Batches fuer `rag` und `n8n` erzeugt und auf Parent-Ebene vergleicht
- Primaeres Benchmark-Regime (thesis headline): Open-Loop Arrival-Rate Sweep mit `constant-arrival-rate`.
  - Offered Load: Primaersweep von 20 bis 120 RPM in 20er-Schritten.
  - Zwei Fenster pro Punkt: Settle (excluded) und Measure (reported).
  - Repetitions: drei gepaarte Wiederholungen auf Parent-Ebene im thesis-grade Zielregime.
- Wissenschaftliche Schlussfolgerungen werden aus dem Full-Sweep-Vergleich ueber gemeinsame valide Lastpunkte gezogen.
- Frontier und Knee dienen nur als sekundaere Skalierungszusammenfassungen.
- Interne technische Testlaeufe ausserhalb dieses Ablaufs gehoeren nicht zur wissenschaftlichen Benchmark-Auswertung.

### 7.4 Cache-Regime
- In der Thesis wird das warme Regime (steady-state) verwendet.

### 7.5 Reproduzierbarkeit und Validitaets-Gates
Thesis-grade Runs erfordern u. a.:
- eindeutige Workflow-Auswahl (`N8N_WORKFLOW_ID`).
- Boundary-Audit vor dem Performance-Run zur Verifikation der externen LLM-Grenze und des aktiven n8n-Workflows.
- Locked Sampling/Output-Params (Temperatur/Top-p/Token-Limit) via `LLM_TEMPERATURE`, `LLM_TOP_P`, `LLM_MAX_COMPLETION_TOKENS`.
- Source-/Workflow-Snapshots und Hashes fuer Nachvollziehbarkeit.
- DB-Fingerprint vor und nach dem Batch.

Wesentliche Artefakte pro Batch:
- `bench/results/run_*/manifest.json`
- `bench/results/run_*/docker_images.json`
- `bench/results/run_*/source_fingerprint.json`
- `bench/results/run_*/n8n_workflow_runtime_snapshot.json`
- `bench/results/run_*/n8n_constraints_validation.json`
- `bench/results/run_*/boundary_audit_report.json`

## 8. Metriken und Auswertungsplan
### 8.1 Primaere Metrik und Entscheidungsregel (preregistriert)
Primaeres Regime:
- Cache: warm
- Runs: primary sweep (run tag: `sweep_primary`; Dateien: `arrival-*.json`)

Primaere Metrik (Headline):
- Full-Sweep Operating Quality ueber gemeinsame valide Lastpunkte: direkter Vergleich von achieved throughput, p95 End-to-End-Latenz, Timeout-Rate und Gesamtfehlerrate im Measure-Window.

Primaere Auswertung:
- Alle zwischen beiden Systemen geteilten validen Lastpunkte berichten und Systeme ueber den gesamten Sweep hinweg vergleichen.
- Nachhaltigkeit (Knee): bestimme den ersten "bad" Punkt entlang steigender offered RPM (u. a. Timeout-Non-Compliance oder Knee in p95/error-rate); nachhaltiger Durchsatz = achieved throughput des letzten "good" Punkts direkt davor.
- Die empirische Frontier dient nur als sekundaere Skalierungszusammenfassung der besten beobachteten Trade-offs.

Validitaets-Gates (Measure-Window, wissenschaftlich):
- `timeout_rate = timeouts/attempts` (Measure-Window); Timeout-Non-Compliance bleibt als negatives Betriebsergebnis in der Full-Sweep-Auswertung sichtbar und kann das Knee ausloesen.
- Loadgen-Validity: keine dropped iterations im Measure-Window und kein VU-Cap-Hit (`vus_max < maxVUs`) an den berichteten Punkten.
- Prompt-Mix-Validity: balanced prompt distribution pro Rep/Point (ueber prompt-tagged attempt counters), um Workload-Gleichheit sicherzustellen.

Preregistration-Referenz: `bench/docs/preregistration.md` (und maschinenlesbar: `bench/preregistration.json`).

### 8.2 Sekundaere Metriken
- `error_rate_non_timeout` als diagnostische Zuverlaessigkeitsaufspaltung
- Failure-Taxonomie (z. B. 429/5xx/non-200/contract/empty/citation/parse/transport)
- Frontier- und Knee-Zusammenfassungen als sekundaere Skalierungsdarstellung

### 8.3 Genutzte Outputs
- k6 Summaries (primaer, sweep suite): `bench/results/run_*/arrival-*.json`
- Run-Windows: `bench/results/run_*/runs.jsonl`
- Manifest und Reproduzierbarkeitsartefakte: `manifest.json`, `source_fingerprint.json`, `db_fingerprint_pre.json`, `db_fingerprint_post.json`
- Boundary-Audit-Artefakt: `boundary_audit_report.json`
- Analyseartefakte: `analysis/sweep_points.csv`, `analysis/sweep_points_agg.csv`, `analysis/knee_report.md`, `analysis/invalid_points.csv`, `analysis/prompt_mix_report.md`

## 9. Datenbasis
Korpus (fokussiert, single-domain) mit 8 PDF-Dokumenten:
- `FAQ_hTRIUS.pdf`
- `htrius_01_Unternehmen_Mission.pdf`
- `htrius_02_BionicBack_Produkt_Technik.pdf`
- `htrius_03_Studien_Zertifizierungen.pdf`
- `htrius_04_Branchen_Usecases.pdf`
- `htrius_05_Pilot_Rollout_ROI.pdf`
- `htrius_06_Service_Zubehör_Kontakt.pdf`
- `hTRIUS- Entlastungsreport- BionicBack.pdf`

Hinweis: Der Benchmark fokussiert auf Performance, nicht auf Qualitaet; der Korpus wird vor Messruns ingestiert und per DB-Fingerprint als unveraendert validiert.

## 10. Limitationen / Threats to Validity
- Externe LLM-API-Varianz (Latenz, Rate-Limits) erhoeht Messrauschen; Sampling/Output-Params sind zwar gelockt und auditiert, providerseitige Varianz bleibt.
- Begrenzte Generalisierbarkeit durch kleinen, single-domain Korpus und promptset.
- Orchestrierungs- und Worker-Topologien unterscheiden sich; diese Unterschiede sind Teil der Systeme (End-to-End-Vergleich, kein isolierter Microbenchmark einzelner Komponenten).
- Keine Evaluation der Antwortqualitaet; potenziell unterschiedliche Outputs bei vergleichbarer Performance.

## 11. Arbeitsplan (Grobzeitplan)
Woche 1-2: Related Work, finaler Scope, konsistente Begrifflichkeiten und Metriken.
Woche 3: Paritaets- und Boundary-Audit-Validierung, Dataset-Freeze-Checks.
Woche 4: Pilotlaeufe, Guardrails/Stichprobenstabilitaet, Fixes bei Messproblemen.
Woche 5-6: Haupt-Datenerhebung (warm-Regime) inkl. Artefakt- und Validitaetsgates.
Woche 7: Zusatzdiagnostik und Konsistenzpruefungen der Analyseartefakte.
Woche 8-9: Statistische Auswertung, Tabellen/Figuren, Diskussion (shared valid points, Frontier/Knee, Grenzen).
Woche 10: Schreiben, Revision, Reproduzierbarkeits-Check (Artefaktvollstaendigkeit).

## 12. Vorlaeufige Gliederung
Abstract
Zusammenfassung
Liste von Abkürzungen
Liste von Tabellen
1. # Einleitung
  - Motivation und Problem Statement
  - Wissenschaftlicher Ansatz
  - Umfang und Abgrenzung des Themas
  - Struktur der Thesis
2. # Grundlagen
  - ## Künstliche Intelligenz
    - Begriff und Zielsetzung
    - Wissensrepräsentation und Ansätze
    - Maschinelles Lernen und generative KI
    - Datenverarbeitung und Information Retrieval
    - Informationsgenerierung und Retrieval in KI-Systemen
    - Retrieval-Augmented Generation als methodischer Ansatz
    - Einordnung von RAG in moderne KI-Systeme
  - ## KI-Agenten
    - Begriff und Einordnung
    - Grundlegende Eigenschaften 
    - Tool-Nutzung als Erweiterung agentischer Fähigkeiten
    - APIs, Datenbanken und Suchsysteme als externe Ressourcen
    - RAG als Werkzeug für Wissensintegration
    - Konzeptionelle Zusammenhänge
    - Anwendungsfelder
    - Relevanz für moderne Informationsverarbeitende Systeme
  - ## Retrieval Augmented Generation
    - Begriff und Einordnung in die Künstliche Intelligenz
    - Kombination von Retrieval und Generierung
    - Zentrale Komponenten eines RAG-Ansatzes
    - Wissensintegraiton, Aktualität und Reduktion von Halluzinationen
    - Einsatzszenarien und Anwendungskontext
    - Herausforderung und Grenzen
    - Einordnung und Bedeutung für wissensbasierte KI-Systeme
  - ## Low-Code Plattformen
    - Begriffsbestimmung und Abgrenzung
    - Grundkonzepte: visuelle Modellierung, Workflows und Integration 
    - Einordnung in moderne Softwareentwicklung und digitale Transformation 
    - n8n als Workflow-Automationsplattform
    - Architektur- und Funktionsprinzipien
    - Anwendungsfelder und KI-Integration
    - Chancen, Grenzen und Herausforderungen
    - Relevanz für moderne informationsverarbeitende Systeme
  - ## Benchmarking
    - Begriff und Einordnung
    - Zielsetzung von End-to-End-Tests
    - Konzeptioneller Aufbau eines Benchmarking-Systems
    - Zentrale Leistungsmetriken
    - Trade-offs zwischen Latenz, Durchsatz und Fehlerrate
    - Vergleichbarkeit, Reproduzierbarkeit und Valididät
    - Einordnung der Relevanz
3. Systemdesign und Implementierung
  - Testserver
  - n8n
  - rag_service
  - Geteilte Komponenten
4. Benchmark-Methodik (Workload, Kontrollen, Metriken, Prereg-Regeln)
  - Metriken
  - Prereg-Regeln
  - Benchmark-Scripts
  - Analyse-Scripts
5. Ergebnisse (shared valid points, Latenz/Durchsatz/Fehler, Frontier/Knee)
6. Diskussion (Interpretation, Limitationen, Implikationen)
7. Fazit und Ausblick

## 13. Startliteratur (Initiale Auswahl)
- Lewis et al. (2020): Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks. NeurIPS. arXiv:2005.11401
- Karpukhin et al. (2020): Dense Passage Retrieval for Open-Domain Question Answering. arXiv:2004.04906
- Es et al. (2024): RAGAs: Automated Evaluation of Retrieval Augmented Generation. EACL Demos. DOI: 10.18653/v1/2024.eacl-demo.16
- Ajimati et al. (2025): Adoption of low-code and no-code development: A systematic literature review and future research agenda. Journal of Systems and Software. DOI: 10.1016/j.jss.2024.112300
- Dean & Barroso (2013): The Tail at Scale. Communications of the ACM. DOI: 10.1145/2408776.2408794
- van der Aalst et al. (2003): Workflow Patterns. Distributed and Parallel Databases. DOI: 10.1023/A:1022883727209

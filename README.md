# RAG-System-Benchmark

Ein wissenschaftliches Benchmarking-Projekt, das zwei RAG-Implementierungen (Retrieval-Augmented Generation) unter konstanter Ankunftsrate vergleicht: einen **Low-Code-n8n-Workflow** gegenüber einem **Code-First-Python-FastAPI-Service**. Das Projekt bildet die empirische Grundlage einer Bachelorarbeit an der HdM Stuttgart.

---

## Bachelorarbeit

**Titel:** _Vergleich von Low-Code- und Code-First-Ansätzen für RAG-Systeme in einem End-To-End Benchmark_
**Sprache:** Deutsch

**Zentrale Forschungsfrage:**

> _Welcher der beiden Ansätze eignet sich besser für den dauerhaften Einsatz eines RAG-Systems unter Last, wenn gleichzeitig ein skalierbarer und stabiler Systembetrieb gewährleistet sein muss?_

**Teilfragen:**

- **FQ1:** Wie unterscheiden sich n8n und Python-RAG in Leistung und Skalierbarkeit?
- **FQ2:** Wo liegen die Skalierbarkeitsgrenzen der jeweiligen Systeme?
- **FQ3:** Unter welchen Bedingungen ist welche Architektur vorzuziehen?

**Wichtigste Ergebnisse:**

| Befund                     | Details                                                                                            |
| -------------------------- | -------------------------------------------------------------------------------------------------- |
| Gültiger Vergleichsbereich | 10–20 RPM (RAG verletzt Prompt-Mix-Validität ab 30+ RPM)                                           |
| RAG p95-Latenz bei 10 RPM  | 37–42 s                                                                                            |
| n8n p95-Latenz bei 10 RPM  | 52,5 s (einzelner Datenpunkt; alle höheren Lasten mit 100 % Timeout)                               |
| n8n Prompt-Mix-Disziplin   | Gültig bis 40 RPM über Redis-Queue; Ausführungen laufen in Timeout, sind aber gleichmäßig verteilt |
| Entscheidung               | `trade_off_not_single_winner` — kein System dominiert; Wahl ist last- und kontextabhängig          |

**Praktische Empfehlung:**

- **< 20 RPM, latenzkritisch** → Python-RAG
- **> 20 RPM oder Workflow-Integration erforderlich** → n8n
- **Hybrid** → Ingest/Admin über n8n, Anfragen über Python-RAG

---

## Architektur

### Überblick

```
k6 Load Generator (constant-arrival-rate)
        ↓
  ┌─────────────┐     ┌─────────────────────┐
  │  n8n Workflow│     │ Python FastAPI RAG   │
  │  (webhook → │     │ (sync /query via     │
  │  AI agent →  │     │  ProcessPoolExecutor)│
  │  PGVector)   │     │                     │
  └──────┬───────┘     └──────────┬──────────┘
         └──────────┬─────────────┘
                    ↓
        PostgreSQL + pgVector (shared)
        Redis (queue broker, shared)
                    ↓
        k6 JSON output (measure-window metrics)
                    ↓
        analyze_sweep.py → sweep_analysis package
                    ↓
        compare_isolated_batches.py → parent comparison
                    ↓
        prereg_decision.py → preregistration decision
```

### System Under Test: Python-RAG-Service (`rag_service/`)

FastAPI-Anwendung mit RQ-Background-Workern:

| Komponente      | Datei                       | Beschreibung                                                       |
| --------------- | --------------------------- | ------------------------------------------------------------------ |
| Einstiegspunkt  | `app.py`                    | `/query`, `/ingest`, `/delete`, `/health`, `/metrics`              |
| Query-Flow      | `query.py`                  | Zweistufig: strukturierte Analyse → optionaler Abruf → LLM-Antwort |
| LLM-Integration | `llm.py`                    | OpenAI-Client mit Circuit Breaker und Caching                      |
| Vektorsuche     | `vector_store.py`           | pgVector-Ähnlichkeitssuche                                         |
| Ingestion       | `ingest.py`                 | Dokument-Chunking und Embedding-Erstellung                         |
| Cache           | `cache.py` / `llm_cache.py` | TTL- und größenbegrenzter LLM-Response-Cache                       |
| Worker          | `workers/`                  | RQ-Background-Worker für Ingest- und Query-Jobs                    |

Endpunkt-Verträge und vollständige Umgebungsvariablen-Referenz: [`rag_service/README.md`](rag_service/README.md)

### System Under Test: n8n-Workflow

- **Image:** `n8nio/n8n:1.123.18` im Queue-Modus mit 5 Worker-Replikas
- **Flow:** Webhook-Trigger → AI-Agent-Node → PGVector-Abruf → Antwort
- **Queue-Disziplin:** Redis-basierte Job-Queue; Anfragen werden auch bei hoher Last gleichmäßig angenommen und verteilt (Prompt-Mix bleibt erhalten), Ausführungslatenz überschreitet jedoch ab ~20 RPM den 120-s-Timeout

### Gemeinsame Infrastruktur

| Komponente            | Image                                | Zweck                                            |
| --------------------- | ------------------------------------ | ------------------------------------------------ |
| PostgreSQL + pgVector | `supabase/postgres:15.8.1.085`       | Vektorspeicher und Metadaten                     |
| Redis                 | `redis:7-alpine`                     | n8n-Queue + RAG-RQ-Worker                        |
| Open WebUI            | `ghcr.io/open-webui/open-webui:main` | Chat-Oberfläche (Port 3001)                      |
| Supabase Studio       | `supabase/studio:2025.10.27`         | Datenbank-Dashboard (Port 3002)                  |
| Portainer             | `portainer/portainer-ce:alpine`      | Container-Verwaltung (Port 9000)                 |
| Traefik (optional)    | `traefik:v3.6.2`                     | Lokales HTTPS über `docker-compose.override.yml` |

**Testhardware:** AMD Ryzen 5 4500U, ~7,5 GB RAM, Debian 13 — Single-Machine-All-in-One-Docker-Compose-Deployment.

**Paritätskontrollen (beide Systeme identisch):**

- Embedding-Modell: `text-embedding-3-small`
- Chat-Modell: `gpt-5-nano` (feste Temperatur, Top-p, Token-Limit)
- Retrieval: topK=16 (n8n) / 15 effektive Kontexte (RAG)
- Reranking: deaktiviert
- Timeout: 120 s pro Anfrage

---

## Schnellstart

### Voraussetzungen

- Docker + Docker Compose mit `COMPOSE_COMPATIBILITY=1` (in `.env` gesetzt)
- k6 (Lasttesttool) im PATH verfügbar
- Python 3.10+ (für Analyse-Skripte)
- Befüllte `.env`-Datei (aus Vorlage kopieren und ausfüllen; siehe [Konfiguration](#konfiguration))

### Stack starten

```bash
# Alle Services starten (n8n, Supabase, Redis, RAG-Service, Open WebUI, Portainer)
docker compose up -d --build

# Stoppen ohne Volumes zu entfernen
docker compose stop

# Vollständiges Teardown inkl. Volumes
docker compose down -v
```

Die Services starten in Abhängigkeitsreihenfolge; `db-init` stellt sicher, dass die `n8n_data`-Datenbank vor dem Start von n8n existiert.

---

## Benchmark ausführen

### 1. Boundary-Audit (vor dem vollständigen Lauf erforderlich)

Validiert Modell-Constraints, Workflow-Konfiguration und Sampling-Integrität. Erzeugt `boundary_audit_report.json`.

```bash
./bench/run_boundary_audit.sh
```

Berichtspfad exportieren:

```bash
export BENCH_BOUNDARY_AUDIT_REPORT_PATH=/absolute/path/to/boundary_audit_report.json
```

### 2. Vollständiger Paarvergleich — Kanonischer Thesis-Lauf

Führt isolierte Child-Batches für beide Endpunkte mit wechselnder Reihenfolge über 3 gepaarte Wiederholungen aus. Dies ist der primäre Benchmark der Thesis.

```bash
# Kanonisches Thesis-Profil laden
set -a; source bench/profiles/thesis_compare.env; set +a

# Paarvergleich ausführen (wechselt rag/n8n-Reihenfolge über Wiederholungen)
./bench/run_compare_pair.sh
```

**Parameter (aus `bench/profiles/thesis_compare.env`):**

| Parameter                           | Wert                            |
| ----------------------------------- | ------------------------------- |
| RPM-Sweep                           | 10, 20, 30, …, 100              |
| Settle-Fenster                      | 180 s                           |
| Measure-Fenster                     | 720 s                           |
| Gepaarte Wiederholungen             | 3                               |
| Paar-Reihenfolge                    | Alternierend (rag, n8n, rag, …) |
| Validitätsgate — Timeout            | ≤ 1 % pro Rep pro Punkt         |
| Validitätsgate — Prompt-Mix         | Max. Δ1 Versuch pro Prompt      |
| Validitätsgate — Dropped Iterations | 0                               |

Ergebnisse werden in `bench/results/compare_<timestamp>/` gespeichert.

### 3. Einzelendpunkt-Smoke-Test

Schnelle Validierung eines einzelnen Endpunkts vor dem vollständigen Lauf:

```bash
# RAG-Smoke-Test bei 20 RPM
BENCH_REQUIRE_BOUNDARY_AUDIT=0 \
BENCH_SWEEP_SMOKE_RPM_LIST=20 \
BENCH_TARGET_ENDPOINT=rag \
BENCH_SWEEP_STOP_AFTER_SMOKE=1 \
./bench/run_all.sh

# n8n-Smoke-Test bei 20 RPM
BENCH_REQUIRE_BOUNDARY_AUDIT=0 \
BENCH_SWEEP_SMOKE_RPM_LIST=20 \
BENCH_TARGET_ENDPOINT=n8n \
BENCH_SWEEP_STOP_AFTER_SMOKE=1 \
./bench/run_all.sh
```

---

## Analyse-Pipeline

### Sweep-Analyse (Einzellauf)

Verarbeitet ein einzelnes Child-Batch-Ergebnisverzeichnis zu CSV, Knee-Report, Prompt-Mix-Report und Frontier-Plots:

```bash
python bench/helpers/analysis/analyze_sweep.py <results_dir>
```

Ausgaben (in `<results_dir>/analysis/`):

- `sweep_points.csv` — rohe Metriken pro Wiederholung
- `sweep_points_agg.csv` — aggregiert nach RPM (Median, p95)
- `knee_report.json` / `.md` — Sättigungsgrenz-Analyse
- `prompt_mix_report.md` — Überprüfung der Prompt-Verteilung
- `invalid_points.csv` — Einträge, die Validitätsgates nicht bestanden haben
- `frontier_*.png` — Performance-Frontier-Plots

### Paarvergleich

Erstellt die übergeordneten Vergleichsartefakte aus zwei isolierten Child-Batches:

```bash
python bench/helpers/analysis/compare_isolated_batches.py <rag_dir> <n8n_dir> --out <output_dir>
```

Ausgaben: `pair_comparison.csv`, `pair_comparison.md`, `prereg_decision.json`.

Das Skript `prereg_decision.py` wertet die Präregistrierungs-Gewinnerregel aus:

- Voraussetzung: keine schlechtere Validitätsabdeckung + Gewinne bei timeout_rate + Gewinne bei error_rate + Gewinne bei Durchsatz/Latenz + nicht schlechterer nachhaltiger Durchsatz
- Andernfalls: `trade_off_not_single_winner`

Vollständige Entscheidungsspezifikation: [`bench/preregistration.json`](bench/preregistration.json)

---

## Repository-Struktur

```
RAG-System-Benchmark/
├── bench/                         # Benchmark-Harness
│   ├── run_compare_pair.sh        # Paarvergleich (primärer Einstiegspunkt)
│   ├── run_all.sh                 # Einzelendpunkt-Child-Batch-Runner
│   ├── run_boundary_audit.sh      # Vorab-Boundary-Audit
│   ├── preregistration.json       # Entscheidungsspez. (Metriken, Gates, Gewinnerregel)
│   ├── profiles/
│   │   └── thesis_compare.env     # Kanonisches Thesis-Benchmark-Profil
│   ├── k6/
│   │   ├── rag.js                 # k6-Lasttest für RAG-Endpunkt
│   │   └── n8n.js                 # k6-Lasttest für n8n-Endpunkt
│   ├── lib/                       # Bash-Bibliotheksmodule
│   ├── helpers/
│   │   ├── analysis/              # Python-Analyse-Pipeline
│   │   │   ├── analyze_sweep.py   # Sweep-Analyse-CLI
│   │   │   ├── compare_isolated_batches.py  # Paarvergleich
│   │   │   ├── prereg_decision.py # Präregistrierungs-Auswertung
│   │   │   └── sweep_analysis/    # Kern-Analysepaket
│   │   ├── audit/                 # Boundary-Audit-Hilfsprogramme
│   │   └── artifacts/             # Manifest, Fingerprints, Validierung
│   ├── prompts.json               # 10 Holdout-Evaluierungsprompts
│   ├── results/                   # Benchmark-Ausgaben (gitignored)
│   └── docs/                      # Protokoll-, Metriken- und Checklisten-Docs
│
├── rag_service/                   # Python-FastAPI-RAG-Service
│   ├── app.py
│   ├── query.py
│   ├── llm.py
│   ├── vector_store.py
│   ├── workers/
│   ├── Dockerfile
│   └── README.md
│
├── docs/                          # Weitere Dokumentation
│   ├── thesis/                    # Thesis-Projektdokumentation
│   └── engineering/               # Stack- / Toolchain-Dokumentation
│
├── n8n/                           # n8n-Workflow-Exporte und gemeinsame Dateien
├── supabase/                      # Supabase-Init-Skripte
├── openai_proxy/                  # OpenAI-Proxy-Service für Audit-Modus
├── docker-compose.yml             # Haupt-Stack
├── docker-compose.override.yml    # Optionaler Traefik-HTTPS-Overlay
├── docker-compose.bench.yml       # Benchmark-spezifische Compose-Konfiguration
├── docker-compose.audit.yml       # Audit-Modus-Compose-Konfiguration
└── .env                           # Secrets und Service-Konfiguration
```

---

## Konfiguration

### Wichtige Umgebungsvariablen (`.env`)

| Variable                              | Beschreibung                                        |
| ------------------------------------- | --------------------------------------------------- |
| `OPENAI_API_KEY`                      | OpenAI-API-Schlüssel                                |
| `OPENAI_BASE_URL`                     | OpenAI-kompatibler Base-URL                         |
| `CHAT_MODEL`                          | Chat-Modell (Thesis: `gpt-5-nano`)                  |
| `EMBEDDING_MODEL`                     | Embedding-Modell (Thesis: `text-embedding-3-small`) |
| `LLM_TEMPERATURE` / `LLM_TOP_P`       | Für Thesis-Läufe fest auf `1` gesetzt               |
| `LLM_MAX_COMPLETION_TOKENS`           | Fest auf `32768` gesetzt                            |
| `RETRIEVE_TOP_K`                      | Retrieval-Tiefe (Thesis: `16`)                      |
| `API_TOKEN`                           | Authentifizierungstoken für den RAG-Service         |
| `REDIS_URL`                           | Redis-Verbindungsstring                             |
| `POSTGRES_PASSWORD` / `POSTGRES_HOST` | Datenbank-Zugangsdaten                              |
| `N8N_ENCRYPTION_KEY`                  | n8n-Credential-Verschlüsselung                      |

### Wichtige Benchmark-Variablen

Über `bench/profiles/thesis_compare.env` oder als Shell-Exports gesetzt:

| Variable                           | Beschreibung                     |
| ---------------------------------- | -------------------------------- |
| `BENCH_TARGET_ENDPOINT`            | `rag` oder `n8n`                 |
| `BENCH_SWEEP_RPM_LIST`             | Kommagetrennte RPM-Werte         |
| `BENCH_SETTLE_SECONDS`             | Dauer des Settle-Fensters        |
| `BENCH_MEASURE_SECONDS`            | Dauer des Measure-Fensters       |
| `BENCH_REPS`                       | Wiederholungen pro Endpunkt      |
| `BENCH_REQUIRE_BOUNDARY_AUDIT`     | `1` = Vorab-Audit erzwingen      |
| `BENCH_BOUNDARY_AUDIT_REPORT_PATH` | Absoluter Pfad zum Audit-Bericht |

---

## Infrastrukturdetails

Der Docker-Compose-Stack betreibt 13+ Services auf einem einzelnen Host. Die vollständige dienstweise Dokumentation befindet sich in der [Infrastruktur-README](docs/engineering/README.md).

### Portübersicht

| Service          | Port     | Beschreibung             |
| ---------------- | -------- | ------------------------ |
| n8n              | 5678     | Workflow-UI              |
| Open WebUI       | 3001     | Chat-UI                  |
| RAG Pipeline     | 8080     | Interne API              |
| Supabase Storage | 5000     | Storage-API              |
| Supabase Studio  | 3002     | DB-Dashboard             |
| Portainer        | 9000     | Container-UI             |
| Traefik          | 80 / 443 | Lokales HTTPS (optional) |

### Persistente Volumes

| Volume             | Zweck                           |
| ------------------ | ------------------------------- |
| `n8n_storage`      | Workflow-Daten und Zugangsdaten |
| `supabase_data`    | PostgreSQL                      |
| `supabase_storage` | Objektspeicher                  |
| `open-webui`       | Chat-Interface-Daten            |
| `db-config`        | Datenbankkonfiguration          |
| `portainer_data`   | Portainer-Zustand               |

---

## Weiterführende Dokumentation

| Dokument                           | Pfad                                                       |
| ---------------------------------- | ---------------------------------------------------------- |
| Benchmark-Harness-Überblick        | [`bench/README.md`](bench/README.md)                       |
| Protokoll, Metriken, Checkliste    | [`bench/docs/`](bench/docs/)                               |
| RAG-Service-Endpunkte und Umgebung | [`rag_service/README.md`](rag_service/README.md)           |
| Engineering- / Stack-Überblick     | [`docs/engineering/README.md`](docs/engineering/README.md) |
| Thesis-Projektdokumentation        | [`docs/thesis/README.md`](docs/thesis/README.md)           |
| Präregistrierungsspezifikation     | [`bench/preregistration.json`](bench/preregistration.json) |

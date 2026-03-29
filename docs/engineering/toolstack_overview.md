# Toolstack Overview - n8n + Supabase + PGVector + RAG + Open WebUI

## Overview

This stack provides a self-contained AI automation and data platform that connects workflow orchestration, semantic retrieval, and chat interaction in one environment.

It integrates:

- n8n for process automation and orchestration
- Supabase as the data and authentication layer (Postgres + Auth + Storage)
- PGVector for vector search and semantic retrieval
- Redis for queue-based job handling
- RAG Pipeline (FastAPI + RQ) for ingestion, search, and chat responses
- Open WebUI as a human-friendly interface for AI interaction
- Portainer for container management
- Traefik for internal Supabase storage proxying (kept in the override)

Together, they form a modular ecosystem where data, automation, and reasoning can operate seamlessly - locally or in the cloud.

---

## Concept

The stack is designed around three core ideas:

1. Automation - n8n manages workflows that connect APIs, databases, and AI models.
2. Retrieval - PGVector plus the RAG pipeline enable semantic search and knowledge retrieval.
3. Interaction - Open WebUI provides a conversational layer where users can directly engage with data and workflows.

All services communicate over a shared network and use persistent storage, making the system reproducible, extendable, and secure.

---

## Main Components

### n8n - Automation Engine

Handles workflow logic, event triggers, and API integrations.
Runs in queue mode through Redis for scalable and asynchronous execution.

### Supabase - Backend Platform

Offers PostgreSQL storage, authentication, and file management.
Acts as the central database and identity hub for the entire stack.

### Supabase/PGVector - Vector Database

Stores embeddings for semantic search, retrieval-augmented generation (RAG), and AI context memory.
Used by the RAG pipeline and n8n workflows for contextual data.

### Redis - Queue Broker

Manages distributed jobs and ensures reliable execution across multiple workers.

### RAG Pipeline - Retrieval Service

FastAPI + RQ service aligned with the n8n agentic RAG flow. It ingests files or raw text, stores embeddings in PGVector, and serves synchronous `/query` responses using a structured decision step (LLM) plus retrieval and answer generation. Chat memory parity is implemented via Postgres.

### Open WebUI - AI Interaction Interface

A web-based UI for interacting with local or external AI models. It connects to the RAG pipeline using the custom pipe in `openwebui_rag_pipe.py`.

### Portainer - Container Management

Provides a lightweight UI for managing local Docker services.

### Traefik - Internal HTTP Proxy

Optional internal HTTP proxy used by Supabase Studio/storage flows (configured in `docker-compose.override.yml`). n8n and Studio are accessed directly via the server IP and published ports.

---

## Data and Communication Flow

1. User Interaction:
   A request or question is sent via Open WebUI.

2. Retrieval and Generation:
   Open WebUI calls the RAG pipeline `/query` endpoint, which pulls context from PGVector and returns a response.

3. Automation Trigger:
   n8n workflows can ingest data, call the RAG pipeline, or enrich Supabase records.

4. Computation and Storage:
   Supabase manages relational data, while PGVector stores embeddings. Redis supports background jobs.

---

## Key Features

- Fully containerized and isolated architecture
- Authentication, storage, and Postgres via Supabase
- Local vector search and semantic indexing with PGVector
- Asynchronous automation through Redis queue mode
- FastAPI RAG pipeline with queued ingest and synchronous query
- Chat-driven interface via Open WebUI with a custom pipe
- Optional internal Studio/storage proxying via Traefik

---

## Intent

The goal of this composition is to create a foundational AI infrastructure that unifies automation, data management, and interaction in a single stack.

It is suitable for:

- AI agent backends
- RAG-based knowledge systems
- Research automation environments
- Edge or local AI deployments

Each component remains independent but interoperable, enabling flexible scaling and customization.

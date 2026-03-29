import argparse
import json
import os
import platform
import hashlib
from datetime import datetime, timezone
from typing import Any


def read_file(path: str):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def sha256_file(path: str) -> str | None:
    if not os.path.exists(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: str):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def read_json_field(path: str, field: str):
    data = read_json(path)
    if not isinstance(data, dict):
        return None
    return data.get(field)


def read_json_path(path: str, keys: list[str]):
    obj = read_json(path)
    current: Any = obj
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def explicit_or_env(explicit: str | None, env_name: str) -> str | None:
    if explicit is not None and explicit != "":
        return explicit
    return os.getenv(env_name)


def host_info() -> dict[str, Any]:
    info: dict[str, Any] = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "hostname": platform.node(),
    }

    os_release = read_file("/etc/os-release")
    if os_release:
        for line in os_release.splitlines():
            if line.startswith("PRETTY_NAME="):
                info["os"] = line.split("=", 1)[1].strip().strip('"')
                break

    cpuinfo = read_file("/proc/cpuinfo")
    if cpuinfo:
        for line in cpuinfo.splitlines():
            if line.lower().startswith("model name"):
                info["cpu_model"] = line.split(":", 1)[1].strip()
                break

    meminfo = read_file("/proc/meminfo")
    if meminfo:
        for line in meminfo.splitlines():
            if line.startswith("MemTotal"):
                info["memory_total_kb"] = int(line.split()[1])
                break

    return info


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", required=True)
    parser.add_argument("--images", required=False)
    parser.add_argument("--prereg", required=False)
    parser.add_argument("--batch-kind", required=False)
    parser.add_argument("--target-endpoint", required=False)
    parser.add_argument("--parent-compare-id", required=False)
    parser.add_argument("--child-batch-id", required=False)
    parser.add_argument("--pair-plan", required=False)
    parser.add_argument("--pair-validation", required=False)
    parser.add_argument("--pair-comparison", required=False)
    parser.add_argument("--prompts-path", required=False)
    parser.add_argument("--smoke-rpm-list", required=False)
    parser.add_argument("--smoke-settle-seconds", required=False)
    parser.add_argument("--smoke-measure-seconds", required=False)
    parser.add_argument("--smoke-reps", required=False)
    parser.add_argument("--primary-rpm-start", required=False)
    parser.add_argument("--primary-rpm-end", required=False)
    parser.add_argument("--primary-rpm-step", required=False)
    parser.add_argument("--primary-settle-seconds", required=False)
    parser.add_argument("--primary-measure-seconds", required=False)
    parser.add_argument("--primary-reps", required=False)
    parser.add_argument("--stop-after-smoke", required=False)
    parser.add_argument("--timeout-rate-max", required=False)
    parser.add_argument("--child-manifest", action="append", default=None)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    runs = []
    if os.path.exists(args.runs):
        with open(args.runs, "r", encoding="utf-8") as handle:
            content = handle.read().strip()
            if content.startswith("["):
                runs = json.loads(content)
            elif content:
                runs = [json.loads(line) for line in content.splitlines() if line.strip()]

    images = None
    if args.images and os.path.exists(args.images):
        with open(args.images, "r", encoding="utf-8") as handle:
            try:
                images = json.load(handle)
            except json.JSONDecodeError:
                images = handle.read()

    out_dir = os.path.dirname(os.path.abspath(args.output))

    db_fp_pre = read_json(os.path.join(out_dir, "db_fingerprint_pre.json"))
    db_fp_post = read_json(os.path.join(out_dir, "db_fingerprint_post.json"))
    prereg_path = args.prereg
    preregistration = None
    if prereg_path:
        preregistration = {
            "path": prereg_path,
            "id": read_json_field(prereg_path, "id"),
            "schema_version": read_json_field(prereg_path, "schema_version"),
            "sha256": sha256_file(prereg_path),
        }

    pair_children = []
    for child_manifest in args.child_manifest or []:
        pair_children.append(
            {
                "path": child_manifest,
                "sha256": sha256_file(child_manifest),
            }
        )

    artifacts = {
        "source_fingerprint": {
            "path": "source_fingerprint.json",
            "sha256": sha256_file(os.path.join(out_dir, "source_fingerprint.json")),
            "fingerprint_sha256": read_json_field(os.path.join(out_dir, "source_fingerprint.json"), "fingerprint_sha256"),
        },
        "db_fingerprint_pre": {
            "path": "db_fingerprint_pre.json",
            "fingerprint_sha256": (db_fp_pre or {}).get("fingerprint_sha256"),
        },
        "db_fingerprint_post": {
            "path": "db_fingerprint_post.json",
            "fingerprint_sha256": (db_fp_post or {}).get("fingerprint_sha256"),
        },
        "compose_ps": {
            "path": "compose_ps.json",
            "sha256": sha256_file(os.path.join(out_dir, "compose_ps.json")),
        },
        "pip_freeze_rag_pipeline": {
            "path": "pip_freeze_rag-pipeline.txt",
            "sha256": sha256_file(os.path.join(out_dir, "pip_freeze_rag-pipeline.txt")),
        },
        "rag_runtime_env": {
            "path": "rag_runtime_env.txt",
            "sha256": sha256_file(os.path.join(out_dir, "rag_runtime_env.txt")),
        },
        "n8n_workflow_chatbot_sha256": {
            "path": "n8n_workflow_chatbot_sha256.txt",
            "sha256": sha256_file(os.path.join(out_dir, "n8n_workflow_chatbot_sha256.txt")),
        },
        "n8n_workflow_runtime_snapshot": {
            "path": "n8n_workflow_runtime_snapshot.json",
            "sha256": sha256_file(os.path.join(out_dir, "n8n_workflow_runtime_snapshot.json")),
            "workflow_content_sha256": read_json_field(
                os.path.join(out_dir, "n8n_workflow_runtime_snapshot.json"),
                "workflow_content_sha256",
            ),
        },
        "boundary_audit_report": {
            "path": "boundary_audit_report.json",
            "sha256": sha256_file(os.path.join(out_dir, "boundary_audit_report.json")),
            "pass": read_json_field(os.path.join(out_dir, "boundary_audit_report.json"), "pass"),
            "token_ratio_n8n_over_rag": read_json_path(
                os.path.join(out_dir, "boundary_audit_report.json"),
                ["workload_parity", "tokens_per_request_total", "n8n_over_rag_ratio"],
            ),
        },
        "thesis_batch_validation": {
            "path": "thesis_batch_validation.json",
            "sha256": sha256_file(os.path.join(out_dir, "thesis_batch_validation.json")),
            "pass": read_json_field(os.path.join(out_dir, "thesis_batch_validation.json"), "pass"),
        },
    }

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "batch_kind": args.batch_kind,
        "target_endpoint": args.target_endpoint or os.getenv("BENCH_TARGET_ENDPOINT"),
        "parent_compare_id": args.parent_compare_id or os.getenv("BENCH_PARENT_COMPARE_ID"),
        "child_batch_id": args.child_batch_id or os.getenv("BENCH_CHILD_BATCH_ID"),
        "bench_env": {
            "BENCH_MODE": os.getenv("BENCH_MODE"),
            "TIMING_LOG_DIR": os.getenv("TIMING_LOG_DIR"),
            "N8N_EXECUTIONS_DATA_SAVE_ON_SUCCESS": os.getenv("N8N_EXECUTIONS_DATA_SAVE_ON_SUCCESS"),
            "BENCH_CACHE_REGIME": os.getenv("BENCH_CACHE_REGIME"),
            "BENCH_COLD_RESET_WAIT": os.getenv("BENCH_COLD_RESET_WAIT"),
            "BENCH_COLD_RESET_N8N_WORKERS": os.getenv("BENCH_COLD_RESET_N8N_WORKERS"),
            "BENCH_STRICT": os.getenv("BENCH_STRICT"),
            "BENCH_PROMPTS_PATH": explicit_or_env(args.prompts_path, "BENCH_PROMPTS_PATH"),
            "PROMPT_BASE_SEED": os.getenv("PROMPT_BASE_SEED"),
            "BENCH_MINIMAL_STACK": os.getenv("BENCH_MINIMAL_STACK"),
            "BENCH_N8N_WORKERS": os.getenv("BENCH_N8N_WORKERS"),

            "BENCH_ARRIVAL_DURATION": os.getenv("BENCH_ARRIVAL_DURATION"),
            "BENCH_ARRIVAL_TIME_UNIT": os.getenv("BENCH_ARRIVAL_TIME_UNIT"),
            "BENCH_ARRIVAL_PREALLOCATED_VUS": os.getenv("BENCH_ARRIVAL_PREALLOCATED_VUS"),
            "BENCH_ARRIVAL_MAX_VUS": os.getenv("BENCH_ARRIVAL_MAX_VUS"),

            "BENCH_SWEEP_SMOKE_RPM_LIST": explicit_or_env(args.smoke_rpm_list, "BENCH_SWEEP_SMOKE_RPM_LIST"),
            "BENCH_SWEEP_SMOKE_SETTLE_SECONDS": explicit_or_env(args.smoke_settle_seconds, "BENCH_SWEEP_SMOKE_SETTLE_SECONDS"),
            "BENCH_SWEEP_SMOKE_MEASURE_SECONDS": explicit_or_env(args.smoke_measure_seconds, "BENCH_SWEEP_SMOKE_MEASURE_SECONDS"),
            "BENCH_SWEEP_SMOKE_REPS": explicit_or_env(args.smoke_reps, "BENCH_SWEEP_SMOKE_REPS"),
            "BENCH_SWEEP_PRIMARY_RPM_START": explicit_or_env(args.primary_rpm_start, "BENCH_SWEEP_PRIMARY_RPM_START"),
            "BENCH_SWEEP_PRIMARY_RPM_END": explicit_or_env(args.primary_rpm_end, "BENCH_SWEEP_PRIMARY_RPM_END"),
            "BENCH_SWEEP_PRIMARY_RPM_STEP": explicit_or_env(args.primary_rpm_step, "BENCH_SWEEP_PRIMARY_RPM_STEP"),
            "BENCH_SWEEP_PRIMARY_SETTLE_SECONDS": explicit_or_env(args.primary_settle_seconds, "BENCH_SWEEP_PRIMARY_SETTLE_SECONDS"),
            "BENCH_SWEEP_PRIMARY_MEASURE_SECONDS": explicit_or_env(args.primary_measure_seconds, "BENCH_SWEEP_PRIMARY_MEASURE_SECONDS"),
            "BENCH_SWEEP_PRIMARY_REPS": explicit_or_env(args.primary_reps, "BENCH_SWEEP_PRIMARY_REPS"),
            "BENCH_SWEEP_STOP_AFTER_SMOKE": explicit_or_env(args.stop_after_smoke, "BENCH_SWEEP_STOP_AFTER_SMOKE"),
            "BENCH_SWEEP_TIMEOUT_RATE_MAX": explicit_or_env(args.timeout_rate_max, "BENCH_SWEEP_TIMEOUT_RATE_MAX"),
            "BENCH_SWEEP_REQUIRE_PROMPT_TAGS": os.getenv("BENCH_SWEEP_REQUIRE_PROMPT_TAGS"),

            "BENCH_PREREG_EVAL": os.getenv("BENCH_PREREG_EVAL"),
            "BENCH_PREREG_ENFORCE": os.getenv("BENCH_PREREG_ENFORCE"),
            "K6_HTTP_TIMEOUT": os.getenv("K6_HTTP_TIMEOUT"),
            "K6_REQUIRE_CITATIONS": os.getenv("K6_REQUIRE_CITATIONS"),
            "BENCH_REQUIRE_BOUNDARY_AUDIT": os.getenv("BENCH_REQUIRE_BOUNDARY_AUDIT"),
            "BENCH_VALIDATE_BATCH_STRICT": os.getenv("BENCH_VALIDATE_BATCH_STRICT"),
            "BENCH_TARGET_ENDPOINT": os.getenv("BENCH_TARGET_ENDPOINT"),
            "BENCH_PARENT_COMPARE_ID": os.getenv("BENCH_PARENT_COMPARE_ID"),
            "BENCH_CHILD_BATCH_ID": os.getenv("BENCH_CHILD_BATCH_ID"),
            "BENCH_PAIR_REP": os.getenv("BENCH_PAIR_REP"),
            "BENCH_PAIR_ORDER": os.getenv("BENCH_PAIR_ORDER"),
            "BENCH_PAIR_PROMPT_SEED": os.getenv("BENCH_PAIR_PROMPT_SEED"),
            "BENCH_PAIR_REPS": os.getenv("BENCH_PAIR_REPS"),
            "BENCH_PAIR_ORDER_MODE": os.getenv("BENCH_PAIR_ORDER_MODE"),
            "BENCH_RESULTS_RELATIVE_DIR": os.getenv("BENCH_RESULTS_RELATIVE_DIR"),

            # Target endpoints (non-secret)
            "N8N_WEBHOOK_URL": os.getenv("N8N_WEBHOOK_URL"),
            "RAG_ENDPOINT_URL": os.getenv("RAG_ENDPOINT_URL"),
            "RAG_WORKER_COUNT": os.getenv("RAG_WORKER_COUNT"),
            "RAG_API_WORKERS": os.getenv("RAG_API_WORKERS"),
            "RAG_TIMINGS_ON_ERROR_ONLY": os.getenv("RAG_TIMINGS_ON_ERROR_ONLY"),
            "LOG_OPENAI_USAGE": os.getenv("LOG_OPENAI_USAGE"),
            "OTEL_TRACES_EXPORTER": os.getenv("OTEL_TRACES_EXPORTER"),
            "OTEL_EXPORTER_OTLP_ENDPOINT": os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"),
            "OTEL_TRACES_SAMPLER": os.getenv("OTEL_TRACES_SAMPLER"),
            "OTEL_TRACES_SAMPLER_ARG": os.getenv("OTEL_TRACES_SAMPLER_ARG"),
            # Safe runtime config values for rag_service (do NOT record API keys).
            "CHAT_MODEL": os.getenv("CHAT_MODEL"),
            "EMBEDDING_MODEL": os.getenv("EMBEDDING_MODEL"),
            "OPENAI_BASE_URL": os.getenv("OPENAI_BASE_URL"),
            "RETRIEVE_TOP_K": os.getenv("RETRIEVE_TOP_K"),
            "LLM_TEMPERATURE": os.getenv("LLM_TEMPERATURE"),
            "LLM_TOP_P": os.getenv("LLM_TOP_P"),
            "LLM_MAX_COMPLETION_TOKENS": os.getenv("LLM_MAX_COMPLETION_TOKENS"),
            "EMBEDDING_CACHE_ENABLED": os.getenv("EMBEDDING_CACHE_ENABLED"),
            "VECTOR_SEARCH_CACHE_ENABLED": os.getenv("VECTOR_SEARCH_CACHE_ENABLED"),
            "SEMANTIC_LLM_CACHE_ENABLED": os.getenv("SEMANTIC_LLM_CACHE_ENABLED"),
            "LLM_CACHE_ENABLED": os.getenv("LLM_CACHE_ENABLED"),

            # Declared external API parity for n8n (non-secret)
            "N8N_OPENAI_CREDENTIAL_NAME": os.getenv("N8N_OPENAI_CREDENTIAL_NAME"),
            "N8N_OPENAI_CREDENTIAL_ID": os.getenv("N8N_OPENAI_CREDENTIAL_ID"),
            "N8N_CHAT_MODEL": os.getenv("N8N_CHAT_MODEL"),
            "N8N_EMBEDDING_MODEL": os.getenv("N8N_EMBEDDING_MODEL"),
            "N8N_OPENAI_BASE_URL": os.getenv("N8N_OPENAI_BASE_URL"),
            "N8N_WORKFLOW_ID": os.getenv("N8N_WORKFLOW_ID"),
        },
        "artifacts": artifacts,
        "docker_images": images,
        "host_info": host_info(),
        "preregistration": preregistration,
        "pairing": {
            "pair_plan": (
                {
                    "path": args.pair_plan,
                    "sha256": sha256_file(args.pair_plan),
                }
                if args.pair_plan
                else None
            ),
            "pair_validation": (
                {
                    "path": args.pair_validation,
                    "sha256": sha256_file(args.pair_validation),
                    "pass": read_json_field(args.pair_validation, "pass"),
                }
                if args.pair_validation
                else None
            ),
            "pair_comparison": (
                {
                    "path": args.pair_comparison,
                    "sha256": sha256_file(args.pair_comparison),
                }
                if args.pair_comparison
                else None
            ),
            "child_manifests": pair_children,
        },
        "runs": runs,
    }

    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)


if __name__ == "__main__":
    main()

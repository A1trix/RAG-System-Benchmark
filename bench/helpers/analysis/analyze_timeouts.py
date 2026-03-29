import argparse
import csv
import json
import re
from pathlib import Path


ACCESS_RE = re.compile(r"query request_id=([a-f0-9-]+) status=(\d+) duration_ms=(\d+)")


def load_access_log(path: Path):
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = ACCESS_RE.search(line)
        if not match:
            continue
        request_id, status, duration_ms = match.group(1), int(match.group(2)), int(match.group(3))
        rows.append({"request_id": request_id, "status": status, "duration_ms": duration_ms})
    return rows


def load_timings(path: Path):
    timings = {}
    if not path.exists():
        return timings
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            request_id = obj.get("request_id")
            if request_id:
                timings[request_id] = obj
    return timings


def classify_bottleneck(queue_wait, retrieval, llm, post, overhead):
    candidates = {
        "queue_wait": queue_wait,
        "retrieval": retrieval,
        "llm": llm,
        "post": post,
        "overhead": max(overhead, 0),
    }
    best = max(candidates.items(), key=lambda item: item[1])
    if best[1] <= 0:
        return "unknown"
    return best[0]


def main():
    parser = argparse.ArgumentParser(description="Correlate access log durations with timing JSONL.")
    parser.add_argument("--log-file", required=True, help="Path to rag-pipeline log file.")
    parser.add_argument("--timings", required=True, help="Path to timings-rag.jsonl.")
    parser.add_argument("--output", required=True, help="CSV output path.")
    parser.add_argument("--top", type=int, default=50, help="Number of slowest requests to output.")
    args = parser.parse_args()

    access = load_access_log(Path(args.log_file))
    timings = load_timings(Path(args.timings))

    if not access:
        print("No access log entries found.")
        return

    rows = []
    missing = 0
    for entry in access:
        request_id = entry["request_id"]
        timing = timings.get(request_id)
        if timing is None:
            rows.append({
                "request_id": request_id,
                "status": entry["status"],
                "duration_ms": entry["duration_ms"],
                "queue_wait_ms": None,
                "retrieval_ms": None,
                "llm_ms": None,
                "post_ms": None,
                "overhead_ms": None,
                "bottleneck": "missing",
            })
            missing += 1
            continue
        queue_wait = timing.get("queue_wait_ms") or 0
        retrieval = timing.get("retrieval_ms") or 0
        llm = timing.get("llm_ms") or 0
        post = timing.get("post_ms") or 0
        overhead = entry["duration_ms"] - (queue_wait + retrieval + llm + post)
        rows.append({
            "request_id": request_id,
            "status": entry["status"],
            "duration_ms": entry["duration_ms"],
            "queue_wait_ms": queue_wait,
            "retrieval_ms": retrieval,
            "llm_ms": llm,
            "post_ms": post,
            "overhead_ms": overhead,
            "bottleneck": classify_bottleneck(queue_wait, retrieval, llm, post, overhead),
        })

    rows.sort(key=lambda item: item["duration_ms"], reverse=True)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        for row in rows[: args.top]:
            writer.writerow(row)

    print(
        f"Processed {len(access)} access log entries; {missing} missing timing entries. "
        f"Wrote {min(len(rows), args.top)} rows to {output_path}."
    )


if __name__ == "__main__":
    main()

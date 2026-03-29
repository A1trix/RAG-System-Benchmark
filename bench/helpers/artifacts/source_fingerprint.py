#!/usr/bin/env python3
"""Compute a reproducible source/config fingerprint for a benchmark run.

This is a thesis-grade reproducibility artifact meant to identify the exact
code/config used for a run batch, even when no git commit hash is available.

It produces:
- per-file sha256 digests (no file contents)
- a stable aggregate sha256 over the per-file list

Secrets policy:
- This script only hashes files it is pointed at.
- Do NOT include secret-bearing files (e.g., a root .env) in the root-map.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import fnmatch
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Sequence


DEFAULT_EXCLUDES = (
    "**/.git/**",
    "**/__pycache__/**",
    "**/.pytest_cache/**",
    "**/.mypy_cache/**",
    "**/.ruff_cache/**",
    "**/.venv/**",
    "**/*.pyc",
    "**/*.pyo",
    "**/.DS_Store",
    # Generated benchmark data (must not affect source fingerprint)
    "bench/results/**",
    "bench/prometheus/data/**",
    "bench/grafana/data/**",
)


def _utc_now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _canonical_json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("utf-8")


def _matches_any(path_posix: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(path_posix, pat) for pat in patterns)


def _iter_files_pruned(root: Path, *, label: str, excludes: Sequence[str]) -> Iterable[Path]:
    """Yield files under root, pruning excluded directories early."""
    if root.is_file():
        yield root
        return
    if not root.is_dir():
        return

    root_abs = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root_abs):
        dp = Path(dirpath)
        try:
            rel_dir = dp.relative_to(root_abs)
        except Exception:
            rel_dir = Path(".")

        # Prune excluded directories in-place.
        kept = []
        for d in dirnames:
            cand = dp / d
            try:
                rel_cand = cand.relative_to(root_abs)
            except Exception:
                rel_cand = Path(d)
            virtual_dir = (Path(label) / rel_cand).as_posix().rstrip("/")
            probe = virtual_dir + "/x"
            if _matches_any(probe, excludes):
                continue
            kept.append(d)
        dirnames[:] = kept

        for name in filenames:
            p = dp / name
            yield p


def _parse_root_map(values: list[str]) -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    for raw in values:
        if "=" not in raw:
            raise SystemExit(f"Invalid --root-map (expected label=path): {raw}")
        label, path = raw.split("=", 1)
        label = label.strip()
        path = path.strip()
        if not label:
            raise SystemExit(f"Invalid --root-map (empty label): {raw}")
        if not path:
            raise SystemExit(f"Invalid --root-map (empty path): {raw}")
        out.append((label, Path(path)))
    return out


def build_fingerprint(root_maps: list[tuple[str, Path]], excludes: Sequence[str]) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    missing: list[str] = []
    total_bytes = 0

    for label, root in root_maps:
        if not root.exists():
            missing.append(f"{label}={root}")
            continue

        for p in _iter_files_pruned(root, label=label, excludes=excludes):
            try:
                rel = p.relative_to(root)
            except Exception:
                rel = Path(p.name)

            virtual = (Path(label) / rel).as_posix()
            if _matches_any(virtual, excludes):
                continue

            size = int(p.stat().st_size)
            digest = _sha256_file(p)
            files.append({"path": virtual, "size": size, "sha256": digest})
            total_bytes += size

    files.sort(key=lambda item: item["path"])

    payload: dict[str, Any] = {
        "generated_at": _utc_now_iso(),
        "version": 1,
        "roots": [{"label": label, "path": str(path)} for label, path in root_maps],
        "excludes": list(excludes),
        "missing_roots": missing,
        "file_count": len(files),
        "total_bytes": total_bytes,
        "files": files,
    }

    # Stable hash over content-relevant parts (exclude generated_at).
    for_hash = dict(payload)
    for_hash.pop("generated_at", None)
    payload["fingerprint_sha256"] = hashlib.sha256(_canonical_json_bytes(for_hash)).hexdigest()
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute a reproducible source/config fingerprint")
    parser.add_argument(
        "--root-map",
        action="append",
        default=[],
        help="Root mapping label=path (repeatable). Paths may be a directory or a single file.",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Exclude glob pattern applied to virtual paths (repeatable).",
    )
    parser.add_argument(
        "--no-default-excludes",
        action="store_true",
        help="Disable default exclude patterns.",
    )
    parser.add_argument("--output", required=True, help="Output JSON file path")
    args = parser.parse_args()

    root_maps = _parse_root_map(list(args.root_map))
    if not root_maps:
        raise SystemExit("At least one --root-map is required")

    excludes = list(args.exclude)
    if not args.no_default_excludes:
        excludes = list(DEFAULT_EXCLUDES) + excludes

    fp = build_fingerprint(root_maps, excludes)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(fp, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

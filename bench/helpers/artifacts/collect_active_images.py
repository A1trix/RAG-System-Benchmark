#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


def load_compose_ps(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None

    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]

    items: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            raise ValueError(f"compose ps output is not JSON: {path}")
        if isinstance(item, dict):
            items.append(item)
    if not items:
        raise ValueError(f"compose ps output had no JSON objects: {path}")
    return items


def is_running_entry(entry: dict[str, Any]) -> bool:
    state = str(entry.get("State") or "").strip().lower()
    if state:
        return state == "running"

    status = str(entry.get("Status") or "").strip().lower()
    if status:
        return status.startswith("up") or status == "running"

    return True


def inspect_image(image_ref: str) -> dict[str, Any]:
    result = subprocess.run(
        ["docker", "image", "inspect", image_ref],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return {}

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}

    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        return {}

    image = payload[0]
    return {
        "ImageID": image.get("Id"),
        "RepoTags": image.get("RepoTags") or [],
        "RepoDigests": image.get("RepoDigests") or [],
        "Created": image.get("Created"),
        "Architecture": image.get("Architecture"),
        "Os": image.get("Os"),
        "Size": image.get("Size"),
    }


def collect_active_images(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cache: dict[str, dict[str, Any]] = {}
    images: list[dict[str, Any]] = []

    for entry in entries:
        if not is_running_entry(entry):
            continue
        image_ref = str(entry.get("Image") or "").strip()
        if not image_ref:
            continue
        if image_ref not in cache:
            cache[image_ref] = inspect_image(image_ref)

        images.append(
            {
                "Service": entry.get("Service"),
                "ContainerName": entry.get("Name") or entry.get("Names"),
                "ContainerID": entry.get("ID"),
                "Image": image_ref,
                **cache[image_ref],
            }
        )

    images.sort(key=lambda item: (str(item.get("Service") or ""), str(item.get("ContainerName") or "")))
    return images


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect image metadata for active benchmark containers")
    parser.add_argument("--compose-ps", required=True, help="Path to compose_ps.json")
    parser.add_argument("--output", required=True, help="Output JSON path")
    args = parser.parse_args()

    entries = load_compose_ps(Path(args.compose_ps))
    images = collect_active_images(entries)
    if not images:
        raise SystemExit("no active compose images found")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(images, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

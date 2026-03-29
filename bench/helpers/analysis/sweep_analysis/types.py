from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PointKey:
    endpoint: str
    prompt_set: str
    offered_rpm: int

from __future__ import annotations

import re
from typing import Any, Iterable, Optional

def metric_values(metric: Any) -> dict[str, Any]:
    """Return the value-map for a k6 metric.

    k6 `--summary-export` has produced (at least) two shapes:
    - metric = {"values": {"avg":..., "p(95)":...}, ...}
    - metric = {"avg":..., "p(95)":..., ...}
    """

    if not isinstance(metric, dict):
        return {}
    values = metric.get("values")
    if isinstance(values, dict) and values:
        return values
    return metric

def _parse_k6_metric_tags(key: str) -> dict[str, str]:
    """Parse k6 metric tags from a summary-export metric key.

    Example: "attempts_measure_prompt{prompt_id:0,scenario:measure}".
    """

    if not isinstance(key, str) or "{" not in key or not key.endswith("}"):
        return {}
    inner = key.split("{", 1)[1][:-1]
    tags: dict[str, str] = {}
    for part in inner.split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        k, v = part.split(":", 1)
        k = k.strip()
        v = v.strip()
        if k:
            tags[k] = v
    return tags

def _metric_base_name(key: str) -> str:
    if not isinstance(key, str):
        return ""
    return key.split("{", 1)[0]

def pick_metric_key(metrics: dict[str, Any], base: str, required_substrings: list[str]) -> str:
    keys = [k for k in metrics.keys() if isinstance(k, str) and (k == base or k.startswith(base + "{"))]
    for k in keys:
        if all(s in k for s in required_substrings):
            return k
    return base

def counter_count_best_effort(metrics: dict[str, Any], base: str, required_substrings: list[str] | None = None) -> Optional[int]:
    subs = required_substrings or []
    key = pick_metric_key(metrics, base, subs)
    metric = metrics.get(key)
    vals = metric_values(metric)
    return as_int(vals.get("count"))

def tagged_counter_series(
    metrics: dict[str, Any],
    base: str,
    *,
    tag_key: str,
    required_substrings: list[str] | None = None,
) -> dict[str, int]:
    """Return a mapping tag_value -> counter.count.

    Only includes metric keys that are tagged (base{...}).
    """

    out: dict[str, int] = {}
    subs = required_substrings or []
    for k, metric in metrics.items():
        if not isinstance(k, str):
            continue
        if not (k.startswith(base + "{") and k.endswith("}")):
            continue
        if any(s not in k for s in subs):
            continue
        tags = _parse_k6_metric_tags(k)
        tv = tags.get(tag_key)
        if tv is None:
            continue
        vals = metric_values(metric)
        c = as_int(vals.get("count"))
        if c is None:
            continue
        out[str(tv)] = int(c)
    return out

def _sorted_prompt_ids(ids: Iterable[str]) -> list[str]:
    xs = [str(x) for x in ids if x is not None]
    ints: list[tuple[int, str]] = []
    strs: list[str] = []
    for s in xs:
        i = as_int(s)
        if i is None:
            strs.append(s)
        else:
            ints.append((int(i), s))
    if strs and ints:
        # Mixed: keep stable lexical order.
        return sorted(set(xs))
    if ints and not strs:
        return [str(i) for i, _ in sorted(ints, key=lambda t: t[0])]
    return sorted(set(xs))

def as_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None

def as_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        s = str(value)
        if s.isdigit():
            return int(s)
        return int(float(s))
    except Exception:
        return None

def parse_duration_seconds(duration: Any) -> Optional[float]:
    """Parse k6-ish duration strings like 300s, 5m, 1h."""
    if duration is None:
        return None
    if isinstance(duration, (int, float)):
        return float(duration)
    s = str(duration).strip()
    if not s:
        return None
    m = re.match(r"^(?P<num>[0-9]+(?:\.[0-9]+)?)\s*(?P<unit>ms|s|m|h)$", s)
    if not m:
        # Allow plain seconds.
        try:
            return float(s)
        except Exception:
            return None
    num = float(m.group("num"))
    unit = m.group("unit")
    if unit == "ms":
        return num / 1000.0
    if unit == "s":
        return num
    if unit == "m":
        return num * 60.0
    if unit == "h":
        return num * 3600.0
    return None

def counter_count(metrics: dict[str, Any], name: str) -> Optional[int]:
    metric = metrics.get(name)
    vals = metric_values(metric)
    return as_int(vals.get("count"))

def trend_quantile_ms(metrics: dict[str, Any], name: str, key: str) -> Optional[float]:
    metric = metrics.get(name)
    vals = metric_values(metric)
    return as_float(vals.get(key))

def safe_div(n: Optional[float], d: Optional[float]) -> Optional[float]:
    try:
        if n is None or d is None:
            return None
        if d == 0:
            return None
        return float(n) / float(d)
    except Exception:
        return None

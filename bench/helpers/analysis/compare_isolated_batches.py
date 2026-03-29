#!/usr/bin/env python3
"""Build parent comparison artifacts from isolated rag/n8n child batches."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from statistics import median
from typing import Any

from sweep_analysis.aggregation import (
    aggregate_points,
    build_agg_fields,
    build_invalid_rows,
    build_rep_fields,
    mark_pareto_best_tradeoffs,
)
from sweep_analysis.discovery import FAILURE_MODE_COUNTER_BASES
from sweep_analysis.io_utils import save_markdown_table, write_csv
from sweep_analysis.knee import build_sorted_cohorts, compute_knee_report
from sweep_analysis.plots import (
    color_for_endpoint,
    display_name_for_endpoint,
    display_name_for_prompt_set,
    ensure_matplotlib,
    generate_plots,
    save_figure_outputs,
    style_axes,
)
from sweep_analysis.reports import write_knee_reports


PRIMARY_METRICS: dict[str, dict[str, Any]] = {
    "throughput_success_rps": {"column": "throughput_success_rps_mean", "higher_better": True},
    "latency_p95_s": {"column": "latency_p95_s_mean", "higher_better": False},
    "timeout_rate": {"column": "timeout_rate_mean", "higher_better": False},
    "error_rate_total": {"column": "error_rate_total_mean", "higher_better": False},
}


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def parse_cell(value: str) -> Any:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    lower = text.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    try:
        if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
            return int(text)
        return float(text)
    except Exception:
        return text


def load_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [{k: parse_cell(v) for k, v in row.items()} for row in reader]


def _as_float(x: Any) -> float | None:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def resolve_results_dir(raw_path: str, parent_dir: Path) -> Path:
    path = Path(raw_path).expanduser()
    if path.exists():
        return path

    normalized = str(raw_path or "").replace("\\", "/")
    marker = "/bench/"
    if marker in normalized:
        suffix = normalized.split(marker, 1)[1]
        mapped = parent_dir.parents[1] / suffix
        if mapped.exists():
            return mapped
    elif normalized.startswith("results/"):
        mapped = parent_dir.parents[1] / normalized
        if mapped.exists():
            return mapped

    return path


def _group_rows_by_endpoint(rows: list[dict[str, Any]]) -> dict[str, dict[int, dict[str, Any]]]:
    grouped: dict[str, dict[int, dict[str, Any]]] = {}
    for row in rows:
        endpoint = str(row.get("endpoint") or "").strip()
        rpm = row.get("offered_rpm")
        try:
            rpm_i = int(float(str(rpm)))
        except Exception:
            continue
        if not endpoint:
            continue
        grouped.setdefault(endpoint, {})[rpm_i] = row
    return grouped


def _save_figure(fig: Any, out_base: Path, caption_meta: dict[str, Any] | None = None) -> dict[str, Path | None]:
    return save_figure_outputs(fig, out_base, caption_meta=caption_meta)


def _endpoint_colors(plt: Any, labels: list[str]) -> dict[str, Any]:
    cmap = plt.get_cmap("tab10")
    return {label: color_for_endpoint(label, fallback=cmap(idx % 10)) for idx, label in enumerate(labels)}


def _format_req_s(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f} requests/s"


def _format_seconds(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f} s"


def _format_rpm_list(rpms: list[int]) -> str:
    labels = [f"{int(rpm)} RPM" for rpm in sorted({int(rpm) for rpm in rpms})]
    if not labels:
        return "no shared valid load levels"
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} and {labels[1]}"
    return ", ".join(labels[:-1]) + f", and {labels[-1]}"


def _valid_rpms_by_endpoint(rows_by_endpoint: dict[str, dict[int, dict[str, Any]]]) -> dict[str, list[int]]:
    return {
        endpoint: sorted(rpm for rpm, row in rpm_rows.items() if bool(row.get("point_valid")))
        for endpoint, rpm_rows in rows_by_endpoint.items()
    }


def _shared_valid_rpms(valid_by_endpoint: dict[str, list[int]]) -> list[int]:
    valid_sets = [set(values) for values in valid_by_endpoint.values()]
    return sorted(set.intersection(*valid_sets)) if valid_sets else []


def _value_at(rows_by_endpoint: dict[str, dict[int, dict[str, Any]]], endpoint: str, rpm: int, field: str) -> float | None:
    return _as_float(rows_by_endpoint.get(endpoint, {}).get(rpm, {}).get(field))


def _humanize_reason_code(reason_code: str) -> str:
    reason = str(reason_code or "").strip()
    mapping = {
        "measure_seconds_missing": "missing measurement coverage",
        "queue_saturation": "queue saturation",
        "prompt_mix_invalid": "prompt-mix imbalance",
        "dropped_iterations": "dropped iterations",
        "vus_cap": "virtual-user cap hit",
    }
    return mapping.get(reason, reason.replace("_", " "))


def _invalid_reason_map(invalid_rows: list[dict[str, Any]]) -> dict[tuple[str, int], list[str]]:
    out: dict[tuple[str, int], list[str]] = {}
    for row in invalid_rows:
        if str(row.get("row_type") or "") != "point":
            continue
        endpoint = str(row.get("endpoint") or "").strip()
        rpm = row.get("offered_rpm")
        try:
            rpm_i = int(float(str(rpm)))
        except Exception:
            continue
        raw = str(row.get("reason_codes") or "").strip()
        reasons = [_humanize_reason_code(part) for part in raw.split(",") if part.strip()]
        out[(endpoint, rpm_i)] = reasons
    return out


def _single_endpoint_extension_sentence(
    valid_by_endpoint: dict[str, list[int]],
    endpoint_labels: dict[str, str],
    shared_valid_rpms: list[int],
) -> str:
    candidate_rpms = sorted({rpm for rpms in valid_by_endpoint.values() for rpm in rpms if rpm not in set(shared_valid_rpms)})
    for rpm in candidate_rpms:
        valid_endpoints = [endpoint for endpoint, rpms in valid_by_endpoint.items() if rpm in rpms]
        invalid_endpoints = [endpoint for endpoint in valid_by_endpoint if rpm not in valid_by_endpoint.get(endpoint, [])]
        if len(valid_endpoints) == 1 and invalid_endpoints:
            valid_label = endpoint_labels[valid_endpoints[0]]
            invalid_label = endpoint_labels[invalid_endpoints[0]]
            return (
                f"{valid_label} remains valid at {rpm} RPM, while {invalid_label} contributes no plotted point at that load "
                "because the sweep point was invalid in the parent comparison."
            )
    return ""


def build_parent_caption_metas(
    *,
    agg_rows: list[dict[str, Any]],
    invalid_rows: list[dict[str, Any]],
    knee_report: dict[str, Any],
    prompt_set: str,
) -> dict[str, dict[str, Any]]:
    rows_by_endpoint = _group_rows_by_endpoint(agg_rows)
    endpoints = sorted(rows_by_endpoint.keys())
    endpoint_labels = {endpoint: display_name_for_endpoint(endpoint) for endpoint in endpoints}
    valid_by_endpoint = _valid_rpms_by_endpoint(rows_by_endpoint)
    shared_valid_rpms = _shared_valid_rpms(valid_by_endpoint)
    invalid_reason_map = _invalid_reason_map(invalid_rows)
    prompt_label = display_name_for_prompt_set(prompt_set)
    extension_sentence = _single_endpoint_extension_sentence(valid_by_endpoint, endpoint_labels, shared_valid_rpms)

    throughput_caption = (
        f"This figure compares mean successful throughput as a function of offered load for the {prompt_label}."
    )
    latency_caption = f"This figure reports p95 latency at each validity-compliant offered load for the {prompt_label}."

    if len(endpoints) == 2 and len(shared_valid_rpms) == 1:
        rpm = shared_valid_rpms[0]
        left, right = endpoints
        left_thr = _value_at(rows_by_endpoint, left, rpm, "throughput_success_rps_mean")
        right_thr = _value_at(rows_by_endpoint, right, rpm, "throughput_success_rps_mean")
        if left_thr is not None and right_thr is not None:
            better_thr = left if left_thr > right_thr else right
            other_thr = right if better_thr == left else left
            better_thr_value = left_thr if better_thr == left else right_thr
            other_thr_value = right_thr if other_thr == right else left_thr
            throughput_caption += (
                f" At the shared valid load of {rpm} RPM, {endpoint_labels[better_thr]} achieves {_format_req_s(better_thr_value)}, "
                f"whereas {endpoint_labels[other_thr]} reaches {_format_req_s(other_thr_value)}."
            )

        left_lat = _value_at(rows_by_endpoint, left, rpm, "latency_p95_s_mean")
        right_lat = _value_at(rows_by_endpoint, right, rpm, "latency_p95_s_mean")
        if left_lat is not None and right_lat is not None:
            better_lat = left if left_lat < right_lat else right
            other_lat = right if better_lat == left else left
            better_lat_value = left_lat if better_lat == left else right_lat
            other_lat_value = right_lat if other_lat == right else left_lat
            latency_caption += (
                f" At the shared valid load of {rpm} RPM, {endpoint_labels[better_lat]} shows substantially lower p95 latency than "
                f"{endpoint_labels[other_lat]} ({_format_seconds(better_lat_value)} versus {_format_seconds(other_lat_value)})."
            )
    elif shared_valid_rpms:
        throughput_caption += f" Only validity-compliant sweep points are plotted across shared valid loads of {_format_rpm_list(shared_valid_rpms)}."
        latency_caption += f" Only validity-compliant sweep points are plotted across shared valid loads of {_format_rpm_list(shared_valid_rpms)}."
    else:
        throughput_caption += " No shared valid load level was available in this parent comparison."
        latency_caption += " No shared valid load level was available in this parent comparison."

    if extension_sentence:
        throughput_caption += f" {extension_sentence}"
        latency_caption += f" {extension_sentence}"

    error_values = [
        _as_float(row.get("error_rate_total_mean"))
        for row in agg_rows
        if bool(row.get("point_valid")) and _as_float(row.get("error_rate_total_mean")) is not None
    ]
    all_zero_error = bool(error_values) and all(abs(value or 0.0) <= 1e-12 for value in error_values)
    error_caption = "This figure compares the total error rate across validity-compliant sweep points."
    if all_zero_error:
        error_caption += (
            " For all plotted points, both endpoints exhibit a total error rate of 0.0, indicating that retained benchmark points "
            "were not affected by observed request failures within the measurement window."
        )
    else:
        error_caption += " Non-zero values identify benchmark points where observed request failures occurred within the measurement window."

    validity_caption = (
        "This figure summarizes benchmark validity coverage by endpoint and offered load. Filled markers denote load levels that are valid "
        "for both endpoints, open markers denote endpoint-specific valid points, and crosses denote invalid points."
    )
    if len(endpoints) == 2:
        shared_text = _format_rpm_list(shared_valid_rpms) if shared_valid_rpms else "no shared valid load levels"
        validity_caption += f" In the current comparison, both {endpoint_labels[endpoints[0]]} and {endpoint_labels[endpoints[1]]} are valid at {shared_text}."
        for endpoint in endpoints:
            extra_rpms = [rpm for rpm in valid_by_endpoint.get(endpoint, []) if rpm not in shared_valid_rpms]
            if extra_rpms:
                validity_caption += f" {endpoint_labels[endpoint]} remains additionally valid at {_format_rpm_list(extra_rpms)}."
        for endpoint in endpoints:
            invalid_rpms = sorted(
                rpm
                for rpm in rows_by_endpoint.get(endpoint, {})
                if rpm not in valid_by_endpoint.get(endpoint, [])
            )
            if invalid_rpms:
                rpm = invalid_rpms[0]
                reasons = invalid_reason_map.get((endpoint, rpm), [])
                if reasons:
                    reasons_text = ", ".join(reasons[:-1]) + (f" and {reasons[-1]}" if len(reasons) > 1 else reasons[0])
                    validity_caption += f" {endpoint_labels[endpoint]} is invalid at {rpm} RPM due to {reasons_text}."

    knee_cohorts = knee_report.get("cohorts") if isinstance(knee_report, dict) else {}
    sustainability_items: dict[str, dict[str, Any]] = {}
    if isinstance(knee_cohorts, dict):
        for _, cohort in sorted(knee_cohorts.items()):
            if not isinstance(cohort, dict):
                continue
            endpoint = str(cohort.get("endpoint") or "").strip()
            if not endpoint:
                continue
            knee_obj = cohort.get("knee")
            knee: dict[str, Any] = knee_obj if isinstance(knee_obj, dict) else {}
            sustainability_items[endpoint] = knee
    sustainability_caption = (
        f"This two-panel figure summarizes sustainable throughput and the last validity-compliant offered load for the {prompt_label}."
    )
    if len(endpoints) == 2 and all(endpoint in sustainability_items for endpoint in endpoints):
        left, right = endpoints
        left_thr = _as_float(sustainability_items[left].get("sustainable_throughput_success_rps"))
        right_thr = _as_float(sustainability_items[right].get("sustainable_throughput_success_rps"))
        left_rpm = _as_float(sustainability_items[left].get("last_good_rpm"))
        right_rpm = _as_float(sustainability_items[right].get("last_good_rpm"))
        if all(value is not None for value in (left_thr, right_thr, left_rpm, right_rpm)):
            better_thr = left if (left_thr or 0.0) > (right_thr or 0.0) else right
            other_thr = right if better_thr == left else left
            better_thr_value = left_thr if better_thr == left else right_thr
            other_thr_value = right_thr if other_thr == right else left_thr
            better_rpm_endpoint = left if (left_rpm or 0.0) > (right_rpm or 0.0) else right
            other_rpm_endpoint = right if better_rpm_endpoint == left else left
            better_rpm_value = left_rpm if better_rpm_endpoint == left else right_rpm
            other_rpm_value = right_rpm if other_rpm_endpoint == right else left_rpm
            sustainability_caption += (
                f" {endpoint_labels[better_thr]} attains the higher sustainable throughput "
                f"({_format_req_s(better_thr_value)} versus {_format_req_s(other_thr_value)}) and {endpoint_labels[better_rpm_endpoint]} reaches the higher "
                f"last good load level ({int(better_rpm_value or 0.0)} RPM versus {int(other_rpm_value or 0.0)} RPM)."
            )

    frontier_caption = (
        "This figure plots valid operating points in throughput-latency space and highlights the best p95 trade-off frontier for each endpoint, "
        "with annotations indicating offered load in RPM."
    )
    if len(endpoints) == 2 and len(shared_valid_rpms) == 1:
        rpm = shared_valid_rpms[0]
        left, right = endpoints
        left_thr = _value_at(rows_by_endpoint, left, rpm, "throughput_success_rps_mean")
        right_thr = _value_at(rows_by_endpoint, right, rpm, "throughput_success_rps_mean")
        left_lat = _value_at(rows_by_endpoint, left, rpm, "latency_p95_s_mean")
        right_lat = _value_at(rows_by_endpoint, right, rpm, "latency_p95_s_mean")
        if None not in {left_thr, right_thr, left_lat, right_lat}:
            better = None
            if (left_thr or 0.0) > (right_thr or 0.0) and (left_lat or 0.0) < (right_lat or 0.0):
                better = left
                other = right
            elif (right_thr or 0.0) > (left_thr or 0.0) and (right_lat or 0.0) < (left_lat or 0.0):
                better = right
                other = left
            else:
                better = None
                other = None
            if better and other:
                frontier_caption += (
                    f" At {rpm} RPM, {endpoint_labels[better]} combines higher successful throughput and lower p95 latency than {endpoint_labels[other]}."
                )
    if extension_sentence:
        frontier_caption += f" {extension_sentence}"

    limited_shared = len(shared_valid_rpms)
    limitation_suffix = (
        "Because only one shared-valid load level was available in this batch, the cross-endpoint comparison is descriptive rather than inferential."
        if limited_shared <= 1
        else f"Because only {limited_shared} shared-valid load levels were available in this batch, the cross-endpoint comparison remains descriptive rather than inferential."
    )

    return {
        "compare_throughput_over_rpm": {
            "title": "Successful Throughput over Offered Load",
            "label": "fig:compare-throughput-over-rpm",
            "short_caption": "Mean successful throughput across validity-compliant offered loads for the two compared endpoints.",
            "caption": throughput_caption,
            "limitation": limitation_suffix,
            "usage_note": "Primary performance figure for successful request rate across offered load.",
        },
        "compare_latency_p95_over_rpm": {
            "title": "p95 Latency over Offered Load",
            "label": "fig:compare-latency-p95-over-rpm",
            "short_caption": "p95 latency across validity-compliant offered loads for the two compared endpoints.",
            "caption": latency_caption,
            "limitation": "Latency is shown only for validity-compliant points, so absent points reflect invalidated sweep levels rather than measured latency estimates.",
            "usage_note": "Primary response-time figure for matched-load comparison.",
        },
        "compare_error_rate_over_rpm": {
            "title": "Total Error Rate over Offered Load",
            "label": "fig:compare-error-rate-over-rpm",
            "short_caption": "Total error rate across validity-compliant offered loads for the two compared endpoints.",
            "caption": error_caption,
            "limitation": "An all-zero error-rate plot should not be interpreted as evidence of equivalent robustness at higher load, because invalid sweep points are excluded from this figure.",
            "usage_note": "Primary reliability figure for retained benchmark points.",
        },
        "compare_validity_coverage_over_rpm": {
            "title": "Validity Coverage across Offered Load Levels",
            "label": "fig:compare-validity-coverage-over-rpm",
            "short_caption": "Validity status by endpoint and offered load, distinguishing shared-valid, endpoint-only valid, and invalid points.",
            "caption": validity_caption,
            "limitation": "This visualization represents validity-gating outcomes rather than a direct performance metric and should be interpreted together with the throughput and latency figures.",
            "usage_note": "Use to explain why some higher-load points are excluded from direct comparison.",
        },
        "compare_sustainability_summary": {
            "title": "Sustainability Summary of Compared Endpoints",
            "label": "fig:compare-sustainability-summary",
            "short_caption": "Sustainable throughput and last valid load level for each endpoint.",
            "caption": sustainability_caption,
            "limitation": "Sustainability here reflects the observed operating envelope of this batch rather than a precise threshold estimate.",
            "usage_note": "Secondary scalability summary tied to the knee report.",
        },
        "compare_throughput_latency_frontier": {
            "title": "Throughput-Latency Frontier of Valid Operating Points",
            "label": "fig:compare-throughput-latency-frontier",
            "short_caption": "Valid operating points in throughput-latency space, highlighting the p95 best-tradeoff frontier for each endpoint.",
            "caption": frontier_caption,
            "limitation": "The frontier is an empirical summary of validity-compliant points from this batch and should not be treated as a generalized Pareto estimate.",
            "usage_note": "Supporting trade-off figure for throughput versus latency.",
        },
    }


def write_figure_references_index(
    analysis_dir: Path,
    figure_order: list[str],
    caption_metas: dict[str, dict[str, Any]],
) -> Path:
    lines = ["# Figure References", "", f"Analysis dir: `{analysis_dir}`", ""]
    for stem in figure_order:
        meta = caption_metas.get(stem) or {}
        title = str(meta.get("title") or stem)
        label = str(meta.get("label") or "")
        usage_note = str(meta.get("usage_note") or "")
        short_caption = str(meta.get("short_caption") or "")
        lines.extend([f"## {title}", ""])
        if label:
            lines.append(f"- Label: `{label}`")
        lines.append(f"- File: `{stem}.png`")
        if short_caption:
            lines.append(f"- Short caption: {short_caption}")
        if usage_note:
            lines.append(f"- Thesis use: {usage_note}")
        lines.append("")

    out_path = analysis_dir / "figure_references.md"
    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return out_path


def write_validity_coverage_plot(
    analysis_dir: Path,
    agg_rows: list[dict[str, Any]],
    caption_meta: dict[str, Any] | None = None,
) -> Path | None:
    try:
        plt = ensure_matplotlib()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return None

    rows_by_endpoint = _group_rows_by_endpoint(agg_rows)
    endpoints = sorted(rows_by_endpoint.keys())
    if not endpoints:
        return None

    shared_valid_rpms = set(_shared_valid_rpms(_valid_rpms_by_endpoint(rows_by_endpoint)))
    colors = _endpoint_colors(plt, endpoints)
    endpoint_labels = {endpoint: display_name_for_endpoint(endpoint) for endpoint in endpoints}

    fig, ax = plt.subplots(figsize=(8.6, max(3.3, 1.9 + 0.95 * len(endpoints))), dpi=160)
    y_positions = {endpoint: idx for idx, endpoint in enumerate(endpoints)}

    for endpoint in endpoints:
        rpm_rows = rows_by_endpoint[endpoint]
        y = y_positions[endpoint]
        shared = sorted(rpm for rpm, row in rpm_rows.items() if bool(row.get("point_valid")) and rpm in shared_valid_rpms)
        valid_only = sorted(rpm for rpm, row in rpm_rows.items() if bool(row.get("point_valid")) and rpm not in shared_valid_rpms)
        invalid = sorted(rpm for rpm, row in rpm_rows.items() if not bool(row.get("point_valid")))
        color = colors[endpoint]

        if shared:
            ax.scatter(shared, [y] * len(shared), marker="o", s=60, color=color, zorder=3)
        if valid_only:
            ax.scatter(valid_only, [y] * len(valid_only), marker="o", s=60, facecolors="none", edgecolors=color, linewidths=1.5, zorder=3)
        if invalid:
            ax.scatter(invalid, [y] * len(invalid), marker="x", s=64, color=color, linewidths=1.6, zorder=4)

    ax.scatter([], [], marker="o", s=60, color="black", label="shared valid")
    ax.scatter([], [], marker="o", s=60, facecolors="none", edgecolors="black", linewidths=1.5, label="valid for one endpoint only")
    ax.scatter([], [], marker="x", s=64, color="black", linewidths=1.6, label="invalid")
    ax.set_title("Validity Coverage across Offered Load Levels")
    ax.set_xlabel("Offered load (RPM)")
    ax.set_ylabel("Endpoint")
    ax.set_yticks([y_positions[endpoint] for endpoint in endpoints])
    ax.set_yticklabels([endpoint_labels[endpoint] for endpoint in endpoints])
    ax.set_ylim(-0.6, len(endpoints) - 0.4)
    style_axes(ax, grid_axis="x")
    ax.legend(loc="best", fontsize=8)

    out_base = analysis_dir / "compare_validity_coverage_over_rpm"
    _save_figure(fig, out_base, caption_meta=caption_meta)
    plt.close(fig)
    return out_base.with_suffix(".png")


def write_sustainability_summary_plot(
    analysis_dir: Path,
    knee_report: dict[str, Any],
    caption_meta: dict[str, Any] | None = None,
) -> Path | None:
    try:
        plt = ensure_matplotlib()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return None

    cohorts = knee_report.get("cohorts") if isinstance(knee_report, dict) else None
    if not isinstance(cohorts, dict) or not cohorts:
        return None

    items: list[dict[str, Any]] = []
    for key, cohort in sorted(cohorts.items()):
        if not isinstance(cohort, dict):
            continue
        endpoint = str(cohort.get("endpoint") or key)
        prompt_set = str(cohort.get("prompt_set") or "")
        label = display_name_for_endpoint(endpoint) if not prompt_set else f"{display_name_for_endpoint(endpoint)} ({display_name_for_prompt_set(prompt_set)})"
        knee_obj = cohort.get("knee")
        knee: dict[str, Any] = knee_obj if isinstance(knee_obj, dict) else {}
        items.append(
            {
                "label": label,
                "sustainable_thr_rps": _as_float(knee.get("sustainable_throughput_success_rps")),
                "last_good_rpm": _as_float(knee.get("last_good_rpm")),
                "first_bad_rpm": _as_float(knee.get("first_bad_rpm")),
                "first_bad_reasons": ", ".join(str(x) for x in (knee.get("first_bad_reasons") or []) if x is not None),
            }
        )

    if not items:
        return None

    labels = [item["label"] for item in items]
    colors = _endpoint_colors(plt, labels)
    xs = list(range(len(items)))
    throughput_vals = [item["sustainable_thr_rps"] if item["sustainable_thr_rps"] is not None else 0.0 for item in items]
    last_good_vals = [item["last_good_rpm"] if item["last_good_rpm"] is not None else 0.0 for item in items]

    fig, axes = plt.subplots(1, 2, figsize=(9.4, 4.4), dpi=160)
    bar_colors = [colors[label] for label in labels]

    bars_thr = axes[0].bar(xs, throughput_vals, color=bar_colors)
    axes[0].set_title("Sustainable throughput")
    axes[0].set_ylabel("Successful throughput (requests/s)")
    axes[0].set_xticks(xs)
    axes[0].set_xticklabels(labels)
    axes[0].set_ylim(bottom=0.0)
    style_axes(axes[0], grid_axis="y")
    for bar, item in zip(bars_thr, items):
        value = item["sustainable_thr_rps"]
        text = f"{value:.3f}" if value is not None else "n/a"
        axes[0].annotate(text, (bar.get_x() + bar.get_width() / 2, bar.get_height()), textcoords="offset points", xytext=(0, 4), ha="center", fontsize=8)

    bars_rpm = axes[1].bar(xs, last_good_vals, color=bar_colors)
    axes[1].set_title("Last valid load level")
    axes[1].set_ylabel("Offered load (RPM)")
    axes[1].set_xticks(xs)
    axes[1].set_xticklabels(labels)
    axes[1].set_ylim(bottom=0.0)
    style_axes(axes[1], grid_axis="y")
    for bar, item in zip(bars_rpm, items):
        value = item["last_good_rpm"]
        if value is None:
            text = "n/a"
        else:
            text = f"{int(value)} RPM"
            if item["first_bad_rpm"] is not None:
                text += f"\nfirst bad {int(item['first_bad_rpm'])}"
        axes[1].annotate(text, (bar.get_x() + bar.get_width() / 2, bar.get_height()), textcoords="offset points", xytext=(0, 4), ha="center", fontsize=8)

    out_base = analysis_dir / "compare_sustainability_summary"
    _save_figure(fig, out_base, caption_meta=caption_meta)
    plt.close(fig)
    return out_base.with_suffix(".png")


def write_throughput_latency_frontier_plot(
    analysis_dir: Path,
    agg_rows: list[dict[str, Any]],
    caption_meta: dict[str, Any] | None = None,
) -> Path | None:
    try:
        plt = ensure_matplotlib()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return None

    rows_by_endpoint = _group_rows_by_endpoint(agg_rows)
    endpoints = sorted(rows_by_endpoint.keys())
    if not endpoints:
        return None

    colors = _endpoint_colors(plt, endpoints)
    fig, ax = plt.subplots(figsize=(8.6, 5.4), dpi=160)

    plotted = False
    for endpoint in endpoints:
        valid_rows = [row for _, row in sorted(rows_by_endpoint[endpoint].items()) if bool(row.get("point_valid"))]
        if not valid_rows:
            continue
        plotted = True
        color = colors[endpoint]
        throughput_all = [float(_as_float(row.get("throughput_success_rps_mean")) or 0.0) for row in valid_rows]
        latency_all = [float(_as_float(row.get("latency_p95_s_mean")) or 0.0) for row in valid_rows]
        frontier_rows = [row for row in valid_rows if bool(row.get("on_best_tradeoff_p95"))]
        if not frontier_rows:
            frontier_rows = valid_rows

        ax.plot(throughput_all, latency_all, linestyle=":", linewidth=1.0, marker="o", markersize=4, color=color, alpha=0.35)

        frontier_rows = sorted(frontier_rows, key=lambda row: float(_as_float(row.get("throughput_success_rps_mean")) or 0.0))
        frontier_x = [float(_as_float(row.get("throughput_success_rps_mean")) or 0.0) for row in frontier_rows]
        frontier_y = [float(_as_float(row.get("latency_p95_s_mean")) or 0.0) for row in frontier_rows]
        ax.plot(frontier_x, frontier_y, linestyle="-", linewidth=1.8, marker="o", markersize=5, color=color, label=display_name_for_endpoint(endpoint))

        for row, x, y in zip(frontier_rows, frontier_x, frontier_y):
            rpm = row.get("offered_rpm")
            if rpm is None:
                continue
            ax.annotate(f"{int(rpm)} RPM", (x, y), textcoords="offset points", xytext=(5, 4), fontsize=7)

    if not plotted:
        plt.close(fig)
        return None

    ax.set_title("Throughput-Latency Frontier of Valid Operating Points")
    ax.set_xlabel("Successful throughput (requests/s)")
    ax.set_ylabel("p95 latency (s)")
    ax.set_xlim(left=0.0)
    ax.set_ylim(bottom=0.0)
    style_axes(ax)
    ax.legend(loc="best", fontsize=8)

    out_base = analysis_dir / "compare_throughput_latency_frontier"
    _save_figure(fig, out_base, caption_meta=caption_meta)
    plt.close(fig)
    return out_base.with_suffix(".png")


def _metric_counts(rows_by_endpoint: dict[str, dict[int, dict[str, Any]]], shared_rpms: list[int], metric_name: str) -> dict[str, Any]:
    spec = PRIMARY_METRICS[metric_name]
    column = str(spec["column"])
    higher_better = bool(spec["higher_better"])
    endpoints = sorted(rows_by_endpoint.keys())
    if len(endpoints) != 2:
        return {
            "column": column,
            "higher_better": higher_better,
            "comparisons": 0,
            "wins": {},
            "median_difference": {},
            "winner": None,
        }

    left, right = endpoints
    wins = {left: 0, right: 0, "tie": 0}
    diffs_left_minus_right: list[float] = []
    compared = 0
    for rpm in shared_rpms:
        lv = _as_float(rows_by_endpoint.get(left, {}).get(rpm, {}).get(column))
        rv = _as_float(rows_by_endpoint.get(right, {}).get(rpm, {}).get(column))
        if lv is None or rv is None:
            continue
        compared += 1
        diffs_left_minus_right.append(lv - rv)
        if abs(lv - rv) <= 1e-12:
            wins["tie"] += 1
        elif higher_better:
            wins[left if lv > rv else right] += 1
        else:
            wins[left if lv < rv else right] += 1

    winner = None
    if wins.get(left, 0) > wins.get(right, 0):
        winner = left
    elif wins.get(right, 0) > wins.get(left, 0):
        winner = right
    elif compared > 0:
        winner = "tie"

    med = median(diffs_left_minus_right) if diffs_left_minus_right else None
    return {
        "column": column,
        "higher_better": higher_better,
        "comparisons": compared,
        "wins": wins,
        "median_difference": {
            f"{left}_minus_{right}": med,
            f"{right}_minus_{left}": (-med if med is not None else None),
        },
        "winner": winner,
    }


def build_prompt_mix_report(path: Path, parent_dir: Path, child_meta: list[dict[str, Any]], rep_rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Prompt Mix Report",
        "",
        f"Parent compare dir: `{parent_dir}`",
        "",
        "This parent comparison reuses child-batch prompt-mix checks from isolated sweep analyses.",
        "Child sweep points are combined only after each child batch has already produced prompt_mix_ok fields.",
        "",
        "## Child Batches",
        "",
        "| child_batch_id | endpoint | pair_rep | pair_order | pair_prompt_seed | primary_rows | primary_prompt_mix_ok |",
        "|---|---|---:|---|---:|---:|---|",
    ]
    for child in child_meta:
        primary_rows = sum(1 for row in rep_rows if str(row.get("child_batch_id") or "") == str(child.get("child_batch_id") or ""))
        lines.append(
            "| {child_batch_id} | {endpoint} | {pair_rep} | {pair_order} | {pair_prompt_seed} | {primary_rows} | {prompt_mix_ok} |".format(
                child_batch_id=str(child.get("child_batch_id") or ""),
                endpoint=str(child.get("endpoint") or ""),
                pair_rep=str(child.get("pair_rep") or ""),
                pair_order=str(child.get("pair_order") or ""),
                pair_prompt_seed=str(child.get("pair_prompt_seed") or ""),
                primary_rows=str(primary_rows),
                prompt_mix_ok="yes" if bool(child.get("primary_prompt_mix_ok")) else "no",
            )
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def build_pair_comparison_outputs(
    analysis_dir: Path,
    parent_dir: Path,
    agg_rows: list[dict[str, Any]],
    child_meta: list[dict[str, Any]],
) -> tuple[Path, Path, Path]:
    rows_by_endpoint = _group_rows_by_endpoint(agg_rows)
    validity: dict[str, dict[str, Any]] = {}
    for endpoint, rpm_rows in rows_by_endpoint.items():
        valid_rpms = sorted(rpm for rpm, row in rpm_rows.items() if bool(row.get("point_valid")))
        validity[endpoint] = {
            "offered_rpms": sorted(rpm_rows.keys()),
            "valid_rpms": valid_rpms,
            "valid_point_count": len(valid_rpms),
        }

    valid_sets = [set(data.get("valid_rpms") or []) for data in validity.values()]
    shared_valid_rpms = sorted(set.intersection(*valid_sets)) if valid_sets else []
    metric_results = {
        name: _metric_counts(rows_by_endpoint, shared_valid_rpms, name)
        for name in PRIMARY_METRICS
    }

    endpoints = sorted(rows_by_endpoint.keys())
    table_rows: list[dict[str, Any]] = []
    if len(endpoints) == 2:
        left, right = endpoints
        rpms = sorted(set(rows_by_endpoint.get(left, {}).keys()) | set(rows_by_endpoint.get(right, {}).keys()))
        for rpm in rpms:
            lrow = rows_by_endpoint.get(left, {}).get(rpm, {})
            rrow = rows_by_endpoint.get(right, {}).get(rpm, {})
            table_rows.append(
                {
                    "offered_rpm": rpm,
                    f"{left}_point_valid": lrow.get("point_valid"),
                    f"{right}_point_valid": rrow.get("point_valid"),
                    f"{left}_throughput_success_rps_mean": lrow.get("throughput_success_rps_mean"),
                    f"{right}_throughput_success_rps_mean": rrow.get("throughput_success_rps_mean"),
                    f"{left}_latency_p95_s_mean": lrow.get("latency_p95_s_mean"),
                    f"{right}_latency_p95_s_mean": rrow.get("latency_p95_s_mean"),
                    f"{left}_timeout_rate_mean": lrow.get("timeout_rate_mean"),
                    f"{right}_timeout_rate_mean": rrow.get("timeout_rate_mean"),
                    f"{left}_error_rate_total_mean": lrow.get("error_rate_total_mean"),
                    f"{right}_error_rate_total_mean": rrow.get("error_rate_total_mean"),
                    "shared_valid": rpm in shared_valid_rpms,
                }
            )

    out_json = analysis_dir / "pair_comparison.json"
    out_csv = analysis_dir / "pair_comparison.csv"
    out_md = analysis_dir / "pair_comparison.md"

    out_json.write_text(
        json.dumps(
            {
                "parent_dir": str(parent_dir),
                "child_batches": child_meta,
                "validity_coverage": validity,
                "shared_valid_offered_rpms": shared_valid_rpms,
                "primary_metrics": metric_results,
                "rows": table_rows,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    if table_rows:
        write_csv(out_csv, list(table_rows[0].keys()), table_rows)
        header = list(table_rows[0].keys())
        rows = [[str(row.get(h, "")) for h in header] for row in table_rows]
        save_markdown_table(
            out_md,
            header=header,
            rows=rows,
            title="Pair Comparison Report",
            intro_lines=[f"Parent compare dir: `{parent_dir}`"],
        )
    else:
        write_csv(out_csv, ["offered_rpm"], [])
        out_md.write_text("# Pair Comparison Report\n\nNo pair comparison rows were produced.\n", encoding="utf-8")
    return out_json, out_csv, out_md


def main() -> int:
    parser = argparse.ArgumentParser(description="Build isolated pair comparison artifacts")
    parser.add_argument("parent_dir", help="Path to bench/results/compare_<timestamp>")
    parser.add_argument("--pair-plan", default=None, help="Path to pair_plan.json (default: <parent>/pair_plan.json)")
    parser.add_argument("--prereg", default=None, help="Path to preregistration JSON")
    args = parser.parse_args()

    parent_dir = Path(args.parent_dir)
    analysis_dir = parent_dir / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    pair_plan_path = Path(args.pair_plan) if args.pair_plan else (parent_dir / "pair_plan.json")
    prereg_path = Path(args.prereg) if args.prereg else (parent_dir.parents[1] / "preregistration.json")

    pair_plan = load_json(pair_plan_path) or {}
    prereg = load_json(prereg_path) or {}
    children = pair_plan.get("children") if isinstance(pair_plan, dict) else None
    if not isinstance(children, list) or not children:
        raise SystemExit(f"pair plan has no children: {pair_plan_path}")

    prompt_set = str((prereg.get("scope") or {}).get("prompt_set") or "in_scope")
    expected_reps = int((pair_plan.get("pair_repetitions") if isinstance(pair_plan, dict) else None) or 0)
    if expected_reps <= 0:
        design = prereg.get("design") or {}
        sweep_track = design.get("sweep_track") if isinstance(design, dict) else {}
        expected_reps = int(((sweep_track or {}).get("stage1_primary") or {}).get("repetitions") or 1)

    rep_rows: list[dict[str, Any]] = []
    child_meta: list[dict[str, Any]] = []
    discovered_measure_counter_bases: set[str] = {str(base) for base in FAILURE_MODE_COUNTER_BASES}

    for entry in children:
        if not isinstance(entry, dict):
            continue
        child_dir = resolve_results_dir(str(entry.get("results_dir") or ""), parent_dir)
        child_manifest = load_json(child_dir / "manifest.json") or {}
        child_csv = child_dir / "analysis" / "sweep_points.csv"
        child_rows = load_csv_rows(child_csv)
        child_agg_rows = load_csv_rows(child_dir / "analysis" / "sweep_points_agg.csv")
        pair_rep = int(entry.get("pair_rep") or 0)
        endpoint = str(entry.get("endpoint") or "").strip()
        child_batch_id = str(entry.get("child_batch_id") or child_dir.name)
        pair_order = str(entry.get("pair_order") or "").strip()
        pair_prompt_seed = entry.get("pair_prompt_seed")
        child_primary_agg = [row for row in child_agg_rows if str(row.get("run_tags") or "") == "sweep_primary"]
        primary_prompt_mix_ok = bool(child_primary_agg) and all(bool(row.get("point_prompt_mix_valid")) for row in child_primary_agg)
        if not primary_prompt_mix_ok:
            print(f"WARNING: child batch has prompt-mix-invalid or missing primary aggregate rows: {child_dir}", file=sys.stderr)
            print(f"WARNING: skipping this child batch from comparison analysis", file=sys.stderr)
            continue

        child_meta.append(
            {
                "pair_rep": pair_rep,
                "endpoint": endpoint,
                "child_batch_id": child_batch_id,
                "pair_order": pair_order,
                "pair_prompt_seed": pair_prompt_seed,
                "primary_prompt_mix_ok": primary_prompt_mix_ok,
                "results_dir": str(child_dir),
                "manifest": str(child_dir / "manifest.json"),
                "manifest_batch_kind": child_manifest.get("batch_kind"),
            }
        )

        for row in child_rows:
            if str(row.get("run_tag") or "") != "sweep_primary":
                continue
            if str(row.get("prompt_set") or "") != prompt_set:
                continue
            merged = dict(row)
            merged["rep"] = pair_rep
            merged["target_endpoint"] = endpoint
            merged["parent_compare_id"] = pair_plan.get("parent_compare_id")
            merged["child_batch_id"] = child_batch_id
            merged["pair_rep"] = pair_rep
            merged["pair_order"] = pair_order
            merged["pair_prompt_seed"] = pair_prompt_seed
            rep_rows.append(merged)
            for key in merged.keys():
                if key.endswith("_count"):
                    base = key[: -len("_count")]
                    if base.endswith("_measure") and base not in {
                        "attempts_measure",
                        "successes_measure",
                        "timeouts_measure",
                        "errors_total_measure",
                        "errors_non_timeout_measure",
                    }:
                        discovered_measure_counter_bases.add(base)

    rep_rows.sort(key=lambda row: (str(row.get("endpoint") or ""), int(row.get("offered_rpm") or 0), int(row.get("rep") or 0)))
    if not rep_rows:
        raise SystemExit("no sweep_primary rep rows found across isolated child batches")

    rep_csv = analysis_dir / "sweep_points.csv"
    write_csv(rep_csv, build_rep_fields(discovered_measure_counter_bases), rep_rows)

    agg_rows, by_point_all = aggregate_points(
        rep_rows,
        discovered_measure_counter_bases=discovered_measure_counter_bases,
        expected_reps=expected_reps,
        bootstrap_iters=5000,
        bootstrap_seed=0,
        error_non_timeout_max=None,
        seed_bump=0,
    )
    mark_pareto_best_tradeoffs(agg_rows)
    agg_csv = analysis_dir / "sweep_points_agg.csv"
    write_csv(agg_csv, build_agg_fields(discovered_measure_counter_bases), agg_rows)

    invalid_csv = analysis_dir / "invalid_points.csv"
    invalid_rows = build_invalid_rows(rep_rows, agg_rows, by_point_all, expected_reps)
    write_csv(
        invalid_csv,
        ["row_type", "run_id", "run_tag", "endpoint", "prompt_set", "offered_rpm", "rep", "reason_codes"],
        invalid_rows,
    )

    prompt_md = analysis_dir / "prompt_mix_report.md"
    build_prompt_mix_report(prompt_md, parent_dir, child_meta, rep_rows)

    gates = prereg.get("gates") or {}
    timeout_rate_max = float(((gates.get("timeout_compliance") or {}).get("timeout_rate_max") or 0.01))
    knee_detection = prereg.get("knee_detection") or {}
    piecewise = knee_detection.get("piecewise_regression") or {}
    args_ns = argparse.Namespace(
        timeout_rate_max=timeout_rate_max,
        error_non_timeout_max=None,
        expected_prompts=None,
        require_prompt_tags=False,
        enforce_validity=False,
        expected_reps=expected_reps,
        bootstrap_iters=5000,
        bootstrap_seed=0,
        knee_min_points_per_seg=int(piecewise.get("min_points_per_segment") or 2),
        knee_p95_slope_factor=float(((piecewise.get("p95") or {}).get("slope_factor") or 2.5)),
        knee_p95_slope_abs_threshold=float(((piecewise.get("p95") or {}).get("slope_abs_threshold_s_per_rpm") or 0.005)),
        knee_error_slope_factor=float(((piecewise.get("error_rate_total") or {}).get("slope_factor") or 3.0)),
        knee_error_slope_abs_threshold=float(((piecewise.get("error_rate_total") or {}).get("slope_abs_threshold_per_rpm") or 0.001)),
    )
    cohorts_all = build_sorted_cohorts(agg_rows)
    cohorts_knee = build_sorted_cohorts(agg_rows)
    knee_report = compute_knee_report(
        results_dir=parent_dir,
        args=args_ns,
        include_run_tags=["sweep_primary"],
        knee_run_tags=["sweep_primary"],
        warnings=[],
        cohorts_all=cohorts_all,
        cohorts_knee=cohorts_knee,
    )
    caption_metas = build_parent_caption_metas(
        agg_rows=agg_rows,
        invalid_rows=invalid_rows,
        knee_report=knee_report,
        prompt_set=prompt_set,
    )
    standard_plot_stems = [
        "compare_throughput_over_rpm",
        "compare_latency_p95_over_rpm",
        "compare_error_rate_over_rpm",
    ]
    support_plot_stems = [
        "compare_validity_coverage_over_rpm",
        "compare_sustainability_summary",
        "compare_throughput_latency_frontier",
    ]
    write_knee_reports(analysis_dir, parent_dir, knee_report, args_ns)
    generate_plots(
        analysis_dir,
        cohorts_all,
        file_prefix="compare_",
        title_prefix="",
        caption_meta_by_stem={stem: caption_metas[stem] for stem in standard_plot_stems},
    )
    validity_plot = write_validity_coverage_plot(
        analysis_dir,
        agg_rows,
        caption_meta=caption_metas.get("compare_validity_coverage_over_rpm"),
    )
    sustainability_plot = write_sustainability_summary_plot(
        analysis_dir,
        knee_report,
        caption_meta=caption_metas.get("compare_sustainability_summary"),
    )
    frontier_plot = write_throughput_latency_frontier_plot(
        analysis_dir,
        agg_rows,
        caption_meta=caption_metas.get("compare_throughput_latency_frontier"),
    )

    build_pair_comparison_outputs(analysis_dir, parent_dir, agg_rows, child_meta)
    figure_index = write_figure_references_index(
        analysis_dir,
        figure_order=standard_plot_stems + support_plot_stems,
        caption_metas=caption_metas,
    )

    print(f"Wrote {rep_csv}")
    print(f"Wrote {agg_csv}")
    print(f"Wrote {invalid_csv}")
    print(f"Wrote {prompt_md}")
    print(f"Wrote {analysis_dir / 'knee_report.json'}")
    print(f"Wrote {analysis_dir / 'knee_report.md'}")
    print(f"Wrote {analysis_dir / 'compare_throughput_over_rpm.png'}")
    print(f"Wrote {analysis_dir / 'compare_latency_p95_over_rpm.png'}")
    print(f"Wrote {analysis_dir / 'compare_error_rate_over_rpm.png'}")
    print(f"Wrote {analysis_dir / 'compare_throughput_over_rpm.caption.md'}")
    print(f"Wrote {analysis_dir / 'compare_latency_p95_over_rpm.caption.md'}")
    print(f"Wrote {analysis_dir / 'compare_error_rate_over_rpm.caption.md'}")
    if validity_plot is not None:
        print(f"Wrote {validity_plot}")
        print(f"Wrote {analysis_dir / 'compare_validity_coverage_over_rpm.caption.md'}")
    if sustainability_plot is not None:
        print(f"Wrote {sustainability_plot}")
        print(f"Wrote {analysis_dir / 'compare_sustainability_summary.caption.md'}")
    if frontier_plot is not None:
        print(f"Wrote {frontier_plot}")
        print(f"Wrote {analysis_dir / 'compare_throughput_latency_frontier.caption.md'}")
    print(f"Wrote {figure_index}")
    print(f"Wrote {analysis_dir / 'pair_comparison.json'}")
    print(f"Wrote {analysis_dir / 'pair_comparison.csv'}")
    print(f"Wrote {analysis_dir / 'pair_comparison.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

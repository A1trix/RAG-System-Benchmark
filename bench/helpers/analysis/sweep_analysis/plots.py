from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional, Sequence

from .metrics import as_float


THESIS_ENDPOINT_COLORS: dict[str, str] = {
    "rag": "#4C78A8",
    "n8n": "#F58518",
}


def _apply_thesis_style(plt: Any) -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "figure.dpi": 160,
            "axes.titlesize": 12,
            "axes.labelsize": 10,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "legend.fontsize": 8,
            "axes.titlepad": 10.0,
            "axes.linewidth": 0.8,
            "grid.alpha": 0.35,
            "grid.linestyle": ":",
            "grid.linewidth": 0.7,
            "savefig.bbox": "tight",
        }
    )


def ensure_matplotlib() -> Any:
    try:
        mplconfigdir = os.environ.get("MPLCONFIGDIR")
        if not mplconfigdir:
            mplconfigdir = str(Path(tempfile.gettempdir()) / "matplotlib")
            os.environ["MPLCONFIGDIR"] = mplconfigdir
        Path(mplconfigdir).mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    try:
        import importlib

        matplotlib = importlib.import_module("matplotlib")
        matplotlib.use("Agg")
        plt = importlib.import_module("matplotlib.pyplot")
        _apply_thesis_style(plt)
        return plt
    except Exception as exc:
        raise RuntimeError(f"matplotlib required for plots: {exc}")


def display_name_for_endpoint(endpoint: str) -> str:
    endpoint_key = str(endpoint or "").strip().lower()
    return {
        "rag": "RAG service",
        "n8n": "n8n workflow",
    }.get(endpoint_key, str(endpoint or ""))


def display_name_for_prompt_set(prompt_set: str) -> str:
    prompt_key = str(prompt_set or "").strip().lower()
    return {
        "in_scope": "in-scope prompts",
    }.get(prompt_key, prompt_key.replace("_", " "))


def color_for_endpoint(endpoint: str, fallback: Any = None) -> Any:
    endpoint_key = str(endpoint or "").strip().lower().split(":", 1)[0]
    return THESIS_ENDPOINT_COLORS.get(endpoint_key, fallback)


def style_axes(ax: Any, *, grid_axis: str = "both") -> None:
    ax.grid(True, axis=grid_axis, linestyle=":", linewidth=0.7, alpha=0.35)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#6b7280")
    ax.spines["bottom"].set_color("#6b7280")
    ax.spines["left"].set_linewidth(0.8)
    ax.spines["bottom"].set_linewidth(0.8)


def write_caption_sidecar(out_base: Path, caption_meta: dict[str, Any] | None) -> Path | None:
    if not caption_meta:
        return None

    title = str(caption_meta.get("title") or out_base.name)
    label = str(caption_meta.get("label") or "")
    short_caption = str(caption_meta.get("short_caption") or "")
    caption = str(caption_meta.get("caption") or "")
    limitation = str(caption_meta.get("limitation") or "")
    usage_note = str(caption_meta.get("usage_note") or "")
    png_name = out_base.with_suffix(".png").name
    pdf_name = out_base.with_suffix(".pdf").name
    sidecar_path = out_base.with_suffix(".caption.md")

    latex_lines: list[str] = []
    if label and short_caption:
        latex_lines = [
            "```tex",
            "\\begin{figure}[htbp]",
            "  \\centering",
            f"  \\includegraphics[width=\\linewidth]{{{pdf_name}}}",
            f"  \\caption{{{short_caption}}}",
            f"  \\label{{{label}}}",
            "\\end{figure}",
            "```",
        ]

    lines = [f"# {title}", ""]
    if label:
        lines.extend([f"Label: `{label}`", ""])
    lines.extend(["Files:", f"- `{png_name}`", f"- `{pdf_name}`", ""])
    if short_caption:
        lines.extend([f"Short caption: {short_caption}", ""])
    if caption:
        lines.extend([f"Caption: {caption}", ""])
    if limitation:
        lines.extend([f"Limitation: {limitation}", ""])
    if usage_note:
        lines.extend([f"Usage note: {usage_note}", ""])
    if latex_lines:
        lines.extend(["Suggested LaTeX:", *latex_lines, ""])

    sidecar_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return sidecar_path


def save_figure_outputs(fig: Any, out_base: Path, caption_meta: dict[str, Any] | None = None) -> dict[str, Path | None]:
    fig.tight_layout()
    png = out_base.with_suffix(".png")
    pdf = out_base.with_suffix(".pdf")
    fig.savefig(png)
    fig.savefig(pdf)
    caption_path = write_caption_sidecar(out_base, caption_meta)
    return {"png": png, "pdf": pdf, "caption": caption_path}


def plot_xy(
    plt: Any,
    out_base: Path,
    title: str,
    x_label: str,
    y_label: str,
    series: list[dict[str, Any]],
    annotate_rpm: bool = True,
    y_log: bool = False,
    y_min: float | None = None,
    y_max: float | None = None,
    note_text: str | None = None,
    legend_loc: str = "best",
    caption_meta: dict[str, Any] | None = None,
) -> None:
    fig, ax = plt.subplots(figsize=(8.2, 5.0), dpi=160)
    plotted_any = False
    for s in series:
        xs = s.get("x") or []
        ys = s.get("y") or []
        if not xs or not ys:
            continue
        plotted_any = True
        xerr = s.get("xerr")
        yerr = s.get("yerr")
        label = s.get("label")
        marker = s.get("marker", "o")
        line = bool(s.get("line", True))
        linewidth = float(s.get("linewidth") or (1.6 if line else 0.0))
        markersize = float(s.get("markersize") or 5.0)
        color = s.get("color")
        fmt = f"-{marker}" if line else marker
        ax.errorbar(
            xs,
            ys,
            xerr=xerr,
            yerr=yerr,
            fmt=fmt,
            color=color,
            ecolor=color,
            capsize=3,
            linewidth=linewidth,
            markersize=markersize,
            label=label,
            alpha=0.92,
        )
        if annotate_rpm:
            rpms = s.get("rpm") or []
            for xi, yi, rpm in zip(xs, ys, rpms):
                if xi is None or yi is None or rpm is None:
                    continue
                ax.annotate(f"{rpm} RPM", (xi, yi), textcoords="offset points", xytext=(5, 4), fontsize=7)

    ax.set_title(title)
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    if y_log:
        ax.set_yscale("log")
    if y_min is not None or y_max is not None:
        bottom, top = ax.get_ylim()
        if y_min is not None:
            bottom = float(y_min)
        if y_max is not None:
            top = float(y_max)
        if top <= bottom:
            top = bottom + 1.0
        ax.set_ylim(bottom=bottom, top=top)
    style_axes(ax)
    if plotted_any and any(s.get("label") for s in series):
        ax.legend(loc=legend_loc, fontsize=8)
    if note_text:
        ax.text(
            0.02,
            0.96,
            note_text,
            transform=ax.transAxes,
            va="top",
            ha="left",
            fontsize=8,
            bbox={"facecolor": "white", "edgecolor": "#d1d5db", "boxstyle": "round,pad=0.3", "alpha": 0.92},
        )

    save_figure_outputs(fig, out_base, caption_meta=caption_meta)
    plt.close(fig)


def clear_plot_outputs(analysis_dir: Path) -> None:
    for pattern in ("*.png", "*.pdf", "*.caption.md"):
        for path in analysis_dir.glob(pattern):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
    figure_index = analysis_dir / "figure_references.md"
    if figure_index.exists():
        try:
            figure_index.unlink()
        except FileNotFoundError:
            pass


def filter_xy_points(
    rpms_in: list[int],
    x_in: Sequence[Optional[float]],
    y_in: Sequence[Optional[float]],
    xerr_in: Sequence[Optional[float]] | None = None,
    yerr_in: Sequence[Optional[float]] | None = None,
) -> tuple[list[int], list[float], list[float], list[float] | None, list[float] | None]:
    rpms_out: list[int] = []
    x_out: list[float] = []
    y_out: list[float] = []
    xerr_out: list[float] = []
    yerr_out: list[float] = []
    for i, (rpm, x, y) in enumerate(zip(rpms_in, x_in, y_in)):
        if x is None or y is None:
            continue
        try:
            xf = float(x)
            yf = float(y)
        except Exception:
            continue
        rpms_out.append(int(rpm))
        x_out.append(xf)
        y_out.append(yf)
        if xerr_in is not None:
            xe = xerr_in[i] if i < len(xerr_in) else None
            xerr_out.append(float(xe) if xe is not None else 0.0)
        if yerr_in is not None:
            ye = yerr_in[i] if i < len(yerr_in) else None
            yerr_out.append(float(ye) if ye is not None else 0.0)
    return (
        rpms_out,
        x_out,
        y_out,
        xerr_out if xerr_in is not None else None,
        yerr_out if yerr_in is not None else None,
    )


def sorted_valid_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows_sorted = sorted(rows, key=lambda r: int(r.get("offered_rpm") or 0))
    return [r for r in rows_sorted if bool(r.get("point_valid"))]


def build_single_series(
    rows: list[dict[str, Any]],
    y_field: str,
    ysd_field: str,
    marker: str = "o",
    label: str | None = None,
    color: Any = None,
) -> dict[str, Any]:
    rows_sorted = sorted_valid_rows(rows)
    rpms = [int(r.get("offered_rpm") or 0) for r in rows_sorted]
    x: list[Optional[float]] = [float(int(r.get("offered_rpm") or 0)) for r in rows_sorted]
    y: list[Optional[float]] = [as_float(r.get(y_field)) for r in rows_sorted]
    ysd: list[Optional[float]] = [as_float(r.get(ysd_field)) for r in rows_sorted]
    rp, xx, yy, _, yee = filter_xy_points(rpms, x, y, None, ysd)
    return {
        "label": label,
        "x": xx,
        "y": yy,
        "yerr": yee,
        "rpm": rp,
        "marker": marker,
        "line": True,
        "color": color,
    }


def series_for_plot(
    cohort_list: list[tuple[tuple[str, str], list[dict[str, Any]]]],
    y_field: str,
    ysd_field: str,
    markers: list[str],
    include_prompt_set: bool,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, ((endpoint, prompt_set), rows) in enumerate(cohort_list):
        endpoint_label = display_name_for_endpoint(endpoint)
        label = f"{endpoint_label} ({display_name_for_prompt_set(prompt_set)})" if include_prompt_set else endpoint_label
        out.append(
            build_single_series(
                rows,
                y_field,
                ysd_field,
                marker=markers[idx % len(markers)],
                label=label,
                color=color_for_endpoint(endpoint),
            )
        )
    return out


def plot_standard_outputs(
    plt: Any,
    analysis_dir: Path,
    throughput_series: list[dict[str, Any]],
    latency_series: list[dict[str, Any]],
    error_series: list[dict[str, Any]],
    *,
    file_prefix: str = "",
    title_prefix: str = "",
    annotate_rpm: bool = False,
    caption_meta_by_stem: dict[str, dict[str, Any]] | None = None,
) -> None:
    prefix = file_prefix or ""
    caption_meta_by_stem = caption_meta_by_stem or {}
    error_has_positive = any(any((y or 0.0) > 0.0 for y in (series.get("y") or [])) for series in error_series)
    error_y_max = None if error_has_positive else 0.01
    error_note = None if error_has_positive else "No observed errors at valid points"

    throughput_stem = f"{prefix}throughput_over_rpm"
    latency_stem = f"{prefix}latency_p95_over_rpm"
    error_stem = f"{prefix}error_rate_over_rpm"

    plot_xy(
        plt,
        analysis_dir / throughput_stem,
        title=f"{title_prefix}Successful Throughput over Offered Load",
        x_label="Offered load (RPM)",
        y_label="Successful throughput (requests/s)",
        series=throughput_series,
        annotate_rpm=annotate_rpm,
        y_min=0.0,
        caption_meta=caption_meta_by_stem.get(throughput_stem),
    )
    plot_xy(
        plt,
        analysis_dir / latency_stem,
        title=f"{title_prefix}p95 Latency over Offered Load",
        x_label="Offered load (RPM)",
        y_label="p95 latency (s)",
        series=latency_series,
        annotate_rpm=annotate_rpm,
        y_min=0.0,
        caption_meta=caption_meta_by_stem.get(latency_stem),
    )
    plot_xy(
        plt,
        analysis_dir / error_stem,
        title=f"{title_prefix}Total Error Rate over Offered Load",
        x_label="Offered load (RPM)",
        y_label="Total error rate",
        series=error_series,
        annotate_rpm=annotate_rpm,
        y_min=0.0,
        y_max=error_y_max,
        note_text=error_note,
        caption_meta=caption_meta_by_stem.get(error_stem),
    )


def plot_single_cohort_generic_outputs(
    plt: Any,
    analysis_dir: Path,
    endpoint: str,
    prompt_set: str,
    rows: list[dict[str, Any]],
    *,
    file_prefix: str = "",
    title_prefix: str = "",
    caption_meta_by_stem: dict[str, dict[str, Any]] | None = None,
) -> None:
    default_prefix = f"{display_name_for_endpoint(endpoint)} ({display_name_for_prompt_set(prompt_set)}): "
    plot_standard_outputs(
        plt,
        analysis_dir,
        throughput_series=[build_single_series(rows, "throughput_success_rps_mean", "throughput_success_rps_sd", color=color_for_endpoint(endpoint))],
        latency_series=[build_single_series(rows, "latency_p95_s_mean", "latency_p95_s_sd", color=color_for_endpoint(endpoint))],
        error_series=[build_single_series(rows, "error_rate_total_mean", "error_rate_total_sd", color=color_for_endpoint(endpoint))],
        file_prefix=file_prefix,
        title_prefix=title_prefix or default_prefix,
        annotate_rpm=False,
        caption_meta_by_stem=caption_meta_by_stem,
    )


def plot_multi_cohort_generic_outputs(
    plt: Any,
    analysis_dir: Path,
    cohort_list: list[tuple[tuple[str, str], list[dict[str, Any]]]],
    *,
    file_prefix: str = "",
    title_prefix: str = "",
    caption_meta_by_stem: dict[str, dict[str, Any]] | None = None,
) -> None:
    markers = ["o", "s", "^", "D", "v", "P", "X"]
    include_prompt_set = len({prompt_set for (_, prompt_set), _ in cohort_list}) > 1
    plot_standard_outputs(
        plt,
        analysis_dir,
        throughput_series=series_for_plot(
            cohort_list,
            "throughput_success_rps_mean",
            "throughput_success_rps_sd",
            markers,
            include_prompt_set,
        ),
        latency_series=series_for_plot(
            cohort_list,
            "latency_p95_s_mean",
            "latency_p95_s_sd",
            markers,
            include_prompt_set,
        ),
        error_series=series_for_plot(
            cohort_list,
            "error_rate_total_mean",
            "error_rate_total_sd",
            markers,
            include_prompt_set,
        ),
        file_prefix=file_prefix,
        title_prefix=title_prefix,
        annotate_rpm=False,
        caption_meta_by_stem=caption_meta_by_stem,
    )


def generate_plots(
    analysis_dir: Path,
    cohorts_all: dict[tuple[str, str], list[dict[str, Any]]],
    *,
    file_prefix: str = "",
    title_prefix: str = "",
    caption_meta_by_stem: dict[str, dict[str, Any]] | None = None,
) -> None:
    try:
        plt = ensure_matplotlib()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return

    clear_plot_outputs(analysis_dir)

    cohort_list = sorted(cohorts_all.items(), key=lambda kv: (kv[0][0], kv[0][1]))
    if not cohort_list:
        return
    if len(cohort_list) == 1:
        (endpoint, prompt_set), rows = cohort_list[0]
        plot_single_cohort_generic_outputs(
            plt,
            analysis_dir,
            endpoint,
            prompt_set,
            rows,
            file_prefix=file_prefix,
            title_prefix=title_prefix,
            caption_meta_by_stem=caption_meta_by_stem,
        )
    else:
        plot_multi_cohort_generic_outputs(
            plt,
            analysis_dir,
            cohort_list,
            file_prefix=file_prefix,
            title_prefix=title_prefix,
            caption_meta_by_stem=caption_meta_by_stem,
        )


def _calc_correlation(x, y):
    """Calculate Pearson correlation coefficient between two sequences."""
    try:
        import numpy as np
        x_arr = np.array(x, dtype=float)
        y_arr = np.array(y, dtype=float)
        mask = np.isfinite(x_arr) & np.isfinite(y_arr)
        x_clean = x_arr[mask]
        y_clean = y_arr[mask]
        if len(x_clean) < 2:
            return 0.0
        return float(np.corrcoef(x_clean, y_clean)[0, 1])
    except Exception:
        return 0.0


def plot_token_latency_correlation(
    plt,
    analysis_dir,
    cohorts_all,
    *,
    file_prefix="",
    title_prefix="",
    caption_meta_by_stem=None,
):
    """Generate scatter plot showing token usage vs latency correlation."""
    from .aggregation import mean_sd

    caption_meta_by_stem = caption_meta_by_stem or {}
    prefix = file_prefix or ""
    stem = f"{prefix}token_latency_correlation"
    out_path = analysis_dir / stem

    cohort_list = sorted(cohorts_all.items(), key=lambda kv: (kv[0][0], kv[0][1]))
    if not cohort_list:
        return

    fig, ax = plt.subplots(figsize=(8, 6))
    _apply_thesis_style(plt)

    all_x = []
    all_y = []
    colors_by_endpoint = {}

    for (endpoint, prompt_set), rows in cohort_list:
        x_vals = []  # latency_p95_s
        y_vals = []  # tokens_total

        for r in rows:
            latency = as_float(r.get("latency_p95_s_mean"))
            tokens = as_float(r.get("tokens_total_mean"))
            if latency is not None and tokens is not None:
                x_vals.append(latency)
                y_vals.append(tokens)
                all_x.append(latency)
                all_y.append(tokens)

        if x_vals and y_vals:
            color = color_for_endpoint(endpoint)
            colors_by_endpoint[endpoint] = color
            ax.scatter(
                x_vals,
                y_vals,
                marker="o",
                s=80,
                alpha=0.6,
                color=color,
                label=display_name_for_endpoint(endpoint),
                edgecolors="white",
                linewidths=0.5,
            )

    if all_x and all_y:
        # Add trend line
        try:
            import numpy as np
            x_arr = np.array(all_x)
            y_arr = np.array(all_y)
            z = np.polyfit(x_arr, y_arr, 1)
            p = np.poly1d(z)
            x_line = np.linspace(min(all_x), max(all_x), 100)
            ax.plot(x_line, p(x_line), "--", color="#6b7280", alpha=0.5, linewidth=1.5)
        except Exception:
            pass

        # Calculate and display correlation
        corr = _calc_correlation(all_x, all_y)
        ax.text(
            0.95,
            0.05,
            f"Pearson r = {corr:.3f}",
            transform=ax.transAxes,
            ha="right",
            va="bottom",
            fontsize=9,
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.8),
        )

    ax.set_xlabel("p95 Latency (s)", fontsize=10)
    ax.set_ylabel("Total Tokens per Successful Request", fontsize=10)
    ax.set_title(
        f"{title_prefix}Token Usage vs Latency Correlation", fontsize=12
    )
    style_axes(ax)

    if len(colors_by_endpoint) > 1:
        ax.legend(loc="best", fontsize=8)

    fig.savefig(f"{out_path}.png", dpi=160, bbox_inches="tight")
    fig.savefig(f"{out_path}.pdf", bbox_inches="tight")
    plt.close(fig)

    write_caption_sidecar(out_path, caption_meta_by_stem.get(stem))


def plot_token_efficiency(
    plt,
    analysis_dir,
    cohorts_all,
    *,
    file_prefix="",
    title_prefix="",
    caption_meta_by_stem=None,
):
    """Generate plot showing tokens per throughput (efficiency metric)."""
    from .aggregation import mean_sd

    caption_meta_by_stem = caption_meta_by_stem or {}
    prefix = file_prefix or ""
    stem = f"{prefix}token_efficiency"
    out_path = analysis_dir / stem

    cohort_list = sorted(cohorts_all.items(), key=lambda kv: (kv[0][0], kv[0][1]))
    if not cohort_list:
        return

    fig, ax = plt.subplots(figsize=(8, 6))
    _apply_thesis_style(plt)

    markers = ["o", "s", "^", "D", "v", "P", "X"]
    marker_idx = 0

    for (endpoint, prompt_set), rows in cohort_list:
        x_vals = []  # throughput_success_rps
        y_vals = []  # tokens_total

        for r in rows:
            throughput = as_float(r.get("throughput_success_rps_mean"))
            tokens = as_float(r.get("tokens_total_mean"))
            if throughput is not None and tokens is not None and throughput > 0:
                x_vals.append(throughput)
                y_vals.append(tokens)

        if x_vals and y_vals:
            color = color_for_endpoint(endpoint)
            marker = markers[marker_idx % len(markers)]
            marker_idx += 1
            ax.plot(
                x_vals,
                y_vals,
                marker=marker,
                markersize=6,
                linewidth=1.5,
                alpha=0.8,
                color=color,
                label=f"{display_name_for_endpoint(endpoint)}",
            )

    ax.set_xlabel("Throughput (requests/s)", fontsize=10)
    ax.set_ylabel("Total Tokens per Successful Request", fontsize=10)
    ax.set_title(
        f"{title_prefix}Token Efficiency vs Throughput", fontsize=12
    )
    style_axes(ax)
    ax.legend(loc="best", fontsize=8)

    fig.savefig(f"{out_path}.png", dpi=160, bbox_inches="tight")
    fig.savefig(f"{out_path}.pdf", bbox_inches="tight")
    plt.close(fig)

    write_caption_sidecar(out_path, caption_meta_by_stem.get(stem))

# src/dashboard/charts.py
#
# Three chart builders that read from the metrics dict produced by timer.py.
#
# ── CPU scale contract ────────────────────────────────────────────────────────
# All CPU fields are on the 0-100 % scale (100 % = full system capacity).
# Three slices always sum to exactly 100 %:
#
#   cpu_proc_avg_percent      pipeline process
#   cpu_others_avg_percent    other processes
#   cpu_free_percent          genuinely idle
#
# Peak marker uses cpu_sys_peak_percent (same 0-100 scale).
# Card values and chart bars therefore show identical numbers.
#
# ── RAM contract ──────────────────────────────────────────────────────────────
# ram_others_avg_mb is derived from (total − available) − pipeline_rss so it
# correctly excludes OS file-cache inflation.  Three RAM slices always sum to
# system total RAM.
#
# ── Hover behaviour ───────────────────────────────────────────────────────────
# CPU and RAM charts use hovermode="x unified" — one hover shows all stacked
# layers plus the peak marker simultaneously.
#
# ── Extensibility ─────────────────────────────────────────────────────────────
# Sub-process display labels are driven by STEP_LABEL_MAP in config/settings.py.
# Add a new sub-process there — no changes needed here.

from __future__ import annotations

import psutil
import plotly.graph_objects as go
from plotly.graph_objects import Figure

from config.settings import STEP_LABEL_MAP

# ── Palette ────────────────────────────────────────────────────────────────────
_BLUE        = "#2563EB"
_BLUE_FREE   = "#DBEAFE"
_AMBER       = "#F59E0B"
_AMBER_LIGHT = "#FCD34D"
_GREEN_FREE  = "#D1FAE5"
_SLATE       = "#475569"
_GRID        = "rgba(148,163,184,0.2)"

_FONT = dict(
    family="'IBM Plex Mono', 'Courier New', monospace",
    size=12,
    color="#1e293b",
)
_HOVER_STYLE = dict(
    bgcolor="#1e293b",
    bordercolor="#334155",
    font=dict(
        family="'IBM Plex Mono', 'Courier New', monospace",
        size=12,
        color="#f1f5f9",
    ),
)

_CPU_CORES    = psutil.cpu_count(logical=True) or 1
_TOTAL_RAM_MB = psutil.virtual_memory().total / 1024 ** 2


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _step_labels(perf_steps: dict) -> list[str]:
    return [k.replace("_", " ").title() for k in perf_steps]


def _get(v: dict, *keys: str, default: float = 0.0) -> float:
    """Return the value of the first matching key, or *default*."""
    for k in keys:
        if k in v:
            return v[k]
    return default


def _legend_cfg() -> dict:
    return dict(
        orientation="h",
        yanchor="top",
        y=-0.18,
        xanchor="center",
        x=0.5,
        font=dict(size=11),
    )


def _base_layout(**overrides) -> dict:
    """Return a minimal shared layout dict.  Callers can override any key."""
    base = dict(
        font=_FONT,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        legend=_legend_cfg(),
        hoverlabel=_HOVER_STYLE,
    )
    base.update(overrides)
    return base


# ── CPU stacked bar ────────────────────────────────────────────────────────────

def chart_cpu(perf_steps: dict) -> Figure:
    """
    Stacked bar: Pipeline CPU / Other Processes / Free (all 0-100 %).
    Peak shown as a diamond scatter marker.
    Unified hover shows all three slices + peak in one tooltip.
    """
    labels      = _step_labels(perf_steps)
    proc_cpu    = [_get(v, "cpu_proc_avg_percent")    for v in perf_steps.values()]
    others_cpu  = [_get(v, "cpu_others_avg_percent")  for v in perf_steps.values()]
    free_cpu    = [_get(v, "cpu_free_percent",
                        default=max(round(100 - p - o, 1), 0))
                   for v, p, o in zip(perf_steps.values(), proc_cpu, others_cpu)]
    peak_cpu    = [_get(v, "cpu_sys_peak_percent", "cpu_peak_percent")
                   for v in perf_steps.values()]
    cores_used  = [round(p / 100 * _CPU_CORES, 1) for p in proc_cpu]

    fig = go.Figure()

    # Layer 1 — pipeline process
    fig.add_trace(go.Bar(
        name="Pipeline CPU (avg %)",
        x=labels,
        y=proc_cpu,
        marker_color=_BLUE,
        text=[f"{p:.1f}%<br>~{c}c" for p, c in zip(proc_cpu, cores_used)],
        textposition="inside",
        insidetextanchor="middle",
        hovertemplate="<span style='color:#93C5FD'>Pipeline </span>  %{y:.1f}%<extra></extra>",
    ))

    # Layer 2 — other processes
    fig.add_trace(go.Bar(
        name="Other Processes CPU",
        x=labels,
        y=others_cpu,
        marker_color=_SLATE,
        marker_opacity=0.6,
        hovertemplate="<span style='color:#94a3b8'>Others   </span>  %{y:.1f}%<extra></extra>",
    ))

    # Layer 3 — genuinely idle
    fig.add_trace(go.Bar(
        name="CPU Free (actual)",
        x=labels,
        y=free_cpu,
        marker_color=_BLUE_FREE,
        marker_line_width=0,
        hovertemplate="<span style='color:#bfdbfe'>Free     </span>  %{y:.1f}%<extra></extra>",
    ))

    # Peak marker
    fig.add_trace(go.Scatter(
        name="CPU Peak %",
        x=labels,
        y=peak_cpu,
        mode="markers+text",
        marker=dict(symbol="diamond", size=10, color=_AMBER,
                    line=dict(color="#fff", width=1)),
        text=[f"peak {p:.0f}%" for p in peak_cpu],
        textposition="top center",
        textfont=dict(size=10, color=_AMBER),
        hovertemplate="<span style='color:#FCD34D'>Peak     </span>  %{y:.1f}%<extra></extra>",
    ))

    fig.update_layout(
        **_base_layout(
            barmode="stack",
            hovermode="x unified",
            margin=dict(t=40, b=40, l=70, r=80),
            xaxis=dict(title="", gridcolor=_GRID),
            yaxis=dict(title="CPU %", range=[0, 110],
                       gridcolor=_GRID, zeroline=False, title_standoff=10),
            title=dict(
                text=f"Machine: {_CPU_CORES} logical cores · 100% = full capacity",
                font=dict(size=11, color=_SLATE),
                x=0, xanchor="left", pad=dict(b=8),
            ),
        )
    )
    return fig


# ── RAM stacked bar ────────────────────────────────────────────────────────────

def chart_ram(perf_steps: dict) -> Figure:
    """
    Stacked bar: Pipeline RAM / Other Processes / Free (in MB).
    Every bar reaches system-total RAM.
    Peak shown as a diamond scatter marker.
    Unified hover shows all three slices + peak in one tooltip.
    """
    labels     = _step_labels(perf_steps)
    proc_mb    = [_get(v, "ram_avg_mb")         for v in perf_steps.values()]
    others_mb  = [_get(v, "ram_others_avg_mb")  for v in perf_steps.values()]
    peak_mb    = [_get(v, "ram_peak_mb")         for v in perf_steps.values()]
    free_mb    = [max(_TOTAL_RAM_MB - p - o, 0)  for p, o in zip(proc_mb, others_mb)]

    proc_pct   = [round(p / _TOTAL_RAM_MB * 100, 1) for p in proc_mb]
    others_pct = [round(o / _TOTAL_RAM_MB * 100, 1) for o in others_mb]
    peak_pct   = [round(p / _TOTAL_RAM_MB * 100, 1) for p in peak_mb]

    fig = go.Figure()

    fig.add_trace(go.Bar(
        name="Pipeline RAM (avg)",
        x=labels,
        y=proc_mb,
        marker_color=_AMBER,
        text=[f"{p:.0f} MB<br>({pp:.1f}%)" for p, pp in zip(proc_mb, proc_pct)],
        textposition="inside",
        insidetextanchor="middle",
        customdata=proc_pct,
        hovertemplate=(
            "<span style='color:#FCD34D'>Pipeline </span>"
            "  %{y:.0f} MB (%{customdata:.1f}%)<extra></extra>"
        ),
    ))

    fig.add_trace(go.Bar(
        name="Other Processes RAM",
        x=labels,
        y=others_mb,
        marker_color=_SLATE,
        marker_opacity=0.5,
        customdata=others_pct,
        hovertemplate=(
            "<span style='color:#94a3b8'>Others   </span>"
            "  %{y:.0f} MB (%{customdata:.1f}%)<extra></extra>"
        ),
    ))

    fig.add_trace(go.Bar(
        name="RAM Free (actual)",
        x=labels,
        y=free_mb,
        marker_color=_GREEN_FREE,
        marker_line_width=0,
        hovertemplate="<span style='color:#6ee7b7'>Free     </span>  %{y:.0f} MB<extra></extra>",
    ))

    fig.add_trace(go.Scatter(
        name="RAM Peak (MB)",
        x=labels,
        y=peak_mb,
        mode="markers+text",
        marker=dict(symbol="diamond", size=10, color=_AMBER_LIGHT,
                    line=dict(color="#fff", width=1)),
        text=[f"peak {p:.0f} MB ({pp:.1f}%)" for p, pp in zip(peak_mb, peak_pct)],
        textposition="top center",
        textfont=dict(size=10, color=_AMBER_LIGHT),
        customdata=peak_pct,
        hovertemplate=(
            "<span style='color:#FDE68A'>Peak     </span>"
            "  %{y:.0f} MB (%{customdata:.1f}%)<extra></extra>"
        ),
    ))

    fig.update_layout(
        **_base_layout(
            barmode="stack",
            hovermode="x unified",
            margin=dict(t=40, b=40, l=70, r=80),
            xaxis=dict(title="", gridcolor=_GRID),
            yaxis=dict(
                title="RAM (MB)",
                range=[0, _TOTAL_RAM_MB * 1.15],
                gridcolor=_GRID,
                zeroline=False,
                title_standoff=10,
            ),
            title=dict(
                text=f"System RAM: {_TOTAL_RAM_MB / 1024:.1f} GB total",
                font=dict(size=11, color=_SLATE),
                x=0, xanchor="left", pad=dict(b=8),
            ),
        )
    )
    return fig


# ── Waterfall / Gantt ──────────────────────────────────────────────────────────

def chart_waterfall(perf_steps: dict) -> Figure:
    """
    Horizontal Gantt grouped by parent step.

    Naming convention: "parent_step.sub_process" → auto-grouped.
    Top-level steps are shown as section dividers.
    Sub-processes are individual bars with duration / RAM / CPU on hover.
    Bar colour is interpolated from blue (low CPU) to amber (high CPU).
    """
    parents = {k: v for k, v in perf_steps.items() if "." not in k}
    subs    = {k: v for k, v in perf_steps.items() if "." in k}

    # ── Build row list ─────────────────────────────────────────────────────────
    rows: list[dict] = []
    cursor = 0.0

    for parent_key, parent_val in parents.items():
        parent_label = parent_key.replace("_", " ").title()
        parent_dur   = parent_val.get("duration_seconds", 0)

        rows.append(dict(
            label=parent_label.upper(),
            start=cursor,
            duration=parent_dur,
            metrics=parent_val,
            is_parent=True,
        ))

        children     = {k: v for k, v in subs.items()
                        if k.startswith(parent_key + ".")}
        child_cursor = cursor

        for child_key, child_val in children.items():
            suffix      = child_key.split(".", 1)[1]
            child_label = STEP_LABEL_MAP.get(suffix, suffix.replace("_", " ").title())
            child_dur   = child_val.get("duration_seconds", 0)

            rows.append(dict(
                label=f"    {child_label}",
                start=child_cursor,
                duration=child_dur,
                metrics=child_val,
                is_parent=False,
            ))
            child_cursor += child_dur

        cursor += parent_dur

    total = cursor

    # ── CPU-based colour interpolation (blue → amber) ─────────────────────────
    all_cpu = [
        _get(r["metrics"], "cpu_proc_avg_percent", "cpu_avg_percent")
        for r in rows if not r["is_parent"]
    ]
    max_cpu = max(all_cpu) if all_cpu else 1.0

    def _cpu_color(pct: float, is_parent: bool) -> str:
        if is_parent:
            return "rgba(100,116,139,0.15)"
        t = min(pct / max_cpu, 1.0) if max_cpu else 0.0
        r = int(37  + (245 - 37)  * t)
        g = int(99  + (158 - 99)  * t)
        b = int(235 + (11  - 235) * t)
        return f"rgb({r},{g},{b})"

    # ── Build traces ───────────────────────────────────────────────────────────
    fig      = go.Figure()
    shapes:  list[dict] = []
    y_labels = [row["label"] for row in rows]

    for row in rows:
        m       = row["metrics"]
        dur     = row["duration"]
        pct_t   = dur / total * 100 if total else 0.0
        cpu_avg = _get(m, "cpu_proc_avg_percent", "cpu_avg_percent")

        fig.add_trace(go.Bar(
            name=row["label"],
            y=[row["label"]],
            x=[dur],
            base=row["start"],
            orientation="h",
            marker_color=_cpu_color(cpu_avg, row["is_parent"]),
            marker_line_color=(
                "rgba(37,99,235,0.8)" if row["is_parent"]
                else "rgba(255,255,255,0.5)"
            ),
            marker_line_width=2 if row["is_parent"] else 1,
            text=f"  {dur:.2f}s" if not row["is_parent"] else "",
            textposition="inside",
            insidetextanchor="start",
            customdata=[[
                dur,
                _get(m, "ram_avg_mb"),
                _get(m, "ram_peak_mb"),
                cpu_avg,
                _get(m, "cpu_sys_peak_percent", "cpu_peak_percent"),
                pct_t,
            ]],
            hovertemplate=(
                "<b>%{y}</b><br>"
                "<span style='color:#475569'>──────────────────────────</span><br>"
                "<span style='color:#f1f5f9'>Duration </span>"
                "  %{customdata[0]:.3f}s &nbsp;|&nbsp; %{customdata[5]:.1f}% of total<br>"
                "<span style='color:#f1f5f9'>RAM avg  </span>  %{customdata[1]:.0f} MB<br>"
                "<span style='color:#f1f5f9'>RAM peak </span>  %{customdata[2]:.0f} MB<br>"
                "<span style='color:#f1f5f9'>CPU avg  </span>  %{customdata[3]:.1f}%<br>"
                "<span style='color:#f1f5f9'>CPU peak </span>  %{customdata[4]:.1f}%<br>"
                "<extra></extra>"
            ),
        ))

        if row["is_parent"]:
            shapes.append(dict(
                type="line",
                xref="paper", yref="y",
                x0=0, x1=1,
                y0=row["label"], y1=row["label"],
                line=dict(color="rgba(37,99,235,0.3)", width=1.5, dash="dot"),
            ))

    n_rows = len(rows)
    fig.update_layout(
        **_base_layout(
            barmode="overlay",
            margin=dict(t=50, b=60, l=200, r=80),
            showlegend=False,
            height=max(400, n_rows * 60 + 120),
            shapes=shapes,
            xaxis=dict(title="Elapsed time (seconds)",
                       gridcolor=_GRID, zeroline=False),
            yaxis=dict(
                autorange="reversed",
                gridcolor=_GRID,
                tickfont=dict(family="'IBM Plex Mono', monospace", size=11),
                tickmode="array",
                tickvals=y_labels,
                ticktext=[
                    f"<b>{r['label']}</b>" if r["is_parent"] else r["label"]
                    for r in rows
                ],
            ),
            annotations=[dict(
                x=total, y=1.04,
                xref="x", yref="paper",
                text=f"Total pipeline: {total:.2f}s",
                showarrow=False,
                font=dict(size=11, color=_SLATE),
                xanchor="right",
            )],
        )
    )
    return fig
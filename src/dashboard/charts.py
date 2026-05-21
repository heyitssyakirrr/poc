# src/dashboard/charts.py
# Performance-focused Plotly charts.
#
#   chart_cpu(perf_steps)        — stacked bar: CPU used vs available per step.
#                                  Max bar height = cores × 100%.
#                                  Annotated with estimated cores used.
#   chart_ram(perf_steps)        — stacked bar: RAM used (peak) vs free (min)
#                                  per step. Max bar height = total system RAM.
#                                  Secondary Y axis shows % of system RAM.
#   chart_waterfall(perf_steps)  — horizontal Gantt: each step placed
#                                  sequentially on a wall-clock time axis.

import psutil
import plotly.graph_objects as go
from plotly.graph_objects import Figure

# ── Palette ───────────────────────────────────────────────────────────────────
_BLUE        = "#2563EB"
_BLUE_LIGHT  = "#93C5FD"
_BLUE_FREE   = "#DBEAFE"   # free CPU headroom
_AMBER       = "#F59E0B"
_AMBER_LIGHT = "#FCD34D"
_GREEN       = "#10B981"
_GREEN_FREE  = "#D1FAE5"   # free RAM headroom
_SLATE       = "#475569"
_GRID        = "rgba(148,163,184,0.2)"
_FONT        = dict(family="'IBM Plex Mono', 'Courier New', monospace", size=12, color="#1e293b")
_MARGIN      = dict(t=60, b=40, l=70, r=80)

_CPU_CORES    = psutil.cpu_count(logical=True)
_MAX_CPU_PCT  = _CPU_CORES * 100
_TOTAL_RAM_MB = psutil.virtual_memory().total / 1024 ** 2


def _step_labels(perf_steps: dict) -> list[str]:
    return [k.replace("_", " ").title() for k in perf_steps]


# ── CPU stacked bar ───────────────────────────────────────────────────────────

def chart_cpu(perf_steps: dict) -> Figure:
    """
    Stacked bar per step:
      Bottom (blue)  = CPU avg % used   (system-wide, so can exceed 100%)
      Top    (light) = CPU % still free  = (cores × 100) - used
    Total bar always = cores × 100  → gives instant headroom context.
    Annotated with estimated cores used = used% / 100.
    """
    labels    = _step_labels(perf_steps)
    used      = [v.get("cpu_avg_percent",  0) for v in perf_steps.values()]
    peak      = [v.get("cpu_peak_percent", 0) for v in perf_steps.values()]
    free      = [max(_MAX_CPU_PCT - u, 0)     for u in used]
    est_cores = [round(u / 100, 1)            for u in used]

    fig = go.Figure()

    # Used CPU
    fig.add_trace(go.Bar(
        name="CPU Used (avg %)",
        x=labels,
        y=used,
        marker_color=_BLUE,
        text=[f"{u:.1f}%<br>~{c} cores" for u, c in zip(used, est_cores)],
        textposition="inside",
        insidetextanchor="middle",
        hovertemplate=(
            "<b>%{x}</b><br>"
            "CPU avg: %{y:.1f}%<br>"
            "Est. cores used: %{customdata:.1f} / " + str(_CPU_CORES) +
            "<extra></extra>"
        ),
        customdata=est_cores,
    ))

    # Free CPU headroom
    fig.add_trace(go.Bar(
        name="CPU Free",
        x=labels,
        y=free,
        marker_color=_BLUE_FREE,
        marker_line_width=0,
        hovertemplate=(
            "<b>%{x}</b><br>"
            "CPU free: %{y:.1f}%<br>"
            "(" + str(_CPU_CORES) + " cores × 100 = " + str(_MAX_CPU_PCT) + "% max)"
            "<extra></extra>"
        ),
    ))

    # Peak markers as scatter dots
    fig.add_trace(go.Scatter(
        name="CPU Peak %",
        x=labels,
        y=peak,
        mode="markers+text",
        marker=dict(symbol="diamond", size=10, color=_AMBER, line=dict(color="#fff", width=1)),
        text=[f"peak {p:.0f}%" for p in peak],
        textposition="top center",
        textfont=dict(size=10, color=_AMBER),
        hovertemplate="<b>%{x}</b><br>CPU peak: %{y:.1f}%<extra></extra>",
    ))

    fig.update_layout(
        barmode="stack",
        font=_FONT,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=_MARGIN,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        xaxis=dict(title="", gridcolor=_GRID),
        yaxis=dict(
            title=f"CPU % (max = {_CPU_CORES} cores × 100 = {_MAX_CPU_PCT}%)",
            range=[0, _MAX_CPU_PCT * 1.15],
            gridcolor=_GRID,
            zeroline=False,
        ),
        annotations=[dict(
            x=1, y=1.06, xref="paper", yref="paper",
            text=f"Machine: {_CPU_CORES} logical cores",
            showarrow=False,
            font=dict(size=10, color=_SLATE),
            xanchor="right",
        )],
    )
    return fig


# ── RAM stacked bar ───────────────────────────────────────────────────────────

def chart_ram(perf_steps: dict) -> Figure:
    """
    Stacked bar per step:
      Bottom (amber) = RAM peak used by process (MB)
      Top    (light) = minimum free RAM seen during step (MB)
    Total bar ≈ total system RAM → gives instant pressure context.
    Secondary Y axis shows % of total system RAM.
    """
    labels    = _step_labels(perf_steps)
    peak_mb   = [v.get("ram_peak_mb",    0) for v in perf_steps.values()]
    free_min  = [v.get("ram_free_min_mb",0) for v in perf_steps.values()]

    # % of total RAM
    peak_pct     = [round(p / _TOTAL_RAM_MB * 100, 1) for p in peak_mb]
    free_min_pct = [round(f / _TOTAL_RAM_MB * 100, 1) for f in free_min]

    fig = go.Figure()

    # Used RAM (peak)
    fig.add_trace(go.Bar(
        name="RAM Peak Used (MB)",
        x=labels,
        y=peak_mb,
        yaxis="y1",
        marker_color=_AMBER,
        text=[f"{p:.0f} MB<br>({pp:.1f}%)" for p, pp in zip(peak_mb, peak_pct)],
        textposition="inside",
        insidetextanchor="middle",
        hovertemplate=(
            "<b>%{x}</b><br>"
            "RAM peak: %{y:.0f} MB (%{customdata:.1f}% of system)<extra></extra>"
        ),
        customdata=peak_pct,
    ))

    # Free RAM (minimum during step)
    fig.add_trace(go.Bar(
        name="RAM Free (min during step)",
        x=labels,
        y=free_min,
        yaxis="y1",
        marker_color=_GREEN_FREE,
        marker_line_width=0,
        text=[f"{f:.0f} MB free<br>({fp:.1f}%)" for f, fp in zip(free_min, free_min_pct)],
        textposition="inside",
        insidetextanchor="middle",
        hovertemplate=(
            "<b>%{x}</b><br>"
            "Min free RAM: %{y:.0f} MB (%{customdata:.1f}% of system)<extra></extra>"
        ),
        customdata=free_min_pct,
    ))

    y_max_mb  = _TOTAL_RAM_MB * 1.05
    y_max_pct = 105.0

    fig.update_layout(
        barmode="stack",
        font=_FONT,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=_MARGIN,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        xaxis=dict(title="", gridcolor=_GRID),
        yaxis=dict(
            title="RAM (MB)",
            range=[0, y_max_mb],
            gridcolor=_GRID,
            zeroline=False,
        ),
        yaxis2=dict(
            title="% of system RAM",
            range=[0, y_max_pct],
            overlaying="y",
            side="right",
            showgrid=False,
            zeroline=False,
            ticksuffix="%",
        ),
        annotations=[dict(
            x=1, y=1.06, xref="paper", yref="paper",
            text=f"System RAM: {_TOTAL_RAM_MB / 1024:.1f} GB",
            showarrow=False,
            font=dict(size=10, color=_SLATE),
            xanchor="right",
        )],
    )
    return fig


# ── Waterfall / Gantt ─────────────────────────────────────────────────────────

def chart_waterfall(perf_steps: dict) -> Figure:
    """
    Horizontal Gantt — each step bar starts where the previous ended.
    Immediately shows which step dominates wall-clock time.
    """
    labels    = _step_labels(perf_steps)
    durations = [v.get("duration_seconds", 0) for v in perf_steps.values()]

    starts, cursor = [], 0.0
    for d in durations:
        starts.append(cursor)
        cursor += d

    total  = sum(durations)
    colors = [_BLUE, _AMBER, _GREEN, "#8B5CF6", "#EF4444"]

    fig = go.Figure()

    for i, (label, start, dur) in enumerate(zip(labels, starts, durations)):
        pct = dur / total * 100 if total else 0
        fig.add_trace(go.Bar(
            name=label,
            y=[label],
            x=[dur],
            base=start,
            orientation="h",
            marker_color=colors[i % len(colors)],
            text=f"  {dur:.2f}s ({pct:.1f}%)",
            textposition="inside",
            insidetextanchor="start",
            hovertemplate=(
                f"<b>{label}</b><br>"
                f"Start: {start:.2f}s<br>"
                f"Duration: {dur:.2f}s<br>"
                f"Share: {pct:.1f}%<extra></extra>"
            ),
        ))

    fig.update_layout(
        barmode="overlay",
        font=_FONT,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=50, b=50, l=180, r=80),
        showlegend=False,
        xaxis=dict(title="Elapsed time (seconds)", gridcolor=_GRID, zeroline=False),
        yaxis=dict(autorange="reversed", gridcolor=_GRID),
        annotations=[dict(
            x=total, y=-0.18,
            xref="x", yref="paper",
            text=f"Total: {total:.2f}s",
            showarrow=False,
            font=dict(size=11, color=_SLATE),
            xanchor="right",
        )],
    )
    return fig
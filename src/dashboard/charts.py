# src/dashboard/charts.py
# Performance-focused Plotly charts.
#
#   chart_cpu(perf_steps)        — stacked bar: CPU used (avg) vs available per step.
#                                  Max bar height = cores × 100%.
#                                  Peak shown as scatter diamond marker.
#   chart_ram(perf_steps)        — stacked bar: RAM avg used vs remaining free
#                                  per step. Every bar reaches total system RAM.
#                                  Peak shown as scatter diamond marker.
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
    Peak shown as scatter diamond marker.
    """
    labels    = _step_labels(perf_steps)
    used      = [v.get("cpu_avg_percent",  0) for v in perf_steps.values()]
    peak      = [v.get("cpu_peak_percent", 0) for v in perf_steps.values()]
    free      = [max(_MAX_CPU_PCT - u, 0)     for u in used]
    est_cores = [round(u / 100, 1)            for u in used]

    fig = go.Figure()

    # Used CPU (avg)
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
      Bottom (amber) = RAM avg used by process during step (MB)
      Top    (light) = remaining RAM headroom = total system RAM - avg used
    Every bar reaches exactly _TOTAL_RAM_MB → consistent height, instant context.
    Peak shown as scatter diamond marker (same pattern as CPU chart).
    """
    labels  = _step_labels(perf_steps)
    avg_mb  = [v.get("ram_avg_mb",  0) for v in perf_steps.values()]
    peak_mb = [v.get("ram_peak_mb", 0) for v in perf_steps.values()]
    # headroom = total system RAM minus avg used — always fills bar to the top
    free_mb = [max(_TOTAL_RAM_MB - a, 0) for a in avg_mb]

    avg_pct  = [round(a / _TOTAL_RAM_MB * 100, 1) for a in avg_mb]
    peak_pct = [round(p / _TOTAL_RAM_MB * 100, 1) for p in peak_mb]

    fig = go.Figure()

    # Avg RAM used
    fig.add_trace(go.Bar(
        name="RAM Avg Used (MB)",
        x=labels,
        y=avg_mb,
        marker_color=_AMBER,
        text=[f"{a:.0f} MB<br>({ap:.1f}%)" for a, ap in zip(avg_mb, avg_pct)],
        textposition="inside",
        insidetextanchor="middle",
        hovertemplate=(
            "<b>%{x}</b><br>"
            "RAM avg: %{y:.0f} MB (%{customdata:.1f}% of system)<extra></extra>"
        ),
        customdata=avg_pct,
    ))

    # Free headroom — fills bar to total system RAM
    fig.add_trace(go.Bar(
        name="RAM Free Headroom",
        x=labels,
        y=free_mb,
        marker_color=_GREEN_FREE,
        marker_line_width=0,
        hovertemplate=(
            "<b>%{x}</b><br>"
            "RAM headroom: %{y:.0f} MB<extra></extra>"
        ),
    ))

    # Peak markers as scatter dots — mirrors CPU chart style
    fig.add_trace(go.Scatter(
        name="RAM Peak (MB)",
        x=labels,
        y=peak_mb,
        mode="markers+text",
        marker=dict(symbol="diamond", size=10, color=_AMBER_LIGHT, line=dict(color="#fff", width=1)),
        text=[f"peak {p:.0f} MB ({pp:.1f}%)" for p, pp in zip(peak_mb, peak_pct)],
        textposition="top center",
        textfont=dict(size=10, color=_AMBER_LIGHT),
        hovertemplate="<b>%{x}</b><br>RAM peak: %{y:.0f} MB (%{customdata:.1f}%)<extra></extra>",
        customdata=peak_pct,
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
            title="RAM (MB)",
            range=[0, _TOTAL_RAM_MB * 1.15],
            gridcolor=_GRID,
            zeroline=False,
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
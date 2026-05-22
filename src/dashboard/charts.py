#   chart_cpu(perf_steps)        — stacked bar: CPU used (avg) vs available per step.
#                                  Max bar height = cores × 100%.
#                                  Peak shown as scatter diamond marker.
#   chart_ram(perf_steps)        — stacked bar: RAM avg used vs remaining free
#                                  per step. Every bar reaches total system RAM.
#                                  Peak shown as scatter diamond marker.
#   chart_waterfall(perf_steps)  — horizontal Gantt: each step placed
#                                  sequentially on a wall-clock time axis.
#
# Sub-process display labels are driven by STEP_LABEL_MAP in config/settings.py.
# Add a new sub-process? Add one line there — no changes needed here.

import psutil
import plotly.graph_objects as go
from plotly.graph_objects import Figure

from config.settings import STEP_LABEL_MAP

# ── Palette ───────────────────────────────────────────────────────────────────
_BLUE        = "#2563EB"
_BLUE_LIGHT  = "#93C5FD"
_BLUE_FREE   = "#DBEAFE"
_AMBER       = "#F59E0B"
_AMBER_LIGHT = "#FCD34D"
_GREEN       = "#10B981"
_GREEN_FREE  = "#D1FAE5"
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
            "<span style='color:#475569'>──────────────────────────</span><br>"
            "<span style='color:#f1f5f9'>CPU avg  </span>  %{y:.1f}%<br>"
            "<span style='color:#f1f5f9'>Est. cores</span>  %{customdata:.1f} / " + str(_CPU_CORES) + "<br>"
            "<extra></extra>"
        ),
        customdata=est_cores,
    ))

    fig.add_trace(go.Bar(
        name="CPU Free",
        x=labels,
        y=free,
        marker_color=_BLUE_FREE,
        marker_line_width=0,
        hovertemplate=(
            "<b>%{x}</b><br>"
            "<span style='color:#475569'>──────────────────────────</span><br>"
            "<span style='color:#f1f5f9'>CPU free </span>  %{y:.1f}%<br>"
            "<span style='color:#f1f5f9'>Max      </span>  " + str(_CPU_CORES) + " cores × 100 = " + str(_MAX_CPU_PCT) + "%<br>"
            "<extra></extra>"
        ),
    ))

    fig.add_trace(go.Scatter(
        name="CPU Peak %",
        x=labels,
        y=peak,
        mode="markers+text",
        marker=dict(symbol="diamond", size=10, color=_AMBER, line=dict(color="#fff", width=1)),
        text=[f"peak {p:.0f}%" for p in peak],
        textposition="top center",
        textfont=dict(size=10, color=_AMBER),
        hovertemplate=(
            "<b>%{x}</b><br>"
            "<span style='color:#475569'>──────────────────────────</span><br>"
            "<span style='color:#f1f5f9'>CPU peak </span>  %{y:.1f}%<br>"
            "<extra></extra>"
        ),
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
        hoverlabel=dict(
            bgcolor="#1e293b",
            bordercolor="#334155",
            font=dict(family="'IBM Plex Mono', 'Courier New', monospace", size=12, color="#f1f5f9"),
        ),
    )
    return fig


# ── RAM stacked bar ───────────────────────────────────────────────────────────

def chart_ram(perf_steps: dict) -> Figure:
    """
    Stacked bar per step:
      Bottom (amber) = RAM avg used by process during step (MB)
      Top    (light) = remaining RAM headroom = total system RAM - avg used
    Every bar reaches exactly _TOTAL_RAM_MB → consistent height, instant context.
    Peak shown as scatter diamond marker.
    """
    labels  = _step_labels(perf_steps)
    avg_mb  = [v.get("ram_avg_mb",  0) for v in perf_steps.values()]
    peak_mb = [v.get("ram_peak_mb", 0) for v in perf_steps.values()]
    free_mb = [max(_TOTAL_RAM_MB - a, 0) for a in avg_mb]

    avg_pct  = [round(a / _TOTAL_RAM_MB * 100, 1) for a in avg_mb]
    peak_pct = [round(p / _TOTAL_RAM_MB * 100, 1) for p in peak_mb]

    fig = go.Figure()

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
            "<span style='color:#475569'>──────────────────────────</span><br>"
            "<span style='color:#f1f5f9'>RAM avg  </span>  %{y:.0f} MB<br>"
            "<span style='color:#f1f5f9'>% of sys </span>  %{customdata:.1f}%<br>"
            "<extra></extra>"
        ),
        customdata=avg_pct,
    ))

    fig.add_trace(go.Bar(
        name="RAM Free Headroom",
        x=labels,
        y=free_mb,
        marker_color=_GREEN_FREE,
        marker_line_width=0,
        hovertemplate=(
            "<b>%{x}</b><br>"
            "<span style='color:#475569'>──────────────────────────</span><br>"
            "<span style='color:#f1f5f9'>Headroom </span>  %{y:.0f} MB<br>"
            "<extra></extra>"
        ),
    ))

    fig.add_trace(go.Scatter(
        name="RAM Peak (MB)",
        x=labels,
        y=peak_mb,
        mode="markers+text",
        marker=dict(symbol="diamond", size=10, color=_AMBER_LIGHT, line=dict(color="#fff", width=1)),
        text=[f"peak {p:.0f} MB ({pp:.1f}%)" for p, pp in zip(peak_mb, peak_pct)],
        textposition="top center",
        textfont=dict(size=10, color=_AMBER_LIGHT),
        hovertemplate=(
            "<b>%{x}</b><br>"
            "<span style='color:#475569'>──────────────────────────</span><br>"
            "<span style='color:#f1f5f9'>RAM peak </span>  %{y:.0f} MB<br>"
            "<span style='color:#f1f5f9'>% of sys </span>  %{customdata:.1f}%<br>"
            "<extra></extra>"
        ),
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
        hoverlabel=dict(
            bgcolor="#1e293b",
            bordercolor="#334155",
            font=dict(family="'IBM Plex Mono', 'Courier New', monospace", size=12, color="#f1f5f9"),
        ),
    )
    return fig


# ── Waterfall / Gantt ─────────────────────────────────────────────────────────

def chart_waterfall(perf_steps: dict) -> Figure:
    """
    Horizontal Gantt grouped by parent step.
    Naming convention: "parent_step.sub_process" → auto-grouped.
    Top-level steps shown as section dividers.
    Sub-processes shown as individual bars with duration + RAM + CPU on hover.

    Sub-process display labels come from STEP_LABEL_MAP in config/settings.py.
    Adding a new sub-process only requires adding one entry there.
    """
    parents = {k: v for k, v in perf_steps.items() if "." not in k}
    subs    = {k: v for k, v in perf_steps.items() if "." in k}

    rows   = []
    cursor = 0.0

    for parent_key, parent_val in parents.items():
        parent_label = parent_key.replace("_", " ").title()
        parent_dur   = parent_val.get("duration_seconds", 0)

        rows.append({
            "label":     parent_label.upper(),
            "start":     cursor,
            "duration":  parent_dur,
            "metrics":   parent_val,
            "is_parent": True,
        })

        children     = {k: v for k, v in subs.items() if k.startswith(parent_key + ".")}
        child_cursor = cursor

        for child_key, child_val in children.items():
            raw         = child_key.split(".", 1)[1]
            # Label resolved from settings — no hardcoding here
            child_label = STEP_LABEL_MAP.get(raw, raw.replace("_", " ").title())
            child_dur   = child_val.get("duration_seconds", 0)

            rows.append({
                "label":     f"    {child_label}",
                "start":     child_cursor,
                "duration":  child_dur,
                "metrics":   child_val,
                "is_parent": False,
            })
            child_cursor += child_dur

        cursor += parent_dur

    total = cursor

    all_cpu = [r["metrics"].get("cpu_avg_percent", 0) for r in rows if not r["is_parent"]]
    max_cpu = max(all_cpu) if all_cpu else 1

    def _cpu_color(pct: float, is_parent: bool) -> str:
        if is_parent:
            return "rgba(100,116,139,0.15)"
        t = min(pct / max_cpu, 1.0) if max_cpu else 0
        r = int(37  + (245 - 37)  * t)
        g = int(99  + (158 - 99)  * t)
        b = int(235 + (11  - 235) * t)
        return f"rgb({r},{g},{b})"

    fig = go.Figure()

    for row in rows:
        m       = row["metrics"]
        dur     = row["duration"]
        pct_t   = dur / total * 100 if total else 0
        cpu_avg = m.get("cpu_avg_percent", 0)

        fig.add_trace(go.Bar(
            name=row["label"],
            y=[row["label"]],
            x=[dur],
            base=row["start"],
            orientation="h",
            marker_color=_cpu_color(cpu_avg, row["is_parent"]),
            marker_line_color="rgba(37,99,235,0.8)" if row["is_parent"] else "rgba(255,255,255,0.5)",
            marker_line_width=2 if row["is_parent"] else 1,
            text=f"  {dur:.2f}s" if not row["is_parent"] else "",
            textposition="inside",
            insidetextanchor="start",
            customdata=[[
                m.get("ram_avg_mb",       0),
                m.get("ram_peak_mb",      0),
                m.get("cpu_avg_percent",  0),
                m.get("cpu_peak_percent", 0),
                pct_t,
            ]],
            hovertemplate=(
                "<b>%{y}</b><br>"
                "<span style='color:#475569'>──────────────────────────</span><br>"
                "<span style='color:#f1f5f9'>Duration </span>  %{x:.3f}s &nbsp;|&nbsp; %{customdata[4]:.1f}% of total<br>"
                "<span style='color:#f1f5f9'>RAM avg  </span>  %{customdata[0]:.0f} MB<br>"
                "<span style='color:#f1f5f9'>RAM peak </span>  %{customdata[1]:.0f} MB<br>"
                "<span style='color:#f1f5f9'>CPU avg  </span>  %{customdata[2]:.1f}%<br>"
                "<span style='color:#f1f5f9'>CPU peak </span>  %{customdata[3]:.1f}%<br>"
                "<extra></extra>"
            ),
        ))

    y_labels = [row["label"] for row in rows]
    shapes   = []

    for row in rows:
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
        barmode="overlay",
        font=_FONT,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=50, b=60, l=200, r=80),
        showlegend=False,
        height=max(400, n_rows * 60 + 120),
        shapes=shapes,
        xaxis=dict(title="Elapsed time (seconds)", gridcolor=_GRID, zeroline=False),
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
        hoverlabel=dict(
            bgcolor="#1e293b",
            bordercolor="#334155",
            font=dict(family="'IBM Plex Mono', 'Courier New', monospace", size=12, color="#f1f5f9"),
        ),
    )
    return fig
# src/dashboard/report.py
#
# Exports a fully self-contained static HTML report from the metrics JSON.
# No server, no dependencies — a single .html file with Plotly bundled inline.
# All charts retain full hover/tooltip interactivity.
#
# Usage (called automatically by main.py after the pipeline completes):
#   from src.dashboard.report import export_report
#   export_report()
#
# The output path is:  data/report_<timestamp>.html
# A stable symlink/copy is also written to:  data/report_latest.html
#
# Adding a new chart
# ──────────────────
# 1. Add a chart_xxx() builder in charts.py.
# 2. Add a _Section entry to _SECTIONS below.
# Done — layout, embedding, and file writing are all automatic.

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

import plotly
import plotly.graph_objects as go
from loguru import logger

from config.settings import METRICS_FILE, DATA_DIR, DASHBOARD_TITLE, STEP_WRITE, STEP_READ
from src.dashboard.charts import chart_cpu, chart_ram, chart_waterfall
from src.reader import load_metrics

# ── Output paths ───────────────────────────────────────────────────────────────
REPORT_DIR    = DATA_DIR
REPORT_LATEST = REPORT_DIR / "report_latest.html"


# ── Section registry ───────────────────────────────────────────────────────────
# Each entry describes one chart panel in the report.
# To add a chart: import its builder and append a _Section here.

class _Section(NamedTuple):
    heading:     str           # displayed above the chart
    chart_fn:    callable      # callable(perf_steps) → go.Figure
    full_width:  bool = False  # True = spans both columns; False = half-width


_SECTIONS: list[_Section] = [
    _Section(
        heading="CPU — Used vs Available",
        chart_fn=chart_cpu,
        full_width=False,
    ),
    _Section(
        heading="RAM — Peak Used vs Free",
        chart_fn=chart_ram,
        full_width=False,
    ),
    _Section(
        heading="Pipeline Timeline",
        chart_fn=chart_waterfall,
        full_width=True,
    ),
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fig_to_json(fig: go.Figure) -> str:
    """Serialise a Plotly figure to a JSON string safe for embedding in HTML."""
    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)


def _plotly_bundle() -> str:
    """
    Return the full Plotly JS bundle as a string.
    Reads from the pip package so no network call is needed at export time.
    """
    import plotly
    bundle = Path(plotly.__file__).parent / "package_data" / "plotly.min.js"
    if not bundle.exists():
        raise FileNotFoundError(
            f"plotly.min.js not found at {bundle}. "
            "Make sure plotly is installed: pip install plotly"
        )
    return bundle.read_text(encoding="utf-8")


def _kpi_cards_html(metrics: dict) -> str:
    """
    Render the throughput KPI cards — identical markup and CSS classes to
    the live dashboard (index.html  ── Throughput & File section).

    Each card is only emitted when the metric value actually exists so a
    read-only or generate-only run never shows empty cards.
    """
    gen  = metrics.get(STEP_WRITE, {})
    read = metrics.get(STEP_READ,  {})

    parquet_size_mb    = gen.get("parquet_size_mb")  or read.get("parquet_size_mb")
    total_rows         = gen.get("rows_written")      or read.get("rows_read")
    write_rows_per_sec = gen.get("rows_per_second")
    write_mb_per_sec   = gen.get("mb_per_second")
    read_rows_per_sec  = read.get("rows_per_second")
    read_mb_per_sec    = read.get("mb_per_second")

    def _card(label: str, value: str, sub: str = "", accent: str = "") -> str:
        cls = f"kpi-card {accent}".strip()
        sub_html = f'<div class="sub">{sub}</div>' if sub else ""
        return f"""
        <div class="{cls}">
          <div class="label">{label}</div>
          <div class="value">{value}</div>
          {sub_html}
        </div>"""

    cards = []

    if parquet_size_mb is not None:
        cards.append(_card(
            "Parquet Size",
            f'{parquet_size_mb:.1f} <span style="font-size:.9rem;color:var(--text-muted)">MB</span>',
            accent="green",
        ))

    if total_rows is not None:
        cards.append(_card("Total Rows", f'{int(total_rows):,}'))

    if write_rows_per_sec is not None:
        cards.append(_card(
            "Write Speed",
            f'{write_rows_per_sec:,.0f}',
            sub="rows / second",
            accent="amber",
        ))

    if write_mb_per_sec is not None:
        cards.append(_card(
            "Write Throughput",
            f'{write_mb_per_sec:.1f} <span style="font-size:.9rem;color:var(--text-muted)">MB/s</span>',
            accent="amber",
        ))

    if read_rows_per_sec is not None:
        cards.append(_card(
            "Read Speed",
            f'{read_rows_per_sec:,.0f}',
            sub="rows / second",
        ))

    if read_mb_per_sec is not None:
        cards.append(_card(
            "Read Throughput",
            f'{read_mb_per_sec:.1f} <span style="font-size:.9rem;color:var(--text-muted)">MB/s</span>',
        ))

    return "\n".join(cards)


def _step_cards_html(metrics: dict) -> str:
    """Render the per-step breakdown cards as an HTML string."""
    perf_steps = {
        k: v for k, v in metrics.items()
        if isinstance(v, dict) and "duration_seconds" in v and "." not in k
    }

    cards = []
    for step, vals in perf_steps.items():
        cpu_avg  = vals.get("cpu_proc_avg_percent", vals.get("cpu_avg_percent", 0))
        cpu_peak = vals.get("cpu_sys_peak_percent", vals.get("cpu_peak_percent", 0))
        cores    = vals.get("cpu_cores_total", 1)

        rows_html = ""
        metric_rows = [
            ("Duration",      f"{vals['duration_seconds']:.2f}s",                        "highlight"),
            ("RAM avg",       f"{vals.get('ram_avg_mb', 0):.1f} MB",                     ""),
            ("RAM peak",      f"{vals.get('ram_peak_mb', 0):.1f} MB",                    "amber"),
            ("Free RAM (min)",f"{vals.get('ram_free_min_mb', 0):.1f} MB",                ""),
            ("CPU avg",       f"{cpu_avg:.1f}% (~{cpu_avg/100*cores:.1f} / {cores}c)",   ""),
            ("CPU peak",      f"{cpu_peak:.1f}%",                                         "amber"),
        ]
        if "rows_per_second" in vals:
            metric_rows.append(
                ("Throughput", f"{vals['rows_per_second']:,.0f} rows/s", "")
            )

        for key, val, cls in metric_rows:
            rows_html += f"""
            <div class="metric-row">
              <span class="metric-key">{key}</span>
              <span class="metric-val {cls}">{val}</span>
            </div>"""

        cards.append(f"""
        <div class="step-card">
          <div class="step-name">{step.replace('_', ' ')}</div>
          {rows_html}
        </div>""")

    return "\n".join(cards)


# ── HTML template ──────────────────────────────────────────────────────────────

def _render_html(
    metrics:   dict,
    generated: str,
    plotly_js: str,
) -> str:
    """
    Build and return the full HTML document as a string.

    Charts are embedded as JSON blobs and initialised by a small inline script.
    Plotly is bundled inline so the file works with no internet access.
    """
    perf_steps_top = {
        k: v for k, v in metrics.items()
        if isinstance(v, dict) and "duration_seconds" in v and "." not in k
    }
    perf_steps_all = {
        k: v for k, v in metrics.items()
        if isinstance(v, dict) and "duration_seconds" in v
    }

    # Build chart JSON blobs and the grid HTML together so they stay in sync.
    chart_data_tags  = []
    chart_grid_html  = []
    half_width_open  = False   # tracks whether a two-column row is open

    for idx, section in enumerate(_SECTIONS):
        data_id  = f"chart-data-{idx}"
        div_id   = f"chart-{idx}"

        # Pick the right steps dict — waterfall needs sub-steps too
        steps = perf_steps_all if section.full_width else perf_steps_top
        fig   = section.chart_fn(steps)

        chart_data_tags.append(
            f'<script type="application/json" id="{data_id}">'
            f'{_fig_to_json(fig)}'
            f'</script>'
        )

        height  = "420px" if not section.full_width else "auto"
        panel   = f"""
        <div class="chart-card {'full' if section.full_width else ''}">
          <h3>{section.heading}</h3>
          <div id="{div_id}" style="width:100%;height:{height}"></div>
        </div>"""

        if section.full_width:
            if half_width_open:
                chart_grid_html.append('</div>')   # close pending two-col row
                half_width_open = False
            chart_grid_html.append('<div class="chart-grid-1">')
            chart_grid_html.append(panel)
            chart_grid_html.append('</div>')
        else:
            if not half_width_open:
                chart_grid_html.append('<div class="chart-grid-2">')
                half_width_open = True
            chart_grid_html.append(panel)
            # Close the two-col row after every second half-width panel
            col_count = sum(1 for s in _SECTIONS[:idx+1] if not s.full_width)
            if col_count % 2 == 0:
                chart_grid_html.append('</div>')
                half_width_open = False

    if half_width_open:
        chart_grid_html.append('</div>')

    # Inline JS: initialise every chart from its JSON blob
    init_calls = "\n  ".join(
        f"plot('chart-{idx}', 'chart-data-{idx}');"
        for idx in range(len(_SECTIONS))
    )

    kpi_cards  = _kpi_cards_html(metrics)

    step_cards = _step_cards_html(metrics)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>{DASHBOARD_TITLE} — Report</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
  <script>{plotly_js}</script>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    :root {{
      --bg:          #f1f5f9;
      --surface:     #ffffff;
      --border:      rgba(0,0,0,0.07);
      --text:        #1e293b;
      --text-muted:  #64748b;
      --blue:        #2563EB;
      --amber:       #F59E0B;
      --amber-d:     #d97706;
      --green:       #10B981;
    }}

    body {{
      font-family: 'IBM Plex Sans', sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
    }}

    header {{
      border-bottom: 1px solid var(--border);
      padding: 1rem 2rem;
      display: flex;
      align-items: center;
      gap: 1rem;
      background: var(--surface);
    }}
    header .badge {{
      font-family: 'IBM Plex Mono', monospace;
      font-size: .7rem;
      background: var(--blue);
      color: #fff;
      padding: .2rem .6rem;
      border-radius: 4px;
      letter-spacing: .05em;
    }}
    header h1 {{ font-size: 1rem; font-weight: 600; }}
    header .generated {{
      margin-left: auto;
      font-family: 'IBM Plex Mono', monospace;
      font-size: .7rem;
      color: var(--text-muted);
    }}

    .container {{ max-width: 1400px; margin: 0 auto; padding: 2rem; }}

    .section-label {{
      font-family: 'IBM Plex Mono', monospace;
      font-size: .72rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: .1em;
      color: var(--blue);
      margin: 2rem 0 1rem;
      display: flex;
      align-items: center;
      gap: .6rem;
    }}
    .section-label::after {{
      content: '';
      flex: 1;
      height: 1px;
      background: var(--border);
    }}

    /* KPI cards — identical to index.html */
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 1rem;
    }}
    .kpi-card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 1.1rem 1.3rem;
      position: relative;
      overflow: hidden;
    }}
    .kpi-card::before {{
      content: '';
      position: absolute;
      top: 0; left: 0; right: 0;
      height: 2px;
      background: var(--blue);
    }}
    .kpi-card.amber::before {{ background: var(--amber); }}
    .kpi-card.green::before {{ background: var(--green); }}
    .kpi-card .label {{
      font-family: 'IBM Plex Mono', monospace;
      font-size: .68rem;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: .07em;
      margin-bottom: .4rem;
    }}
    .kpi-card .value {{
      font-family: 'IBM Plex Mono', monospace;
      font-size: 1.45rem;
      font-weight: 600;
      color: var(--text);
      line-height: 1.1;
    }}
    .kpi-card .sub {{
      font-size: .72rem;
      color: var(--text-muted);
      margin-top: .3rem;
    }}

    /* Step cards */
    .step-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 1rem;
    }}
    .step-card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 1.2rem 1.4rem;
    }}
    .step-name {{
      font-family: 'IBM Plex Mono', monospace;
      font-size: .78rem;
      color: var(--blue);
      text-transform: uppercase;
      letter-spacing: .06em;
      margin-bottom: .9rem;
      padding-bottom: .6rem;
      border-bottom: 1px solid var(--border);
    }}
    .metric-row {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      padding: .3rem 0;
    }}
    .metric-row + .metric-row {{ border-top: 1px solid var(--border); }}
    .metric-key {{ font-size: .78rem; color: var(--text-muted); }}
    .metric-val {{
      font-family: 'IBM Plex Mono', monospace;
      font-size: .9rem;
      font-weight: 600;
    }}
    .metric-val.highlight {{ color: var(--blue); }}
    .metric-val.amber     {{ color: var(--amber-d); }}

    /* Chart grid */
    .chart-grid-2 {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 1.2rem;
      margin-bottom: 1.2rem;
    }}
    .chart-grid-1 {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 1.2rem;
      margin-bottom: 1.2rem;
    }}
    .chart-card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 1.2rem 1.4rem;
    }}
    .chart-card h3 {{
      font-family: 'IBM Plex Mono', monospace;
      font-size: .75rem;
      font-weight: 600;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: .08em;
      margin-bottom: .75rem;
    }}

    footer {{
      text-align: center;
      padding: 2rem;
      font-family: 'IBM Plex Mono', monospace;
      font-size: .68rem;
      color: var(--text-muted);
      border-top: 1px solid var(--border);
      margin-top: 2rem;
    }}

    @media (max-width: 900px) {{
      .chart-grid-2 {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>

<header>
  <span class="badge">POC</span>
  <h1>{DASHBOARD_TITLE} — Static Report</h1>
  <span class="generated">Generated: {generated}</span>
</header>

<div class="container">

  <p class="section-label">Throughput &amp; File</p>
  <div class="kpi-grid">
    {kpi_cards}
  </div>

  <p class="section-label">Step Breakdown</p>
  <div class="step-grid">
    {step_cards}
  </div>

  <p class="section-label">Resource Usage</p>
  {"".join(chart_grid_html)}

</div>

<footer>POC — Pipeline Performance Report · {generated}</footer>

{"".join(chart_data_tags)}

<script>
  const cfg = {{ responsive: true, displayModeBar: true, scrollZoom: false }};

  function plot(divId, dataId) {{
    const fig = JSON.parse(document.getElementById(dataId).textContent);
    Plotly.newPlot(divId, fig.data, fig.layout, cfg);
  }}

  {init_calls}
</script>

</body>
</html>"""


# ── Public entry point ─────────────────────────────────────────────────────────

def export_report(out_dir: Path = REPORT_DIR) -> Path:
    """
    Read the metrics JSON, render the report, and write two files:

      <out_dir>/report_<YYYYMMDD_HHMMSS>.html   timestamped — never overwritten
      <out_dir>/report_latest.html               always points to the latest run

    Returns the path of the timestamped file.
    """
    metrics = load_metrics()
    if not metrics:
        logger.warning("No metrics found — skipping report export.")
        return None

    out_dir.mkdir(parents=True, exist_ok=True)

    generated  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    timestamp  = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path   = out_dir / f"report_{timestamp}.html"
    latest     = out_dir / "report_latest.html"

    plotly_js  = _plotly_bundle()
    html       = _render_html(metrics, generated, plotly_js)

    out_path.write_text(html, encoding="utf-8")
    shutil.copy2(out_path, latest)

    size_kb = out_path.stat().st_size / 1024
    logger.success(f"Report exported → {out_path.name} ({size_kb:.0f} KB)")
    logger.success(f"Latest symlink  → {latest.name}")

    return out_path
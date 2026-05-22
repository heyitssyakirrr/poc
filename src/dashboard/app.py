# src/dashboard/app.py
# FastAPI dashboard — shows pipeline performance metrics only.
# Launched automatically by main.py after the pipeline completes.
# Can also be run standalone: python src/dashboard/app.py
#   (requires data/performance_metrics.json to already exist)

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import json
import psutil
import plotly
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from loguru import logger

import src.logger  # noqa: F401

from config.settings import (
    DASHBOARD_TITLE, DASHBOARD_HOST, DASHBOARD_PORT,
    DASHBOARD_DEBUG, METRICS_FILE,
    STEP_WRITE, STEP_READ,
)
from src.dashboard.assets import ensure_plotly_js
from src.dashboard.charts import chart_cpu, chart_ram, chart_waterfall
from src.reader import load_metrics

# ── App factory ────────────────────────────────────────────────────────────────
app = FastAPI()

STATIC_DIR    = Path(__file__).parent / "static"
TEMPLATES_DIR = Path(__file__).parent / "templates"

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _fig_json(fig) -> str:
    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    metrics = load_metrics()

    # Steps only — exclude the top-level "system" key
    perf_steps = {
        k: v for k, v in metrics.items()
        if isinstance(v, dict) and "duration_seconds" in v
    }

    # Top-level steps only — for KPI cards, step breakdown, CPU chart, RAM chart
    perf_steps_top = {k: v for k, v in perf_steps.items() if "." not in k}

    # All steps including sub-processes — for waterfall chart only
    perf_steps_all = perf_steps

    # KPI cards — step keys come from settings constants, never hardcoded strings
    gen  = perf_steps.get(STEP_WRITE, {})
    read = perf_steps.get(STEP_READ,  {})

    kpis = {
        "parquet_size_mb":    gen.get("parquet_size_mb")  or read.get("parquet_size_mb"),
        "total_rows":         gen.get("rows_written")      or read.get("rows_read"),
        "write_rows_per_sec": gen.get("rows_per_second"),
        "write_mb_per_sec":   gen.get("mb_per_second"),
        "read_rows_per_sec":  read.get("rows_per_second"),
        "read_mb_per_sec":    read.get("mb_per_second"),
    }

    total_ram_mb = psutil.virtual_memory().total / 1024 ** 2
    cpu_cores    = psutil.cpu_count(logical=True)

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "title":            DASHBOARD_TITLE,
            "perf_steps":       perf_steps_top,
            "kpis":             kpis,
            "cpu_cores_total":  cpu_cores,
            "total_ram_mb":     round(total_ram_mb, 0),   # passed explicitly — no template guesswork
            "fig_cpu":          _fig_json(chart_cpu(perf_steps_top)),
            "fig_ram":          _fig_json(chart_ram(perf_steps_top)),
            "fig_waterfall":    _fig_json(chart_waterfall(perf_steps_all)),
        },
    )


@app.get("/health")
async def health():
    return JSONResponse({
        "status":         "ok",
        "metrics_exists": METRICS_FILE.exists(),
    })


# ── Standalone entry point ─────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    ensure_plotly_js()
    logger.info(f"Dashboard → http://localhost:{DASHBOARD_PORT}")
    uvicorn.run(
        "src.dashboard.app:app",
        host=DASHBOARD_HOST,
        port=DASHBOARD_PORT,
        reload=DASHBOARD_DEBUG,
    )
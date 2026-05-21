# Run:  python src/dashboard/app.py
# Open: http://localhost:5000

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import json
import plotly
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from loguru import logger

import src.logger  # noqa: F401 — configure loguru handlers

from config.settings import (
    DASHBOARD_TITLE, DASHBOARD_HOST, DASHBOARD_PORT,
    DASHBOARD_DEBUG, PARQUET_FILE,
)
from src.dashboard.assets import ensure_plotly_js
from src.dashboard.charts import (
    chart_by_type, chart_by_channel, chart_daily_volume,
    chart_by_status, chart_by_merchant, chart_flagged, chart_by_currency,
)
from src.reader import read_parquet, summarise, load_metrics

# ── App factory ────────────────────────────────────────────────────────────────
app = FastAPI()

# ── Static files + templates ───────────────────────────────────────────────────
STATIC_DIR    = Path(__file__).parent / "static"
TEMPLATES_DIR = Path(__file__).parent / "templates"

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# ── Module-level data cache — loaded once on first request ─────────────────────
_cache: dict = {}


def _load_cache() -> None:
    """Read Parquet + build all summaries. Populates _cache in-place."""
    if _cache:
        return  # already loaded
    logger.info("Loading data into dashboard cache…")
    df = read_parquet()
    _cache["summaries"]  = summarise(df)
    _cache["row_count"]  = len(df)
    _cache["total_amt"]  = round(float(df["amount"].sum()), 2)
    _cache["avg_amt"]    = round(float(df["amount"].mean()), 2)
    _cache["flagged"]    = int(df["is_flagged"].sum())
    _cache["unique_acc"] = int(df["account_id"].nunique())
    logger.success("Dashboard cache ready.")


def _fig_json(fig) -> str:
    """Serialise a Plotly figure to JSON for the Jinja2 template."""
    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if not PARQUET_FILE.exists():
        return templates.TemplateResponse(
            request=request,
            name="error.html",
            context={"title": DASHBOARD_TITLE},
        )

    _load_cache()
    S       = _cache["summaries"]
    metrics = load_metrics()

    perf_steps = {
        k: v for k, v in metrics.items()
        if isinstance(v, dict) and "duration_seconds" in v
    }

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "title":      DASHBOARD_TITLE,
            "row_count":  f"{_cache['row_count']:,}",
            "total_amt":  f"RM {_cache['total_amt']:,.2f}",
            "avg_amt":    f"RM {_cache['avg_amt']:,.2f}",
            "flagged":    f"{_cache['flagged']:,}",
            "unique_acc": f"{_cache['unique_acc']:,}",
            "perf_steps": perf_steps,
            "sys_info":   metrics.get("system", {}),
            "fig_type":     _fig_json(chart_by_type(S["by_type"])),
            "fig_channel":  _fig_json(chart_by_channel(S["by_channel"])),
            "fig_daily":    _fig_json(chart_daily_volume(S["daily_volume"])),
            "fig_status":   _fig_json(chart_by_status(S["by_status"])),
            "fig_merchant": _fig_json(chart_by_merchant(S["by_merchant"])),
            "fig_flagged":  _fig_json(chart_flagged(S["flagged"])),
            "fig_currency": _fig_json(chart_by_currency(S["by_currency"])),
        },
    )


@app.get("/health")
async def health():
    """Health-check endpoint — useful for server monitoring."""
    return JSONResponse({
        "status":         "ok",
        "parquet_exists": PARQUET_FILE.exists(),
        "cache_loaded":   bool(_cache),
    })


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    ensure_plotly_js()   # copy JS from pip package to static folder (idempotent)
    logger.info(f"Dashboard → http://localhost:{DASHBOARD_PORT}")
    uvicorn.run(
        "src.dashboard.app:app",
        host=DASHBOARD_HOST,
        port=DASHBOARD_PORT,
        reload=DASHBOARD_DEBUG,
    )
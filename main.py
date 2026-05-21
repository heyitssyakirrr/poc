#!/usr/bin/env python3
# main.py
# Single entry point — generate → read → save metrics → launch dashboard.
#
# Usage:
#   python main.py              full pipeline then open dashboard
#   python main.py --generate   generate Parquet only (no dashboard)
#   python main.py --read       read only, then open dashboard
#   python main.py --dashboard  launch dashboard only (metrics must exist)

import sys
import argparse
import platform
import psutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import src.logger  # noqa: F401 — configure loguru as side-effect
from loguru import logger

from config.settings import PARQUET_FILE, DASHBOARD_HOST, DASHBOARD_PORT, DASHBOARD_DEBUG
from src.generator import generate_parquet
from src.reader    import read_parquet
from src.timer     import save_metrics, get_metrics


# ── System info ────────────────────────────────────────────────────────────────

def _system_info() -> dict:
    mem = psutil.virtual_memory()
    info = {
        "os":           f"{platform.system()} {platform.release()}",
        "python":       platform.python_version(),
        "cpu_cores":    psutil.cpu_count(logical=True),
        "cpu_freq_mhz": round(psutil.cpu_freq().current, 0) if psutil.cpu_freq() else "N/A",
        "ram_gb":       round(mem.total / 1024 ** 3, 1),
        "ram_avail_gb": round(mem.available / 1024 ** 3, 1),
    }
    logger.info("── System Info " + "─" * 46)
    for k, v in info.items():
        logger.info(f"  {k:<16}: {v}")
    logger.info("─" * 60)
    return info


# ── Pipeline steps ─────────────────────────────────────────────────────────────

def step_generate() -> None:
    logger.info("STEP 1 — Generate 5M rows → Parquet")
    generate_parquet()


def step_read() -> None:
    if not PARQUET_FILE.exists():
        logger.error(f"Parquet not found: {PARQUET_FILE}  →  run --generate first.")
        sys.exit(1)
    logger.info("STEP 2 — Read Parquet")
    read_parquet()


def step_dashboard() -> None:
    """Launch the FastAPI dashboard (blocking — call last)."""
    import uvicorn
    from src.dashboard.assets import ensure_plotly_js

    ensure_plotly_js()
    logger.success("─" * 60)
    logger.success(f"Dashboard → http://localhost:{DASHBOARD_PORT}")
    logger.success("─" * 60)

    uvicorn.run(
        "src.dashboard.app:app",
        host=DASHBOARD_HOST,
        port=DASHBOARD_PORT,
        reload=DASHBOARD_DEBUG,
    )


# ── CLI ────────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="POC — 5M Parquet Pipeline")
    p.add_argument("--generate",  action="store_true", help="Generate Parquet only (skips dashboard)")
    p.add_argument("--read",      action="store_true", help="Read only, then open dashboard")
    p.add_argument("--dashboard", action="store_true", help="Launch dashboard only (metrics must exist)")
    return p.parse_args()


def main() -> None:
    args     = _parse_args()
    sys_info = _system_info()

    if args.dashboard:
        step_dashboard()
        return

    if args.generate:
        step_generate()
    elif args.read:
        step_read()
    else:
        step_generate()
        step_read()

    save_metrics(extra={"system": sys_info})

    logger.success("─" * 60)
    logger.success("PIPELINE COMPLETE")
    for step, vals in get_metrics().items():
        if isinstance(vals, dict) and "duration_seconds" in vals:
            logger.success(
                f"  {step:<42} "
                f"{vals['duration_seconds']:.2f}s  |  "
                f"peak RAM {vals.get('ram_peak_mb', 0):.0f} MB  |  "
                f"CPU {vals.get('cpu_percent', 0):.1f}%"
            )
    logger.success("─" * 60)

    if not args.generate:
        step_dashboard()


if __name__ == "__main__":
    main()
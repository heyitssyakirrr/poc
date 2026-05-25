#!/usr/bin/env python3
# main.py
# Single entry point — generate → read → save metrics → export report → launch dashboard.
#
# Usage:
#   python main.py              full pipeline then open dashboard
#   python main.py --generate   generate Parquet only (no dashboard)
#   python main.py --read       read only, then open dashboard
#   python main.py --dashboard  launch dashboard only (metrics must exist)
#
# Adding a new pipeline step
# ──────────────────────────
# 1. Write your step function below (def step_xxx).
# 2. Append it to PIPELINE_STEPS:  ("xxx", step_xxx)
# 3. Done — CLI flag, run order, and metrics summary are all automatic.

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
from src.dashboard.report import export_report 


# ── System info ────────────────────────────────────────────────────────────────

def _system_info() -> dict:
    mem  = psutil.virtual_memory()
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


# ── Pipeline step functions ────────────────────────────────────────────────────

def step_generate() -> None:
    logger.info("STEP — Generate rows → Parquet")
    generate_parquet()


def step_read() -> None:
    if not PARQUET_FILE.exists():
        logger.error(f"Parquet not found: {PARQUET_FILE}  →  run --generate first.")
        sys.exit(1)
    logger.info("STEP — Read Parquet")
    read_parquet()


# ── Steps registry ─────────────────────────────────────────────────────────────
PIPELINE_STEPS: list[tuple[str, callable]] = [
    ("generate", step_generate),
    ("read",     step_read),
]


# ── Dashboard ──────────────────────────────────────────────────────────────────

def step_dashboard() -> None:
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
    p = argparse.ArgumentParser(description="POC — Parquet Pipeline")
    for name, _ in PIPELINE_STEPS:
        p.add_argument(
            f"--{name}",
            action="store_true",
            help=f"Run only the '{name}' step (skips all others and dashboard)",
        )
    p.add_argument(
        "--dashboard",
        action="store_true",
        help="Launch dashboard only (metrics must exist)",
    )
    p.add_argument(
        "--no-report",
        action="store_true",
        help="Skip static HTML report export",
    )
    return p.parse_args()


def main() -> None:
    args     = _parse_args()
    sys_info = _system_info()

    if args.dashboard:
        step_dashboard()
        return

    selected = [name for name, _ in PIPELINE_STEPS if getattr(args, name, False)]
    run_all  = not selected

    steps_to_run = PIPELINE_STEPS if run_all else [
        (name, fn) for name, fn in PIPELINE_STEPS if name in selected
    ]

    for name, fn in steps_to_run:
        logger.info(f"Running step: {name}")
        fn()

    save_metrics(extra={"system": sys_info})

    logger.success("─" * 60)
    logger.success("PIPELINE COMPLETE")
    for step, vals in get_metrics().items():
        if isinstance(vals, dict) and "duration_seconds" in vals:
            logger.success(
                f"  {step:<42} "
                f"{vals['duration_seconds']:.2f}s  |  "
                f"peak RAM {vals.get('ram_peak_mb', 0):.0f} MB  |  "
                f"CPU {vals.get('cpu_proc_avg_percent', vals.get('cpu_avg_percent', 0)):.1f}%"
            )
    logger.success("─" * 60)

    # Export static HTML report (skipped for generate-only runs — no read metrics yet)
    skip_report = selected == ["generate"]
    if not skip_report and not args.no_report:
        report_path = export_report()
        if report_path:
            logger.success(f"Share this file → {report_path}")

    skip_dashboard = selected == ["generate"]
    if not skip_dashboard:
        step_dashboard()


if __name__ == "__main__":
    main()
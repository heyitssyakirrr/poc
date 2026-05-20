#!/usr/bin/env python3
# main.py
# Pipeline entry point — generate → read → aggregate → save metrics.
#
# Usage:
#   python main.py              full pipeline
#   python main.py --generate   generate Parquet only
#   python main.py --read       read + aggregate only (Parquet must exist)

import sys
import argparse
import platform
import psutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import src.logger  # noqa: F401 — configure loguru as side-effect
from loguru import logger

from config.settings import PARQUET_FILE
from src.generator import generate_parquet
from src.reader    import read_parquet, summarise
from src.timer     import save_metrics, get_metrics


# ── System info ────────────────────────────────────────────────────────────────

def _system_info() -> dict:
    mem = psutil.virtual_memory()
    info = {
        "os":        f"{platform.system()} {platform.release()}",
        "python":    platform.python_version(),
        "cpu_cores": psutil.cpu_count(logical=True),
        "ram_gb":    round(mem.total / 1024 ** 3, 1),
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
    df = read_parquet()
    logger.info("STEP 3 — Aggregate summaries")
    summarise(df)


# ── CLI ────────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="POC — 5M Parquet Pipeline")
    p.add_argument("--generate", action="store_true", help="Generate Parquet only")
    p.add_argument("--read",     action="store_true", help="Read + aggregate only")
    return p.parse_args()


def main() -> None:
    args     = _parse_args()
    sys_info = _system_info()

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
            logger.success(f"  {step:<42} {vals['duration_seconds']:.2f}s")
    logger.success("─" * 60)
    logger.info("Next: python src/dashboard/app.py")


if __name__ == "__main__":
    main()

# src/reader/parquet_reader.py
# Reads the Parquet file and measures read performance.
# No aggregations — this project measures pipeline performance, not data content.
# Throughput metrics (rows/s, MB/s) are patched into the timer entry via
# patch_metrics() — no direct access to timer internals.

import json
import pandas as pd
from loguru import logger

from config.settings import PARQUET_FILE, METRICS_FILE, STEP_READ
from src.timer import timer, patch_metrics, get_metrics


def read_parquet(columns=None) -> pd.DataFrame:
    df = None

    with timer(STEP_READ):

        with timer(f"{STEP_READ}.open_and_deserialize"):
            df = pd.read_parquet(PARQUET_FILE, columns=columns)

        with timer(f"{STEP_READ}.validate_schema"):
            _ = df.dtypes   # forces schema resolution if lazy

    size_mb   = PARQUET_FILE.stat().st_size / 1024 ** 2
    duration  = get_metrics()[STEP_READ]["duration_seconds"]
    row_count = len(df)

    patch_metrics(STEP_READ, {
        "rows_read":       row_count,
        "parquet_size_mb": round(size_mb, 2),
        "rows_per_second": round(row_count / duration, 0),
        "mb_per_second":   round(size_mb / duration, 2),
    })

    logger.info(
        f"Loaded {row_count:,} rows × {df.shape[1]} columns | "
        f"{size_mb:.1f} MB | "
        f"{get_metrics()[STEP_READ]['rows_per_second']:,.0f} rows/s"
    )
    return df


def load_metrics() -> dict:
    """Load persisted performance metrics JSON. Returns empty dict if not found."""
    if not METRICS_FILE.exists():
        return {}
    with open(METRICS_FILE, encoding="utf-8") as f:
        return json.load(f)
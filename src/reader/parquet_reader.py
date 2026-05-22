# src/reader/parquet_reader.py
# Reads the Parquet file and measures read performance.
# No aggregations — this project measures pipeline performance, not data content.
# Throughput metrics (rows/s, MB/s) are patched into the timer entry after reading.

import json
import pandas as pd
from loguru import logger

from config.settings import PARQUET_FILE, METRICS_FILE
from src.timer import timer, _metrics


def read_parquet(columns=None) -> pd.DataFrame:
    df = None

    with timer("read_parquet"):

        with timer("read_parquet.open_and_deserialize"):
            df = pd.read_parquet(PARQUET_FILE, columns=columns)

        with timer("read_parquet.validate_schema"):
            _ = df.dtypes   # forces schema resolution if lazy

    size_mb  = PARQUET_FILE.stat().st_size / 1024 ** 2
    duration = _metrics["read_parquet"]["duration_seconds"]
    row_count = len(df)
    _metrics["read_parquet"].update({
        "rows_read":       row_count,
        "parquet_size_mb": round(size_mb, 2),
        "rows_per_second": round(row_count / duration, 0),
        "mb_per_second":   round(size_mb / duration, 2),
    })

    logger.info(
        f"Loaded {row_count:,} rows × {df.shape[1]} columns | "
        f"{size_mb:.1f} MB | "
        f"{_metrics['read_parquet']['rows_per_second']:,.0f} rows/s"
    )
    return df


def load_metrics() -> dict:
    """Load persisted performance metrics JSON. Returns empty dict if not found."""
    if not METRICS_FILE.exists():
        return {}
    with open(METRICS_FILE, encoding="utf-8") as f:
        return json.load(f)
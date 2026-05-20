# src/reader/parquet_reader.py
# Reads the Parquet file and produces pre-aggregated summaries.
# The dashboard reads from these summaries — never re-scans 5M rows per request.

import json
import pandas as pd
import pyarrow.parquet as pq
from loguru import logger

from config.settings import PARQUET_FILE, METRICS_FILE
from src.timer import timer


def read_parquet(columns: list[str] | None = None) -> pd.DataFrame:
    """
    Load the Parquet file into a DataFrame.
    Pass `columns` for column pruning — faster reads, lower RAM.
    """
    with timer("read_parquet"):
        df = pd.read_parquet(PARQUET_FILE, columns=columns)
    logger.info(f"Loaded {len(df):,} rows × {df.shape[1]} columns")
    return df


def summarise(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """
    Run all aggregations once. Returns a dict of small summary DataFrames.
    Add new aggregations here; the dashboard just reads the dict key.
    """
    with timer("aggregate_summaries"):
        summaries = {

            "by_type": (
                df.groupby("transaction_type")
                  .agg(count=("transaction_id", "count"), total_amount=("amount", "sum"))
                  .reset_index()
            ),

            "by_channel": (
                df.groupby("channel")
                  .agg(count=("transaction_id", "count"))
                  .reset_index()
                  .sort_values("count", ascending=False)
            ),

            # Tail 90 days keeps the line chart readable
            "daily_volume": (
                df.assign(date=df["timestamp"].dt.date)
                  .groupby("date")
                  .agg(count=("transaction_id", "count"), total_amount=("amount", "sum"))
                  .reset_index()
                  .sort_values("date")
                  .tail(90)
            ),

            "by_status": (
                df.groupby("status")
                  .agg(count=("transaction_id", "count"))
                  .reset_index()
            ),

            "flagged": (
                df.groupby("is_flagged")
                  .agg(count=("transaction_id", "count"), total_amount=("amount", "sum"))
                  .reset_index()
            ),

            "by_merchant": (
                df.groupby("merchant_category")
                  .agg(avg_amount=("amount", "mean"), count=("transaction_id", "count"))
                  .reset_index()
                  .sort_values("avg_amount", ascending=False)
            ),

            "by_currency": (
                df.groupby("currency")
                  .agg(count=("transaction_id", "count"), total_amount=("amount", "sum"))
                  .reset_index()
            ),
        }

    logger.success(f"Aggregations complete — {len(summaries)} summaries built.")
    return summaries


def load_metrics() -> dict:
    """Load persisted performance metrics JSON. Returns empty dict if not found."""
    if not METRICS_FILE.exists():
        return {}
    with open(METRICS_FILE, encoding="utf-8") as f:
        return json.load(f)

# src/generator/data_generator.py
# Generates TOTAL_ROWS of realistic banking transactions in CHUNK_SIZE batches
# and streams them into a single Parquet file — RAM stays bounded at ~CHUNK_SIZE rows.
# After writing, throughput metrics (rows/s, MB/s, file size) are patched into
# the timer entry via patch_metrics() — no direct access to timer internals.

import random
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from faker import Faker
from loguru import logger

from config.settings import (
    TOTAL_ROWS, CHUNK_SIZE, RANDOM_SEED,
    PARQUET_FILE, PARQUET_COMPRESSION, PARQUET_ROW_GROUP_SIZE,
    STEP_WRITE,
)
from src.timer import timer, patch_metrics, get_metrics

# ── Domain constants ───────────────────────────────────────────────────────────
TRANSACTION_TYPES = ["CREDIT", "DEBIT", "TRANSFER", "WITHDRAWAL", "DEPOSIT"]
CHANNELS          = ["MOBILE", "WEB", "ATM", "BRANCH", "POS"]
CURRENCIES        = ["MYR", "USD", "SGD", "EUR"]
STATUSES          = ["SUCCESS", "FAILED", "PENDING", "REVERSED"]
MERCHANT_CATS     = ["RETAIL", "FOOD", "TRAVEL", "UTILITIES", "HEALTHCARE", "EDUCATION", "ENTERTAINMENT"]

SCHEMA = pa.schema([
    pa.field("transaction_id",    pa.string()),
    pa.field("account_id",        pa.string()),
    pa.field("customer_name",     pa.string()),
    pa.field("transaction_type",  pa.string()),
    pa.field("amount",            pa.float64()),
    pa.field("currency",          pa.string()),
    pa.field("channel",           pa.string()),
    pa.field("status",            pa.string()),
    pa.field("merchant_category", pa.string()),
    pa.field("timestamp",         pa.timestamp("ms")),
    pa.field("balance_after",     pa.float64()),
    pa.field("is_flagged",        pa.bool_()),
])


def _make_chunk(fake: Faker, rng: random.Random, size: int) -> pa.Table:
    return pa.table(
        {
            "transaction_id":    [fake.uuid4()                                          for _ in range(size)],
            "account_id":        [f"ACC{rng.randint(100_000, 999_999)}"                 for _ in range(size)],
            "customer_name":     [fake.name()                                           for _ in range(size)],
            "transaction_type":  rng.choices(TRANSACTION_TYPES,                         k=size),
            "amount":            [round(rng.uniform(1.0, 50_000.0), 2)                  for _ in range(size)],
            "currency":          rng.choices(CURRENCIES, weights=[70, 15, 10, 5],       k=size),
            "channel":           rng.choices(CHANNELS,                                  k=size),
            "status":            rng.choices(STATUSES, weights=[85, 5, 7, 3],           k=size),
            "merchant_category": rng.choices(MERCHANT_CATS,                             k=size),
            "timestamp":         pa.array(
                                     pd.to_datetime(
                                         [fake.date_time_between(start_date="-2y") for _ in range(size)]
                                     ),
                                     type=pa.timestamp("ms"),
                                 ),
            "balance_after":     [round(rng.uniform(0.0, 200_000.0), 2)                 for _ in range(size)],
            "is_flagged":        rng.choices([True, False], weights=[2, 98],             k=size),
        },
        schema=SCHEMA,
    )


def generate_parquet() -> None:
    PARQUET_FILE.parent.mkdir(parents=True, exist_ok=True)

    with timer(STEP_WRITE):

        with timer(f"{STEP_WRITE}.init"):
            fake = Faker("en_US")
            Faker.seed(RANDOM_SEED)
            rng    = random.Random(RANDOM_SEED)
            writer = None

        with timer(f"{STEP_WRITE}.generate_and_write_chunks"):
            num_chunks   = TOTAL_ROWS // CHUNK_SIZE
            remainder    = TOTAL_ROWS  % CHUNK_SIZE
            rows_written = 0
            try:
                for i in range(num_chunks):
                    table = _make_chunk(fake, rng, CHUNK_SIZE)
                    if writer is None:
                        writer = pq.ParquetWriter(
                            PARQUET_FILE,
                            schema=SCHEMA,
                            compression=PARQUET_COMPRESSION,
                        )
                    writer.write_table(table, row_group_size=PARQUET_ROW_GROUP_SIZE)
                    rows_written += CHUNK_SIZE
                    if (i + 1) % 10 == 0:
                        pct = rows_written / TOTAL_ROWS * 100
                        logger.info(f"  Progress: {rows_written:,} / {TOTAL_ROWS:,} rows ({pct:.0f}%)")

                if remainder:
                    writer.write_table(_make_chunk(fake, rng, remainder), row_group_size=PARQUET_ROW_GROUP_SIZE)
                    rows_written += remainder
            finally:
                pass  # writer closed in next sub-process

        with timer(f"{STEP_WRITE}.close_and_flush"):
            if writer:
                writer.close()

    # Patch throughput into the parent step entry via the public API —
    # no direct access to timer internals.
    size_mb  = PARQUET_FILE.stat().st_size / 1024 ** 2
    duration = get_metrics()[STEP_WRITE]["duration_seconds"]

    patch_metrics(STEP_WRITE, {
        "rows_written":    rows_written,
        "parquet_size_mb": round(size_mb, 2),
        "rows_per_second": round(rows_written / duration, 0),
        "mb_per_second":   round(size_mb / duration, 2),
    })

    logger.success(
        f"Parquet written → {PARQUET_FILE.name} | "
        f"{size_mb:.1f} MB | {rows_written:,} rows | "
        f"{get_metrics()[STEP_WRITE]['rows_per_second']:,.0f} rows/s"
    )
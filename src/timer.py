# src/timer.py
# Context manager that measures elapsed time and RAM per pipeline step.
# Results are accumulated in _metrics and written to JSON via save_metrics().

import time
import json
import psutil
from contextlib import contextmanager
from typing import Optional
from loguru import logger
from config.settings import METRICS_FILE

_metrics: dict = {}


@contextmanager
def timer(label: str, store: bool = True):
    """
    Wraps a code block to measure duration and RAM delta.

    Usage:
        with timer("my_step"):
            do_work()
    """
    process    = psutil.Process()
    mem_before = process.memory_info().rss / 1024 ** 2  # MB
    cpu_before = process.cpu_percent(interval=None)  # prime the counter

    logger.info(f"[START] {label}")
    t0 = time.perf_counter()

    yield

    elapsed   = time.perf_counter() - t0
    mem_after = process.memory_info().rss / 1024 ** 2
    mem_delta = mem_after - mem_before
    cpu_usage = process.cpu_percent(interval=None) # % since last call

    logger.info(f"[END]   {label} — {elapsed:.2f}s | RAM delta: {mem_delta:+.1f} MB | CPU: {cpu_usage:.1f}%")

    if store:
        _metrics[label] = {
            "duration_seconds": round(elapsed, 4),
            "ram_delta_mb":     round(mem_delta, 2),
            "cpu_percent":      round(cpu_usage, 1),
        }


def save_metrics(extra: Optional[dict] = None) -> None:
    """Persist all collected metrics plus any extra info to JSON."""
    METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {**_metrics, **(extra or {})}
    with open(METRICS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    logger.info(f"Metrics saved → {METRICS_FILE}")


def get_metrics() -> dict:
    return dict(_metrics)

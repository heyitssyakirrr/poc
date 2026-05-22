# src/timer.py
# Context manager that measures elapsed time, RAM (delta + avg + peak + free),
# and CPU (avg + peak) per step.
#
# Background thread samples every 100 ms:
#   - process RSS      → ram_avg_mb, ram_peak_mb
#   - system free RAM  → ram_free_min_mb  (worst-case pressure during step)
#   - cpu_percent      → cpu_avg_percent, cpu_peak_percent
#
# Results accumulate in _metrics and are written to JSON via save_metrics().

import time
import json
import threading
import psutil
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional
from loguru import logger
from config.settings import METRICS_FILE

_metrics: dict = {}

_CPU_CORES    = psutil.cpu_count(logical=True)
_TOTAL_RAM_MB = psutil.virtual_memory().total / 1024 ** 2


@contextmanager
def timer(label: str, store: bool = True):
    """
    Measures per step:
      duration_seconds
      ram_before_mb, ram_after_mb, ram_delta_mb, ram_avg_mb, ram_peak_mb
      ram_free_before_mb, ram_free_after_mb, ram_free_min_mb
      cpu_avg_percent, cpu_peak_percent
      cpu_cores_total
      start_time, end_time  (ISO-8601 UTC)
    """
    process = psutil.Process()

    # ── Baseline snapshots ────────────────────────────────────────────────────
    mem_before       = process.memory_info().rss / 1024 ** 2
    ram_free_before  = psutil.virtual_memory().available / 1024 ** 2
    process.cpu_percent(interval=None)          # prime — first call is always 0
    psutil.cpu_percent(interval=None)           # prime system-wide counter too

    # ── Shared mutable state for background thread ────────────────────────────
    _stop        = threading.Event()
    _peak_rss    = [mem_before]
    _free_min    = [ram_free_before]
    _rss_samples = []                           # collect samples → avg + peak
    _cpu_samples = []                           # collect samples → avg + peak

    def _sampler():
        while not _stop.is_set():
            # RAM
            rss  = process.memory_info().rss / 1024 ** 2
            free = psutil.virtual_memory().available / 1024 ** 2
            _rss_samples.append(rss)
            if rss  > _peak_rss[0]: _peak_rss[0] = rss
            if free < _free_min[0]: _free_min[0] = free

            # CPU — system-wide aggregate across all cores
            cpu = psutil.cpu_percent(interval=None)
            if cpu > 0:             # skip 0.0 artefacts from priming
                _cpu_samples.append(cpu)

            _stop.wait(timeout=0.1)

    sampler = threading.Thread(target=_sampler, daemon=True)

    start_dt = datetime.now(timezone.utc)
    logger.info(f"[START] {label}")
    t0 = time.perf_counter()

    sampler.start()
    try:
        yield
    finally:
        _stop.set()
        sampler.join(timeout=1.0)

    elapsed = time.perf_counter() - t0
    end_dt  = datetime.now(timezone.utc)

    mem_after      = process.memory_info().rss / 1024 ** 2
    ram_free_after = psutil.virtual_memory().available / 1024 ** 2

    ram_avg  = round(sum(_rss_samples) / len(_rss_samples), 2) if _rss_samples else round(mem_before, 2)
    cpu_avg  = round(sum(_cpu_samples) / len(_cpu_samples), 1) if _cpu_samples else 0.0
    cpu_peak = round(max(_cpu_samples), 1)                      if _cpu_samples else 0.0

    logger.info(
        f"[END]   {label} — {elapsed:.2f}s | "
        f"RAM Δ: {mem_after - mem_before:+.1f} MB | "
        f"RAM avg: {ram_avg:.1f} MB | "
        f"RAM peak: {_peak_rss[0]:.1f} MB | "
        f"Free RAM min: {_free_min[0]:.1f} MB | "
        f"CPU avg: {cpu_avg:.1f}% | CPU peak: {cpu_peak:.1f}%"
    )

    if store:
        _metrics[label] = {
            "duration_seconds":  round(elapsed, 4),
            # process RAM
            "ram_before_mb":     round(mem_before,             2),
            "ram_after_mb":      round(mem_after,              2),
            "ram_delta_mb":      round(mem_after - mem_before, 2),
            "ram_avg_mb":        ram_avg,
            "ram_peak_mb":       round(_peak_rss[0],           2),
            # system free RAM
            "ram_free_before_mb": round(ram_free_before,       2),
            "ram_free_after_mb":  round(ram_free_after,        2),
            "ram_free_min_mb":    round(_free_min[0],          2),
            # CPU
            "cpu_avg_percent":   cpu_avg,
            "cpu_peak_percent":  cpu_peak,
            "cpu_cores_total":   _CPU_CORES,
            # timestamps
            "start_time":        start_dt.isoformat(),
            "end_time":          end_dt.isoformat(),
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
# src/timer.py
# Context manager that measures elapsed time, RAM (delta + avg + peak + free),
# and CPU (avg + peak) per step.
#
# Background thread samples every 100 ms:
#   - process RSS      → ram_avg_mb, ram_peak_mb
#   - system free RAM  → ram_free_min_mb  (worst-case pressure during step)
#   - cpu_percent      → cpu_avg_percent, cpu_peak_percent
#
# Results accumulate in MetricsStore (metrics_store singleton) and are
# written to JSON via save_metrics().
#
# Public API
# ──────────
#   timer(label)               context manager — measure a block
#   patch_metrics(label, dict) merge extra keys into an existing entry
#   save_metrics(extra)        persist everything to JSON
#   get_metrics()              return a snapshot dict

import time
import json
import threading
import psutil
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional
from loguru import logger
from config.settings import METRICS_FILE

_CPU_CORES    = psutil.cpu_count(logical=True)
_TOTAL_RAM_MB = psutil.virtual_memory().total / 1024 ** 2


# ── MetricsStore ───────────────────────────────────────────────────────────────

class MetricsStore:
    """
    Thread-safe store for per-step performance metrics.
    Replaces the old bare _metrics dict so callers never touch internals directly.
    """

    def __init__(self) -> None:
        self._data: dict = {}
        self._lock = threading.Lock()

    def set(self, label: str, value: dict) -> None:
        with self._lock:
            self._data[label] = value

    def patch(self, label: str, extra: dict) -> None:
        """Merge extra keys into an existing entry. No-op if label not found."""
        with self._lock:
            if label in self._data:
                self._data[label].update(extra)

    def get(self) -> dict:
        with self._lock:
            return dict(self._data)

    def clear(self) -> None:
        with self._lock:
            self._data = {}


# Module-level singleton — import this, never the old _metrics dict
metrics_store = MetricsStore()

# ── Backwards-compat shim ──────────────────────────────────────────────────────
# generator.py and reader.py used to import _metrics directly.
# They now call patch_metrics() instead, but this shim prevents hard crashes
# if any forgotten import still references _metrics.
class _MetricsShim(dict):
    """Proxy that warns loudly when old code tries to use _metrics directly."""
    def __getitem__(self, key):
        logger.warning(
            f"Deprecated: direct access to _metrics['{key}']. "
            "Use patch_metrics() instead."
        )
        return metrics_store.get().get(key, {})

    def __setitem__(self, key, value):
        logger.warning(
            f"Deprecated: direct mutation of _metrics['{key}']. "
            "Use metrics_store.set() instead."
        )
        metrics_store.set(key, value)

_metrics = _MetricsShim()


# ── Public helpers ─────────────────────────────────────────────────────────────

def patch_metrics(label: str, extra: dict) -> None:
    """
    Merge extra keys into an existing metrics entry.
    Call this after a timer() block to attach throughput or row-count data.

    Example
    -------
    patch_metrics("write_parquet", {
        "rows_written":    rows_written,
        "parquet_size_mb": round(size_mb, 2),
        "rows_per_second": round(rows_written / duration, 0),
        "mb_per_second":   round(size_mb / duration, 2),
    })
    """
    metrics_store.patch(label, extra)


def save_metrics(extra: Optional[dict] = None) -> None:
    """Persist all collected metrics plus any extra info to JSON."""
    METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {**metrics_store.get(), **(extra or {})}
    with open(METRICS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    logger.info(f"Metrics saved → {METRICS_FILE}")


def get_metrics() -> dict:
    """Return a snapshot of all collected metrics."""
    return metrics_store.get()


# ── Timer context manager ──────────────────────────────────────────────────────

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
    process.cpu_percent(interval=None)   # prime — first call is always 0
    psutil.cpu_percent(interval=None)    # prime system-wide counter too

    # ── Shared mutable state for background thread ────────────────────────────
    _stop        = threading.Event()
    _peak_rss    = [mem_before]
    _free_min    = [ram_free_before]
    _rss_samples = []
    _cpu_samples = []

    def _sampler():
        while not _stop.is_set():
            rss  = process.memory_info().rss / 1024 ** 2
            free = psutil.virtual_memory().available / 1024 ** 2
            _rss_samples.append(rss)
            if rss  > _peak_rss[0]: _peak_rss[0] = rss
            if free < _free_min[0]: _free_min[0] = free

            cpu = psutil.cpu_percent(interval=None)
            if cpu > 0:
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
        metrics_store.set(label, {
            "duration_seconds":   round(elapsed, 4),
            # process RAM
            "ram_before_mb":      round(mem_before,             2),
            "ram_after_mb":       round(mem_after,              2),
            "ram_delta_mb":       round(mem_after - mem_before, 2),
            "ram_avg_mb":         ram_avg,
            "ram_peak_mb":        round(_peak_rss[0],           2),
            # system free RAM
            "ram_free_before_mb": round(ram_free_before,        2),
            "ram_free_after_mb":  round(ram_free_after,         2),
            "ram_free_min_mb":    round(_free_min[0],           2),
            # CPU
            "cpu_avg_percent":    cpu_avg,
            "cpu_peak_percent":   cpu_peak,
            "cpu_cores_total":    _CPU_CORES,
            # timestamps
            "start_time":         start_dt.isoformat(),
            "end_time":           end_dt.isoformat(),
        })
# src/timer.py
# Context manager that measures elapsed time, RAM (delta + avg + peak + free),
# and CPU (avg + peak) per step.
#
# All CPU values are stored on the SAME 0-100% scale where:
#   100% = the full system capacity (all cores fully used)
#   This matches psutil.cpu_percent(percpu=False) which averages across cores.
#
# Background thread samples every 100 ms:
#   - process RSS           → ram_avg_mb, ram_peak_mb
#   - system free RAM       → ram_free_min_mb  (worst-case pressure during step)
#   - psutil.cpu_percent()  → cpu_sys_avg_percent, cpu_sys_peak_percent  (0-100, system-wide avg)
#   - process.cpu_percent() → cpu_proc_avg_percent  (normalised to 0-100 by dividing by cpu_count)
#   - derived               → cpu_others_avg_percent = sys_avg - proc_avg (clamped ≥ 0)
#                          → cpu_free_percent        = 100 - sys_avg       (clamped ≥ 0)
#
# All three slices (pipeline + others + free) always sum to exactly 100%.
# The card and chart therefore show identical numbers — no conversion needed.
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
    Measures per step and stores to metrics_store under `label`.

    Stored keys
    ───────────
    duration_seconds          wall-clock elapsed time

    RAM (process RSS):
      ram_before_mb           RSS at block entry
      ram_after_mb            RSS at block exit
      ram_delta_mb            after - before
      ram_avg_mb              mean RSS across samples
      ram_peak_mb             peak RSS across samples

    RAM (system free):
      ram_free_before_mb      free at block entry
      ram_free_after_mb       free at block exit
      ram_free_min_mb         minimum free across samples (worst-case pressure)
      ram_sys_used_avg_mb     mean total system RAM in use
      ram_others_avg_mb       sys_used_avg - ram_avg  (other processes)

    CPU — ALL on 0-100% scale (100% = all cores fully utilised):
      cpu_sys_avg_percent     system-wide average (psutil.cpu_percent averaged)
      cpu_sys_peak_percent    system-wide peak    (max psutil.cpu_percent sample)
      cpu_proc_avg_percent    pipeline process average (process.cpu_percent / cpu_count)
      cpu_others_avg_percent  sys_avg - proc_avg  (clamped ≥ 0)
      cpu_free_percent        100 - sys_avg       (clamped ≥ 0)
      cpu_cores_total         logical core count

    Legacy aliases (kept for backwards compat with existing JSON / templates):
      cpu_avg_percent         → same as cpu_sys_avg_percent
      cpu_peak_percent        → same as cpu_sys_peak_percent
    """
    process = psutil.Process()

    # ── Baseline snapshots ────────────────────────────────────────────────────
    mem_before      = process.memory_info().rss / 1024 ** 2
    ram_free_before = psutil.virtual_memory().available / 1024 ** 2
    # Prime the non-blocking counters (first call always returns 0.0)
    process.cpu_percent(interval=None)
    psutil.cpu_percent(interval=None)

    # ── Shared mutable state for background thread ────────────────────────────
    _stop            = threading.Event()
    _peak_rss        = [mem_before]
    _free_min        = [ram_free_before]
    _rss_samples     = []
    _sys_cpu_samples = []   # psutil.cpu_percent() → 0-100
    _proc_cpu_samples= []   # process.cpu_percent() → 0-(N*100), normalised below
    _sys_used_samples= []

    def _sampler() -> None:
        while not _stop.is_set():
            # RAM
            rss  = process.memory_info().rss / 1024 ** 2
            vm   = psutil.virtual_memory()
            free = vm.available / 1024 ** 2

            _rss_samples.append(rss)
            _sys_used_samples.append(vm.used / 1024 ** 2)
            if rss  > _peak_rss[0]: _peak_rss[0] = rss
            if free < _free_min[0]: _free_min[0] = free

            # CPU — collect raw values; normalisation happens after the block
            sys_cpu  = psutil.cpu_percent(interval=None)   # 0-100
            proc_cpu = process.cpu_percent(interval=None)  # 0-(N*100)
            if sys_cpu  > 0: _sys_cpu_samples.append(sys_cpu)
            if proc_cpu > 0: _proc_cpu_samples.append(proc_cpu)

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

    # ── RAM aggregates ────────────────────────────────────────────────────────
    ram_avg       = round(sum(_rss_samples)      / len(_rss_samples),      2) if _rss_samples      else round(mem_before, 2)
    sys_used_avg  = round(sum(_sys_used_samples) / len(_sys_used_samples), 2) if _sys_used_samples else ram_avg
    ram_others    = max(round(sys_used_avg - ram_avg, 2), 0)

    # ── CPU aggregates — normalised to 0-100% ─────────────────────────────────
    # psutil.cpu_percent()  is already 0-100 (averaged across all cores).
    # process.cpu_percent() is 0-(N*100); divide by cpu_count to get 0-100.
    # Both are now on the same scale → proc + others + free = 100%.
    cpu_sys_avg   = round(sum(_sys_cpu_samples)  / len(_sys_cpu_samples),  1) if _sys_cpu_samples  else 0.0
    cpu_sys_peak  = round(max(_sys_cpu_samples),                           1) if _sys_cpu_samples  else 0.0
    cpu_proc_avg  = round(
        (sum(_proc_cpu_samples) / len(_proc_cpu_samples)) / _CPU_CORES, 1
    ) if _proc_cpu_samples else 0.0
    cpu_others    = max(round(cpu_sys_avg - cpu_proc_avg, 1), 0.0)
    cpu_free      = max(round(100.0 - cpu_sys_avg,        1), 0.0)

    logger.info(
        f"[END]   {label} — {elapsed:.2f}s | "
        f"RAM Δ {mem_after - mem_before:+.1f} MB | "
        f"RAM avg {ram_avg:.1f} MB | RAM peak {_peak_rss[0]:.1f} MB | "
        f"Free RAM min {_free_min[0]:.1f} MB | "
        f"CPU sys avg {cpu_sys_avg:.1f}% | CPU sys peak {cpu_sys_peak:.1f}% | "
        f"CPU proc avg {cpu_proc_avg:.1f}% | CPU others {cpu_others:.1f}% | CPU free {cpu_free:.1f}%"
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
            "ram_sys_used_avg_mb":    sys_used_avg,
            "ram_others_avg_mb":      ram_others,

            # CPU — all 0-100% (100% = full system capacity)
            "cpu_sys_avg_percent":    cpu_sys_avg,
            "cpu_sys_peak_percent":   cpu_sys_peak,
            "cpu_proc_avg_percent":   cpu_proc_avg,
            "cpu_others_avg_percent": cpu_others,
            "cpu_free_percent":       cpu_free,
            "cpu_cores_total":        _CPU_CORES,

            # Legacy aliases — keeps old JSON / templates working without changes
            "cpu_avg_percent":    cpu_sys_avg,
            "cpu_peak_percent":   cpu_sys_peak,

            # timestamps
            "start_time":         start_dt.isoformat(),
            "end_time":           end_dt.isoformat(),
        })
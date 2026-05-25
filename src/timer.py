# src/timer.py
#
# Context manager that measures elapsed time, RAM, and CPU per pipeline step.
#
# ── CPU scale (0-100%, 100% = all cores fully utilised) ───────────────────────
# All CPU values live on the SAME normalised scale so card values and chart bars
# always show identical numbers. Three slices always sum to exactly 100 %:
#
#   cpu_proc_avg_percent    pipeline process share  (proc.cpu_percent / cpu_count)
#   cpu_others_avg_percent  other processes share   (sys_avg − proc_avg, clamped ≥ 0)
#   cpu_free_percent        idle share              (100 − sys_avg, clamped ≥ 0)
#
# ── RAM accounting ────────────────────────────────────────────────────────────
# "Used" is derived from (total − available) NOT from vm.used, because on Linux
# vm.used includes the OS page/file cache which inflates "others RAM".
# vm.available is the amount the OS can hand to a new process immediately
# (it includes reclaimable cache), giving the most accurate three-way split:
#
#   pipeline RSS  + others RSS  + free  =  total RAM
#
# ── Sampling ──────────────────────────────────────────────────────────────────
# A background thread samples every SAMPLE_INTERVAL_S seconds.
# CPU counters are primed immediately before the thread starts (not before the
# shared-state setup) so the very first sample is already valid.
# Zero CPU readings are kept — they are legitimate idle samples, not artefacts.
#
# ── Public API ────────────────────────────────────────────────────────────────
#   timer(label)               context manager — measure a block
#   patch_metrics(label, dict) merge extra keys into an existing entry
#   save_metrics(extra)        persist all metrics to JSON
#   get_metrics()              return a snapshot dict

from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generator, Optional

import psutil
from loguru import logger

from config.settings import METRICS_FILE

# ── Module-level constants ─────────────────────────────────────────────────────
_CPU_CORES: int = psutil.cpu_count(logical=True) or 1
_TOTAL_RAM_MB: float = psutil.virtual_memory().total / 1024 ** 2
SAMPLE_INTERVAL_S: float = 0.10  # sampling cadence in seconds


# ── MetricsStore ───────────────────────────────────────────────────────────────

class MetricsStore:
    """
    Thread-safe key-value store for per-step performance metrics.

    Design notes
    ────────────
    • All mutations go through set() / patch() — callers never touch _data directly.
    • get() returns a shallow copy so callers can't mutate internal state.
    • clear() is provided for test isolation; production code doesn't call it.
    """

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._lock = threading.Lock()

    def set(self, label: str, value: dict[str, Any]) -> None:
        with self._lock:
            self._data[label] = value

    def patch(self, label: str, extra: dict[str, Any]) -> None:
        """Merge *extra* into an existing entry. Silent no-op if label is absent."""
        with self._lock:
            if label in self._data:
                self._data[label].update(extra)

    def get(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._data)

    def clear(self) -> None:
        with self._lock:
            self._data = {}


# Module-level singleton — import and use this everywhere.
metrics_store = MetricsStore()


# ── Public helpers ─────────────────────────────────────────────────────────────

def patch_metrics(label: str, extra: dict[str, Any]) -> None:
    """
    Merge *extra* keys into an existing timer entry.

    Call this after a timer() block to attach derived data such as
    throughput, row counts, or file sizes — data that isn't available
    until the step has completed.

    Example
    -------
    with timer("write_parquet"):
        write(...)

    patch_metrics("write_parquet", {"rows_written": n, "mb_per_second": x})
    """
    metrics_store.patch(label, extra)


def save_metrics(extra: Optional[dict[str, Any]] = None) -> None:
    """
    Persist all collected metrics plus optional *extra* payload to JSON.

    The output file is defined by METRICS_FILE in config/settings.py.
    Parent directories are created automatically.
    """
    METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {**metrics_store.get(), **(extra or {})}
    with open(METRICS_FILE, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    logger.info(f"Metrics saved → {METRICS_FILE}")


def get_metrics() -> dict[str, Any]:
    """Return a point-in-time snapshot of all collected metrics."""
    return metrics_store.get()


# ── Internal sampler helpers ───────────────────────────────────────────────────

class _StepSamples:
    """
    Holds raw samples collected by the background sampler thread.

    Keeping samples in one object makes the aggregation code below
    easier to read and avoids scattering list names across the closure.
    """

    __slots__ = (
        "rss_mb",
        "sys_used_true_mb",   # (total − available) — excludes reclaimable cache
        "free_mb",
        "sys_cpu_pct",         # psutil system-wide 0-100 %
        "proc_cpu_pct",        # process share normalised to 0-100 % (already /= cpu_count)
        "rss_peak_mb",
        "free_min_mb",
    )

    def __init__(self, initial_rss: float, initial_free: float) -> None:
        self.rss_mb:           list[float] = []
        self.sys_used_true_mb: list[float] = []
        self.free_mb:          list[float] = []
        self.sys_cpu_pct:      list[float] = []
        self.proc_cpu_pct:     list[float] = []
        self.rss_peak_mb:      float = initial_rss
        self.free_min_mb:      float = initial_free


def _build_sampler(
    process: psutil.Process,
    samples: _StepSamples,
    stop: threading.Event,
) -> threading.Thread:
    """
    Return a daemon thread that appends resource readings to *samples*
    every SAMPLE_INTERVAL_S seconds until *stop* is set.

    CPU notes
    ─────────
    • Both cpu_percent() counters are primed by the caller immediately
      before this thread is started so the very first reading is valid.
    • Zero readings are kept — they are genuine idle samples.
    • proc_cpu is divided by _CPU_CORES here so the list already holds
      a 0-100 % normalised value and the aggregation code is simpler.

    RAM notes
    ─────────
    • sys_used_true = total − available.  This excludes the OS file-cache
      so "others RAM" = sys_used_true − pipeline_rss reflects actual
      other-process footprint rather than cache-inflated usage.
    """

    def _run() -> None:
        while not stop.is_set():
            vm  = psutil.virtual_memory()
            rss = process.memory_info().rss / 1024 ** 2

            free          = vm.available / 1024 ** 2
            sys_used_true = (vm.total - vm.available) / 1024 ** 2

            samples.rss_mb.append(rss)
            samples.sys_used_true_mb.append(sys_used_true)
            samples.free_mb.append(free)

            if rss  > samples.rss_peak_mb:  samples.rss_peak_mb = rss
            if free < samples.free_min_mb:  samples.free_min_mb = free

            # cpu_percent(interval=None) is non-blocking; returns delta since
            # last call.  Both counters were primed just before start().
            sys_cpu  = psutil.cpu_percent(interval=None)           # 0-100
            proc_cpu = process.cpu_percent(interval=None)          # 0-(N×100)
            proc_cpu_norm = proc_cpu / _CPU_CORES                  # → 0-100

            samples.sys_cpu_pct.append(sys_cpu)
            samples.proc_cpu_pct.append(proc_cpu_norm)

            stop.wait(timeout=SAMPLE_INTERVAL_S)

    return threading.Thread(target=_run, daemon=True, name=f"sampler-{id(samples)}")


def _aggregate(
    samples: _StepSamples,
    mem_before: float,
    mem_after:  float,
) -> dict[str, Any]:
    """
    Compute aggregate statistics from raw samples.

    Returns a flat dict ready to be stored in MetricsStore.
    All CPU values are on the 0-100 % scale (100 % = all cores busy).
    RAM "others" uses (total−available) − pipeline_rss to avoid inflating
    the value with OS page cache.
    """

    def _avg(lst: list[float], fallback: float = 0.0) -> float:
        return round(sum(lst) / len(lst), 2) if lst else fallback

    def _peak(lst: list[float], fallback: float = 0.0) -> float:
        return round(max(lst), 2) if lst else fallback

    # ── RAM ───────────────────────────────────────────────────────────────────
    ram_avg       = _avg(samples.rss_mb, fallback=mem_before)
    sys_used_avg  = _avg(samples.sys_used_true_mb)
    # "Others" = true system usage minus our own RSS — always ≥ 0.
    ram_others    = max(round(sys_used_avg - ram_avg, 2), 0.0)

    # ── CPU ───────────────────────────────────────────────────────────────────
    cpu_sys_avg   = round(_avg(samples.sys_cpu_pct),  1)
    cpu_sys_peak  = round(_peak(samples.sys_cpu_pct), 1)
    cpu_proc_avg  = round(_avg(samples.proc_cpu_pct), 1)
    # Derived slices — clamped so floating-point noise never goes negative.
    cpu_others    = max(round(cpu_sys_avg - cpu_proc_avg, 1), 0.0)
    cpu_free      = max(round(100.0 - cpu_sys_avg,        1), 0.0)

    return {
        # ── RAM — process RSS ─────────────────────────────────────────────────
        "ram_before_mb":          round(mem_before,             2),
        "ram_after_mb":           round(mem_after,              2),
        "ram_delta_mb":           round(mem_after - mem_before, 2),
        "ram_avg_mb":             ram_avg,
        "ram_peak_mb":            round(samples.rss_peak_mb,    2),

        # ── RAM — system ──────────────────────────────────────────────────────
        "ram_free_min_mb":        round(samples.free_min_mb,    2),
        "ram_sys_used_avg_mb":    sys_used_avg,
        "ram_others_avg_mb":      ram_others,

        # ── CPU — all on 0-100 % scale ────────────────────────────────────────
        "cpu_sys_avg_percent":    cpu_sys_avg,
        "cpu_sys_peak_percent":   cpu_sys_peak,
        "cpu_proc_avg_percent":   cpu_proc_avg,
        "cpu_others_avg_percent": cpu_others,
        "cpu_free_percent":       cpu_free,
        "cpu_cores_total":        _CPU_CORES,

        # ── Legacy aliases (keeps existing JSON / templates working) ──────────
        "cpu_avg_percent":        cpu_sys_avg,
        "cpu_peak_percent":       cpu_sys_peak,
    }


# ── Timer context manager ──────────────────────────────────────────────────────

@contextmanager
def timer(label: str, store: bool = True) -> Generator[None, None, None]:
    """
    Measure wall-clock time, RAM, and CPU for a code block and store the
    results in *metrics_store* under *label*.

    Parameters
    ----------
    label:
        Unique key for this step, e.g. "write_parquet" or
        "write_parquet.generate_and_write_chunks".
        Sub-steps use dot notation: "parent.child".
    store:
        Set False to run the sampler without persisting results (useful
        for dry-run benchmarks or unit tests).

    Stored keys
    ───────────
    duration_seconds          wall-clock elapsed time
    start_time / end_time     ISO-8601 UTC timestamps

    RAM (process RSS):
      ram_before_mb, ram_after_mb, ram_delta_mb
      ram_avg_mb, ram_peak_mb

    RAM (system):
      ram_free_min_mb           minimum available RAM during step
      ram_sys_used_avg_mb       mean (total − available) across samples
      ram_others_avg_mb         sys_used_avg − pipeline_rss (true other-proc RAM)

    CPU (all 0-100 %, 100 % = all cores fully utilised):
      cpu_proc_avg_percent      pipeline process share
      cpu_sys_avg_percent       system-wide average
      cpu_sys_peak_percent      system-wide peak
      cpu_others_avg_percent    cpu_sys_avg − cpu_proc_avg
      cpu_free_percent          100 − cpu_sys_avg
      cpu_cores_total           logical core count

    Legacy aliases (backwards-compat):
      cpu_avg_percent  → cpu_sys_avg_percent
      cpu_peak_percent → cpu_sys_peak_percent
    """
    process = psutil.Process()

    # ── Baseline snapshots ────────────────────────────────────────────────────
    mem_before  = process.memory_info().rss / 1024 ** 2
    vm_baseline = psutil.virtual_memory()
    free_before = vm_baseline.available / 1024 ** 2

    samples = _StepSamples(initial_rss=mem_before, initial_free=free_before)
    stop    = threading.Event()

    # ── Prime CPU counters immediately before the sampler starts ──────────────
    # psutil requires one "warm-up" call before interval=None returns valid data.
    # Placing the primes here (after _StepSamples is ready, just before start())
    # ensures the background thread's very first reading is valid.
    process.cpu_percent(interval=None)
    psutil.cpu_percent(interval=None)

    sampler    = _build_sampler(process, samples, stop)
    start_dt   = datetime.now(timezone.utc)

    logger.info(f"[START] {label}")
    t0 = time.perf_counter()

    sampler.start()
    try:
        yield
    finally:
        stop.set()
        sampler.join(timeout=2.0)   # generous timeout; thread is daemon anyway

    elapsed = time.perf_counter() - t0
    end_dt  = datetime.now(timezone.utc)

    mem_after = process.memory_info().rss / 1024 ** 2
    stats     = _aggregate(samples, mem_before, mem_after)

    logger.info(
        f"[END]   {label} — {elapsed:.2f}s | "
        f"RAM Δ {mem_after - mem_before:+.1f} MB | "
        f"RAM avg {stats['ram_avg_mb']:.1f} MB | "
        f"RAM peak {stats['ram_peak_mb']:.1f} MB | "
        f"Free min {stats['ram_free_min_mb']:.1f} MB | "
        f"CPU sys avg {stats['cpu_sys_avg_percent']:.1f}% | "
        f"CPU sys peak {stats['cpu_sys_peak_percent']:.1f}% | "
        f"CPU proc avg {stats['cpu_proc_avg_percent']:.1f}% | "
        f"CPU others {stats['cpu_others_avg_percent']:.1f}% | "
        f"CPU free {stats['cpu_free_percent']:.1f}%"
    )

    if store:
        metrics_store.set(label, {
            "duration_seconds": round(elapsed, 4),
            "start_time":       start_dt.isoformat(),
            "end_time":         end_dt.isoformat(),
            **stats,
        })
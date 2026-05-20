# config/settings.py
# Single source of truth for all project configuration.
# Change values here — never hardcode paths or constants elsewhere.

from pathlib import Path

# ── Directories ────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).resolve().parent.parent
DATA_DIR    = BASE_DIR / "data"
LOG_DIR     = BASE_DIR / "logs"
STATIC_DIR  = BASE_DIR / "src" / "dashboard" / "static"

# ── Files ──────────────────────────────────────────────────────────────────────
PARQUET_FILE    = DATA_DIR / "transactions.parquet"
METRICS_FILE    = DATA_DIR / "performance_metrics.json"
PLOTLY_JS_DEST  = STATIC_DIR / "js" / "plotly.min.js"   # copied from pip package at startup

# ── Data Generation ────────────────────────────────────────────────────────────
TOTAL_ROWS       = 5_000_000   # total rows to generate
CHUNK_SIZE       = 100_000     # rows per batch — tune down if RAM is limited
RANDOM_SEED      = 42          # fixed seed for reproducible output

# ── Parquet ────────────────────────────────────────────────────────────────────
PARQUET_COMPRESSION    = "snappy"   # snappy | gzip | brotli | none
PARQUET_ROW_GROUP_SIZE = 100_000    # affects read performance

# ── Flask Dashboard ────────────────────────────────────────────────────────────
DASHBOARD_TITLE = "POC — 5M Parquet Data Pipeline"
DASHBOARD_HOST  = "0.0.0.0"    # 0.0.0.0 allows LAN access; use 127.0.0.1 for local only
DASHBOARD_PORT  = 5000
DASHBOARD_DEBUG = False         # never True in a bank environment

# ── Logging ────────────────────────────────────────────────────────────────────
LOG_LEVEL     = "INFO"
LOG_ROTATION  = "10 MB"
LOG_RETENTION = "7 days"

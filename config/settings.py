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
TOTAL_ROWS       = 500_000   # total rows to generate
CHUNK_SIZE       = 100_000   # rows per batch — tune down if RAM is limited
RANDOM_SEED      = 42      # fixed seed for reproducible output

# ── Parquet ────────────────────────────────────────────────────────────────────
PARQUET_COMPRESSION    = "snappy"   # snappy | gzip | brotli | none
PARQUET_ROW_GROUP_SIZE = 100_000    # affects read performance

# ── Flask Dashboard ────────────────────────────────────────────────────────────
DASHBOARD_TITLE = "POC — Data Pipeline Performance"
DASHBOARD_HOST  = "127.0.0.1"    # 0.0.0.0 allows LAN access; use 127.0.0.1 for local only
DASHBOARD_PORT  = 5000
DASHBOARD_DEBUG = True  

# ── Logging ────────────────────────────────────────────────────────────────────
LOG_LEVEL     = "INFO"
LOG_ROTATION  = "10 MB"
LOG_RETENTION = "7 days"

# ── Pipeline Step Names ────────────────────────────────────────────────────────
# Single source of truth for step keys used in timer(), metrics patching,
# and dashboard rendering. Rename a step here — everywhere updates automatically.
STEP_WRITE = "write_parquet"
STEP_READ  = "read_parquet"

# ── Waterfall Chart Label Map ──────────────────────────────────────────────────
# Maps sub-process suffix (the part after the dot) to a human-readable label.
# Add an entry here whenever you add a new sub-process timer() block.
# Format:  "<parent_step>.<suffix>": "Display Label"
STEP_LABEL_MAP: dict[str, str] = {
    "init":                      "Initialize",
    "generate_and_write_chunks": "Write Chunks",
    "close_and_flush":           "Close & Flush",
    "open_and_deserialize":      "Load & Deserialize",
    "validate_schema":           "Validate Schema",
}
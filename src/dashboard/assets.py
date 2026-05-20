import shutil
import plotly
from pathlib import Path
from loguru import logger

from config.settings import PLOTLY_JS_DEST

# Plotly always ships plotly.min.js inside its package_data directory
_PLOTLY_JS_SOURCE = Path(plotly.__file__).parent / "package_data" / "plotly.min.js"


def ensure_plotly_js() -> None:
    """
    Copy plotly.min.js from the pip package to Flask's static folder.
    Skipped if the file already exists (idempotent — safe to call on every startup).
    """
    if PLOTLY_JS_DEST.exists():
        logger.debug(f"plotly.min.js already in static folder ({PLOTLY_JS_DEST})")
        return

    if not _PLOTLY_JS_SOURCE.exists():
        raise FileNotFoundError(
            f"plotly.min.js not found inside pip package at {_PLOTLY_JS_SOURCE}. "
            "Make sure plotly is installed: pip install plotly"
        )

    PLOTLY_JS_DEST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_PLOTLY_JS_SOURCE, PLOTLY_JS_DEST)
    size_kb = PLOTLY_JS_DEST.stat().st_size / 1024
    logger.info(f"plotly.min.js copied to static folder ({size_kb:.0f} KB) — serving offline")

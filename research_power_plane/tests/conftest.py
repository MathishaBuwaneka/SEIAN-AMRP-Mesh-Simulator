from __future__ import annotations

import os
import sys
from pathlib import Path


# Streamlit's AppTest file watcher can retain its temporary source directory
# until interpreter shutdown on Windows, causing a spurious cleanup traceback.
os.environ.setdefault("STREAMLIT_SERVER_FILE_WATCHER_TYPE", "none")

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
if str(RESEARCH_ROOT) not in sys.path:
    sys.path.insert(0, str(RESEARCH_ROOT))


def pytest_sessionfinish(session, exitstatus):  # type: ignore[no-untyped-def]
    """Suppress a Streamlit AppTest 1.x cleanup bug on Windows/Python 3.13."""

    if os.name != "nt":
        return
    try:
        from streamlit.testing.v1 import app_test

        # AppTest creates one module-global TemporaryDirectory. A Streamlit
        # worker can still hold it when Python's weakref finalizer runs, which
        # prints a PermissionError after otherwise successful tests.
        app_test.TMP_DIR._finalizer.detach()
    except (AttributeError, ImportError):
        pass

"""Launch the SEIAN PSCAD co-simulation dashboard."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    here = Path(__file__).resolve().parent
    dashboard = here / "dashboard.py"
    return subprocess.call(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(dashboard),
            "--server.headless",
            "true",
        ],
        cwd=here.parent,
    )


if __name__ == "__main__":
    raise SystemExit(main())

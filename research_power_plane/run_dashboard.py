"""Launch the SEIAN PSCAD co-simulation dashboard."""

from __future__ import annotations

import subprocess
import socket
import sys
from pathlib import Path


def main() -> int:
    here = Path(__file__).resolve().parent
    dashboard = here / "dashboard.py"
    port = 8502
    while port < 8600:
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                port += 1
            else:
                break
    else:
        raise RuntimeError("No available dashboard port in 8502-8599.")
    print(f"SEIAN research dashboard: http://localhost:{port}", flush=True)
    return subprocess.call(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(dashboard),
            "--server.headless",
            "true",
            "--server.port",
            str(port),
            "--browser.gatherUsageStats",
            "false",
        ],
        cwd=here.parent,
    )


if __name__ == "__main__":
    raise SystemExit(main())

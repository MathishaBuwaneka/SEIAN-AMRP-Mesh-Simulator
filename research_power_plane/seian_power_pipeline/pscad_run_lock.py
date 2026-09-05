"""Exclude overlapping dashboard/CLI writes to the same PSCAD service."""

from __future__ import annotations

import hashlib
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse


@contextmanager
def exclusive_pscad_run(endpoint: str):
    port = urlparse(endpoint).port or 80
    key = hashlib.sha256(f"local-pscad:{port}".encode("ascii")).hexdigest()[:16]
    path = Path(tempfile.gettempdir()) / f"seian-pscad-run-{key}.lock"
    with path.open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("Another PSCAD operation is in progress. Retry after it finishes.") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

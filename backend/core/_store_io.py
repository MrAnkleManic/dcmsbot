"""Locked read / atomic-rename write primitive for JSON stores.

Ported from iron-resolve/data_adapters/_store_io.py via iln_bot. The shape:

    load → mutate list → dump whole file

without locking, concurrent writers silently clobber each other. The
append-only api-usage log relies on completeness (monthly rollups want
every call accounted for), so silent race loss would be a credibility
risk for the cost-visibility story, not just an operational one.

Usage
-----

    from backend.core._store_io import update_json_store

    with update_json_store(PATH, default=[]) as store:
        store.append(new_entry)
    # lock released here, after atomic rename

Read lock is SHARED (LOCK_SH), write lock is EXCLUSIVE (LOCK_EX).
Writes go to a temp file in the same directory, then `os.replace()`
atomically renames into place.

Windows is not supported (fcntl is POSIX). DCMS deploys on Fly.io
(Linux), so this is fine; revisit if the deploy target ever changes.
"""

from __future__ import annotations

import errno
import fcntl
import json
import logging
import os
import tempfile
from contextlib import contextmanager
from typing import Any, Callable, Iterator

logger = logging.getLogger(__name__)


def _lock_path(data_path: str) -> str:
    return data_path + ".lock"


def load_json_store(path: str, default: Any = None) -> Any:
    """Read a JSON file under a SHARED lock.

    Missing file → return `default`. Corrupt file → log and return
    `default` rather than raise.
    """
    if not os.path.exists(path):
        return default

    lock_path = _lock_path(path)
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_SH)
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("load_json_store: failed to parse %s: %s", path, e)
            return default
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
    finally:
        os.close(lock_fd)


@contextmanager
def update_json_store(
    path: str,
    *,
    default: Any = None,
    write_default: Callable[[Any], Any] | None = None,
    indent: int | None = 2,
    ensure_ascii: bool = True,
) -> Iterator[Any]:
    """Read-modify-write transaction under a single exclusive lock.

    Holds LOCK_EX across load+mutate+save so concurrent appenders
    serialise instead of racing on the read-before-write window.
    Writes via atomic rename, so an interrupted writer leaves the
    canonical file untouched.
    """
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    lock_path = _lock_path(path)
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        if os.path.exists(path):
            try:
                with open(path) as f:
                    data = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(
                    "update_json_store: failed to parse %s, starting from default: %s",
                    path, e,
                )
                data = default if default is not None else None
        else:
            data = default if default is not None else None

        yield data

        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix=os.path.basename(path) + ".",
            suffix=".tmp",
            dir=directory,
        )
        try:
            with os.fdopen(tmp_fd, "w") as f:
                json.dump(
                    data,
                    f,
                    indent=indent,
                    default=write_default,
                    ensure_ascii=ensure_ascii,
                )
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError as e:
                if e.errno != errno.ENOENT:
                    logger.warning(
                        "update_json_store: failed to clean temp file %s: %s",
                        tmp_path, e,
                    )
            raise
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)

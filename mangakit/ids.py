"""Concurrency-safe ids and file locks.

Ids are claimed atomically: a directory id by os.mkdir, a file id by O_CREAT|O_EXCL. The next number
is one past the highest existing number (not the count of entries, which repeats an id after a
deletion and races between two workers)."""
from __future__ import annotations

import contextlib
import fcntl
import os
import re
from pathlib import Path as FsPath

_held: dict[str, int] = {}


def _next(d: FsPath, prefix: str, suffix: str = "") -> int:
    pat = re.compile(rf"^{re.escape(prefix)}(\d+){re.escape(suffix)}$")
    nums = [int(m.group(1)) for m in (pat.match(x.name) for x in d.iterdir()) if m] if d.exists() else []
    return max(nums or [0]) + 1


def claim_dir(d: FsPath, prefix: str, width: int = 4) -> FsPath:
    """Create and return d/<prefix><n> for the first free n >= max+1."""
    d = FsPath(d)
    d.mkdir(parents=True, exist_ok=True)
    n = _next(d, prefix)
    while True:
        p = d / f"{prefix}{n:0{width}d}"
        try:
            os.mkdir(p)
            return p
        except FileExistsError:
            n += 1


def claim_file(d: FsPath, prefix: str, suffix: str, width: int = 4) -> FsPath:
    """Create (empty) and return d/<prefix><n><suffix>, atomically."""
    d = FsPath(d)
    d.mkdir(parents=True, exist_ok=True)
    n = _next(d, prefix, suffix)
    while True:
        p = d / f"{prefix}{n:0{width}d}{suffix}"
        try:
            fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return p
        except FileExistsError:
            n += 1


@contextlib.contextmanager
def locked(lock_file: FsPath):
    """Exclusive advisory lock on lock_file for read-modify-write of a shared record (re-entrant
    within one process)."""
    key = str(FsPath(lock_file).resolve())
    if key in _held:
        _held[key] += 1
        try:
            yield
        finally:
            _held[key] -= 1
        return
    FsPath(lock_file).parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_file, os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        _held[key] = 1
        yield
    finally:
        _held.pop(key, None)
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

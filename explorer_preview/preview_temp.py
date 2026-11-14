"""Windows preview ownership leases, and collection of job directories whose owner died.

A claim is an exclusive ownership lock, not a race-free deletion capability.
The caller must keep it open and pin/revalidate native directory handles before
any future cleanup. Old unmarked jobs deliberately cannot be claimed.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import re
import stat

_MARKER = b"DracoConvPreview lease v1\n"
_NAMES = {"input.drc", "model.mesh", "model.mesh.part", "thumb.png", "ready", "events.log", "lease.v1"}
_GUID = re.compile(r"\{[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\}")


def _validate(job: Path) -> None:
    if not job.is_absolute() or not _GUID.fullmatch(job.name) or job.parent.name != "DracoConvPreview":
        raise ValueError("Not a preview job directory")
    for path in (job, *job.parents):
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_file_attributes & 0x400:
            raise ValueError("Directory is not a plain directory")
    for path in job.iterdir():
        info = path.lstat()
        if (path.name not in _NAMES or not stat.S_ISREG(info.st_mode)
                or info.st_file_attributes & 0x400 or info.st_nlink != 1):
            raise ValueError("Unrecognized or linked preview entry")


def _api():
    if os.name != "nt":
        raise OSError("Preview leases require Windows")
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                               ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    api.CreateFileW.restype = wintypes.HANDLE
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    for name in ("ReadFile", "WriteFile"):
        method = getattr(api, name)
        method.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                           ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        method.restype = wintypes.BOOL
    return api


class PreviewLease:
    """Exclusive, non-inheritable Windows handle; close after all work stops."""

    def __init__(self, api, handle):
        self._api, self._handle = api, handle

    def close(self):
        if self._handle is not None:
            self._api.CloseHandle(self._handle)
            self._handle = None

    def __enter__(self):
        if self._handle is None:
            raise ValueError("Lease is closed")
        return self

    def __exit__(self, *exc):
        self.close()

    def __del__(self):
        self.close()


def _open(job: Path, create: bool) -> PreviewLease:
    api = _api()
    handle = api.CreateFileW(str(job / "lease.v1"), 0xC0000000 if create else 0x80000000,
                             0, None, 1 if create else 3, 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    return PreviewLease(api, handle)


def create_lease(job: Path) -> PreviewLease:
    """Create ownership marker without replacing anything; caller owns handle.

    Call in a newly created GUID directory before starting input/helper work.
    Native owner equivalent: CREATE_NEW, GENERIC_READ|GENERIC_WRITE, sharing 0,
    OPEN_REPARSE_POINT, exact marker bytes; hold until helper has exited.
    """
    job = Path(job)
    _api()
    _validate(job)
    lease = _open(job, True)
    try:
        count = wintypes.DWORD()
        if not lease._api.WriteFile(lease._handle, _MARKER, len(_MARKER), ctypes.byref(count), None):
            raise ctypes.WinError(ctypes.get_last_error())
        if count.value != len(_MARKER):
            raise OSError("Incomplete preview lease marker")
        _validate(job)
        return lease
    except BaseException:
        lease.close()
        raise


def try_claim_stale(job: Path) -> PreviewLease | None:
    """Claim a recognized, unlocked job; errors/active/legacy jobs return None.

    No age or PID heuristics: an owner must hold the exclusive lease throughout
    every use of its directory. Never resume work after releasing the lease.
    This checks a snapshot only; do not pass the path to recursive deletion.
    """
    lease = None
    try:
        job = Path(job)
        _api()
        _validate(job)
        lease = _open(job, False)
        buffer = ctypes.create_string_buffer(len(_MARKER) + 1)
        count = wintypes.DWORD()
        if not lease._api.ReadFile(lease._handle, buffer, len(buffer), ctypes.byref(count), None):
            raise ctypes.WinError(ctypes.get_last_error())
        if buffer.raw[:count.value] != _MARKER:
            raise ValueError("Unknown preview lease marker")
        _validate(job)
        return lease
    except (OSError, ValueError):
        if lease is not None:
            lease.close()
        return None


def collect_stale(base: Path) -> int:
    """Remove job directories under base whose owner died; returns how many were removed.

    A directory is taken only through try_claim_stale: recognized entries, plain files, and a
    lease nobody holds. Deletion is by exact known name, never recursive; anything unexpected
    leaves the directory in place. Directories without a lease (older versions) are not touched.
    """
    removed = 0
    try:
        jobs = [job for job in Path(base).iterdir() if _GUID.fullmatch(job.name)]
    except OSError:
        return 0
    for job in jobs:
        lease = try_claim_stale(job)
        if lease is None:
            continue
        try:
            for name in _NAMES - {"lease.v1"}:
                (job / name).unlink(missing_ok=True)
        except OSError:
            lease.close()
            continue
        lease.close()
        try:
            (job / "lease.v1").unlink()
            job.rmdir()
            removed += 1
        except OSError:
            pass
    return removed

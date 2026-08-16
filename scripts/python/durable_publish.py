#!/usr/bin/env python3
"""Small shared primitives for durable, no-clobber filesystem publication."""

from __future__ import annotations

import ctypes
import errno
import os
import sys


def rename_noreplace(
    source_name: str,
    destination_name: str,
    *,
    src_dir_fd: int,
    dst_dir_fd: int,
) -> None:
    """Atomically rename one directory entry without replacing another.

    Python does not expose the native no-replace rename flags. VibeSquad's
    supported runtime platforms do: macOS has ``renameatx_np(RENAME_EXCL)`` and
    Linux has ``renameat2(RENAME_NOREPLACE)``. Unsupported platforms fail
    closed instead of weakening a publication commit point.
    """

    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        function_name = "renameatx_np"
        flag = 0x00000004  # RENAME_EXCL from <sys/stdio.h>
    elif sys.platform.startswith("linux"):
        function_name = "renameat2"
        flag = 0x00000001  # RENAME_NOREPLACE from <linux/fs.h>
    else:
        raise OSError(errno.ENOTSUP, "atomic no-replace rename is unsupported")
    try:
        rename = getattr(libc, function_name)
    except AttributeError as exc:
        raise OSError(
            errno.ENOTSUP,
            f"atomic no-replace rename is unavailable: {function_name}",
        ) from exc
    rename.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    rename.restype = ctypes.c_int
    result = rename(
        src_dir_fd,
        os.fsencode(source_name),
        dst_dir_fd,
        os.fsencode(destination_name),
        flag,
    )
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), destination_name)


__all__ = ["rename_noreplace"]

"""Requests from the Legion Go Toolbox's Battery playtime.

The toolbox (a separate Decky plugin, running as root) writes
``~/.config/lgo-toolbox/framegen.json``::

    {"version": 1, "updated": 1767000000,
     "games": {"1687950": {"standby": true, "multiplier": 2}}}

standby     give the game an lsfg-vk profile at 1x (off). lsfg-vk only picks a
            game up when it starts, so this prepares the next start.
multiplier  switch frame generation to this while the game runs (2-4), or
            null for off again. Only honoured while the file is fresh: the
            toolbox renews it every minute, so a stopped toolbox cannot leave
            frame generation on.

Frame Suite answers in its bridge file, per game under "toolbox". The file
belongs to the user; it is read without following links, size-limited, and
every value is checked.
"""

import json
import os
import stat

REL = os.path.join(".config", "lgo-toolbox", "framegen.json")
VERSION = 1
MAX_BYTES = 1 << 18
FRESH_S = 180


def path(home):
    return os.path.join(home, REL)


def read(home, now):
    """{appid: {"standby": bool, "multiplier": int or None}}; {} when there is
    no (valid) file. Multipliers in a stale file count as null."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path(home), flags)
    except OSError:
        return {}
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_BYTES:
            return {}
        with os.fdopen(os.dup(fd), "r", encoding="utf-8") as f:
            data = json.loads(f.read(MAX_BYTES + 1))
    except (OSError, ValueError, RecursionError):
        return {}
    finally:
        os.close(fd)
    if not isinstance(data, dict) or data.get("version") != VERSION or not isinstance(data.get("games"), dict):
        return {}
    updated = data.get("updated")
    fresh = isinstance(updated, (int, float)) and not isinstance(updated, bool) and now - updated <= FRESH_S
    out = {}
    for key, v in list(data["games"].items())[:200]:
        if not (isinstance(key, str) and key.isdigit() and len(key) <= 10 and int(key) < 0x80000000):
            continue
        if not isinstance(v, dict) or v.get("standby") is not True:
            continue
        m = v.get("multiplier")
        ok = isinstance(m, int) and not isinstance(m, bool) and 2 <= m <= 4
        out[key] = {"standby": True, "multiplier": m if ok and fresh else None}
    return out


def stamp(home):
    """(mtime_ns, size) of the request file, or None."""
    try:
        st = os.lstat(path(home))
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)

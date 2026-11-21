"""Requests from the Legion Go Toolbox's Battery playtime.

The toolbox (a separate Decky plugin, running as root) writes
``~/.config/lgo-toolbox/framegen.json``::

    {"version": 1, "updated": 1767000000,
     "games": {"1687950": {"standby": true, "multiplier": 2}}}

boost       (with "name") the game is set to Smoothest on the toolbox's Game tab: Frame Suite
            turns its Boost on, through the frontend, which handles the launch options.
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


def _load(home):
    """The request file's content when it is valid, else None."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path(home), flags)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_BYTES:
            return None
        with os.fdopen(os.dup(fd), "r", encoding="utf-8") as f:
            data = json.loads(f.read(MAX_BYTES + 1))
    except (OSError, ValueError, RecursionError):
        return None
    finally:
        os.close(fd)
    if not isinstance(data, dict) or data.get("version") != VERSION or not isinstance(data.get("games"), dict):
        return None
    return data


def _games(data):
    for key, v in list(data["games"].items())[:200]:
        if isinstance(key, str) and key.isdigit() and len(key) <= 10 and int(key) < 0x80000000 \
                and isinstance(v, dict):
            yield key, v


def read_boosts(home):
    """Games the toolbox's Game tab set to Smoothest: {appid: name}. Frame Suite turns their
    Boost on (and off again when the request goes). Not time-limited: it is a choice, not a
    live request."""
    data = _load(home)
    if data is None:
        return {}
    return {key: (v.get("name") if isinstance(v.get("name"), str) else "")[:120]
            for key, v in _games(data) if v.get("boost") is True}


def read(home, now):
    """{appid: {"standby": bool, "multiplier": int or None}}; {} when there is
    no (valid) file. Multipliers in a stale file count as null."""
    data = _load(home)
    if data is None:
        return {}
    updated = data.get("updated")
    fresh = isinstance(updated, (int, float)) and not isinstance(updated, bool) and now - updated <= FRESH_S
    out = {}
    for key, v in _games(data):
        if v.get("standby") is not True:
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

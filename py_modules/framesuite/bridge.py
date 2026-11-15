"""A small file other plugins can read to learn what Frame Suite set up.

``~/.config/frame-suite/bridge.json``, rewritten atomically whenever
something changes. Written for the Legion Go Toolbox's Smooth mode, which
needs to know whether a game's frames are multiplied and by what, but any
tool may read it. Format (version 1)::

    {
      "version": 1,
      "updated": 1767000000,
      "suite_version": "1.0.0",
      "profile": "z1-extreme",
      "games": {
        "1091500": {
          "name": "Cyberpunk 2077",
          "boost": true,
          "route": "optiscaler",            # or "lsfg"
          "frame_generation": {
            "source": "optiscaler",         # "optiscaler" | "lsfg" | "none"
            "multiplier": 2,                # frames on screen per game frame
            "in_game": true                 # made inside the game (the limiter sees them)
          },
          "optiscaler": {"patched": true, "fsr4_variant": "rdna4-native"},
          "lsfg": {"multiplier": 1}
        }
      }
    }

Top level, for the Legion Go Toolbox's Battery playtime: "lsfg_ready"
(lsfg-vk and Lossless Scaling are set up) and "toolbox_fg" (the user lets the
toolbox switch frame generation). Per game, "toolbox" answers its requests
(see toolbox.py): {"standby", "since" (when the lsfg-vk profile was made; 0:
it was there before), "multiplier" (switched on now, or null), "refused"}.

Only games Frame Suite manages or was told about are listed. A reader should
ignore a file whose ``version`` it does not know.
"""

import json
import os
import tempfile
import time

VERSION = 1
REL = os.path.join(".config", "frame-suite", "bridge.json")


def path(home):
    return os.path.join(home, REL)


def frame_generation(route, options, lsfg_multiplier, patched):
    """One generator per game: lsfg-vk when it multiplies, else OptiScaler's
    in-game one when the user said it is switched on."""
    if lsfg_multiplier and lsfg_multiplier > 1 and route != "optiscaler":
        return {"source": "lsfg", "multiplier": int(lsfg_multiplier), "in_game": False}
    if patched and options.get("fg_in_game"):
        return {"source": "optiscaler", "multiplier": 2, "in_game": True}
    if lsfg_multiplier and lsfg_multiplier > 1:
        return {"source": "lsfg", "multiplier": int(lsfg_multiplier), "in_game": False}
    return {"source": "none", "multiplier": 1, "in_game": False}


def write(home, suite_version, profile, games, extra=None):
    target = path(home)
    data = dict(extra or {})
    data.update({"version": VERSION, "updated": int(time.time()), "suite_version": suite_version,
                 "profile": profile, "games": games})
    os.makedirs(os.path.dirname(target), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(target), prefix=".bridge-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=1, sort_keys=True)
        os.chmod(tmp, 0o644)
        os.replace(tmp, target)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return target


def read(home):
    try:
        with open(path(home), "r") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("version") == VERSION else None

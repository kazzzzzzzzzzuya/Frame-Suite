"""What a running game has really loaded.

Whether a mod "took" is otherwise guesswork. Steam starts every process of a
game with ``SteamAppId`` in its environment, and Linux lists the files each
process has mapped, Windows DLLs under Proton included. So for a running
game this says for certain whether OptiScaler, an FSR 4 upscaler, HelixSR or
the lsfg-vk layer are in memory.
"""

import os

UPSCALER = "amd_fidelityfx_upscaler_dx12.dll"


def game_pids(app_id, proc="/proc", uid=None):
    want = str(app_id).encode()
    uid = os.getuid() if uid is None else uid
    out = []
    try:
        names = os.listdir(proc)
    except OSError:
        return out
    for name in names:
        if not name.isdigit():
            continue
        base = os.path.join(proc, name)
        try:
            if os.stat(base).st_uid != uid:
                continue
            with open(os.path.join(base, "environ"), "rb") as f:
                env = f.read(1 << 20).split(b"\0")
        except OSError:
            continue
        if b"SteamAppId=" + want in env or b"SteamGameId=" + want in env:
            out.append(int(name))
    return sorted(out)


def mapped_files(pid, proc="/proc"):
    out = set()
    try:
        with open(os.path.join(proc, str(pid), "maps"), "r", errors="replace") as f:
            for line in f:
                parts = line.split(None, 5)
                if len(parts) == 6 and parts[5].startswith("/"):
                    out.add(parts[5].rstrip("\n"))
    except OSError:
        pass
    return out


def check(app_id, target_dir=None, proxy_dll=None, proc="/proc", uid=None):
    """``running`` False means the game is not running (nothing to say)."""
    pids = game_pids(app_id, proc, uid)
    res = {"running": bool(pids), "readable": False, "optiscaler": False, "fsr4": False,
           "helix": False, "lsfg": False}
    if not pids:
        return res
    files = set()
    for pid in pids:
        files |= mapped_files(pid, proc)
    res["readable"] = bool(files)
    target = os.path.realpath(target_dir).lower() if target_dir else None
    for path in files:
        low = path.lower()
        base = os.path.basename(low)
        if base == "optiscaler.dll" or (
                target and proxy_dll and base == proxy_dll.lower()
                and os.path.dirname(low) == target):
            res["optiscaler"] = True
        if base == UPSCALER:
            res["fsr4"] = True
        if "helixsr" in low or base.startswith("hlx"):
            res["helix"] = True
        if "lsfg" in base and base.endswith((".so", ".dll")) or "lsfg-vk" in base:
            res["lsfg"] = True
    return res

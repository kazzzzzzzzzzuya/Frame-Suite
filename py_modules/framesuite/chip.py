"""Which chip this device has, and which settings profile belongs to it."""

import json
import os
import re

GENERIC = "generic"


def _read(path):
    try:
        with open(path, "r", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return ""


def detect(cpuinfo="/proc/cpuinfo", dmi="/sys/class/dmi/id"):
    model = ""
    for line in _read(cpuinfo).splitlines():
        if line.lower().startswith("model name"):
            model = line.split(":", 1)[1].strip()
            break
    return {
        "cpu": model,
        "vendor": _read(os.path.join(dmi, "sys_vendor")),
        "product": _read(os.path.join(dmi, "product_name")),
        "family": _read(os.path.join(dmi, "product_family")),
    }


def load_profiles(folder):
    out = {}
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        names = []
    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(folder, name), "r") as f:
                p = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(p, dict) and p.get("id") and isinstance(p.get("presets"), dict):
            out[p["id"]] = p
    if GENERIC not in out:
        out[GENERIC] = BUILTIN_GENERIC
    return out


def match(profiles, info):
    """The first profile whose ``match`` patterns all fit; else the generic one."""
    for pid, p in profiles.items():
        rules = p.get("match") or {}
        if not rules:
            continue
        try:
            if all(re.search(pattern, info.get(field, "") or "", re.I) for field, pattern in rules.items()):
                return pid
        except re.error:
            continue
    return GENERIC


BUILTIN_GENERIC = {
    "id": GENERIC,
    "label": "Any device (upstream defaults)",
    "match": {},
    "source": "The defaults the three plugins ship with.",
    "optiscaler": {"fsr4_variant": None, "proxy_dll": "dxgi.dll", "helix": True},
    "default_preset": "balanced",
    "presets": {
        "quality": {"label": "Quality", "lsfg": {"multiplier": 2, "flow_scale": 1.0, "performance_mode": False}, "mako": {"target_fps": 60, "max_multiplier": 2, "ultra_performance": False}},
        "balanced": {"label": "Balanced", "lsfg": {"multiplier": 2, "flow_scale": 0.8, "performance_mode": True}, "mako": {"target_fps": 60, "max_multiplier": 2, "ultra_performance": False}},
        "battery": {"label": "Battery", "lsfg": {"multiplier": 2, "flow_scale": 0.5, "performance_mode": True}, "mako": {"target_fps": 60, "max_multiplier": 2, "ultra_performance": True}},
    },
}

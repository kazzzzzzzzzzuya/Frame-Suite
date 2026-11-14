"""The only place that knows the upstream plugins' backend methods.

Everything Frame Suite does to a game goes through the same methods the
upstream panels call, so a game ends up exactly as if the user had pressed
the buttons there. ``REQUIRED`` is checked by the tests against every new
upstream release: a renamed or changed method stops the release instead of
breaking on a device.
"""

import json
import os

from . import launchopts

# sub -> method -> parameter names the suite passes (checked by tests/test_contract.py)
REQUIRED = {
    "optiscaler": {
        "check_fgmod_path": [],
        "run_install_fgmod": ["selected_default_variant"],
        "get_game_status": ["appid"],
        "patch_game": ["appid", "dll_name", "current_launch_options", "fsr4_variant"],
        "unpatch_game": ["appid"],
        "list_installed_games": [],
    },
    "lsfg": {
        "check_lsfg_vk_installed": [],
        "install_lsfg_vk": [],
        "get_game_configs": [],
        "update_game_config": ["appid", "game_name", "config"],
        "reset_game_config": ["appid"],
    },
    "helix": {
        "get_helix_state": [],
        "get_game": ["appid"],
        "install_optiscaler": ["path", "keep_fsr4"],
        "uninstall_optiscaler": ["path"],
        "uninstall_direct": ["path"],
        "set_anticheat_ack": ["appid", "on"],
        "list_releases": [],
        "download_release": ["tag"],
        "get_download_status": [],
        "set_active": ["tag"],
        "start_setup": ["tag"],
    },
}

LSFG_WORKAROUNDS = os.path.join(".config", "lsfg-vk", "workarounds.json")
TOOLBOX_SMOOTH = os.path.join(".config", "lgo-toolbox", "smooth")


class Unavailable(Exception):
    pass


class Adapters(object):
    def __init__(self, subs, home):
        self.subs = subs
        self.home = home

    def has(self, sub_id):
        sub = self.subs.get(sub_id)
        return bool(sub and sub.ok)

    async def call(self, sub_id, method, *args, **kwargs):
        sub = self.subs.get(sub_id)
        if not sub or not sub.ok:
            raise Unavailable("%s is not available in this build%s" % (
                sub.title if sub else sub_id, ": " + sub.error if sub and sub.error else ""))
        fn = getattr(sub.instance, method, None)
        if fn is None:
            raise Unavailable("%s has no '%s' any more" % (sub.title, method))
        return await fn(*args, **kwargs)

    # --- OptiScaler (Decky-Framegen) -------------------------------------------------

    def og_variants(self):
        mod = self.subs["optiscaler"].module if self.has("optiscaler") else None
        variants = getattr(mod, "FSR4_VARIANTS", None) or {}
        default = getattr(mod, "DEFAULT_FSR4_VARIANT", None)
        return {"default": default,
                "variants": [{"id": k, "label": str(v.get("label", k))} for k, v in variants.items()]}

    def og_valid_dlls(self):
        mod = self.subs["optiscaler"].module if self.has("optiscaler") else None
        return list(getattr(mod, "VALID_DLL_NAMES", None) or ["dxgi.dll"])

    async def og_bundle(self):
        if not self.has("optiscaler"):
            return {"available": False, "installed": False}
        res = await self.call("optiscaler", "check_fgmod_path")
        return {"available": True, "installed": bool(isinstance(res, dict) and res.get("exists"))}

    async def og_install_bundle(self, variant):
        res = await self.call("optiscaler", "run_install_fgmod", variant) if variant else \
            await self.call("optiscaler", "run_install_fgmod")
        ok = isinstance(res, dict) and res.get("status") == "success"
        return {"ok": ok, "message": (res or {}).get("message") or (res or {}).get("output") or ""}

    async def og_status(self, appid):
        if not self.has("optiscaler"):
            return {"available": False, "found": False, "patched": False}
        res = await self.call("optiscaler", "get_game_status", str(appid))
        if not isinstance(res, dict) or res.get("status") != "success":
            return {"available": True, "found": False, "patched": False,
                    "error": (res or {}).get("message", "no answer")}
        return {"available": True, "found": bool(res.get("install_found")),
                "patched": bool(res.get("patched")), "dll": res.get("dll_name"),
                "target_dir": res.get("target_dir"), "variant": res.get("fsr4_variant"),
                "variant_label": res.get("fsr4_variant_label"),
                "version": res.get("optiscaler_version"), "message": res.get("message", ""),
                "name": res.get("name")}

    def og_env(self, dll):
        """The launch settings a patched game needs, as Decky-Framegen writes them."""
        inst = self.subs["optiscaler"].instance if self.has("optiscaler") else None
        build = getattr(inst, "_build_managed_launch_options", None)
        managed = build(dll) if build else None
        if not managed:
            managed = "SteamDeck=0 %command%" if str(dll).endswith(".asi") else \
                "WINEDLLOVERRIDES=%s=n,b SteamDeck=0 %%command%%" % str(dll).rsplit(".", 1)[0]
        return dict(launchopts.parse_env(managed))

    async def og_patch(self, appid, dll, launch_options, variant):
        args = [str(appid), dll, launch_options or ""] + ([variant] if variant else [])
        res = await self.call("optiscaler", "patch_game", *args)
        ok = isinstance(res, dict) and res.get("status") == "success"
        env = dict(launchopts.parse_env(res.get("launch_options") or "")) if ok else {}
        return {"ok": ok, "env": env or (self.og_env(dll) if ok else {}),
                "message": (res or {}).get("message", ""), "target_dir": (res or {}).get("target_dir"),
                "variant": (res or {}).get("fsr4_variant")}

    async def og_unpatch(self, appid):
        res = await self.call("optiscaler", "unpatch_game", str(appid))
        return {"ok": isinstance(res, dict) and res.get("status") == "success",
                "message": (res or {}).get("message", "")}

    async def og_games(self):
        if not self.has("optiscaler"):
            return []
        res = await self.call("optiscaler", "list_installed_games")
        return [g for g in (res or {}).get("games", []) if g.get("install_found", True)]

    # --- lsfg-vk -----------------------------------------------------------------------

    async def lsfg_state(self):
        if not self.has("lsfg"):
            return {"available": False, "installed": False, "lossless": False}
        res = await self.call("lsfg", "check_lsfg_vk_installed")
        return {"available": True, "installed": bool((res or {}).get("installed")),
                "lossless": bool((res or {}).get("lossless_scaling_installed")),
                "lossless_status": str((res or {}).get("lossless_scaling_status") or "")}

    async def lsfg_config(self, appid):
        if not self.has("lsfg"):
            return None
        res = await self.call("lsfg", "get_game_configs")
        for g in (res or {}).get("games", []):
            if str(g.get("appid")) == str(appid):
                return dict(g.get("config") or {})
        return None

    async def lsfg_set(self, appid, name, config):
        res = await self.call("lsfg", "update_game_config", str(appid), name, dict(config))
        return {"ok": bool((res or {}).get("success")), "message": (res or {}).get("error") or ""}

    async def lsfg_reset(self, appid):
        res = await self.call("lsfg", "reset_game_config", str(appid))
        return {"ok": bool((res or {}).get("success")), "message": (res or {}).get("error") or ""}

    def lsfg_base_cap(self, appid):
        """decky-lsfg-vk's own "Base FPS cap" for this game (0 = off)."""
        try:
            with open(os.path.join(self.home, LSFG_WORKAROUNDS), "r") as f:
                data = json.load(f)
            return int(data["apps"][str(appid)]["state"].get("dxvkFrameRate") or 0)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return 0

    def toolbox_cap(self, appid):
        """Whether the Legion Go Toolbox's Smooth mode holds a cap for this game."""
        return os.path.isfile(os.path.join(self.home, TOOLBOX_SMOOTH, "%s.conf" % appid))

    # --- HelixSR -----------------------------------------------------------------------

    async def helix_state(self):
        if not self.has("helix"):
            return {"available": False, "downloaded": False, "built": False}
        s = await self.call("helix", "get_helix_state")
        setup = (s or {}).get("setup") or {}
        return {"available": True, "active": s.get("active"), "downloaded": bool(s.get("downloaded")),
                "built": bool(s.get("built")), "upscaler": s.get("upscaler"),
                "setup_state": setup.get("state"), "setup": setup}

    async def helix_game(self, appid):
        if not self.has("helix"):
            return {"available": False, "ok": False}
        g = await self.call("helix", "get_game", str(appid))
        if not isinstance(g, dict) or not g.get("ok"):
            return {"available": True, "ok": False, "error": (g or {}).get("error", "")}
        optis = [{"dir": o.get("dir"), "kind": o.get("installed_kind"), "configured": bool(o.get("configured")),
                  "disabled": bool(o.get("disabled")), "dx11": bool(o.get("dx11")),
                  "upscaler": o.get("upscaler"), "version": o.get("helix_version"),
                  "check": o.get("check")} for o in g.get("optiscaler") or []]
        direct = [{"path": d.get("path"), "state": d.get("state"), "dx11": bool(d.get("dx11")),
                   "upscaler": d.get("upscaler"), "version": d.get("helix_version"),
                   "check": d.get("check")} for d in g.get("direct") or []]
        return {"available": True, "ok": True, "name": g.get("name"), "path": g.get("path"),
                "optis": optis, "direct": direct, "inputs": list(g.get("inputs") or []),
                "inputs_dx11": g.get("inputs_dx11"), "anticheat": list(g.get("anticheat") or []),
                "running": list(g.get("running") or []), "steam_busy": g.get("steam_busy") or ""}

    async def helix_install(self, opti_dir, keep_fsr4=True):
        res = await self.call("helix", "install_optiscaler", opti_dir, bool(keep_fsr4))
        return {"ok": bool((res or {}).get("ok")),
                "message": (res or {}).get("message") or (res or {}).get("error") or ""}

    async def helix_uninstall(self, opti_dir):
        res = await self.call("helix", "uninstall_optiscaler", opti_dir)
        return {"ok": bool((res or {}).get("ok")),
                "message": (res or {}).get("message") or (res or {}).get("error") or ""}

    async def helix_uninstall_direct(self, dll_path):
        res = await self.call("helix", "uninstall_direct", dll_path)
        return {"ok": bool((res or {}).get("ok")),
                "message": (res or {}).get("message") or (res or {}).get("error") or ""}

    async def helix_ack(self, appid, on):
        if self.has("helix"):
            await self.call("helix", "set_anticheat_ack", str(appid), bool(on))

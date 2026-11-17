"""Frame Suite's own backend: the per-game switch, status, conflicts, setup,
measuring and updates. Talks to the upstream plugins only through
``adapters``."""

import asyncio
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

from . import adapters, bridge, chip, host, ini, launchopts, live, toolbox

ROUTES = ("optiscaler", "lsfg", "mako")
UPSCALERS = ("off", "optiscaler", "scaler", "direct")
UPSCALER_NAMES = {"off": "none", "optiscaler": "FSR 4 through OptiScaler", "scaler": "HelixSR Scaler",
                  "direct": "HelixSR in place of the game's FSR"}
MAKO_TARGETS = (30, 36, 40, 45, 48, 60, 72, 90, 120, 144)
MENU_KEYS = [  # Windows virtual-key codes OptiScaler understands
    {"code": "auto", "label": "Insert (OptiScaler's default)"},
    {"code": "0x24", "label": "Home"},
    {"code": "0x23", "label": "End"},
    {"code": "0x79", "label": "F10"},
    {"code": "0x7A", "label": "F11"},
]
# Upstream backend methods that change what the bridge file reports (True: first argument is the app id).
BRIDGE_TRIGGERS = {
    "optiscaler": {"patch_game": True, "unpatch_game": True, "manual_patch_directory": False,
                   "manual_unpatch_directory": False},
    "lsfg": {"update_game_config": True, "reset_game_config": True, "reset_game_configs": False,
             "reset_all_game_configs": False, "uninstall_lsfg_vk": False},
    # MAKO: any change to its profiles (made on its own page) is picked up as a whole.
    "mako": {"capture_game_profile": False, "create_profile": False, "delete_profile": False, "rename_profile": False,
             "update_profile_config": False, "update_profile_config_fields": False, "set_profile_power_modes": False,
             "install_mako": False, "uninstall_mako": False, "update_mako_config": False},
}
MAKO_CONFIG = os.path.join(".config", "mako-render")
MAKO_STATE_TTL_S = 30.0
BRIDGE_RESYNC_S = 600
TOOLBOX_POLL_S = 3.0          # how often the Legion Go Toolbox's request file is looked at
TOOLBOX_RECHECK_S = 30.0      # ... and acted on even when unchanged (stale requests expire)
LSFG_RECHECK_S = 120.0
TOOLBOX_GONE_S = 600.0        # the request file away this long (not just during a toolbox update): take back
UPDATE_GRACE_S = 900
UPDATE_TTL = 3 * 3600
MEASURE_KEEP = 12


def _now():
    return int(time.time())


def is_shortcut(appid):
    """Games added to Steam by hand have ids with the top bit set."""
    try:
        return int(appid) >= 0x80000000 or int(appid) < 0
    except (TypeError, ValueError):
        return True


class Store(object):
    def __init__(self, path):
        self.path = path
        self.data = {"profile": None, "games": {}, "measure": {}, "acks": {}}
        try:
            with open(path, "r") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                self.data.update(loaded)
        except (OSError, ValueError):
            pass

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.path), prefix=".suite-")
        with os.fdopen(fd, "w") as f:
            json.dump(self.data, f, indent=1, sort_keys=True)
        os.replace(tmp, self.path)

    def game(self, appid, create=False):
        games = self.data.setdefault("games", {})
        key = str(appid)
        if key not in games and create:
            games[key] = {"options": {}, "boost": {"on": False}}
        return games.get(key)


class Suite(object):
    def __init__(self, decky, plugin_dir, proc="/proc"):
        self.decky = decky
        self.log = decky.logger
        self.plugin_dir = plugin_dir
        self.home = decky.DECKY_USER_HOME
        self.proc = proc
        self.subs = host.load_all(plugin_dir, decky)
        self.ad = adapters.Adapters(self.subs, self.home)
        self.store = Store(os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "suite.json"))
        self.profiles = chip.load_profiles(os.path.join(plugin_dir, "profiles"))
        self.chip = chip.detect()
        self.detected = chip.match(self.profiles, self.chip)
        self.lock = host.read_lock(plugin_dir)
        self.version = self._version()
        self.busy = {}            # appid -> True while a change runs
        self.wizard = {"step": None, "phase": "idle", "error": None, "tag": None}
        self.wizard_task = None
        self.measure = {"state": "idle"}
        self.measure_task = None
        self.update_cache = {"time": 0, "result": None}
        self.updating_until = 0.0
        self.sync_task = None
        self.toolbox_task = None
        self._live_target = {}       # appid -> (OptiScaler's folder, its DLL), from the last full look
        self._mako_info = {}         # appid -> MAKO profile fields, for the bridge and the launch options
        self._mako_stamp = None
        self._mako_state = None
        self._mako_state_at = 0.0
        self._tb_stamp = None
        self._tb_checked = 0.0
        self._lsfg_ready = False
        self._tb_gone_since = None
        self._lsfg_checked = 0.0

    # --- basics ----------------------------------------------------------------------

    def _version(self):
        v = getattr(self.decky, "DECKY_PLUGIN_VERSION", None)
        if v:
            return str(v)
        try:
            with open(os.path.join(self.plugin_dir, "package.json"), "r") as f:
                return str(json.load(f).get("version") or "0")
        except (OSError, ValueError):
            return "0"

    def exported(self):
        """``<id>__<method>`` -> coroutine, for the upstream panels."""
        out = {}
        for sub in self.subs.values():
            for name, fn in host.methods(sub).items():
                out[sub.id + host.SEP + name] = fn
        if self.subs["helix"].ok:
            # Its own "update this plugin" would install the stand-alone plugin next to this one.
            out["helix" + host.SEP + "check_plugin_update"] = self._no_helix_update
        # Changes made in the upstream panels reach the bridge file right away.
        for sub_id, names in BRIDGE_TRIGGERS.items():
            for name, per_game in names.items():
                key = sub_id + host.SEP + name
                if key in out:
                    out[key] = self._then_sync(out[key], per_game, mako=sub_id == "mako")
        return out

    def _then_sync(self, fn, per_game, mako=False):
        async def call(*args, **kwargs):
            res = await fn(*args, **kwargs)
            try:
                if mako:
                    self._mako_state_at = 0.0
                    await self.mako_sync(force=True)
                    return res
                appid = str(args[0]) if per_game and args and str(args[0]).lstrip("-").isdigit() else None
                await self.sync_bridge([appid] if appid else None)
            except Exception:
                self.log.exception("Frame Suite: bridge update after an upstream call")
            return res
        return call

    async def _no_helix_update(self, force=False):
        v = self.subs["helix"].version
        return {"ok": True, "current": v, "latest": v, "newer": False, "url": "", "sha256": "",
                "page": "", "notes": "", "published_at": None}

    def profile_id(self):
        chosen = self.store.data.get("profile")
        return chosen if chosen in self.profiles else self.detected

    def profile(self):
        return self.profiles[self.profile_id()]

    def info(self):
        return {
            "version": self.version,
            "repo": self.lock.get("suite_repo") or "",
            "built": self.lock.get("built"),
            "chip": self.chip,
            "detected": self.detected,
            "profile": self.profile_id(),
            "profile_chosen": self.store.data.get("profile"),
            "profiles": [{"id": p["id"], "label": p.get("label", p["id"]), "source": p.get("source", ""),
                          "presets": [{"id": k, "label": v.get("label", k), "mako": v.get("mako")} for k, v in p["presets"].items()],
                          "default_preset": p.get("default_preset")}
                         for p in self.profiles.values()],
            "subs": [self.subs[s].public() for s in host.SUBS],
            "variants": self.ad.og_variants(),
            "menu_keys": MENU_KEYS,
            "bridge": bridge.path(self.home),
            "toolbox_fg": self.toolbox_allowed(),
        }

    def set_profile(self, profile_id):
        self.store.data["profile"] = profile_id if profile_id in self.profiles else None
        self.store.save()
        return self.info()

    # --- per-game options -----------------------------------------------------------

    def options(self, appid):
        p = self.profile()
        entry = self.store.game(appid) or {}
        o = dict(entry.get("options") or {})
        variants = [v["id"] for v in self.ad.og_variants()["variants"]]
        variant = o.get("variant") or (p.get("optiscaler") or {}).get("fsr4_variant")
        if variant not in variants:
            variant = self.ad.og_variants()["default"]
        preset = o.get("preset") if o.get("preset") in p["presets"] else \
            p.get("default_preset") if p.get("default_preset") in p["presets"] else sorted(p["presets"])[0]
        return {
            "preset": preset,
            "route": o.get("route") if o.get("route") in ROUTES else "auto",
            "variant": variant,
            "helix": bool(o.get("helix", (p.get("optiscaler") or {}).get("helix", True))),
            "fg_in_game": bool(o.get("fg_in_game", False)),
            "multiplier": int(o["multiplier"]) if str(o.get("multiplier", "")).isdigit() else None,
            "mako_target": int(o["mako_target"]) if o.get("mako_target") in MAKO_TARGETS else None,
            "mako_max": int(o["mako_max"]) if o.get("mako_max") in (2, 3, 4) else None,
            # The upscaler under MAKO's frame generation: off, OptiScaler's FSR 4 (Decky-Framegen, HelixSR in
            # it when "helix"), HelixSR Scaler, or HelixSR in place of the game's FSR 3.1 (as HelixSR Manager).
            "mako_upscaler": o["mako_upscaler"] if o.get("mako_upscaler") in UPSCALERS else
            ("optiscaler" if o.get("mako_upscale") else "off"),
        }

    def mako_config_for(self, appid):
        """MAKO fields for this game: the chip preset's adaptive frame generation, with the game's own choices."""
        opts = self.options(appid)
        pre = dict(self.profile()["presets"][opts["preset"]].get("mako") or {})
        return {
            "frame_generation_enabled": True,
            "adaptive": True,
            "target_fps": opts["mako_target"] or int(pre.get("target_fps") or 60),
            "adaptive_max_multiplier": opts["mako_max"] or int(pre.get("max_multiplier") or 2),
            "ultra_performance": bool(pre.get("ultra_performance", False)),
        }

    def lsfg_config_for(self, appid):
        opts = self.options(appid)
        cfg = dict(self.profile()["presets"][opts["preset"]].get("lsfg") or {})
        if opts["multiplier"]:
            cfg["multiplier"] = max(2, min(4, opts["multiplier"]))
        return cfg

    async def set_option(self, appid, key, value, launch_options=None):
        if key not in ("preset", "route", "variant", "helix", "fg_in_game", "multiplier", "mako_target", "mako_max",
                       "mako_upscaler"):
            return {"ok": False, "error": "Unknown option."}
        entry = self.store.game(appid, create=True)
        if key == "mako_upscaler" and value not in UPSCALERS:
            return {"ok": False, "error": "Unknown upscaler."}
        if value in (None, "", "auto") and key not in ("helix", "fg_in_game", "mako_upscaler"):
            entry["options"].pop(key, None)
        else:
            entry["options"][key] = value
        self.store.save()
        warnings = []
        boost = entry.get("boost") or {}
        if boost.get("on") and boost.get("route") == "lsfg" and key in ("preset", "multiplier") \
                and (boost.get("applied") or {}).get("lsfg") == "created":
            res = await self.ad.lsfg_set(appid, entry.get("name") or "App %s" % appid, self.lsfg_config_for(appid))
            if not res["ok"]:
                warnings.append("lsfg-vk did not take the new settings: %s" % res["message"])
        mk = (boost.get("applied") or {}).get("mako")
        if boost.get("on") and boost.get("route") == "mako" and key in ("preset", "mako_target", "mako_max") and mk:
            res = await self._safe(self.ad.mako_set(mk, self.mako_config_for(appid)),
                                   {"ok": False, "message": "MAKO did not answer"})
            if not res["ok"]:
                warnings.append("MAKO did not take the new settings: %s" % res["message"])
            await self.mako_sync(force=True)
        view = await self.game(appid, launch_options, entry.get("name"))
        return {"ok": True, "warnings": warnings, "view": view}

    # --- what is true for a game ----------------------------------------------------

    async def _facts(self, appid):
        steam = not is_shortcut(appid)
        og = await self._safe(self.ad.og_status(appid), {"available": False, "found": False, "patched": False}) \
            if steam else {"available": self.ad.has("optiscaler"), "found": False, "patched": False}
        hx = await self._safe(self.ad.helix_game(appid), {"available": False, "ok": False}) \
            if steam else {"available": self.ad.has("helix"), "ok": False}
        return {
            "steam": steam,
            "og": og,
            "hx": hx,
            "bundle": await self._safe(self.ad.og_bundle(), {"available": False, "installed": False}),
            "ls": await self._safe(self.ad.lsfg_state(), {"available": False, "installed": False, "lossless": False}),
            "lcfg": await self._safe(self.ad.lsfg_config(appid), None),
            "hstate": await self._safe(self.ad.helix_state(), {"available": False, "downloaded": False, "built": False}),
            "mk": await self._safe(self.ad.mako_state(), {"available": False, "installed": False, "wrapper": None}),
            "mprof": await self._safe(self.ad.mako_game(appid), None),
            "running": bool(await asyncio.to_thread(live.game_pids, appid, self.proc)),
        }

    async def _safe(self, coro, fallback):
        try:
            return await coro
        except adapters.Unavailable:
            return fallback
        except Exception as exc:
            self.log.exception("Frame Suite: upstream call failed")
            if isinstance(fallback, dict):
                return dict(fallback, error=str(exc))
            return fallback

    def _plan(self, appid, f):
        opts = self.options(appid)
        og, hx = f["og"], f["hx"]
        usable = [o for o in hx.get("optis", []) if not o["dx11"]] if hx.get("ok") else []
        dx11 = bool(hx.get("ok") and hx.get("inputs_dx11"))
        if opts["route"] != "auto":
            route, reason = opts["route"], "Chosen by you for this game."
        elif f.get("mprof"):
            route, reason = "mako", "MAKO already has a profile for this game."
        elif not f["steam"]:
            route, reason = ("mako", "A game added to Steam by hand: MAKO handles these.") if f["mk"].get("installed") \
                else ("lsfg", "A game added to Steam by hand: only lsfg-vk works for these.")
        elif og.get("patched") or usable:
            route, reason = "optiscaler", "OptiScaler is already in this game."
        elif hx.get("ok") and not dx11 and (hx.get("inputs") or any(not d["dx11"] for d in hx.get("direct", []))):
            found = hx.get("inputs") or ["FSR 3.1"]
            route, reason = "optiscaler", "The game has %s, which OptiScaler can replace with FSR 4." % " / ".join(found)
        elif dx11:
            route, reason = "lsfg", "A DirectX 11 game: OptiScaler's FSR 4 and HelixSR need DirectX 12; frame generation works with any game."
        elif hx.get("ok"):
            route, reason = "lsfg", "No DLSS, XeSS or FSR found in the game's files: frame generation it is."
        else:
            route, reason = "lsfg", "The game's files could not be checked for DLSS / FSR; frame generation works with any game."
        if route == "lsfg" and opts["route"] == "auto" and f["mk"].get("installed"):
            # MAKO is set up: its adaptive frame generation needs no Lossless Scaling and holds a target.
            route = "mako"
            reason = reason.replace("frame generation", "MAKO's adaptive frame generation")
        blockers = []
        if route == "optiscaler":
            if not f["steam"]:
                blockers.append({"id": "non-steam", "text": "OptiScaler can only be set up here for games installed "
                                                            "through Steam. Use lsfg-vk for this one."})
            elif not og.get("available"):
                blockers.append({"id": "sub-optiscaler", "text": "The Decky-Framegen part did not load (see Versions)."})
            elif not og.get("found"):
                blockers.append({"id": "not-installed", "text": og.get("error") or og.get("message")
                                 or "The game's files were not found in a Steam library."})
            elif not f["bundle"].get("installed") and not og.get("patched"):
                blockers.append({"id": "setup-optiscaler", "text": "OptiScaler is not set up yet. Run Setup first."})
            if hx.get("ok") and hx.get("running"):
                blockers.append({"id": "running", "text": "Close the game first: its files cannot be changed while it runs."})
            elif hx.get("ok") and hx.get("steam_busy"):
                blockers.append({"id": "steam-busy", "text": hx["steam_busy"]})
        elif route == "mako":
            mk = f["mk"]
            if not mk.get("available"):
                blockers.append({"id": "sub-mako", "text": "The MAKO part did not load (see Versions)."})
            elif not mk.get("installed"):
                blockers.append({"id": "setup-mako", "text": "MAKO's renderer is not installed yet. Run Setup first."})
            elif not f.get("mprof") and not f.get("running"):
                blockers.append({"id": "start-game", "text": "Start the game first: MAKO recognises a game by its "
                                                             "running program. Switch this on while it runs, then "
                                                             "restart the game once."})
        else:
            ls = f["ls"]
            if not f["steam"]:
                # decky-lsfg-vk files these games under an id of its own; its page sets them up correctly.
                blockers.append({"id": "non-steam", "text": "A game added to Steam by hand: set it up on the LSFG-VK "
                                                            "page (Non-Steam tab), which knows how lsfg-vk names "
                                                            "these games."})
            elif not ls.get("available"):
                blockers.append({"id": "sub-lsfg", "text": "The lsfg-vk part did not load (see Versions)."})
            elif not ls.get("installed"):
                blockers.append({"id": "setup-lsfg", "text": "lsfg-vk is not installed yet. Run Setup first."})
            elif not ls.get("lossless"):
                blockers.append({"id": "lossless", "text": "lsfg-vk needs Lossless Scaling from the Steam store, installed "
                                                           "and switched to its \"lsfg-vk\" branch (LSFG-VK page)."})
        return {"route": route, "reason": reason, "blockers": blockers}

    def _conflicts(self, appid, f, entry, launch_options, opts):
        og, hx, lcfg = f["og"], f["hx"], f["lcfg"]
        out = []
        lsfg_mult = int((lcfg or {}).get("multiplier") or 1) if lcfg else 1
        patched = bool(og.get("patched"))
        if patched and lsfg_mult > 1:
            sure = opts["fg_in_game"]
            out.append({"id": "double-fg", "level": "error" if sure else "warn", "fix": "lsfg-reset",
                        "fix_label": "Turn lsfg-vk off for this game",
                        "text": ("Two frame generators: the game's own (through OptiScaler) and lsfg-vk %d×. They "
                                 "multiply each other's frames and add delay. Use one." % lsfg_mult) if sure else
                                ("lsfg-vk %d× is on for this game and OptiScaler is installed too. Fine as long as "
                                 "frame generation stays off in the game's own settings." % lsfg_mult)})
        if patched and og.get("dll") and launch_options is not None:
            env = self.ad.og_env(og["dll"])
            if not launchopts.has_env(launch_options, env) and not launchopts.uses_fgmod_wrapper(launch_options):
                out.append({"id": "launch-missing", "level": "error", "fix": "launch-repair",
                            "fix_label": "Add them again",
                            "text": "OptiScaler is in the game's files, but the launch settings that load it are "
                                    "missing (another tool may have replaced them). Without them the game starts "
                                    "without OptiScaler."})
            elif launchopts.has_env(launch_options, env) and launchopts.uses_fgmod_wrapper(launch_options):
                out.append({"id": "wrapper-twice", "level": "warn", "fix": "wrapper-remove",
                            "fix_label": "Remove the wrapper",
                            "text": "The launch options also run Decky-Framegen's older fgmod wrapper. It is not "
                                    "needed any more and copies the files again at every start."})
        cap = self.ad.lsfg_base_cap(appid)
        if cap and self.ad.toolbox_cap(appid):
            out.append({"id": "two-limiters", "level": "warn",
                        "text": "Two frame limiters: lsfg-vk's Base FPS cap (%d) and the Legion Go Toolbox's Smooth "
                                "frame rate. Switch one off (LSFG-VK page, or the Toolbox's Power tab)." % cap})
        if hx.get("ok") and hx.get("anticheat"):
            out.append({"id": "anticheat", "level": "warn",
                        "text": "This game ships anti-cheat (%s). Changed game files can get an account banned in "
                                "online play. lsfg-vk does not change game files." % ", ".join(hx["anticheat"][:2])})
        boost = (entry or {}).get("boost") or {}
        if boost.get("on") and boost.get("route") == "optiscaler" and not patched:
            out.append({"id": "boost-lost", "level": "error", "fix": "boost-reapply", "fix_label": "Set it up again",
                        "text": "The switch is on, but OptiScaler is no longer in the game's files (a game update "
                                "or \"Verify integrity\" restores the originals)."})
        mprof = f.get("mprof")
        mako_on = bool(mprof and mprof.get("frame_generation_enabled") and not mprof.get("disable_mako"))
        if mako_on and lsfg_mult > 1:
            out.append({"id": "double-fg-mako", "level": "error", "fix": "lsfg-reset",
                        "fix_label": "Turn lsfg-vk off for this game",
                        "text": "Two frame generators: MAKO and lsfg-vk %d× are both on for this game. They multiply "
                                "each other's frames and add delay. Use one." % lsfg_mult})
        if mako_on and patched and opts["fg_in_game"]:
            out.append({"id": "double-fg-mako-game", "level": "error",
                        "text": "Two frame generators: MAKO and the game's own (through OptiScaler). Switch frame "
                                "generation off in the game's settings, or MAKO's off on its page."})
        if mprof and launch_options is not None and f["mk"].get("wrapper") and \
                not launchopts.has_wrapper(launch_options, adapters.MAKO_RUN):
            out.append({"id": "mako-launch-missing", "level": "warn", "fix": "mako-launch-add", "fix_label": "Add it now",
                        "text": "MAKO has a profile for this game, but its launcher is not in the launch options yet "
                                "(Frame Suite adds it within seconds; without it the game starts without MAKO)."})
        if boost.get("on") and boost.get("route") == "mako" and opts["mako_upscaler"] != "off" \
                and not (boost.get("applied") or {}).get("upscaler") \
                and not (opts["mako_upscaler"] == "optiscaler" and patched):
            out.append({"id": "mako-upscale-pending", "level": "warn", "fix": "mako-upscale-add",
                        "fix_label": "Add the upscaler now",
                        "text": "The upscaler (%s) is not in the game yet. Close the game first: its files cannot be "
                                "changed while it runs." % UPSCALER_NAMES[opts["mako_upscaler"]]})
        if boost.get("on") and boost.get("route") == "mako" and not mprof:
            out.append({"id": "boost-lost", "level": "error", "fix": "boost-reapply", "fix_label": "Set it up again",
                        "text": "The switch is on, but MAKO has no profile for this game any more."})
        if boost.get("on") and boost.get("route") == "lsfg" and not lcfg:
            out.append({"id": "boost-lost", "level": "error", "fix": "boost-reapply", "fix_label": "Set it up again",
                        "text": "The switch is on, but lsfg-vk has no profile for this game any more."})
        for sub in self.subs.values():
            if not sub.ok:
                out.append({"id": "sub-" + sub.id, "level": "warn",
                            "text": "%s did not load in this build: %s" % (sub.title, sub.error)})
        return out

    def _menu_key(self, og):
        if not og.get("patched") or not og.get("target_dir"):
            return None
        try:
            with open(os.path.join(og["target_dir"], "OptiScaler.ini"), "r", errors="replace") as f:
                return ini.get(f.read(), "Menu", "ShortcutKey") or "auto"
        except OSError:
            return None

    def _summary(self, f, entry, plan, livecheck):
        og, hx, lcfg = f["og"], f["hx"], f["lcfg"]
        lines = []
        if og.get("patched"):
            lines.append("OptiScaler %s%s" % (og.get("version") or "",
                                              " · " + og["variant_label"] if og.get("variant_label") else ""))
        helix = [o for o in hx.get("optis", []) if o.get("kind") and not o.get("disabled")] if hx.get("ok") else []
        helix += [d for d in hx.get("direct", []) if str(d.get("state", "")).startswith("helixsr")] if hx.get("ok") else []
        if helix:
            lines.append("%s %s" % (helix[0].get("upscaler") or "HelixSR", helix[0].get("version") or ""))
        if lcfg:
            lines.append("lsfg-vk %d×" % int(lcfg.get("multiplier") or 1))
        mprof = f.get("mprof")
        if mprof and not mprof.get("disable_mako"):
            if not mprof.get("frame_generation_enabled"):
                lines.append("MAKO (frame generation off)")
            elif mprof.get("adaptive"):
                lines.append("MAKO adaptive %s fps, up to %s×" % (mprof.get("target_fps"), mprof.get("adaptive_max_multiplier")))
            else:
                lines.append("MAKO %s×" % mprof.get("multiplier"))
        if livecheck.get("running") and livecheck.get("readable"):
            loaded = [n for k, n in (("optiscaler", "OptiScaler"), ("fsr4", "FSR 4 upscaler"),
                                     ("helix", "HelixSR"), ("lsfg", "lsfg-vk"), ("mako", "MAKO")) if livecheck.get(k)]
            live_line = "Running now, loaded: " + (", ".join(loaded) if loaded else "none of them")
        elif livecheck.get("running"):
            live_line = "Running now (its memory could not be read to check what is loaded)."
        else:
            live_line = "Not running. Start the game to see what really loads."
        return {"active": [l.strip() for l in lines], "live": live_line}

    async def game(self, appid, launch_options=None, name=None):
        """launch_options None: unknown (Steam did not hand them out), so nothing is said about them."""
        appid = str(appid)
        f = await self._facts(appid)
        entry = self.store.game(appid)
        opts = self.options(appid)
        plan = self._plan(appid, f)
        og = f["og"]
        self._live_target[appid] = (og.get("target_dir"), og.get("dll"))
        livecheck = await asyncio.to_thread(live.check, appid, og.get("target_dir"), og.get("dll"), self.proc)
        name = name or og.get("name") or f["hx"].get("name") or (entry or {}).get("name") or "App %s" % appid
        boost = dict((entry or {}).get("boost") or {"on": False})
        view = {
            "appid": appid, "name": name, "steam": f["steam"],
            "boost": {"on": bool(boost.get("on")), "route": boost.get("route"), "time": boost.get("time"),
                      "applied": boost.get("applied") or {}},
            "options": opts, "plan": plan,
            "optiscaler": og, "bundle": f["bundle"],
            "helix": {"available": f["hx"].get("available", False), "ok": f["hx"].get("ok", False),
                      "built": f["hstate"].get("built", False), "active": f["hstate"].get("active"),
                      "optis": f["hx"].get("optis", []), "direct": f["hx"].get("direct", []),
                      "inputs": f["hx"].get("inputs", [])},
            "lsfg": dict(f["ls"], config=f["lcfg"], base_cap=self.ad.lsfg_base_cap(appid)),
            "anticheat": f["hx"].get("anticheat", []) if f["hx"].get("ok") else [],
            "acked": bool(self.store.data.get("acks", {}).get(appid)),
            "running": bool(livecheck.get("running") or (f["hx"].get("ok") and f["hx"].get("running"))),
            "live": livecheck,
            "menu_key": self._menu_key(og),
            "conflicts": self._conflicts(appid, f, entry, launch_options, opts),
            "summary": self._summary(f, entry, plan, livecheck),
            "measure": self.store.data.get("measure", {}).get(appid, []),
            "toolbox": (self.store.data.get("toolbox") or {}).get(appid),
            "mako": dict(f["mk"], profile=f.get("mprof")),
            "busy": bool(self.busy.get(appid)),
        }
        if entry is not None or og.get("patched") or f["lcfg"] or f.get("mprof"):
            self._write_bridge(appid, view)
        return view

    def _bridge_entry(self, appid, name, patched, variant, lsfg_mult):
        entry = self.store.game(appid) or {}
        boost = entry.get("boost") or {}
        on = bool(boost.get("on"))
        mk = self._mako_info.get(appid)
        mako_on = bool(mk and mk.get("frame_generation_enabled") and not mk.get("disable_mako"))
        route = boost.get("route") if on else ("optiscaler" if patched else "mako" if mako_on
                                               else "lsfg" if lsfg_mult > 1 else None)
        tb = (self.store.data.get("toolbox") or {}).get(appid)
        if route is None and not on and not tb and not mk:
            return None
        fg = bridge.frame_generation(route, self.options(appid), lsfg_mult, patched)
        if mako_on:
            fg = bridge.mako_frame_generation(mk)
        out = {
            "name": name or entry.get("name") or (tb or {}).get("name") or "App %s" % appid,
            "boost": on, "route": route,
            "frame_generation": fg,
            "optiscaler": {"patched": bool(patched), "fsr4_variant": variant},
            "lsfg": {"multiplier": lsfg_mult},
        }
        if mk:
            out["mako"] = bridge.mako_entry(mk)
        if tb:
            out["toolbox"] = {"standby": tb.get("since") is not None and not tb.get("refused"),
                              "since": tb.get("since"), "multiplier": tb.get("applied"),
                              "refused": tb.get("refused")}
        return out

    async def live_state(self, appid):
        """Cheap: only whether the game runs and what it has loaded (no look at its files).
        The page polls this and asks for the full picture when it changes."""
        target, dll = self._live_target.get(str(appid), (None, None))
        return await asyncio.to_thread(live.check, str(appid), target, dll, self.proc)

    # --- MAKO: profiles, the bridge and the launch options --------------------------------------

    def _mako_stamp_now(self):
        out = []
        for fn in ("conf.toml", "profile-metadata.json", "profile-wrapper-settings.json"):
            try:
                st = os.stat(os.path.join(self.home, MAKO_CONFIG, fn))
                out.append((fn, st.st_mtime_ns, st.st_size))
            except OSError:
                out.append((fn, None, None))
        return tuple(out)

    async def mako_sync(self, force=False):
        """Read MAKO's game profiles again when its files changed, and tell the bridge."""
        stamp = self._mako_stamp_now()
        if not force and stamp == self._mako_stamp:
            return
        self._mako_stamp = stamp
        info = {}
        if self.ad.has("mako"):
            profiles = await self._safe(self.ad.mako_profiles(), None)
            if profiles is None:
                return
            for appid, profile in profiles.items():
                cfg = await self._safe(self.ad.mako_config(profile), None)
                info[appid] = dict(cfg or {}, profile=profile)
        if info != self._mako_info:
            old = set(self._mako_info)
            self._mako_info = info
            await self.sync_bridge(sorted(old | set(info)))

    async def _mako_installed(self):
        now = time.time()
        if self._mako_state is None or now - self._mako_state_at > MAKO_STATE_TTL_S:
            self._mako_state = await self._safe(self.ad.mako_state(), {"available": False, "installed": False,
                                                                       "wrapper": None})
            self._mako_state_at = now
        return self._mako_state

    def _mako_mark(self, appid, ours):
        marks = self.store.data.setdefault("mako_launch", {})
        if ours:
            marks[str(appid)] = True
        else:
            marks.pop(str(appid), None)
        self.store.save()

    async def mako_launch_plan(self):
        """For the frontend, which writes Steam's launch options: games that should start through
        MAKO's launcher, and the ones Frame Suite added it to. Without MAKO's renderer nothing is
        wanted, so the launcher is taken out again before a game could fail to start."""
        await self.mako_sync()
        mk = await self._mako_installed()
        wrapper = mk.get("wrapper") if mk.get("installed") else None
        want = sorted(a for a, i in self._mako_info.items() if not i.get("disable_mako")) if wrapper else []
        return {"wrapper": wrapper, "want": want, "ours": sorted(self.store.data.get("mako_launch", {}))}

    async def mako_launch_fix(self, appid, launch_options):
        """The launch options this game should have as far as MAKO's launcher goes:
        {"launch_options", "changed", "ours"} (ours: whether Frame Suite now has it there)."""
        appid = str(appid)
        text = launch_options or ""
        plan = await self.mako_launch_plan()
        has = launchopts.has_wrapper(text, adapters.MAKO_RUN)
        if appid in plan["want"] and not has:
            new, _ = launchopts.add_wrapper(text, plan["wrapper"])
            return {"launch_options": new, "changed": True, "ours": True}
        if appid not in plan["want"] and appid in plan["ours"] and has:
            return {"launch_options": launchopts.remove_wrapper(text, adapters.MAKO_RUN), "changed": True,
                    "ours": False}
        return {"launch_options": text, "changed": False, "ours": appid in plan["ours"] and has}

    def mako_launch_mark(self, appid, added):
        if not str(appid).isdigit():
            return {"ok": False}
        self._mako_mark(appid, bool(added))
        return {"ok": True}

    def _bridge_top(self):
        return {"lsfg_ready": bool(self._lsfg_ready), "toolbox_fg": self.toolbox_allowed()}

    def _bridge_put(self, entries):
        """entries: appid -> entry or None (remove). Written only when something changed."""
        try:
            data = bridge.read(self.home) or {}
            current = data.get("games") or {}
            games = {k: v for k, v in current.items() if isinstance(v, dict)}
            for appid, entry in entries.items():
                if entry is None:
                    games.pop(appid, None)
                else:
                    games[appid] = entry
            top = self._bridge_top()
            if games != current or any(data.get(k) != v for k, v in top.items()) or \
                    not os.path.isfile(bridge.path(self.home)):
                bridge.write(self.home, self.version, self.profile_id(), games, top)
        except OSError:
            self.log.exception("Frame Suite: could not write the bridge file")

    def _write_bridge(self, appid, view):
        lsfg_mult = int(((view["lsfg"].get("config") or {}).get("multiplier")) or 1)
        self._bridge_put({appid: self._bridge_entry(
            appid, view["name"], bool(view["optiscaler"].get("patched")),
            view["optiscaler"].get("variant"), lsfg_mult)})

    async def sync_bridge(self, appids=None):
        """Bring the bridge file in step with the games' real state: for the given games, or for every
        game it lists or Frame Suite has settings for. Other tools read it without asking us, so it must
        not keep saying OptiScaler is in a game after a game update restored the files."""
        if appids is None:
            known = set(((bridge.read(self.home) or {}).get("games") or {}))
            known |= set(self.store.data.get("games", {}))
            known |= set(self.store.data.get("toolbox", {}))
            known |= set(self._mako_info)
            appids = sorted(known)
        entries = {}
        configs = None
        if self.ad.has("lsfg"):
            res = await self._safe(self.ad.call("lsfg", "get_game_configs"), {})
            configs = {str(g.get("appid")): g.get("config") or {} for g in (res or {}).get("games", [])} \
                if isinstance(res, dict) and res.get("games") is not None else None
        for appid in appids:
            appid = str(appid)
            og = await self._safe(self.ad.og_status(appid), {"available": False}) \
                if not is_shortcut(appid) else {"available": True, "patched": False}
            if not og.get("available") or og.get("error") or configs is None:
                continue        # unknown is not "gone": leave the entry as it is
            try:
                lsfg_mult = int((configs.get(appid) or {}).get("multiplier") or 1)
            except (TypeError, ValueError):
                lsfg_mult = 1
            entries[appid] = self._bridge_entry(appid, og.get("name"), bool(og.get("patched")),
                                                og.get("variant"), lsfg_mult)
        self._bridge_put(entries)
        return len(entries)

    async def _sync_forever(self):
        while True:
            try:
                await self.sync_bridge()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.log.exception("Frame Suite: bridge resync")
            await asyncio.sleep(BRIDGE_RESYNC_S)

    def start(self):
        if self.sync_task is None or self.sync_task.done():
            self.sync_task = asyncio.ensure_future(self._sync_forever())
        if self.toolbox_task is None or self.toolbox_task.done():
            self.toolbox_task = asyncio.ensure_future(self._toolbox_forever())

    def stop(self):
        for task in (self.wizard_task, self.measure_task, self.sync_task, self.toolbox_task):
            if task and not task.done():
                task.cancel()

    def prepare_update(self):
        """The panel is about to hand a newer build to Decky. Decky runs the uninstall hooks for an
        update as well; within this window they are skipped, so an update does not undo anything."""
        self.updating_until = time.time() + UPDATE_GRACE_S
        return {"ok": True}

    def updating(self):
        return time.time() < self.updating_until

    def forget(self):
        """The plugin is being removed for good: other tools must not keep following its file."""
        try:
            os.unlink(bridge.path(self.home))
        except OSError:
            pass

    # --- the Legion Go Toolbox's Battery playtime -------------------------------------------

    def toolbox_allowed(self):
        return self.store.data.get("toolbox_fg", True) is not False

    async def set_toolbox_allowed(self, on):
        self.store.data["toolbox_fg"] = bool(on)
        self.store.save()
        await self.toolbox_sync(force=True)
        return self.info()

    async def _toolbox_forever(self):
        while True:
            try:
                await self.mako_sync()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.log.exception("Frame Suite: MAKO profiles")
            try:
                await self.toolbox_sync()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.log.exception("Frame Suite: toolbox requests")
            await asyncio.sleep(TOOLBOX_POLL_S)

    def _standby_config(self):
        p = self.profile()
        preset = p["presets"].get("battery") or p["presets"][p["default_preset"]]
        return dict(preset.get("lsfg") or {}, multiplier=1)

    async def _tb_set_multiplier(self, appid, profile_name, cfg, mult):
        res = await self.ad.lsfg_set(appid, profile_name, dict(cfg, multiplier=int(mult)))
        if res["ok"]:
            cfg["multiplier"] = int(mult)
        return res

    async def _tb_release(self, appid, rec, configs, remove=False):
        """Frame generation back to what it was; with remove, the standby profile goes too
        (only one Frame Suite made, still at 1x, and not in use by Boost)."""
        name, cfg = configs.get(appid, (None, None))
        if rec.get("applied") is not None and cfg is not None:
            res = await self._tb_set_multiplier(appid, name, cfg, rec.get("restore") or 1)
            if res["ok"]:
                rec["applied"] = rec["restore"] = None
        boost = (self.store.game(appid) or {}).get("boost") or {}
        if remove and rec.get("created") and cfg is not None and int(cfg.get("multiplier") or 1) <= 1 \
                and not (boost.get("on") and boost.get("route") == "lsfg"):
            await self._safe(self.ad.lsfg_reset(appid), {"ok": False})

    async def toolbox_sync(self, force=False):
        """Act on the toolbox's requests (see toolbox.py) and answer in the bridge file."""
        now = time.time()
        stamp = toolbox.stamp(self.home)
        if not force and stamp == self._tb_stamp and now - self._tb_checked < TOOLBOX_RECHECK_S:
            return
        self._tb_stamp, self._tb_checked = stamp, now
        if force or now - self._lsfg_checked >= LSFG_RECHECK_S:
            ls = await self._safe(self.ad.lsfg_state(), {"installed": False, "lossless": False})
            self._lsfg_ready = bool(ls.get("installed") and ls.get("lossless"))
            self._lsfg_checked = now
        reqs = toolbox.read(self.home, now)
        recs = self.store.data.setdefault("toolbox", {})
        gone = stamp is None
        self._tb_gone_since = (self._tb_gone_since or now) if gone else None
        keep_standby = gone and now - self._tb_gone_since < TOOLBOX_GONE_S
        if not reqs and not recs:
            self._bridge_put({})          # keeps the top-level answers current
            return
        before = json.dumps(recs, sort_keys=True)
        configs = {}
        if self.ad.has("lsfg"):
            res = await self._safe(self.ad.call("lsfg", "get_game_configs"), {})
            configs = {str(g.get("appid")): (g.get("profile"), dict(g.get("config") or {}))
                       for g in (res or {}).get("games", [])}
        allowed = self.toolbox_allowed()
        for appid, req in reqs.items():
            rec = recs.setdefault(appid, {"created": False, "since": None, "restore": None,
                                          "applied": None, "refused": None, "blocked": False})
            opts = self.options(appid)
            reason = None
            if not allowed:
                reason = "Switched off in Frame Suite (Chip, versions and updates)."
            elif not self._lsfg_ready:
                reason = "lsfg-vk or Lossless Scaling is not set up (Frame Suite's Setup)."
            elif rec.get("blocked"):
                reason = "Removed in Frame Suite for this game."
            elif opts["fg_in_game"]:
                reason = "The game's own frame generation is in use."
            if reason:
                await self._tb_release(appid, rec, configs, remove=not allowed)
                rec["refused"] = reason
                if not allowed and rec.get("created"):
                    rec["created"], rec["since"] = False, None
                continue
            rec["refused"] = None
            name, cfg = configs.get(appid, (None, None))
            if cfg is None:
                og = await self._safe(self.ad.og_status(appid), {})
                rec["name"] = og.get("name") or rec.get("name") or "App %s" % appid
                res = await self.ad.lsfg_set(appid, rec["name"], self._standby_config())
                if not res["ok"]:
                    rec["refused"] = "lsfg-vk did not take the profile: %s" % res["message"]
                    continue
                rec.update(created=True, since=now)
                res = await self._safe(self.ad.call("lsfg", "get_game_configs"), {})
                configs = {str(g.get("appid")): (g.get("profile"), dict(g.get("config") or {}))
                           for g in (res or {}).get("games", [])}
                name, cfg = configs.get(appid, (rec["name"], self._standby_config()))
            elif rec.get("since") is None:
                rec["since"] = 0.0      # the user's own profile, there before the game started
            want = req["multiplier"]
            cur = int(cfg.get("multiplier") or 1)
            if want:
                if rec.get("applied") is None:
                    rec["restore"] = cur
                if cur != want:
                    res = await self._tb_set_multiplier(appid, name, cfg, want)
                    if not res["ok"]:
                        rec["refused"] = "lsfg-vk did not take the change: %s" % res["message"]
                        continue
                rec["applied"] = want
            elif rec.get("applied") is not None:
                await self._tb_release(appid, rec, configs)
        released = [a for a in recs if a not in reqs]
        for appid in released:
            if keep_standby:
                # Probably a toolbox update (its uninstall step removes the file, the new
                # version writes it again): frame generation off, the profiles stay a while.
                await self._tb_release(appid, recs[appid], configs)
                continue
            await self._tb_release(appid, recs[appid], configs, remove=True)
            del recs[appid]
        if keep_standby:
            released = []
        if json.dumps(recs, sort_keys=True) != before:
            self.store.save()
            # Only the games that changed: looking at a game's files costs battery.
            await self.sync_bridge(sorted(set(reqs) | set(released)))
        else:
            self._bridge_put({})

    # --- the switch -------------------------------------------------------------------

    async def boost_on(self, appid, name, launch_options, ack=False):
        appid = str(appid)
        launch_options = launch_options or ""
        if self.busy.get(appid):
            return {"ok": False, "error": "A change for this game is still running."}
        self.busy[appid] = True
        try:
            return await self._boost_on(appid, name, launch_options, bool(ack))
        except adapters.Unavailable as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            self.log.exception("Frame Suite: boost_on")
            return {"ok": False, "error": "Unexpected error: %s" % exc}
        finally:
            self.busy.pop(appid, None)

    async def _boost_on(self, appid, name, launch_options, ack):
        f = await self._facts(appid)
        plan = self._plan(appid, f)
        if plan["blockers"]:
            return {"ok": False, "error": plan["blockers"][0]["text"], "blocker": plan["blockers"][0]["id"]}
        entry = self.store.game(appid, create=True)
        if (entry.get("boost") or {}).get("on"):
            return {"ok": False, "error": "Already on for this game. Switch it off first to set it up again."}
        opts = self.options(appid)
        name = name or f["og"].get("name") or f["hx"].get("name") or entry.get("name") or "App %s" % appid
        entry["name"] = name
        route = plan["route"]
        applied, warnings, done = {}, [], []
        new_lo, added = launch_options, []

        upscale = route == "mako" and opts["mako_upscaler"] != "off"
        if route == "optiscaler" or (upscale and not f["hx"].get("running")):
            # The anti-cheat question comes first, before anything is changed.
            asked = await self._anticheat_ack(appid, f, ack)
            if asked:
                return asked
        if route == "optiscaler":
            res = await self._upscaler_in(appid, f, opts, "optiscaler", launch_options, applied, warnings, done)
            if not res["ok"]:
                return res
            new_lo, added = res["launch_options"], res["added"]
        elif route == "mako":
            prof = f.get("mprof")
            if prof:
                applied["mako"] = prof["profile"]
                applied["mako_created"] = False
                done.append("MAKO already had a profile for this game; kept as it is.")
            else:
                res = await self.ad.mako_capture(appid, name)
                if not res["ok"] or not res["profile"]:
                    return {"ok": False, "error": res["message"] or "MAKO could not make a profile for this game."}
                cfg = self.mako_config_for(appid)
                set_res = await self.ad.mako_set(res["profile"], cfg)
                if not set_res["ok"]:
                    await self._safe(self.ad.mako_delete(res["profile"]), None)
                    return {"ok": False, "error": "MAKO did not take the settings: %s" % set_res["message"]}
                applied["mako"] = res["profile"]
                applied["mako_created"] = True
                done.append("MAKO adaptive frame generation: %d fps on screen, at most %d× generated. Restart the "
                            "game once for it to start." % (cfg["target_fps"], cfg["adaptive_max_multiplier"]))
            wrapper = f["mk"].get("wrapper")
            if wrapper:
                new_lo, did = launchopts.add_wrapper(launch_options, wrapper)
                if did:
                    applied["wrapper"] = True
                    self._mako_mark(appid, True)
            if upscale and f["hx"].get("running"):
                # MAKO needed the game running; OptiScaler needs it closed. The page offers the second step.
                warnings.append("The upscaler is added once the game is closed: close it, then choose "
                                "\"Add the upscaler now\" on Frame Suite's page.")
            elif upscale:
                res = await self._upscaler_in(appid, f, opts, opts["mako_upscaler"], new_lo, applied, warnings, done)
                if res["ok"]:
                    new_lo, added = res["launch_options"], res["added"]
                else:
                    warnings.append("The upscaler was not added: %s" % res["error"])
            await self.mako_sync(force=True)
        else:
            if f["lcfg"]:
                applied["lsfg"] = "kept"
                done.append("lsfg-vk already had a profile for this game; kept as it is.")
            else:
                res = await self.ad.lsfg_set(appid, name, self.lsfg_config_for(appid))
                if not res["ok"]:
                    return {"ok": False, "error": res["message"] or "lsfg-vk did not accept the settings."}
                applied["lsfg"] = "created"
                cfg = self.lsfg_config_for(appid)
                done.append("lsfg-vk profile created (%d×, flow scale %s)." % (cfg.get("multiplier", 2),
                                                                             cfg.get("flow_scale")))
        entry["boost"] = {"on": True, "route": route, "applied": applied, "time": _now(),
                          "profile": self.profile_id(), "lo_before": launch_options, "lo_after": new_lo,
                          "lo_added": added}
        self.store.save()
        view = await self.game(appid, new_lo, name)
        return {"ok": True, "route": route, "launch_options": new_lo, "launch_changed": new_lo != launch_options,
                "done": done, "warnings": warnings, "view": view}

    async def _anticheat_ack(self, appid, f, ack):
        """None when the game may get OptiScaler, else the question for the user."""
        hx, og = f["hx"], f["og"]
        acked = ack or self.store.data.get("acks", {}).get(appid)
        if hx.get("ok") and hx.get("anticheat") and not acked:
            return {"ok": False, "need_ack": True, "anticheat": hx["anticheat"],
                    "error": "This game ships anti-cheat (%s)." % ", ".join(hx["anticheat"][:2])}
        if not hx.get("ok") and not og.get("patched") and not acked:
            # The anti-cheat check is HelixSR Manager's; without it the question is put to the user.
            return {"ok": False, "need_ack": True, "anticheat": ["could not be checked for anti-cheat"],
                    "error": "The game could not be checked for anti-cheat."}
        if ack:
            self.store.data.setdefault("acks", {})[appid] = True
            await self._safe(self.ad.helix_ack(appid, True), None)
        return None

    async def _upscaler_in(self, appid, f, opts, mode, launch_options, applied, warnings, done):
        """An upscaler into the game's files, and the launch settings it needs:
        "optiscaler": OptiScaler (FSR 4) by Decky-Framegen, HelixSR next to it if wanted;
        "scaler": HelixSR Scaler (HelixSR's own OptiScaler with HLX DLSS);
        "direct": HelixSR in place of the game's own FSR 3.1 file."""
        if mode in ("scaler", "direct"):
            return await self._helix_mode_in(appid, mode, launch_options, applied, done)
        og = f["og"]
        dll = og.get("dll") if og.get("patched") else (self.profile().get("optiscaler") or {}).get("proxy_dll")
        if dll not in self.ad.og_valid_dlls():
            dll = "dxgi.dll"
        if og.get("patched"):
            env = self.ad.og_env(dll)
            done.append("OptiScaler was already in the game; kept as it is.")
        else:
            res = await self.ad.og_patch(appid, dll, launch_options, opts["variant"])
            if not res["ok"]:
                return {"ok": False, "error": res["message"] or "Decky-Framegen could not patch the game."}
            applied["patched"] = True
            env = res["env"]
            done.append(res["message"] or "OptiScaler installed.")
        new_lo, added = launch_options, []
        if not launchopts.uses_fgmod_wrapper(launch_options):
            new_lo, added = launchopts.add_env(launch_options, env)
        if opts["helix"]:
            await self._helix_into_game(appid, f, applied, warnings, done)
        applied["upscaler"] = "optiscaler"
        return {"ok": True, "launch_options": new_lo, "added": added}

    async def _helix_mode_in(self, appid, mode, launch_options, applied, done):
        if not self.ad.has("helix"):
            return {"ok": False, "error": "The HelixSR part did not load in this build."}
        hx = await self._safe(self.ad.helix_game(appid), {"ok": False})
        if not hx.get("ok"):
            return {"ok": False, "error": "HelixSR could not read the game's files%s."
                                          % (": " + hx["error"] if hx.get("error") else "")}
        if mode == "direct":
            targets = [d["path"] for d in hx["direct"] if not d["dx11"]
                       and not str(d.get("state", "")).startswith("helixsr") and d.get("state") != "disabled"]
            if not targets:
                return {"ok": False, "error": "The game has no FSR 3.1 file (DirectX 12) that HelixSR can take the "
                                              "place of. Use HelixSR Scaler or FSR 4 instead."}
            paths = []
            for t in targets:
                res = await self._safe(self.ad.helix_install_direct(t), {"ok": False, "message": "no answer"})
                if not res["ok"]:
                    for p in paths:
                        await self._safe(self.ad.helix_uninstall_direct(p), None)
                    return {"ok": False, "error": res["message"] or "HelixSR could not be put in."}
                paths.append(t)
            applied["direct"] = paths
            applied["upscaler"] = "direct"
            done.append("HelixSR is in place of the game's own FSR: choose FSR in the game's graphics settings.")
            return {"ok": True, "launch_options": launch_options, "added": []}
        if not hx.get("path"):
            return {"ok": False, "error": "The game's folder was not found."}
        res = await self._safe(self.ad.helix_install_scaler(hx["path"]), {"ok": False, "message": "no answer"})
        if not res["ok"]:
            return {"ok": False, "error": res["message"] or "HelixSR Scaler could not be put in."}
        applied["scaler"] = hx["path"]
        applied["upscaler"] = "scaler"
        done.append(res["message"] or "HelixSR Scaler installed. In the game, select DLSS.")
        # It needs a launch setting only under another name than dxgi.dll.
        after = await self._safe(self.ad.helix_game(appid), {"ok": False})
        launch = next((o.get("scaler_launch") for o in after.get("optis") or [] if o.get("scaler_launch")), None)
        new_lo, added = launch_options, []
        if launch:
            new_lo, added = launchopts.add_env(launch_options, dict(launchopts.parse_env(launch + " %command%")))
        return {"ok": True, "launch_options": new_lo, "added": added}

    async def _upscaler_out(self, appid, applied, launch_options, lo_added, done, warnings):
        """Takes out what _upscaler_in put in, and its launch settings."""
        for p in applied.get("direct") or []:
            res = await self._safe(self.ad.helix_uninstall_direct(p), {"ok": False, "message": "no answer"})
            if not res["ok"]:
                return {"ok": False, "error": "HelixSR could not be taken out: %s" % res["message"]}
            done.append("The game's own FSR is back.")
        applied.pop("direct", None)
        if applied.get("scaler"):
            res = await self._safe(self.ad.helix_uninstall_scaler(applied["scaler"]), {"ok": False, "message": "no answer"})
            if not res["ok"]:
                return {"ok": False, "error": "HelixSR Scaler could not be taken out: %s" % res["message"]}
            done.append(res["message"] or "HelixSR Scaler removed.")
            applied.pop("scaler", None)
            launch_options = launchopts.remove_env(launch_options, lo_added)
        for d in applied.get("helix") or []:
            res = await self._safe(self.ad.helix_uninstall(d), {"ok": False, "message": "no answer"})
            (done if res["ok"] else warnings).append(
                "HelixSR removed." if res["ok"] else "HelixSR could not be removed: %s" % res["message"])
        applied.pop("helix", None)
        if applied.get("patched"):
            res = await self.ad.og_unpatch(appid)
            if not res["ok"]:
                return {"ok": False, "error": res["message"] or "Decky-Framegen could not restore the game."}
            done.append(res["message"] or "OptiScaler removed.")
            applied.pop("patched", None)
            launch_options = launchopts.remove_env(launch_options, lo_added)
        applied.pop("upscaler", None)
        return {"ok": True, "launch_options": launch_options}

    async def _helix_into_game(self, appid, f, applied, warnings, done):
        if not self.ad.has("helix"):
            return
        if not f["hstate"].get("built"):
            warnings.append("HelixSR is not downloaded and built yet, so the game uses OptiScaler's FSR 4 only. "
                            "Run Setup, then switch this off and on again to add it.")
            return
        hx = await self._safe(self.ad.helix_game(appid), {"ok": False})
        if not hx.get("ok"):
            warnings.append("HelixSR could not read the game's files%s." % (": " + hx["error"] if hx.get("error") else ""))
            return
        targets = [o for o in hx["optis"] if not o["dx11"] and not o["kind"]]
        if not targets and any(o["kind"] for o in hx["optis"]):
            done.append("HelixSR was already in the game; kept as it is.")
            return
        if not targets:
            warnings.append("HelixSR was not added: it needs DirectX 12 and found no OptiScaler folder it can use.")
            return
        dirs = []
        for o in targets:
            res = await self._safe(self.ad.helix_install(o["dir"], True), {"ok": False, "message": "no answer"})
            if res["ok"]:
                dirs.append(o["dir"])
                done.append("HelixSR added: %s" % (res["message"] or o["dir"]))
            else:
                warnings.append("HelixSR was not added: %s" % res["message"])
        if dirs:
            applied["helix"] = dirs

    async def boost_off(self, appid, launch_options):
        appid = str(appid)
        launch_options = launch_options or ""
        entry = self.store.game(appid)
        boost = (entry or {}).get("boost") or {}
        if not boost.get("on"):
            return {"ok": True, "launch_options": launch_options, "launch_changed": False, "done": [],
                    "warnings": [], "view": await self.game(appid, launch_options)}
        if self.busy.get(appid):
            return {"ok": False, "error": "A change for this game is still running."}
        self.busy[appid] = True
        try:
            applied, done, warnings = boost.get("applied") or {}, [], []
            if any(applied.get(k) for k in ("patched", "helix", "direct", "scaler")):
                hx = await self._safe(self.ad.helix_game(appid), {"ok": False})
                if hx.get("ok") and hx.get("running"):
                    return {"ok": False, "error": "Close the game first: its files cannot be changed while it runs."}
            res = await self._upscaler_out(appid, dict(applied), launch_options, None, done, warnings)
            if not res["ok"]:
                return res
            if applied.get("lsfg") == "created":
                res = await self.ad.lsfg_reset(appid)
                (done if res["ok"] else warnings).append(
                    "lsfg-vk profile removed." if res["ok"] else "lsfg-vk profile not removed: %s" % res["message"])
            if applied.get("mako") and applied.get("mako_created"):
                res = await self._safe(self.ad.mako_delete(applied["mako"]), {"ok": False, "message": "no answer"})
                (done if res["ok"] else warnings).append(
                    "MAKO profile removed." if res["ok"] else "MAKO profile not removed: %s" % res["message"])
            if applied.get("wrapper"):
                self._mako_mark(appid, False)
            if applied.get("mako"):
                await self.mako_sync(force=True)
            if launch_options == boost.get("lo_after"):
                new_lo = boost.get("lo_before") or ""
            elif boost.get("lo_added") or applied.get("wrapper"):
                new_lo = launchopts.remove_env(launch_options, boost.get("lo_added"))
                if applied.get("wrapper"):
                    new_lo = launchopts.remove_wrapper(new_lo, adapters.MAKO_RUN)
            else:
                new_lo = launch_options    # OptiScaler was there before and stays: so do its settings
            entry["boost"] = {"on": False}
            self.store.save()
            view = await self.game(appid, new_lo, entry.get("name"))
            return {"ok": True, "launch_options": new_lo, "launch_changed": new_lo != launch_options,
                    "done": done, "warnings": warnings, "view": view}
        except adapters.Unavailable as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            self.log.exception("Frame Suite: boost_off")
            return {"ok": False, "error": "Unexpected error: %s" % exc}
        finally:
            self.busy.pop(appid, None)

    async def remove_all(self, appid, launch_options):
        """Everything the four plugins put into this game, whoever put it there."""
        appid = str(appid)
        launch_options = launch_options or ""
        done, warnings = [], []
        try:
            hx = await self._safe(self.ad.helix_game(appid), {"ok": False})
            if hx.get("ok") and hx.get("running"):
                return {"ok": False, "error": "Close the game first: its files cannot be changed while it runs."}
            scaler_env = []
            if hx.get("ok"):
                scalers = [o for o in hx["optis"] if o.get("scaler_version")]
                if scalers and hx.get("path"):
                    res = await self._safe(self.ad.helix_uninstall_scaler(hx["path"]), {"ok": False, "message": "no answer"})
                    (done if res["ok"] else warnings).append(
                        (res["message"] or "HelixSR Scaler removed.") if res["ok"] else "HelixSR Scaler: %s" % res["message"])
                    for o in scalers:
                        if res["ok"] and o.get("scaler_launch"):
                            scaler_env += [[k, v, None] for k, v in launchopts.parse_env(o["scaler_launch"] + " %command%")]
                for o in hx["optis"]:
                    if o["kind"] in ("ffx", "ngx") and not o.get("scaler_version"):
                        res = await self._safe(self.ad.helix_uninstall(o["dir"]), {"ok": False, "message": "no answer"})
                        (done if res["ok"] else warnings).append(
                            "HelixSR removed from OptiScaler." if res["ok"] else "HelixSR: %s" % res["message"])
                for d in hx["direct"]:
                    if str(d.get("state", "")).startswith("helixsr") or d.get("state") == "disabled":
                        res = await self._safe(self.ad.helix_uninstall_direct(d["path"]),
                                               {"ok": False, "message": "no answer"})
                        (done if res["ok"] else warnings).append(
                            "The game's own FSR 3.1 restored." if res["ok"] else "HelixSR: %s" % res["message"])
            og = await self._safe(self.ad.og_status(appid), {"patched": False})
            new_lo = launchopts.remove_env(launch_options, scaler_env) if scaler_env else launch_options
            if og.get("patched"):
                env = self.ad.og_env(og.get("dll") or "dxgi.dll")
                res = await self.ad.og_unpatch(appid)
                if res["ok"]:
                    done.append(res["message"] or "OptiScaler removed.")
                    new_lo = launchopts.remove_env(new_lo, [[k, v, None] for k, v in env.items()])
                else:
                    warnings.append("OptiScaler: %s" % res["message"])
            if await self._safe(self.ad.lsfg_config(appid), None):
                res = await self._safe(self.ad.lsfg_reset(appid), {"ok": False, "message": "no answer"})
                (done if res["ok"] else warnings).append(
                    "lsfg-vk profile removed." if res["ok"] else "lsfg-vk: %s" % res["message"])
            mprof = await self._safe(self.ad.mako_game(appid), None)
            if mprof:
                res = await self._safe(self.ad.mako_delete(mprof["profile"]), {"ok": False, "message": "no answer"})
                (done if res["ok"] else warnings).append(
                    "MAKO profile removed." if res["ok"] else "MAKO: %s" % res["message"])
            if launchopts.has_wrapper(new_lo, adapters.MAKO_RUN):
                new_lo = launchopts.remove_wrapper(new_lo, adapters.MAKO_RUN)
                done.append("MAKO's launcher taken out of the launch options.")
            self._mako_mark(appid, False)
            await self.mako_sync(force=True)
            entry = self.store.game(appid)
            if entry:
                entry["boost"] = {"on": False}
            rec = (self.store.data.get("toolbox") or {}).get(appid)
            if rec:
                # The toolbox's standby profile is gone with the rest: not made again for this goal.
                rec.update(blocked=True, applied=None, restore=None, created=False, since=None)
            self.store.save()
            if not done and not warnings:
                done.append("Nothing from the four plugins was in this game.")
            view = await self.game(appid, new_lo, (entry or {}).get("name"))
            return {"ok": True, "launch_options": new_lo, "launch_changed": new_lo != launch_options,
                    "done": done, "warnings": warnings, "view": view}
        except adapters.Unavailable as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            self.log.exception("Frame Suite: remove_all")
            return {"ok": False, "error": "Unexpected error: %s" % exc}

    async def fix(self, appid, fix_id, launch_options):
        appid = str(appid)
        launch_options = launch_options or ""
        new_lo, message = launch_options, ""
        if fix_id == "lsfg-reset":
            res = await self._safe(self.ad.lsfg_reset(appid), {"ok": False, "message": "no answer"})
            if not res["ok"]:
                return {"ok": False, "error": res["message"]}
            message = "lsfg-vk is off for this game."
        elif fix_id == "launch-repair":
            og = await self._safe(self.ad.og_status(appid), {"patched": False})
            if og.get("patched"):
                new_lo, added = launchopts.add_env(launch_options, self.ad.og_env(og.get("dll") or "dxgi.dll"))
                entry = self.store.game(appid)
                if entry and (entry.get("boost") or {}).get("on"):
                    entry["boost"].update(lo_after=new_lo, lo_added=added, lo_before=launch_options)
                    self.store.save()
                message = "Launch settings added again."
        elif fix_id == "mako-launch-add":
            res = await self.mako_launch_fix(appid, launch_options)
            new_lo = res["launch_options"]
            if res["changed"] and res["ours"]:
                self._mako_mark(appid, True)
            message = "MAKO's launcher added to the launch options." if res["changed"] else ""
        elif fix_id == "wrapper-remove":
            toks = [t for t in launchopts.split_tokens(launch_options)
                    if not re.search(r"(^|/)fgmod(-uninstaller\.sh)?$", t.strip("'\""))]
            new_lo = " ".join(toks)
            message = "Wrapper removed from the launch options."
        elif fix_id in ("mako-upscale-add", "mako-upscale-add-ack"):
            return await self._mako_upscale(appid, self.options(appid)["mako_upscaler"], launch_options,
                                            fix_id.endswith("-ack"))
        elif fix_id == "mako-upscale-remove":
            return await self._mako_upscale(appid, "off", launch_options)
        elif fix_id.startswith(("mako-upscaler:", "mako-upscaler-ack:")):
            return await self._mako_upscale(appid, fix_id.split(":", 1)[1], launch_options,
                                            fix_id.startswith("mako-upscaler-ack:"))
        elif fix_id == "boost-reapply":
            entry = self.store.game(appid)
            if entry:
                entry["boost"] = {"on": False}
                self.store.save()
            return await self.boost_on(appid, (entry or {}).get("name"), launch_options,
                                       bool(self.store.data.get("acks", {}).get(appid)))
        else:
            return {"ok": False, "error": "Unknown fix."}
        view = await self.game(appid, new_lo)
        return {"ok": True, "launch_options": new_lo, "launch_changed": new_lo != launch_options,
                "done": [message] if message else [], "warnings": [], "view": view}

    async def _mako_upscale(self, appid, mode, launch_options, ack=False):
        """Sets the upscaler under MAKO (see options()). While MAKO's Boost is on, the one in the game is changed
        to it at once (the game must be closed); otherwise it is kept for the next Boost."""
        if mode not in UPSCALERS:
            return {"ok": False, "error": "Unknown upscaler."}
        entry = self.store.game(appid, create=True)
        entry["options"]["mako_upscaler"] = mode
        entry["options"].pop("mako_upscale", None)
        self.store.save()
        boost = entry.get("boost") or {}
        if not (boost.get("on") and boost.get("route") == "mako"):
            view = await self.game(appid, launch_options, entry.get("name"))
            return {"ok": True, "launch_options": launch_options, "launch_changed": False, "done": [],
                    "warnings": [], "view": view}
        if self.busy.get(appid):
            return {"ok": False, "error": "A change for this game is still running."}
        self.busy[appid] = True
        try:
            applied, done, warnings = boost.setdefault("applied", {}), [], []
            current = applied.get("upscaler") or "off"
            new_lo = launch_options
            if current != mode:
                f = await self._facts(appid)
                if f["hx"].get("running"):
                    # The choice is kept; the page offers the step again once the game is closed.
                    view = await self.game(appid, launch_options, entry.get("name"))
                    return {"ok": True, "launch_options": launch_options, "launch_changed": False, "done": [],
                            "warnings": ["Close the game first: its files cannot be changed while it runs. "
                                         "The choice is saved."], "view": view}
                if mode != "off":
                    asked = await self._anticheat_ack(appid, f, ack)
                    if asked:
                        return asked
                if current != "off":
                    res = await self._upscaler_out(appid, applied, launch_options, boost.get("lo_added"),
                                                   done, warnings)
                    if not res["ok"]:
                        return res
                    new_lo = res["launch_options"]
                    boost["lo_added"] = []
                    self.store.save()
                if mode != "off":
                    f = await self._facts(appid)        # what the game has now
                    res = await self._upscaler_in(appid, f, self.options(appid), mode, new_lo, applied,
                                                  warnings, done)
                    if not res["ok"]:
                        boost["lo_after"] = new_lo
                        self.store.save()
                        res["launch_options"], res["launch_changed"] = new_lo, new_lo != launch_options
                        return res
                    new_lo = res["launch_options"]
                    boost["lo_added"] = list(boost.get("lo_added") or []) + list(res["added"])
            boost["lo_after"] = new_lo
            self.store.save()
            view = await self.game(appid, new_lo, entry.get("name"))
            return {"ok": True, "launch_options": new_lo, "launch_changed": new_lo != launch_options,
                    "done": done, "warnings": warnings, "view": view}
        finally:
            self.busy.pop(appid, None)

    async def set_menu_key(self, appid, code):
        if code not in [k["code"] for k in MENU_KEYS]:
            return {"ok": False, "error": "Unknown key."}
        og = await self._safe(self.ad.og_status(appid), {"patched": False})
        if not og.get("patched") or not og.get("target_dir"):
            return {"ok": False, "error": "OptiScaler is not in this game."}
        if (await asyncio.to_thread(live.check, appid, None, None, self.proc)).get("running"):
            return {"ok": False, "error": "Close the game first: OptiScaler rewrites its settings while it runs."}
        path = os.path.join(og["target_dir"], "OptiScaler.ini")
        try:
            with open(path, "r", errors="replace", newline="") as f:
                text = f.read()
            with open(path, "w", newline="") as f:
                f.write(ini.set(text, "Menu", "ShortcutKey", code))
        except OSError as exc:
            return {"ok": False, "error": "OptiScaler.ini could not be changed: %s" % exc.strerror}
        return {"ok": True, "menu_key": code}

    async def games(self):
        """Installed games: Steam's, and games added to Steam by hand (EmuDeck / Steam ROM Manager,
        Heroic, Lutris, ...), the ones with something set up first."""
        listed = {}
        for g in await self._safe(self.ad.og_games(), []):
            listed[str(g["appid"])] = {"appid": str(g["appid"]), "name": g.get("name") or ""}
        if self.ad.has("lsfg"):
            # lsfg-vk's list has both kinds; added-by-hand games carry Steam's app id for them.
            res = await self._safe(self.ad.call("lsfg", "get_installed_games"), {})
            for g in (res or {}).get("games", []):
                appid = str(g.get("appid") or "")
                if appid.isdigit() and appid not in listed:
                    listed[appid] = {"appid": appid, "name": g.get("name") or ""}
                    if g.get("nonSteam"):
                        listed[appid]["non_steam"] = True
        for appid, entry in self.store.data.get("games", {}).items():
            if appid in listed:
                listed[appid]["boost"] = bool((entry.get("boost") or {}).get("on"))
        return sorted(listed.values(), key=lambda g: (not g.get("boost"), g["name"].lower()))

    # --- setup ------------------------------------------------------------------------

    async def setup(self):
        ls = await self._safe(self.ad.lsfg_state(), {"available": False, "installed": False, "lossless": False})
        bundle = await self._safe(self.ad.og_bundle(), {"available": False, "installed": False})
        hs = await self._safe(self.ad.helix_state(), {"available": False, "downloaded": False, "built": False})
        self._mako_state_at = 0.0
        mk = await self._mako_installed()
        download = {}
        if self.ad.has("helix") and self.wizard.get("step") == "helix" and self.wizard.get("phase") == "downloading":
            download = await self._safe(self.ad.call("helix", "get_download_status"), {})
        return {"lsfg": ls, "optiscaler": bundle, "helix": dict(hs, download=download), "mako": mk,
                "wizard": dict(self.wizard), "variant": self.options("0")["variant"]}

    async def setup_run(self, step):
        if self.wizard_task and not self.wizard_task.done():
            return {"ok": False, "error": "A setup step is still running."}
        if step not in ("lsfg", "optiscaler", "helix", "mako"):
            return {"ok": False, "error": "Unknown step."}
        self.wizard = {"step": step, "phase": "starting", "error": None, "tag": None}
        self.wizard_task = asyncio.ensure_future(self._setup_step(step))
        return {"ok": True}

    async def _setup_step(self, step):
        w = self.wizard
        try:
            if step == "lsfg":
                w["phase"] = "installing"
                res = await self.ad.call("lsfg", "install_lsfg_vk")
                if not (res or {}).get("success"):
                    raise RuntimeError((res or {}).get("error") or "lsfg-vk could not be installed.")
            elif step == "mako":
                w["phase"] = "installing"
                res = await self.ad.call("mako", "install_mako")
                if not (res or {}).get("success"):
                    raise RuntimeError((res or {}).get("error") or "MAKO's renderer could not be installed.")
                self._mako_state_at = 0.0
            elif step == "optiscaler":
                w["phase"] = "installing"
                res = await self.ad.og_install_bundle(self.options("0")["variant"])
                if not res["ok"]:
                    raise RuntimeError(res["message"] or "OptiScaler could not be set up.")
            else:
                w["phase"] = "looking"
                rel = await self.ad.call("helix", "list_releases")
                stable = [r for r in (rel or {}).get("releases", []) if not r.get("prerelease")]
                if not stable:
                    raise RuntimeError("No HelixSR release found%s." % (
                        " (offline?)" if (rel or {}).get("offline") else ""))
                tag = w["tag"] = stable[0]["tag"]
                state = await self.ad.helix_state()
                have = any(v.get("tag") == tag for v in
                           (await self.ad.call("helix", "get_helix_state")).get("versions", []))
                if not have:
                    w["phase"] = "downloading"
                    res = await self.ad.call("helix", "download_release", tag)
                    if not (res or {}).get("ok"):
                        raise RuntimeError((res or {}).get("error") or "The download failed.")
                await self.ad.call("helix", "set_active", tag)
                state = await self.ad.helix_state()
                if not state.get("built"):
                    w["phase"] = "building"
                    res = await self.ad.call("helix", "start_setup", tag)
                    if not (res or {}).get("ok"):
                        raise RuntimeError((res or {}).get("error") or "The build could not be started.")
                    while True:
                        await asyncio.sleep(3)
                        state = await self.ad.helix_state()
                        if state.get("setup_state") != "running":
                            break
                    if not state.get("built"):
                        raise RuntimeError("HelixSR's build did not finish (%s). The HelixSR page has the log."
                                           % (state.get("setup_state") or "unknown"))
            w["phase"] = "done"
        except asyncio.CancelledError:
            w["phase"] = "idle"
            raise
        except Exception as exc:
            self.log.exception("Frame Suite: setup step %s", step)
            w["phase"], w["error"] = "failed", str(exc)

    # --- measuring --------------------------------------------------------------------

    def _measure_label(self, view):
        parts = list(view["summary"]["active"]) or ["Nothing added"]
        return " + ".join(parts)

    async def measure_start(self, appid, seconds=20):
        appid = str(appid)
        if self.measure_task and not self.measure_task.done():
            return {"ok": False, "error": "A measurement is already running."}
        python = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else shutil.which("python3")
        if not python:
            return {"ok": False, "error": "No system Python found to run the frame-rate probe."}
        view = await self.game(appid)
        if not view["running"]:
            return {"ok": False, "error": "Start the game first: only a running game can be measured."}
        seconds = max(5, min(120, int(seconds)))
        self.measure = {"state": "running", "appid": appid, "seconds": seconds, "started": time.time(),
                        "label": self._measure_label(view), "note": ""}
        self.measure_task = asyncio.ensure_future(self._measure(python, appid, seconds))
        return {"ok": True}

    async def _measure(self, python, appid, seconds):
        m = self.measure
        env = dict(os.environ)
        # Decky's bundled Python must not leak its libraries into the system one.
        orig = env.pop("LD_LIBRARY_PATH_ORIG", None)
        env.pop("LD_LIBRARY_PATH", None)
        if orig:
            env["LD_LIBRARY_PATH"] = orig
        for k in ("PYTHONHOME", "PYTHONPATH"):
            env.pop(k, None)
        probe = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fps_probe.py")
        proc = None
        windows = []
        try:
            proc = await asyncio.create_subprocess_exec(
                python, probe, str(int(appid)), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
            end = time.time() + seconds
            while time.time() < end:
                try:
                    line = await asyncio.wait_for(proc.stdout.readline(), timeout=2.0)
                except asyncio.TimeoutError:
                    continue
                if not line:
                    break
                text = line.decode(errors="replace").strip()
                if text.startswith("!"):
                    m["note"] = text[1:].strip()
                    continue
                parts = text.split()
                if len(parts) >= 2 and parts[0] != "-":
                    try:
                        windows.append((float(parts[0]), int(parts[1]),
                                        float(parts[2]) if len(parts) > 2 and parts[2] != "-" else None))
                    except ValueError:
                        pass
            result = summarize(windows)
            if not result:
                m.update(state="failed", error=m.get("note") or "No frames were reported for this game.")
                return
            result.update(label=m["label"], time=_now(), seconds=seconds)
            runs = self.store.data.setdefault("measure", {}).setdefault(appid, [])
            runs.insert(0, result)
            del runs[MEASURE_KEEP:]
            self.store.save()
            m.update(state="done", result=result)
        except Exception as exc:
            self.log.exception("Frame Suite: measure")
            m.update(state="failed", error=str(exc))
        finally:
            if proc and proc.returncode is None:
                try:
                    proc.terminate()
                    await asyncio.wait_for(proc.wait(), timeout=3)
                except Exception:
                    pass

    def measure_status(self):
        m = dict(self.measure)
        if m.get("state") == "running":
            m["progress"] = min(1.0, (time.time() - m["started"]) / max(1, m["seconds"]))
        return m

    def measure_clear(self, appid):
        self.store.data.setdefault("measure", {}).pop(str(appid), None)
        self.store.save()
        return {"ok": True}

    # --- updates ----------------------------------------------------------------------

    async def updates(self, force=False):
        cached = self.update_cache
        if cached["result"] and not force and time.time() - cached["time"] < UPDATE_TTL:
            return cached["result"]
        repo = self.lock.get("suite_repo") or ""
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            return {"ok": False, "error": "This build does not know which repository it came from.",
                    "current": self.version, "releases": []}
        try:
            raw = await asyncio.to_thread(_curl_json, "https://api.github.com/repos/%s/releases?per_page=8" % repo)
            releases = []
            for r in raw if isinstance(raw, list) else []:
                asset = next((a for a in r.get("assets", []) if str(a.get("name", "")).endswith(".zip")), None)
                if r.get("draft") or r.get("prerelease") or not asset:
                    continue
                digest = str(asset.get("digest") or "")
                releases.append({"version": re.sub(r"^v", "", r.get("tag_name", "")),
                                 "url": asset["browser_download_url"],
                                 "sha256": digest.split(":", 1)[1] if digest.startswith("sha256:") else "",
                                 "published": r.get("published_at"), "notes": (r.get("body") or "")[:1500]})
            if not releases:
                raise RuntimeError("No release with a plugin zip found (a private repository cannot be read).")
            latest = releases[0]
            result = {"ok": True, "current": self.version, "latest": latest["version"],
                      "newer": version_key(latest["version"]) > version_key(self.version), "releases": releases}
        except Exception as exc:
            result = {"ok": False, "error": str(exc), "current": self.version, "releases": []}
        self.update_cache = {"time": time.time(), "result": result}
        return result


def summarize(windows):
    """windows: (fps, frames, worst-frame fps) per half second."""
    windows = [w for w in windows if w[0] > 0 and w[1] > 0]
    if len(windows) < 4:
        return None
    frames = sum(w[1] for w in windows)
    seconds = sum(w[1] / w[0] for w in windows)
    lows = sorted(w[2] for w in windows if w[2])
    low = lows[max(0, int(len(lows) * 0.05) - 0)] if lows else None
    fps = [w[0] for w in windows]
    return {"fps": round(frames / seconds, 1), "low": round(low, 1) if low else None,
            "spread": round(statistics.pstdev(fps), 1), "windows": len(windows)}


def version_key(v):
    return [int(x) for x in re.findall(r"\d+", str(v).split("-")[0])][:4]


def _curl_json(url):
    env = dict(os.environ)
    orig = env.pop("LD_LIBRARY_PATH_ORIG", None)
    env.pop("LD_LIBRARY_PATH", None)   # the system curl with the system's libraries
    if orig:
        env["LD_LIBRARY_PATH"] = orig
    out = subprocess.run(["curl", "-fsSL", "--max-time", "20", "-H", "Accept: application/vnd.github+json", url],
                         capture_output=True, env=env, timeout=30)
    if out.returncode != 0:
        raise RuntimeError("GitHub could not be reached (%s)." % (out.stderr.decode(errors="replace").strip()[:120]
                                                                  or "curl %d" % out.returncode))
    return json.loads(out.stdout.decode())

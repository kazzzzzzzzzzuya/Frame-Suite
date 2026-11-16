"""A fake Decky and a fake Steam library, so the real upstream backends can
run against a temporary home folder."""

import asyncio
import logging
import os
import shutil
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGE = os.environ.get("FRAME_SUITE_STAGE")
# Decky puts the plugin's py_modules on the path; with a built plugin, test exactly that copy.
sys.path.insert(0, os.path.join(STAGE or ROOT, "py_modules"))
WORK = os.path.join(ROOT, ".work", "upstream")
REQUIRE = os.environ.get("FRAME_SUITE_REQUIRE_INTEGRATION") == "1"

def have_upstreams():
    base = os.path.join(STAGE, "upstream") if STAGE else WORK
    return all(os.path.isfile(os.path.join(base, s, "main.py")) for s in ("lsfg", "optiscaler", "helix", "mako"))


def have_binaries():
    """The built plugin with the downloaded binaries (lsfg-vk and OptiScaler), not a --skip-binaries build."""
    if not STAGE or not os.path.isdir(os.path.join(STAGE, "bin")):
        return False
    names = os.listdir(os.path.join(STAGE, "bin"))
    return any(n.startswith("lsfg-vk-") for n in names) and any(n.lower().startswith("optiscaler") for n in names)


class Env(object):
    """Temporary home + plugin folder + fake ``decky`` module."""

    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="frame-suite-test-")
        self.home = os.path.join(self.tmp, "home")
        self.events = []
        os.makedirs(self.home)
        if STAGE:
            self.plugin_dir = STAGE
        else:
            self.plugin_dir = os.path.join(self.tmp, "plugin")
            os.makedirs(self.plugin_dir)
            for name, src in (("upstream", WORK), ("profiles", os.path.join(ROOT, "profiles")),
                              ("upstreams.json", os.path.join(ROOT, "upstreams.json")),
                              ("package.json", os.path.join(ROOT, "package.json"))):
                os.symlink(src, os.path.join(self.plugin_dir, name))
        self.decky = self._decky()
        self._old_path = os.environ.get("PATH", "")
        self.can_unpack = bool(shutil.which("7z"))   # Decky-Framegen unpacks OptiScaler with it
        self._old_modules = set(sys.modules)

    def _decky(self):
        d = types.ModuleType("decky")
        base = os.path.join(self.tmp, "homebrew")
        d.HOME = d.DECKY_USER_HOME = self.home
        d.DECKY_HOME = base
        d.DECKY_USER = "deck"
        d.DECKY_PLUGIN_DIR = self.plugin_dir
        d.DECKY_PLUGIN_SETTINGS_DIR = os.path.join(base, "settings", "frame-suite")
        d.DECKY_PLUGIN_RUNTIME_DIR = os.path.join(base, "data", "frame-suite")
        d.DECKY_PLUGIN_LOG_DIR = os.path.join(base, "logs", "frame-suite")
        for p in (d.DECKY_PLUGIN_SETTINGS_DIR, d.DECKY_PLUGIN_RUNTIME_DIR, d.DECKY_PLUGIN_LOG_DIR):
            os.makedirs(p)
        d.logger = logging.getLogger("frame-suite-test")
        d.logger.setLevel(logging.CRITICAL)
        d.migrate_settings = d.migrate_runtime = d.migrate_logs = lambda *a: {}

        async def emit(event, *args):
            self.events.append((event, args))

        d.emit = emit
        return d

    def suite(self, proc=None):
        from framesuite.core import Suite
        sys.modules["decky"] = self.decky
        return Suite(self.decky, self.plugin_dir, proc=proc or os.path.join(self.tmp, "proc"))

    def add_game(self, appid, name, folder, files):
        """files: relative path -> bytes."""
        steamapps = os.path.join(self.home, ".steam", "steam", "steamapps")
        game = os.path.join(steamapps, "common", folder)
        os.makedirs(game, exist_ok=True)
        with open(os.path.join(steamapps, "libraryfolders.vdf"), "w") as f:
            f.write('"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n}\n'
                    % os.path.join(self.home, ".steam", "steam"))
        with open(os.path.join(steamapps, "appmanifest_%s.acf" % appid), "w") as f:
            f.write('"AppState"\n{\n\t"appid"\t\t"%s"\n\t"name"\t\t"%s"\n\t"StateFlags"\t\t"4"\n'
                    '\t"installdir"\t\t"%s"\n}\n' % (appid, name, folder))
        for rel, data in files.items():
            p = os.path.join(game, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(data)
        return game

    def close(self):
        os.environ["PATH"] = self._old_path
        # Every module of a bundled plugin goes: they keep the home folder of the test that loaded them.
        roots = [os.path.realpath(p) for p in (WORK, STAGE, os.path.join(ROOT, ".work")) if p]
        for name in set(sys.modules) - self._old_modules:
            mod = sys.modules.get(name)
            path = os.path.realpath(getattr(mod, "__file__", None) or "") if mod else ""
            plugin_module = any(path.startswith(r + os.sep) for r in roots) and \
                not path.startswith(os.path.join(os.path.realpath(STAGE or ROOT), "py_modules", "framesuite"))
            if plugin_module or name.startswith(("framesuite_upstream_", "lsfg_vk")) or name == "decky":
                sys.modules.pop(name, None)
        shutil.rmtree(self.tmp, ignore_errors=True)


def tree(folder):
    out = {}
    for base, _dirs, files in os.walk(folder):
        for fn in files:
            p = os.path.join(base, fn)
            out[os.path.relpath(p, folder)] = os.path.getsize(p)
    return out


_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def run(coro):
    return _LOOP.run_until_complete(coro)


# A Windows program that says it uses DirectX 12 / 11 (the backends look for the DLL name).
EXE_DX12 = b"MZ" + b"\0" * 64 + b"d3d12.dll\0D3D12.dll\0" + b"\0" * 4096
EXE_DX11 = b"MZ" + b"\0" * 64 + b"d3d11.dll\0D3D11.dll\0" + b"\0" * 4096

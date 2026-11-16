"""Loads the three upstream plugins, unmodified, inside one Decky plugin.

Each upstream ``main.py`` is imported under its own module name and sees its
own ``decky`` module: a thin proxy over the real one. That is how HelixSR
Manager keeps its settings in a folder of its own and how its events get a
prefix, without a single change to its source.

Every public backend method of an upstream is offered again as
``<id>__<method>``; the frontend build prefixes the upstream's calls the same
way (see ``src/shims``).
"""

import importlib.util
import inspect
import json
import os
import shutil
import sys
import types

SUBS = ("lsfg", "optiscaler", "helix", "mako")
SEP = "__"

# Folders the stand-alone HelixSR Manager may have been installed under.
HELIX_STANDALONE_DIRS = ("HelixSR-Manager", "HelixSR Manager", "decky-helixsr")


class DeckyProxy(types.ModuleType):
    """The ``decky`` module as one upstream sees it."""

    def __init__(self, real, overrides):
        super().__init__("decky")
        self.__dict__["_real"] = real
        self.__dict__.update(overrides)

    def __getattr__(self, name):
        return getattr(self.__dict__["_real"], name)


class Sub(object):
    def __init__(self, sub_id, meta):
        self.id = sub_id
        self.title = meta.get("title", sub_id)
        self.version = str(meta.get("tag", "")).lstrip("v")
        self.repo = meta.get("repo", "")
        self.instance = None
        self.module = None
        self.error = None

    @property
    def ok(self):
        return self.instance is not None

    def public(self):
        return {"id": self.id, "title": self.title, "version": self.version,
                "repo": self.repo, "ok": self.ok, "error": self.error}


def read_lock(plugin_dir):
    try:
        with open(os.path.join(plugin_dir, "upstreams.json"), "r") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"upstreams": {}}


def _logger(real, sub_id):
    log = getattr(real, "logger", None)
    try:
        return log.getChild(sub_id)
    except AttributeError:
        return log


def helix_dirs(real):
    return {
        "DECKY_PLUGIN_SETTINGS_DIR": os.path.join(real.DECKY_PLUGIN_SETTINGS_DIR, "helix"),
        "DECKY_PLUGIN_RUNTIME_DIR": os.path.join(real.DECKY_PLUGIN_RUNTIME_DIR, "helix"),
        "DECKY_PLUGIN_LOG_DIR": os.path.join(real.DECKY_PLUGIN_LOG_DIR, "helix"),
    }


def migrate_helix_settings(real, dirs):
    """First start only: take over the stand-alone HelixSR Manager's small
    settings files (selected release, HelixSR folder, anti-cheat
    confirmations, added game folders). Its downloaded releases live in the
    home folder and are found again through these settings. Build tools are
    not moved: a moved Wine prefix is not worth the risk, they are fetched
    again by the next build."""
    target = dirs["DECKY_PLUGIN_SETTINGS_DIR"]
    fresh = not os.path.isdir(target)
    for d in dirs.values():
        os.makedirs(d, exist_ok=True)
    if not fresh:
        return None
    base = os.path.dirname(os.path.normpath(real.DECKY_PLUGIN_SETTINGS_DIR))
    for name in HELIX_STANDALONE_DIRS:
        src = os.path.join(base, name)
        if not os.path.isfile(os.path.join(src, "settings.json")):
            continue
        for fn in ("settings.json", "releases.json"):
            try:
                shutil.copy2(os.path.join(src, fn), os.path.join(target, fn))
            except OSError:
                pass
        return src
    return None


def _overrides(real, sub):
    over = {"logger": _logger(real, sub.id)}
    if sub.version:
        over["DECKY_PLUGIN_VERSION"] = sub.version

    # Events reach the frontend under the plugin's prefix, as its calls do (src/shims).
    async def emit(event, *args):
        return await real.emit(sub.id + SEP + event, *args)

    over["emit"] = emit
    if sub.id == "helix":
        dirs = helix_dirs(real)
        migrate_helix_settings(real, dirs)
        over.update(dirs)
    return over


def load(sub, plugin_dir, real):
    """Import one upstream and create its Plugin. Never raises: a broken
    upstream must not take the other two down with it."""
    root = os.path.join(plugin_dir, "upstream", sub.id)
    main = os.path.join(root, "main.py")
    # A checkout for tests keeps a release-zip plugin's own folder intact (.work/upstream/<id>).
    saved = sys.modules.get("decky")
    try:
        if not os.path.isfile(main):
            raise RuntimeError("not part of this build")
        own_modules = os.path.join(root, "py_modules")   # source checkout; the release build flattens these
        if os.path.isdir(own_modules) and own_modules not in sys.path:
            sys.path.append(own_modules)
        sys.modules["decky"] = DeckyProxy(real, _overrides(real, sub))
        name = "framesuite_upstream_" + sub.id
        spec = importlib.util.spec_from_file_location(name, main)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        sub.module = module
        sub.instance = module.Plugin()
    except BaseException as exc:  # noqa: B902 - SyntaxError, SystemExit from an upstream included
        if isinstance(exc, KeyboardInterrupt):
            raise
        sub.error = "%s: %s" % (type(exc).__name__, exc)
        sub.instance = None
        try:
            real.logger.exception("Frame Suite: %s failed to load", sub.id)
        except Exception:
            pass
    finally:
        if saved is not None:
            sys.modules["decky"] = saved
        else:
            sys.modules.pop("decky", None)
    return sub


def load_all(plugin_dir, real):
    lock = read_lock(plugin_dir).get("upstreams", {})
    return {sid: load(Sub(sid, lock.get(sid, {})), plugin_dir, real) for sid in SUBS}


def methods(sub):
    """name -> bound coroutine function, for every public backend method."""
    out = {}
    if not sub.ok:
        return out
    for name in dir(sub.instance):
        if name.startswith("_"):
            continue
        fn = getattr(sub.instance, name, None)
        if inspect.iscoroutinefunction(fn):
            out[name] = fn
    return out


async def lifecycle(subs, hook, log=None):
    """Run ``_main`` / ``_unload`` / ``_uninstall`` / ``_migration`` of every
    upstream that has it; one failing does not stop the others."""
    for sub in subs.values():
        fn = getattr(sub.instance, hook, None) if sub.ok else None
        if fn is None:
            continue
        try:
            await fn()
        except Exception:
            if log:
                log.exception("Frame Suite: %s.%s failed", sub.id, hook)

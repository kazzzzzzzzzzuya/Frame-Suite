"""Frame Suite: decky-lsfg-vk, Decky-Framegen and HelixSR Manager in one
Decky plugin, plus a per-game switch that sets them up for this device's chip.

The three plugins run unmodified (see py_modules/framesuite/host.py). Their
backend methods are available as ``lsfg__*``, ``optiscaler__*`` and
``helix__*``; Frame Suite's own are the ``suite_*`` methods below.
"""

import os

import decky

from framesuite import host
from framesuite.core import Suite

PLUGIN_DIR = getattr(decky, "DECKY_PLUGIN_DIR", None) or os.path.dirname(os.path.abspath(__file__))


class Plugin:
    def __init__(self):
        self.suite = Suite(decky, PLUGIN_DIR)
        for name, fn in self.suite.exported().items():
            setattr(self, name, fn)

    # --- lifecycle: each upstream's own hooks, then ours ---

    async def _migration(self):
        await host.lifecycle(self.suite.subs, "_migration", decky.logger)

    async def _main(self):
        await host.lifecycle(self.suite.subs, "_main", decky.logger)
        self.suite.start()
        loaded = [s.id for s in self.suite.subs.values() if s.ok]
        decky.logger.info("Frame Suite %s loaded (%s), profile %s", self.suite.version,
                          ", ".join(loaded) or "no upstream", self.suite.profile_id())

    async def _unload(self):
        self.suite.stop()
        await host.lifecycle(self.suite.subs, "_unload", decky.logger)

    async def _uninstall(self):
        # Decky runs this for an update too. One started from our own panel leaves everything in place.
        if self.suite.updating():
            decky.logger.info("Frame Suite: updating, uninstall hooks skipped")
            return
        await host.lifecycle(self.suite.subs, "_uninstall", decky.logger)
        self.suite.forget()

    # --- Frame Suite ---

    async def suite_info(self):
        return self.suite.info()

    async def suite_set_profile(self, profile_id):
        return self.suite.set_profile(profile_id)

    async def suite_games(self):
        return await self.suite.games()

    async def suite_prepare_update(self):
        return self.suite.prepare_update()

    async def suite_game(self, appid, launch_options=None, name=None):
        return await self.suite.game(appid, launch_options, name)

    async def suite_set_option(self, appid, key, value, launch_options=None):
        return await self.suite.set_option(appid, key, value, launch_options)

    async def suite_boost_on(self, appid, name, launch_options, ack=False):
        return await self.suite.boost_on(appid, name, launch_options, ack)

    async def suite_boost_off(self, appid, launch_options):
        return await self.suite.boost_off(appid, launch_options)

    async def suite_remove_all(self, appid, launch_options):
        return await self.suite.remove_all(appid, launch_options)

    async def suite_fix(self, appid, fix_id, launch_options):
        return await self.suite.fix(appid, fix_id, launch_options)

    async def suite_set_menu_key(self, appid, code):
        return await self.suite.set_menu_key(appid, code)

    async def suite_setup(self):
        return await self.suite.setup()

    async def suite_setup_run(self, step):
        return await self.suite.setup_run(step)

    async def suite_measure_start(self, appid, seconds=20):
        return await self.suite.measure_start(appid, seconds)

    async def suite_measure_status(self):
        return self.suite.measure_status()

    async def suite_measure_clear(self, appid):
        return self.suite.measure_clear(appid)

    async def suite_set_toolbox_fg(self, on):
        return await self.suite.set_toolbox_allowed(bool(on))

    async def suite_updates(self, force=False):
        return await self.suite.updates(force)

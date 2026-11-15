"""main.py as Decky runs it: the hooks Decky calls around the plugin's life."""

import importlib.util
import os
import unittest

import support
from framesuite import bridge


@unittest.skipUnless(support.have_upstreams() or support.REQUIRE, "upstream plugins are not checked out")
class Hooks(unittest.TestCase):
    def setUp(self):
        self.env = support.Env()
        self.addCleanup(self.env.close)
        import sys
        sys.modules["decky"] = self.env.decky
        root = support.STAGE or support.ROOT
        if not support.STAGE:
            self.env.decky.DECKY_PLUGIN_DIR = self.env.plugin_dir
        spec = importlib.util.spec_from_file_location("frame_suite_main_hooks", os.path.join(root, "main.py"))
        main = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(main)
        self.plugin = main.Plugin()
        self.calls = []
        for sub in self.plugin.suite.subs.values():
            self.assertTrue(sub.ok, sub.error)
            for hook in ("_main", "_unload", "_uninstall"):
                setattr(sub.instance, hook, self._spy(sub.id, hook))

    def _spy(self, sub_id, hook):
        async def fn():
            self.calls.append((sub_id, hook))
        return fn

    def test_start_and_stop(self):
        support.run(self.plugin._main())
        self.assertEqual(sorted(c[0] for c in self.calls if c[1] == "_main"), ["helix", "lsfg", "optiscaler"])
        self.assertFalse(self.plugin.suite.sync_task.done())
        support.run(self.plugin._unload())
        support.run(support.asyncio.sleep(0))
        self.assertTrue(self.plugin.suite.sync_task.cancelled() or self.plugin.suite.sync_task.done())
        self.assertEqual(len([c for c in self.calls if c[1] == "_unload"]), 3)

    def test_one_failing_upstream_hook_does_not_stop_the_others(self):
        async def boom():
            raise RuntimeError("upstream bug")
        self.plugin.suite.subs["lsfg"].instance._main = boom
        support.run(self.plugin._main())
        support.run(self.plugin._unload())
        self.assertEqual(sorted(c[0] for c in self.calls if c[1] == "_main"), ["helix", "optiscaler"])

    def test_removing_the_plugin_runs_the_uninstall_hooks_and_drops_the_bridge_file(self):
        bridge.write(self.env.home, "1", "generic", {})
        support.run(self.plugin._uninstall())
        self.assertEqual(len([c for c in self.calls if c[1] == "_uninstall"]), 3)
        self.assertFalse(os.path.exists(bridge.path(self.env.home)))

    def test_an_update_from_the_panel_undoes_nothing(self):
        bridge.write(self.env.home, "1", "generic", {})
        self.assertTrue(support.run(self.plugin.suite_prepare_update())["ok"])
        support.run(self.plugin._uninstall())           # Decky calls this for updates as well
        self.assertEqual(self.calls, [])
        self.assertTrue(os.path.exists(bridge.path(self.env.home)))


if __name__ == "__main__":
    unittest.main()

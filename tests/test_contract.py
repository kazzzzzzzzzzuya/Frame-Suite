"""The upstream plugins still offer what Frame Suite relies on.

Run against every new upstream release before anything is published: a
renamed method, a changed parameter or a vanished FSR 4 runtime fails here,
on the build machine, instead of on a device.
"""

import inspect
import json
import os
import unittest

import support
from framesuite import adapters, chip, host


@unittest.skipUnless(support.have_upstreams() or support.REQUIRE, "upstream plugins are not checked out")
class Contract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = support.Env()
        cls.suite = cls.env.suite()

    @classmethod
    def tearDownClass(cls):
        cls.env.close()

    def test_all_three_load(self):
        for sub in self.suite.subs.values():
            self.assertTrue(sub.ok, "%s: %s" % (sub.id, sub.error))
            self.assertTrue(sub.version, sub.id)

    def test_methods_and_parameters(self):
        for sub_id, wanted in adapters.REQUIRED.items():
            have = host.methods(self.suite.subs[sub_id])
            for name, params in wanted.items():
                self.assertIn(name, have, "%s.%s is gone" % (sub_id, name))
                sig = list(inspect.signature(have[name]).parameters)
                self.assertEqual(sig[:len(params)], params, "%s.%s%s" % (sub_id, name, sig))

    def test_every_backend_method_is_offered_with_its_prefix(self):
        exported = self.suite.exported()
        for sub in self.suite.subs.values():
            for name in host.methods(sub):
                self.assertIn("%s__%s" % (sub.id, name), exported)
        self.assertGreater(len(exported), 50)
        self.assertFalse([n for n in exported if "___" in n or n.split("__", 1)[1].startswith("_")])

    def test_every_call_the_panels_make_has_a_backend_method(self):
        declared = os.path.join(os.path.dirname(support.STAGE or ""), "declared-calls.json")
        if not support.STAGE or not os.path.isfile(declared):
            self.skipTest("needs the built frontend (run the build)")
        with open(declared) as f:
            names = json.load(f)
        exported = set(self.suite.exported())
        import importlib.util
        spec = importlib.util.spec_from_file_location("frame_suite_main", os.path.join(support.STAGE, "main.py"))
        main = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(main)
        own = {n for n in dir(main.Plugin) if n.startswith("suite_")}
        missing = [n for n in names if n not in exported and n not in own]
        self.assertEqual(missing, [])
        self.assertGreater(len(names), 60)

    def test_helixs_own_updater_can_never_replace_this_plugin(self):
        res = support.run(self.suite.exported()["helix__check_plugin_update"](True))
        self.assertTrue(res["ok"])
        self.assertFalse(res["newer"])
        self.assertEqual(res["url"], "")

    def test_helix_keeps_its_files_in_a_folder_of_its_own(self):
        mod = self.suite.subs["helix"].module
        self.assertTrue(str(mod.SETTINGS_FILE).endswith("frame-suite/helix/settings.json"), mod.SETTINGS_FILE)
        self.assertTrue(str(mod.RUNTIME_DIR).endswith("frame-suite/helix"), mod.RUNTIME_DIR)

    def test_helix_events_arrive_under_its_prefix(self):
        mod = self.suite.subs["helix"].module
        support.run(mod.decky.emit("setup_done", True))
        self.assertEqual(self.env.events[-1], ("helix__setup_done", (True,)))

    def test_profiles_name_fsr4_runtimes_that_exist(self):
        variants = [v["id"] for v in self.suite.ad.og_variants()["variants"]]
        self.assertIn(self.suite.ad.og_variants()["default"], variants)
        for p in chip.load_profiles(self.env.plugin_dir + "/profiles").values():
            wanted = (p.get("optiscaler") or {}).get("fsr4_variant")
            if wanted:
                self.assertIn(wanted, variants, "profile %s" % p["id"])
            self.assertIn((p.get("optiscaler") or {}).get("proxy_dll"), self.suite.ad.og_valid_dlls())

    def test_launch_settings_are_what_the_upstream_writes(self):
        self.assertEqual(self.suite.ad.og_env("dxgi.dll"), {"WINEDLLOVERRIDES": "dxgi=n,b", "SteamDeck": "0"})
        inst = self.suite.subs["optiscaler"].instance
        self.assertTrue(inst._is_managed_launch_options("WINEDLLOVERRIDES=dxgi=n,b SteamDeck=0 %command%"))

    def test_presets_pass_lsfg_vks_own_validation(self):
        from lsfg_vk.config_schema import ConfigurationManager
        for p in self.suite.profiles.values():
            for preset in p["presets"].values():
                for mult in (2, 3, 4):
                    ConfigurationManager.validate_config(dict(preset["lsfg"], multiplier=mult))


if __name__ == "__main__":
    unittest.main()

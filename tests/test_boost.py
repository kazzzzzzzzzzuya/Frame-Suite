"""The per-game switch, end to end, with the real upstream backends working
on a temporary home folder and a made-up Steam library."""

import json
import os
import unittest

import support
from framesuite import bridge, launchopts

DX12 = {"bin/Game.exe": support.EXE_DX12, "bin/nvngx_dlss.dll": b"dlss", "data/pak0.bin": b"x" * 100}
PLAIN = {"Old.exe": support.EXE_DX11, "data.bin": b"y" * 50}
SMOOTH = "MANGOHUD_CONFIGFILE=/home/deck/.config/lgo-toolbox/smooth/1000.conf MANGOHUD=1 %command% -skipintro"


@unittest.skipUnless(support.have_upstreams() or support.REQUIRE, "upstream plugins are not checked out")
class Base(unittest.TestCase):
    def setUp(self):
        self.env = support.Env()
        self.addCleanup(self.env.close)
        self.dx12 = self.env.add_game("1000", "Shiny Game", "ShinyGame", DX12)
        self.plain = self.env.add_game("2000", "Old Game", "OldGame", PLAIN)
        self.suite = self.env.suite()

    def go(self, coro):
        return support.run(coro)

    def setup_step(self, step):
        self.go(self.suite.setup_run(step))
        self.go(self.suite.wizard_task)
        self.assertEqual(self.suite.wizard["phase"], "done", self.suite.wizard)

    def lsfg_profile(self, appid, name, config):
        res = self.go(self.suite.ad.lsfg_set(appid, name, config))
        self.assertTrue(res["ok"], res)

    def lsfg_ready(self):
        async def state():
            return {"available": True, "installed": True, "lossless": True, "lossless_status": ""}
        self.suite.ad.lsfg_state = state


class Planning(Base):
    def test_a_dlss_game_goes_to_optiscaler_and_asks_for_setup_first(self):
        view = self.go(self.suite.game("1000"))
        self.assertEqual(view["plan"]["route"], "optiscaler")
        self.assertIn("DLSS", view["plan"]["reason"])
        self.assertEqual([b["id"] for b in view["plan"]["blockers"]], ["setup-optiscaler"])
        res = self.go(self.suite.boost_on("1000", "Shiny Game", "", False))
        self.assertFalse(res["ok"])
        self.assertEqual(res["blocker"], "setup-optiscaler")
        self.assertEqual(support.tree(self.dx12), {k: len(v) for k, v in DX12.items()})

    def test_a_directx11_game_without_upscaler_goes_to_lsfg(self):
        view = self.go(self.suite.game("2000"))
        self.assertEqual(view["plan"]["route"], "lsfg")
        self.assertEqual([b["id"] for b in view["plan"]["blockers"]], ["setup-lsfg"])

    def test_games_added_by_hand_are_left_to_the_lsfg_page(self):
        for route in ("auto", "optiscaler"):
            self.go(self.suite.set_option("3221225472", "route", route))
            view = self.go(self.suite.game("3221225472"))
            self.assertFalse(view["steam"])
            self.assertEqual(view["plan"]["blockers"][0]["id"], "non-steam")
            self.assertFalse(self.go(self.suite.boost_on("3221225472", "Emu", "", False))["ok"])

    def test_the_choice_can_be_overridden_per_game(self):
        self.go(self.suite.set_option("1000", "route", "lsfg"))
        self.assertEqual(self.go(self.suite.game("1000"))["plan"]["route"], "lsfg")
        self.go(self.suite.set_option("1000", "route", "auto"))
        self.assertEqual(self.go(self.suite.game("1000"))["plan"]["route"], "optiscaler")

    def test_z1_extreme_defaults(self):
        self.suite.detected = "z1-extreme"
        opts = self.suite.options("1000")
        self.assertEqual(opts["variant"], "rdna34-official-411")
        self.assertEqual(opts["preset"], "balanced")
        self.assertEqual(self.suite.lsfg_config_for("1000"),
                         {"multiplier": 2, "flow_scale": 0.8, "performance_mode": True})

    def test_games_list(self):
        names = [g["name"] for g in self.go(self.suite.games())]
        self.assertEqual(sorted(names), ["Old Game", "Shiny Game"])


@unittest.skipUnless((support.have_upstreams() and support.have_binaries()) or support.REQUIRE,
                     "needs the built plugin with its binaries (run the build)")
class Lsfg(Base):
    """Uses the real lsfg-vk the plugin ships; only owning Lossless Scaling is pretended."""

    def setUp(self):
        super().setUp()
        self.setup_step("lsfg")
        self.assertTrue(self.go(self.suite.setup())["lsfg"]["installed"])
        self.lsfg_ready()
        self.conf = os.path.join(self.env.home, ".config", "lsfg-vk", "conf.toml")

    def test_on_creates_the_profile_and_off_removes_it(self):
        res = self.go(self.suite.boost_on("2000", "Old Game", SMOOTH, False))
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["route"], "lsfg")
        self.assertFalse(res["launch_changed"])           # lsfg-vk needs nothing in the launch options
        text = open(self.conf).read()
        self.assertIn('active_in = [ "2000" ]', text)
        self.assertIn("multiplier = 2", text)
        self.assertEqual(res["view"]["summary"]["active"], ["lsfg-vk 2×"])
        b = bridge.read(self.env.home)["games"]["2000"]
        self.assertEqual(b["frame_generation"], {"source": "lsfg", "multiplier": 2, "in_game": False})
        self.assertTrue(b["boost"])

        res = self.go(self.suite.boost_off("2000", SMOOTH))
        self.assertTrue(res["ok"], res)
        self.assertNotIn('"2000"', open(self.conf).read())
        self.assertNotIn("2000", bridge.read(self.env.home)["games"])

    def test_preset_and_multiplier_apply_while_on(self):
        self.go(self.suite.boost_on("2000", "Old Game", "", False))
        self.go(self.suite.set_option("2000", "preset", "quality"))
        self.go(self.suite.set_option("2000", "multiplier", 3))
        text = open(self.conf).read()
        self.assertIn("flow_scale = 1.0", text)
        self.assertIn("multiplier = 3", text)
        self.assertEqual(bridge.read(self.env.home)["games"]["2000"]["frame_generation"]["multiplier"], 3)

    def test_a_profile_the_user_made_is_kept_and_survives_off(self):
        self.lsfg_profile("2000", "Old Game", {"multiplier": 4, "flow_scale": 0.3})
        res = self.go(self.suite.boost_on("2000", "Old Game", "", False))
        self.assertEqual(res["view"]["boost"]["applied"], {"lsfg": "kept"})
        self.assertIn("multiplier = 4", open(self.conf).read())
        self.go(self.suite.boost_off("2000", ""))
        self.assertIn("multiplier = 4", open(self.conf).read())

    def test_two_limiters_are_pointed_out(self):
        os.makedirs(os.path.join(self.env.home, ".config", "lgo-toolbox", "smooth"))
        open(os.path.join(self.env.home, ".config", "lgo-toolbox", "smooth", "2000.conf"), "w").close()
        with open(os.path.join(self.env.home, ".config", "lsfg-vk", "workarounds.json"), "w") as f:
            json.dump({"apps": {"2000": {"state": {"dxvkFrameRate": 60}}}}, f)
        ids = [c["id"] for c in self.go(self.suite.game("2000"))["conflicts"]]
        self.assertIn("two-limiters", ids)

    def test_a_lost_profile_is_noticed_and_repaired(self):
        self.go(self.suite.boost_on("2000", "Old Game", "", False))
        self.go(self.suite.ad.lsfg_reset("2000"))
        view = self.go(self.suite.game("2000"))
        self.assertIn("boost-lost", [c["id"] for c in view["conflicts"]])
        res = self.go(self.suite.fix("2000", "boost-reapply", ""))
        self.assertTrue(res["ok"], res)
        self.assertIn('"2000"', open(self.conf).read())


@unittest.skipUnless((support.have_upstreams() and support.have_binaries()) or support.REQUIRE,
                     "needs the built plugin with its binaries (run the build)")
class OptiScaler(Base):
    """Uses the real OptiScaler bundle Decky-Framegen ships."""

    def setUp(self):
        super().setUp()
        if not self.env.can_unpack:
            if support.REQUIRE:
                self.fail("7z is needed to unpack OptiScaler")
            self.skipTest("no 7z on this machine")
        self.suite.detected = "z1-extreme"
        self.setup_step("optiscaler")
        self.before = support.tree(self.dx12)

    def test_setup_installs_the_bundle_with_the_chips_runtime(self):
        state = self.go(self.suite.setup())
        self.assertTrue(state["optiscaler"]["installed"])
        manifest = json.load(open(os.path.join(self.env.home, "fgmod", "install-manifest.json")))
        self.assertEqual(manifest["selected_default_variant"], "rdna34-official-411")

    def test_on_patches_and_merges_launch_options_and_off_restores_everything(self):
        res = self.go(self.suite.boost_on("1000", "Shiny Game", SMOOTH, False))
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["route"], "optiscaler")
        lo = res["launch_options"]
        self.assertTrue(launchopts.has_env(lo, {"WINEDLLOVERRIDES": "dxgi=n,b", "SteamDeck": "0"}))
        self.assertTrue(lo.startswith("MANGOHUD_CONFIGFILE="))        # the Toolbox's cap stays in front
        self.assertTrue(lo.endswith("%command% -skipintro"))
        view = res["view"]
        self.assertTrue(view["optiscaler"]["patched"])
        self.assertEqual(view["optiscaler"]["variant"], "rdna34-official-411")
        self.assertEqual(view["conflicts"], [])
        self.assertEqual(view["menu_key"], "auto")
        self.assertTrue(os.path.isfile(os.path.join(self.dx12, "bin", "dxgi.dll")))
        self.assertTrue(os.path.isfile(os.path.join(self.dx12, "bin", "amdxcffx64.dll")))   # the 4.1.1 driver override
        self.assertTrue(any("HelixSR is not downloaded" in w for w in res["warnings"]))
        b = bridge.read(self.env.home)["games"]["1000"]
        self.assertEqual(b["route"], "optiscaler")
        self.assertEqual(b["frame_generation"]["multiplier"], 1)

        self.go(self.suite.set_option("1000", "fg_in_game", True, lo))
        self.assertEqual(bridge.read(self.env.home)["games"]["1000"]["frame_generation"],
                         {"source": "optiscaler", "multiplier": 2, "in_game": True})

        res = self.go(self.suite.boost_off("1000", lo))
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["launch_options"], SMOOTH)
        self.assertEqual(support.tree(self.dx12), self.before)

    def test_off_after_other_tools_changed_the_launch_options(self):
        res = self.go(self.suite.boost_on("1000", "Shiny Game", "%command%", False))
        edited = "PROTON_LOG=1 " + res["launch_options"]
        res = self.go(self.suite.boost_off("1000", edited))
        self.assertEqual(res["launch_options"], "PROTON_LOG=1 %command%")

    def test_replaced_launch_options_are_noticed_and_repaired(self):
        self.go(self.suite.boost_on("1000", "Shiny Game", "", False))
        view = self.go(self.suite.game("1000", "gamemoderun %command%"))
        self.assertIn("launch-missing", [c["id"] for c in view["conflicts"]])
        res = self.go(self.suite.fix("1000", "launch-repair", "gamemoderun %command%"))
        self.assertEqual(res["launch_options"], "WINEDLLOVERRIDES=dxgi=n,b SteamDeck=0 gamemoderun %command%")
        self.assertEqual(res["view"]["conflicts"], [])

    def test_a_game_patched_in_decky_framegens_own_panel_is_kept(self):
        inst = self.suite.subs["optiscaler"].instance
        patched = self.go(inst.patch_game("1000", "dxgi.dll", "", "rdna23-int8"))
        self.assertEqual(patched["status"], "success")
        res = self.go(self.suite.boost_on("1000", "Shiny Game", patched["launch_options"], False))
        self.assertTrue(res["ok"], res)
        self.assertFalse(res["launch_changed"])
        self.assertEqual(res["view"]["optiscaler"]["variant"], "rdna23-int8")     # not re-patched
        res = self.go(self.suite.boost_off("1000", res["launch_options"]))
        self.assertFalse(res["launch_changed"])
        self.assertTrue(self.go(self.suite.game("1000"))["optiscaler"]["patched"])  # still theirs

    def test_two_frame_generators_are_pointed_out_and_fixed(self):
        self.setup_step("lsfg")
        res = self.go(self.suite.boost_on("1000", "Shiny Game", "", False))
        lo = res["launch_options"]
        self.lsfg_profile("1000", "Shiny Game", {"multiplier": 2})
        c = [c for c in self.go(self.suite.game("1000", lo))["conflicts"] if c["id"] == "double-fg"][0]
        self.assertEqual(c["level"], "warn")
        self.go(self.suite.set_option("1000", "fg_in_game", True, lo))
        c = [c for c in self.go(self.suite.game("1000", lo))["conflicts"] if c["id"] == "double-fg"][0]
        self.assertEqual(c["level"], "error")
        res = self.go(self.suite.fix("1000", "lsfg-reset", lo))
        self.assertEqual(res["view"]["conflicts"], [])

    def test_anti_cheat_needs_a_yes_first(self):
        os.makedirs(os.path.join(self.dx12, "EasyAntiCheat"))
        res = self.go(self.suite.boost_on("1000", "Shiny Game", "", False))
        self.assertFalse(res["ok"])
        self.assertTrue(res["need_ack"])
        self.assertFalse(os.path.exists(os.path.join(self.dx12, "bin", "dxgi.dll")))
        res = self.go(self.suite.boost_on("1000", "Shiny Game", "", True))
        self.assertTrue(res["ok"], res)

    def test_a_game_update_that_restores_the_files_is_noticed(self):
        res = self.go(self.suite.boost_on("1000", "Shiny Game", "", False))
        os.remove(os.path.join(self.dx12, "bin", "dxgi.dll"))
        view = self.go(self.suite.game("1000", res["launch_options"]))
        self.assertIn("boost-lost", [c["id"] for c in view["conflicts"]])

    def test_menu_key(self):
        self.go(self.suite.boost_on("1000", "Shiny Game", "", False))
        res = self.go(self.suite.set_menu_key("1000", "0x24"))
        self.assertTrue(res["ok"], res)
        self.assertEqual(self.go(self.suite.game("1000"))["menu_key"], "0x24")
        self.assertFalse(self.go(self.suite.set_menu_key("1000", "rm -rf"))["ok"])

    def test_remove_everything(self):
        self.setup_step("lsfg")
        res = self.go(self.suite.boost_on("1000", "Shiny Game", SMOOTH, False))
        self.lsfg_profile("1000", "Shiny Game", {"multiplier": 2})
        res = self.go(self.suite.remove_all("1000", res["launch_options"]))
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["launch_options"], SMOOTH)
        self.assertEqual(support.tree(self.dx12), self.before)
        self.assertFalse(res["view"]["boost"]["on"])
        self.assertIsNone(res["view"]["lsfg"]["config"])


if __name__ == "__main__":
    unittest.main()

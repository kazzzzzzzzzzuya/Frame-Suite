"""The per-game switch, end to end, with the real upstream backends working
on a temporary home folder and a made-up Steam library."""

import json
import os
import time
import unittest

import support
from framesuite import bridge, core, launchopts, toolbox

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
        self.assertEqual(opts["variant"], "rdna4-native")
        self.assertEqual(opts["preset"], "balanced")
        self.assertEqual(self.suite.lsfg_config_for("1000"),
                         {"multiplier": 2, "flow_scale": 0.8, "performance_mode": True})

    def test_without_helixsr_the_anti_cheat_question_goes_to_the_user(self):
        self.suite.subs["helix"].instance = None      # as if that part had failed to load
        async def bundle():
            return {"available": True, "installed": True}
        self.suite.ad.og_bundle = bundle
        self.assertEqual(self.go(self.suite.game("1000"))["plan"]["route"], "lsfg")   # files unchecked: the safe method
        self.go(self.suite.set_option("1000", "route", "optiscaler"))
        res = self.go(self.suite.boost_on("1000", "Shiny Game", "", False))
        self.assertTrue(res.get("need_ack"), res)
        self.assertEqual(support.tree(self.dx12), {k: len(v) for k, v in DX12.items()})

    def test_the_cheap_live_check_sees_a_game_start_and_end(self):
        proc = os.path.join(self.env.tmp, "proc")
        self.assertFalse(self.go(self.suite.live_state("1000"))["running"])
        d = os.path.join(proc, "4242")
        os.makedirs(d)
        with open(os.path.join(d, "environ"), "wb") as f:
            f.write(b"SteamAppId=1000\0")
        with open(os.path.join(d, "maps"), "w") as f:
            f.write("7f-80 r-xp 0 0:0 1 %s/bin/Game.exe\n" % self.dx12)
        state = self.go(self.suite.live_state("1000"))
        self.assertEqual((state["running"], state["readable"]), (True, True))
        self.assertTrue(self.go(self.suite.game("1000"))["running"])
        import shutil
        shutil.rmtree(d)
        self.assertFalse(self.go(self.suite.live_state("1000"))["running"])

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

    def test_changes_in_the_lsfg_panel_reach_the_bridge_file(self):
        calls = self.suite.exported()
        self.go(calls["lsfg__update_game_config"]("2000", "Old Game", {"multiplier": 3}))
        b = bridge.read(self.env.home)["games"]["2000"]
        self.assertEqual((b["boost"], b["route"], b["lsfg"]["multiplier"]), (False, "lsfg", 3))
        self.go(calls["lsfg__reset_game_config"]("2000"))
        self.assertNotIn("2000", bridge.read(self.env.home)["games"])

    def test_a_lost_profile_is_noticed_and_repaired(self):
        self.go(self.suite.boost_on("2000", "Old Game", "", False))
        self.go(self.suite.ad.lsfg_reset("2000"))
        view = self.go(self.suite.game("2000"))
        self.assertIn("boost-lost", [c["id"] for c in view["conflicts"]])
        res = self.go(self.suite.fix("2000", "boost-reapply", ""))
        self.assertTrue(res["ok"], res)
        self.assertIn('"2000"', open(self.conf).read())


@unittest.skipUnless(support.have_upstreams() or support.REQUIRE, "upstream plugins are not checked out")
class Mako(Base):
    """MAKO's real backend: its renderer installed into the test home, a stand-in running game."""

    @classmethod
    def setUpClass(cls):
        import shutil as _sh
        cls.sleep = _sh.which("sleep")

    def setUp(self):
        super().setUp()
        self.suite = self.env.suite(proc="/proc")      # the stand-in game is a real process
        self.setup_step("mako")
        self.games = []
        self.addCleanup(self.stop_games)

    def stop_games(self):
        for p in self.games:
            p.kill()
            p.wait()

    def start_game(self, appid, exe="OldGame"):
        import shutil as _sh
        import subprocess
        path = os.path.join(self.env.tmp, exe)
        _sh.copy(self.sleep, path)
        p = subprocess.Popen([path, "300"], env={"SteamAppId": appid, "SteamGameId": appid})
        self.games.append(p)
        time.sleep(0.3)
        return p

    def wrapper(self):
        return os.path.join(self.env.home, ".local", "bin", "mako-run")

    def test_setup_installs_the_renderer(self):
        st = self.go(self.suite.setup())
        self.assertTrue(st["mako"]["installed"])
        self.assertEqual(st["mako"]["wrapper"], self.wrapper())

    def test_mako_is_the_frame_generation_for_games_without_upscalers(self):
        view = self.go(self.suite.game("2000"))
        self.assertEqual(view["plan"]["route"], "mako")
        self.assertEqual([b["id"] for b in view["plan"]["blockers"]], ["start-game"])
        self.assertEqual(self.go(self.suite.game("1000"))["plan"]["route"], "optiscaler")   # DLSS: OptiScaler first

    def test_boost_sets_up_adaptive_frame_generation_and_off_takes_it_back(self):
        self.suite.detected = "z1-extreme"
        self.start_game("2000")
        res = self.go(self.suite.boost_on("2000", "Old Game", SMOOTH, False))
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["route"], "mako")
        lo = res["launch_options"]
        toks = launchopts.split_tokens(lo)
        self.assertEqual(toks[toks.index("%command%") - 1], self.wrapper())       # right before %command%
        self.assertTrue(lo.startswith("MANGOHUD_CONFIGFILE="))                    # the Toolbox's cap stays first
        prof = self.go(self.suite.ad.mako_game("2000"))
        self.assertEqual((prof["frame_generation_enabled"], prof["adaptive"], prof["target_fps"],
                          prof["adaptive_max_multiplier"]), (True, True, 72, 2))
        b = bridge.read(self.env.home)["games"]["2000"]
        self.assertEqual(b["route"], "mako")
        self.assertEqual(b["frame_generation"], {"source": "mako", "multiplier": 2, "in_game": False,
                                                 "adaptive": True, "target_fps": 72})
        self.assertTrue(b["mako"]["enabled"])
        self.assertIn("MAKO adaptive 72 fps, up to 2×", res["view"]["summary"]["active"])
        # The game's own choice of target, applied to MAKO's profile at once
        self.go(self.suite.set_option("2000", "mako_target", 60, lo))
        self.assertEqual(self.go(self.suite.ad.mako_game("2000"))["target_fps"], 60)
        self.assertEqual(bridge.read(self.env.home)["games"]["2000"]["frame_generation"]["target_fps"], 60)
        res = self.go(self.suite.boost_off("2000", lo))
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["launch_options"], SMOOTH)
        self.assertIsNone(self.go(self.suite.ad.mako_game("2000")))
        self.assertNotIn("2000", bridge.read(self.env.home)["games"])

    def test_a_profile_made_on_makos_own_page_gets_its_launcher_automatically(self):
        calls = self.suite.exported()
        self.start_game("2000")
        r = self.go(calls["mako__capture_game_profile"]("2000", "Old Game"))
        self.assertTrue(r["success"], r)
        plan = self.go(self.suite.mako_launch_plan())
        self.assertEqual((plan["wrapper"], plan["want"]), (self.wrapper(), ["2000"]))
        fix = self.go(self.suite.mako_launch_fix("2000", "gamemoderun %command% -dx12"))
        self.assertEqual(fix["launch_options"], "gamemoderun %s %%command%% -dx12" % self.wrapper())
        self.assertTrue(fix["changed"] and fix["ours"])
        self.suite.mako_launch_mark("2000", True)
        # Already there: nothing to do
        self.assertFalse(self.go(self.suite.mako_launch_fix("2000", fix["launch_options"]))["changed"])
        self.assertIn("2000", bridge.read(self.env.home)["games"])
        # Profile deleted on MAKO's page: the launcher Frame Suite added goes again
        self.go(calls["mako__delete_profile"](r["profile_name"]))
        fix = self.go(self.suite.mako_launch_fix("2000", fix["launch_options"]))
        self.assertEqual(fix["launch_options"], "gamemoderun %command% -dx12")
        self.assertFalse(fix["ours"])
        self.suite.mako_launch_mark("2000", False)
        self.assertNotIn("2000", bridge.read(self.env.home)["games"])

    def test_a_launcher_the_user_added_is_never_taken_out(self):
        lo = "%s %%command%%" % self.wrapper()
        fix = self.go(self.suite.mako_launch_fix("2000", lo))
        self.assertFalse(fix["changed"])
        self.assertEqual(fix["launch_options"], lo)

    def test_without_the_renderer_the_launcher_comes_out_before_a_game_could_fail(self):
        self.start_game("2000")
        self.go(self.suite.boost_on("2000", "Old Game", "", False))
        self.go(self.suite.exported()["mako__uninstall_mako"]())
        self.suite._mako_state_at = 0.0
        plan = self.go(self.suite.mako_launch_plan())
        self.assertEqual(plan["want"], [])
        fix = self.go(self.suite.mako_launch_fix("2000", "%s %%command%%" % self.wrapper()))
        self.assertEqual((fix["launch_options"], fix["changed"]), ("", True))

    def test_remove_everything_takes_mako_out_too(self):
        self.start_game("2000")
        res = self.go(self.suite.boost_on("2000", "Old Game", "", False))
        self.stop_games()                                  # files are only changed with the game closed
        self.games = []
        res = self.go(self.suite.remove_all("2000", res["launch_options"]))
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["launch_options"], "")
        self.assertIsNone(self.go(self.suite.ad.mako_game("2000")))

    @unittest.skipUnless(support.have_binaries() or support.REQUIRE, "needs lsfg-vk from the built plugin")
    def test_mako_and_lsfg_vk_on_one_game_is_pointed_out(self):
        self.setup_step("lsfg")
        self.start_game("2000")
        self.go(self.suite.boost_on("2000", "Old Game", "", False))
        self.go(self.suite.ad.lsfg_set("2000", "Old Game", {"multiplier": 2}))
        ids = [c["id"] for c in self.go(self.suite.game("2000", None))["conflicts"]]
        self.assertIn("double-fg-mako", ids)


@unittest.skipUnless((support.have_upstreams() and support.have_binaries()) or support.REQUIRE,
                     "needs the built plugin with its binaries (run the build)")
class ToolboxRequests(Base):
    """The Legion Go Toolbox's Battery playtime asking for frame generation."""

    def setUp(self):
        super().setUp()
        self.setup_step("lsfg")
        self.lsfg_ready()
        self.conf = os.path.join(self.env.home, ".config", "lsfg-vk", "conf.toml")

    def ask(self, games, updated=None):
        path = toolbox.path(self.env.home)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"version": 1, "updated": int(time.time() if updated is None else updated),
                       "games": games}, f)
        self.go(self.suite.toolbox_sync(force=True))

    def mult(self, appid):
        cfg = self.go(self.suite.ad.lsfg_config(appid))
        return None if cfg is None else int(cfg["multiplier"])

    def answer(self, appid):
        return bridge.read(self.env.home)["games"][appid]["toolbox"]

    def test_standby_then_on_then_off_then_gone(self):
        self.ask({"2000": {"standby": True, "multiplier": None}})
        self.assertEqual(self.mult("2000"), 1)                         # prepared, off
        a = self.answer("2000")
        self.assertTrue(a["standby"])
        self.assertGreater(a["since"], 0)
        self.assertIsNone(a["multiplier"])
        top = bridge.read(self.env.home)
        self.assertEqual((top["lsfg_ready"], top["toolbox_fg"]), (True, True))
        self.ask({"2000": {"standby": True, "multiplier": 2}})
        self.assertEqual(self.mult("2000"), 2)
        self.assertEqual(self.answer("2000")["multiplier"], 2)
        self.ask({"2000": {"standby": True, "multiplier": None}})
        self.assertEqual(self.mult("2000"), 1)
        self.ask({"2000": {"standby": True, "multiplier": 2}})
        os.remove(toolbox.path(self.env.home))                         # a toolbox update removes the file ...
        self.go(self.suite.toolbox_sync(force=True))
        self.assertEqual(self.mult("2000"), 1)                         # ... frame generation off, profile kept
        self.ask({"2000": {"standby": True, "multiplier": None}})      # ... and the new version writes it again
        self.assertEqual(self.mult("2000"), 1)
        self.assertGreater(self.answer("2000")["since"], 0)
        os.remove(toolbox.path(self.env.home))                         # gone for good (uninstalled)
        self.go(self.suite.toolbox_sync(force=True))
        self.suite._tb_gone_since -= core.TOOLBOX_GONE_S + 1
        self.go(self.suite.toolbox_sync(force=True))
        self.assertIsNone(self.mult("2000"))                           # Frame Suite's own profile goes
        self.assertNotIn("2000", bridge.read(self.env.home)["games"])

    def test_a_stale_request_switches_off(self):
        self.ask({"2000": {"standby": True, "multiplier": 2}})
        self.assertEqual(self.mult("2000"), 2)
        self.ask({"2000": {"standby": True, "multiplier": 2}}, updated=time.time() - 600)
        self.assertEqual(self.mult("2000"), 1)

    def test_the_users_own_profile_is_restored_not_removed(self):
        self.lsfg_profile("2000", "Old Game", {"multiplier": 1, "flow_scale": 0.3})
        self.ask({"2000": {"standby": True, "multiplier": 3}})
        self.assertEqual(self.answer("2000")["since"], 0.0)            # active from the game's start
        cfg = self.go(self.suite.ad.lsfg_config("2000"))
        self.assertEqual((cfg["multiplier"], cfg["flow_scale"]), (3, 0.3))
        self.ask({})                                                   # goal removed in the toolbox
        cfg = self.go(self.suite.ad.lsfg_config("2000"))
        self.assertEqual((cfg["multiplier"], cfg["flow_scale"]), (1, 0.3))

    def test_switched_off_in_frame_suite(self):
        self.ask({"2000": {"standby": True, "multiplier": 2}})
        self.go(self.suite.set_toolbox_allowed(False))
        self.assertIsNone(self.mult("2000"))
        a = self.answer("2000")
        self.assertFalse(a["standby"])
        self.assertIn("Switched off", a["refused"])
        self.assertFalse(bridge.read(self.env.home)["toolbox_fg"])
        self.go(self.suite.set_toolbox_allowed(True))
        self.assertEqual(self.mult("2000"), 2)

    def test_remove_everything_is_not_undone_by_the_toolbox(self):
        self.ask({"2000": {"standby": True, "multiplier": None}})
        res = self.go(self.suite.remove_all("2000", ""))
        self.assertTrue(res["ok"], res)
        self.go(self.suite.toolbox_sync(force=True))
        self.assertIsNone(self.mult("2000"))
        self.assertIn("Removed", self.answer("2000")["refused"])

    def test_the_games_own_frame_generation_wins(self):
        self.go(self.suite.set_option("2000", "fg_in_game", True))
        self.ask({"2000": {"standby": True, "multiplier": 2}})
        self.assertIsNone(self.mult("2000"))
        self.assertIn("own frame generation", self.answer("2000")["refused"])


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
        self.assertEqual(manifest["selected_default_variant"], "rdna4-native")

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
        self.assertEqual(view["optiscaler"]["variant"], "rdna4-native")
        self.assertEqual(view["conflicts"], [])
        self.assertEqual(view["menu_key"], "auto")
        self.assertTrue(os.path.isfile(os.path.join(self.dx12, "bin", "dxgi.dll")))
        self.assertTrue(os.path.isfile(os.path.join(self.dx12, "bin", "amd_fidelityfx_upscaler_dx12.dll")))
        self.assertFalse(os.path.exists(os.path.join(self.dx12, "bin", "amdxcffx64.dll")))   # no driver override
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

    def test_unknown_launch_options_raise_no_false_alarm(self):
        res = self.go(self.suite.boost_on("1000", "Shiny Game", "", False))
        self.assertEqual(self.go(self.suite.game("1000", None))["conflicts"], [])
        self.assertIn("launch-missing", [c["id"] for c in self.go(self.suite.game("1000", ""))["conflicts"]])
        self.assertEqual(self.go(self.suite.game("1000", res["launch_options"]))["conflicts"], [])

    def test_the_bridge_file_follows_the_games_real_state(self):
        calls = self.suite.exported()
        # patched in Decky-Framegen's own panel, never seen by Frame Suite's first page
        patched = self.go(calls["optiscaler__patch_game"]("1000", "dxgi.dll", "", "rdna23-int8"))
        self.assertEqual(patched["status"], "success")
        b = bridge.read(self.env.home)["games"]["1000"]
        self.assertEqual((b["boost"], b["route"], b["optiscaler"]["patched"]), (False, "optiscaler", True))
        self.go(self.suite.set_option("1000", "fg_in_game", True))
        self.assertEqual(bridge.read(self.env.home)["games"]["1000"]["frame_generation"]["multiplier"], 2)
        # a game update restores the original files behind everyone's back
        os.remove(os.path.join(self.dx12, "bin", "dxgi.dll"))
        self.go(self.suite.sync_bridge())
        self.assertNotIn("1000", bridge.read(self.env.home)["games"])
        # patched again, then removed in the upstream panel
        self.go(calls["optiscaler__patch_game"]("1000", "dxgi.dll", "", "rdna23-int8"))
        self.assertTrue(bridge.read(self.env.home)["games"]["1000"]["optiscaler"]["patched"])
        self.go(calls["optiscaler__unpatch_game"]("1000"))
        self.assertNotIn("1000", bridge.read(self.env.home)["games"])
        self.assertEqual(support.tree(self.dx12), self.before)

    def test_a_boosted_game_whose_files_were_restored_stops_counting_as_optiscaler(self):
        self.go(self.suite.boost_on("1000", "Shiny Game", "", False))
        self.go(self.suite.set_option("1000", "fg_in_game", True))
        os.remove(os.path.join(self.dx12, "bin", "dxgi.dll"))
        self.go(self.suite.sync_bridge())
        b = bridge.read(self.env.home)["games"]["1000"]
        self.assertTrue(b["boost"])                               # still switched on, and shown as lost
        self.assertFalse(b["optiscaler"]["patched"])
        self.assertEqual(b["frame_generation"]["multiplier"], 1)  # nothing in the game multiplies frames

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


@unittest.skipUnless((support.have_upstreams() and support.have_binaries()) or support.REQUIRE,
                     "needs the built plugin with its binaries (run the build)")
class MakoWithUpscaler(Base):
    """MAKO's frame generation and OptiScaler's FSR 4 in the same game."""

    start_game = Mako.start_game
    stop_games = Mako.stop_games
    wrapper = Mako.wrapper

    def setUp(self):
        import shutil as _sh
        super().setUp()
        self.sleep = _sh.which("sleep")
        self.suite = self.env.suite(proc="/proc")
        self.setup_step("mako")
        self.games = []
        self.addCleanup(self.stop_games)
        if not self.env.can_unpack:
            if support.REQUIRE:
                self.fail("7z is needed to unpack OptiScaler")
            self.skipTest("no 7z on this machine")
        self.suite.detected = "z1-extreme"
        self.setup_step("optiscaler")
        self.before = support.tree(self.dx12)
        self.go(self.suite.set_option("1000", "route", "mako"))
        self.go(self.suite.set_option("1000", "mako_upscale", True))

    def env_ok(self, lo):
        return launchopts.has_env(lo, {"WINEDLLOVERRIDES": "dxgi=n,b", "SteamDeck": "0"})

    def test_mako_first_then_the_upscaler_then_both_out(self):
        self.start_game("1000", "ShinyGame")
        res = self.go(self.suite.boost_on("1000", "Shiny Game", SMOOTH, False))
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["route"], "mako")
        lo = res["launch_options"]
        self.stop_games()
        self.games = []
        view = self.go(self.suite.game("1000", lo))
        if not view["optiscaler"]["patched"]:
            # MAKO needed the game running; the upscaler is the second step with the game closed.
            self.assertIn("mako-upscale-pending", [c["id"] for c in view["conflicts"]])
            res = self.go(self.suite.fix("1000", "mako-upscale-add", lo))
            self.assertTrue(res["ok"], res)
            lo = res["launch_options"]
            view = res["view"]
        self.assertTrue(view["optiscaler"]["patched"])
        self.assertTrue(self.env_ok(lo))
        toks = launchopts.split_tokens(lo)
        self.assertEqual(toks[toks.index("%command%") - 1], self.wrapper())       # MAKO's launcher stays
        self.assertTrue(lo.endswith("%command% -skipintro"))
        self.assertTrue(os.path.isfile(os.path.join(self.dx12, "bin", "dxgi.dll")))
        self.assertNotIn("mako-upscale-pending", [c["id"] for c in view["conflicts"]])
        self.assertNotIn("double-fg-mako-game", [c["id"] for c in view["conflicts"]])
        active = " · ".join(view["summary"]["active"])
        self.assertIn("OptiScaler", active)
        self.assertIn("MAKO adaptive", active)
        self.assertEqual(bridge.read(self.env.home)["games"]["1000"]["frame_generation"]["source"], "mako")

        # The upscaler out again: MAKO stays
        res = self.go(self.suite.fix("1000", "mako-upscale-remove", lo))
        self.assertTrue(res["ok"], res)
        lo = res["launch_options"]
        self.assertFalse(self.env_ok(lo))
        self.assertIn(self.wrapper(), lo)
        self.assertEqual(support.tree(self.dx12), self.before)
        self.assertFalse(self.go(self.suite.game("1000", lo))["options"]["mako_upscale"])

        # In again, then Boost off takes everything out
        res = self.go(self.suite.fix("1000", "mako-upscale-add", lo))
        self.assertTrue(res["ok"], res)
        lo = res["launch_options"]
        self.assertTrue(self.env_ok(lo))
        res = self.go(self.suite.boost_off("1000", lo))
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["launch_options"], SMOOTH)
        self.assertEqual(support.tree(self.dx12), self.before)
        self.assertIsNone(self.go(self.suite.ad.mako_game("1000")))

    def test_with_a_profile_already_there_both_come_in_one_step(self):
        self.start_game("1000", "ShinyGame")
        r = self.go(self.suite.exported()["mako__capture_game_profile"]("1000", "Shiny Game"))
        self.assertTrue(r["success"], r)
        self.stop_games()
        self.games = []
        res = self.go(self.suite.boost_on("1000", "Shiny Game", "", False))
        self.assertTrue(res["ok"], res)
        self.assertTrue(res["view"]["optiscaler"]["patched"])
        self.assertTrue(self.env_ok(res["launch_options"]))
        self.assertIn(self.wrapper(), res["launch_options"])
        res = self.go(self.suite.boost_off("1000", res["launch_options"]))
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["launch_options"], "")
        self.assertEqual(support.tree(self.dx12), self.before)

    def test_anti_cheat_is_asked_before_the_upscaler(self):
        os.makedirs(os.path.join(self.dx12, "EasyAntiCheat"))
        self.before = support.tree(self.dx12)
        self.start_game("1000", "ShinyGame")
        lo = self.go(self.suite.boost_on("1000", "Shiny Game", "", False))["launch_options"]
        self.stop_games()
        self.games = []
        res = self.go(self.suite.fix("1000", "mako-upscale-add", lo))
        self.assertTrue(res.get("need_ack"), res)
        self.assertEqual(support.tree(self.dx12), self.before)
        res = self.go(self.suite.fix("1000", "mako-upscale-add-ack", lo))
        self.assertTrue(res["ok"], res)
        self.assertTrue(os.path.isfile(os.path.join(self.dx12, "bin", "dxgi.dll")))

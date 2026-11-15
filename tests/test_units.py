import json
import os
import shutil
import tempfile
import unittest

import support  # noqa: F401 - sets sys.path
from framesuite import bridge, chip, core, ini, launchopts, live, toolbox

ENV = {"WINEDLLOVERRIDES": "dxgi=n,b", "SteamDeck": "0"}


class LaunchOptions(unittest.TestCase):
    CASES = [
        "",
        "%command%",
        "MANGOHUD_CONFIGFILE=/home/deck/.config/lgo-toolbox/smooth/1.conf MANGOHUD=1 %command% -dx12",
        "~/lsfg %command%",
        'WINEDLLOVERRIDES="winhttp=n,b" gamemoderun %command%',
        "SteamDeck=1 %COMMAND%",
        "PROTON_LOG=1 VKD3D_CONFIG=nodxr %command% --skip-intro \"--name=A B\"",
    ]

    def test_added_settings_are_in_effect_and_everything_else_stays(self):
        for text in self.CASES:
            new, added = launchopts.add_env(text, ENV)
            self.assertTrue(launchopts.has_env(new, ENV), new)
            for tok in launchopts.split_tokens(text):
                if not tok.startswith(("WINEDLLOVERRIDES=", "SteamDeck=")):
                    self.assertIn(tok, launchopts.split_tokens(new), (text, new))
            self.assertEqual(new.lower().count("%command%"), 1)
            self.assertEqual(launchopts.remove_env(new, added), text if text != "%command%" else "")

    def test_text_without_command_stays_an_argument(self):
        new, added = launchopts.add_env("-novid", ENV)
        self.assertEqual(new, "WINEDLLOVERRIDES=dxgi=n,b SteamDeck=0 %command% -novid")
        self.assertEqual(launchopts.remove_env(new, added), "%command% -novid")

    def test_existing_overrides_are_merged_not_replaced(self):
        new, added = launchopts.add_env("WINEDLLOVERRIDES=winhttp=n,b %command%", ENV)
        self.assertIn("WINEDLLOVERRIDES=winhttp=n,b;dxgi=n,b", new)
        self.assertEqual(launchopts.remove_env(new, added), "WINEDLLOVERRIDES=winhttp=n,b %command%")

    def test_adding_twice_changes_nothing(self):
        once, _ = launchopts.add_env("%command%", ENV)
        twice, added = launchopts.add_env(once, ENV)
        self.assertEqual(once, twice)
        self.assertEqual(added, [])

    def test_a_setting_the_user_changed_is_left_alone(self):
        new, added = launchopts.add_env("%command%", ENV)
        edited = new.replace("SteamDeck=0", "SteamDeck=1")
        self.assertIn("SteamDeck=1", launchopts.remove_env(edited, added))

    def test_settings_stay_in_front_of_wrappers(self):
        new, _ = launchopts.add_env("MANGOHUD=1 ~/lsfg %command%", ENV)
        toks = launchopts.split_tokens(new)
        self.assertLess(toks.index("SteamDeck=0"), toks.index("~/lsfg"))
        self.assertEqual(toks[0], "MANGOHUD=1")

    def test_wrapper_is_recognised(self):
        self.assertTrue(launchopts.uses_fgmod_wrapper("~/fgmod/fgmod %command%"))
        self.assertTrue(launchopts.uses_fgmod_wrapper("A=1 /home/deck/fgmod/fgmod %COMMAND%"))
        self.assertFalse(launchopts.uses_fgmod_wrapper("WINEDLLOVERRIDES=dxgi=n,b %command%"))


class Ini(unittest.TestCase):
    TEXT = "; comment\r\n[Menu]\r\n; key\r\nShortcutKey=auto\r\nScale=1.0\r\n\r\n[FrameGen]\r\nEnabled=auto\r\n"

    def test_get(self):
        self.assertEqual(ini.get(self.TEXT, "Menu", "ShortcutKey"), "auto")
        self.assertEqual(ini.get(self.TEXT, "framegen", "enabled"), "auto")
        self.assertIsNone(ini.get(self.TEXT, "Menu", "Enabled"))

    def test_set_keeps_everything_else(self):
        new = ini.set(self.TEXT, "Menu", "ShortcutKey", "0x24")
        self.assertEqual(new, self.TEXT.replace("ShortcutKey=auto", "ShortcutKey=0x24"))

    def test_set_adds_missing_key_and_section(self):
        new = ini.set(self.TEXT, "Menu", "Other", "1")
        self.assertEqual(ini.get(new, "Menu", "Other"), "1")
        self.assertEqual(ini.get(new, "FrameGen", "Enabled"), "auto")
        self.assertLess(new.index("Other=1"), new.index("[FrameGen]"))
        new = ini.set(self.TEXT, "New", "A", "b")
        self.assertEqual(ini.get(new, "New", "A"), "b")
        self.assertTrue(new.startswith(self.TEXT.rstrip("\r\n")))


class Chip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.profiles = chip.load_profiles(os.path.join(support.ROOT, "profiles"))

    def detect(self, model):
        p = os.path.join(self.tmp, "cpuinfo")
        with open(p, "w") as f:
            f.write("processor\t: 0\nvendor_id\t: AuthenticAMD\nmodel name\t: %s\n" % model)
        return chip.match(self.profiles, chip.detect(p, self.tmp))

    def test_legion_go_and_ally_get_the_z1_extreme_profile(self):
        self.assertEqual(self.detect("AMD Ryzen Z1 Extreme"), "z1-extreme")

    def test_other_chips_get_upstream_defaults(self):
        for model in ("AMD Custom APU 0405", "AMD Custom APU 0932", "AMD Ryzen Z2 Extreme", "AMD Ryzen Z1", ""):
            self.assertEqual(self.detect(model), "generic", model)

    def test_every_profile_is_complete(self):
        for p in self.profiles.values():
            self.assertIn(p["default_preset"], p["presets"])
            for preset in p["presets"].values():
                cfg = preset["lsfg"]
                self.assertIn(cfg["multiplier"], (2, 3, 4))
                self.assertTrue(0.25 <= cfg["flow_scale"] <= 1.0)   # lsfg-vk's own limits
                self.assertIsInstance(cfg["performance_mode"], bool)

    def test_a_broken_profile_file_is_skipped(self):
        d = os.path.join(self.tmp, "profiles")
        os.makedirs(d)
        with open(os.path.join(d, "bad.json"), "w") as f:
            f.write("{nope")
        self.assertEqual(list(chip.load_profiles(d)), ["generic"])


class Bridge(unittest.TestCase):
    def test_roundtrip_and_format(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        games = {"1": {"name": "G", "boost": True, "route": "lsfg",
                       "frame_generation": bridge.frame_generation("lsfg", {}, 3, False),
                       "optiscaler": {"patched": False, "fsr4_variant": None}, "lsfg": {"multiplier": 3}}}
        path = bridge.write(tmp, "1.0.0", "z1-extreme", games)
        self.assertEqual(path, os.path.join(tmp, ".config", "frame-suite", "bridge.json"))
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data["version"], 1)
        self.assertEqual(data["games"]["1"]["frame_generation"], {"source": "lsfg", "multiplier": 3, "in_game": False})
        self.assertEqual(bridge.read(tmp)["profile"], "z1-extreme")
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o644)   # a root plugin and the user can both read it

    def test_one_generator_per_game(self):
        fg = bridge.frame_generation
        self.assertEqual(fg("optiscaler", {"fg_in_game": True}, 1, True)["source"], "optiscaler")
        self.assertTrue(fg("optiscaler", {"fg_in_game": True}, 1, True)["in_game"])
        self.assertEqual(fg("optiscaler", {"fg_in_game": False}, 1, True)["multiplier"], 1)
        self.assertEqual(fg("optiscaler", {"fg_in_game": False}, 2, True)["source"], "lsfg")
        self.assertEqual(fg("lsfg", {"fg_in_game": True}, 2, True)["source"], "lsfg")
        self.assertEqual(fg(None, {}, 1, False), {"source": "none", "multiplier": 1, "in_game": False})


class ToolboxFile(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home)
        os.makedirs(os.path.dirname(toolbox.path(self.home)))

    def write(self, data):
        with open(toolbox.path(self.home), "w") as f:
            f.write(data if isinstance(data, str) else json.dumps(data))

    def test_reads_and_checks(self):
        self.write({"version": 1, "updated": 1000, "games": {
            "10": {"standby": True, "multiplier": 2},
            "11": {"standby": True, "multiplier": 9},
            "12": {"standby": True, "multiplier": True},
            "13": {"standby": False, "multiplier": 2},
            "3221225472": {"standby": True, "multiplier": 2},
            "x": {"standby": True}, "14": "yes"}})
        self.assertEqual(toolbox.read(self.home, 1010), {
            "10": {"standby": True, "multiplier": 2},
            "11": {"standby": True, "multiplier": None},
            "12": {"standby": True, "multiplier": None}})
        # stale: standby stays, frame generation off
        self.assertEqual(toolbox.read(self.home, 5000)["10"], {"standby": True, "multiplier": None})

    def test_bad_files(self):
        for data in ("{", "[]", '{"version": 2, "games": {}}', '{"version": 1, "games": []}', ""):
            self.write(data)
            self.assertEqual(toolbox.read(self.home, 0), {}, data)
        os.remove(toolbox.path(self.home))
        self.assertEqual(toolbox.read(self.home, 0), {})
        other = os.path.join(self.home, "other.json")
        with open(other, "w") as f:
            json.dump({"version": 1, "updated": 0, "games": {"1": {"standby": True}}}, f)
        os.symlink(other, toolbox.path(self.home))
        self.assertEqual(toolbox.read(self.home, 0), {})


class Live(unittest.TestCase):
    def setUp(self):
        self.proc = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.proc)

    def process(self, pid, env, maps):
        d = os.path.join(self.proc, str(pid))
        os.makedirs(d)
        with open(os.path.join(d, "environ"), "wb") as f:
            f.write(b"\0".join(env) + b"\0")
        with open(os.path.join(d, "maps"), "w") as f:
            for m in maps:
                f.write("7f00-7f01 r-xp 00000000 103:02 1234                    %s\n" % m)

    def test_not_running(self):
        self.process(10, [b"SteamAppId=999"], [])
        res = live.check("1000", proc=self.proc)
        self.assertFalse(res["running"])

    def test_loaded_parts_are_found(self):
        game = "/home/deck/.steam/steam/steamapps/common/Game/bin"
        self.process(11, [b"HOME=/home/deck", b"SteamAppId=1000"],
                     [game + "/dxgi.dll", game + "/amd_fidelityfx_upscaler_dx12.dll",
                      "/home/deck/.local/lib/liblsfg-vk-layer.so", "/usr/lib/libc.so.6"])
        self.process(12, [b"SteamAppId=10000"], [game + "/HelixSR/helixsr.dll"])   # another game
        res = live.check("1000", target_dir=game, proxy_dll="dxgi.dll", proc=self.proc)
        self.assertEqual({k: res[k] for k in ("running", "optiscaler", "fsr4", "lsfg", "helix")},
                         {"running": True, "optiscaler": True, "fsr4": True, "lsfg": True, "helix": False})

    def test_the_systems_own_dxgi_does_not_count(self):
        self.process(13, [b"SteamGameId=1000"], ["/usr/share/steam/proton/lib64/wine/dxgi.dll"])
        res = live.check("1000", target_dir="/games/Game", proxy_dll="dxgi.dll", proc=self.proc)
        self.assertTrue(res["running"])
        self.assertFalse(res["optiscaler"])


class Numbers(unittest.TestCase):
    def test_summary_counts_frames_not_windows(self):
        windows = [(60.0, 30, 55.0)] * 10 + [(30.0, 15, 20.0)] * 10
        s = core.summarize(windows)
        self.assertEqual(s["fps"], 45.0)           # 450 frames in 10 seconds
        self.assertEqual(s["low"], 20.0)
        self.assertIsNone(core.summarize(windows[:3]))

    def test_versions_compare_by_number(self):
        self.assertGreater(core.version_key("1.0.10"), core.version_key("1.0.9"))
        self.assertEqual(core.version_key("v1.2.3-pre"), [1, 2, 3])

    def test_shortcuts(self):
        self.assertFalse(core.is_shortcut("1091500"))
        self.assertTrue(core.is_shortcut("3221225472"))
        self.assertTrue(core.is_shortcut("-1073741824"))


if __name__ == "__main__":
    unittest.main()

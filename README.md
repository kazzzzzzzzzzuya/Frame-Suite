# Frame Suite

Three Decky plugins in one, plus a per-game switch that sets them up for your device's chip.

| Inside | What it does |
|---|---|
| [decky-lsfg-vk](https://github.com/xXJSONDeruloXx/decky-lsfg-vk) | Lossless Scaling frame generation (lsfg-vk 2.0) for any game |
| [Decky-Framegen](https://github.com/xXJSONDeruloXx/Decky-Framegen) | OptiScaler: FSR 4 / XeSS upscaling and FSR frame generation in DirectX 12 games |
| [HelixSR Manager](https://github.com/PeroTuncay/DeckyHelixSRManager) | HelixSR's upscaler next to FSR 4, inside OptiScaler or in place of a game's FSR 3.1 |

The three plugins run **unmodified**: their full panels are one button away, and every stable release
of any of them produces a new Frame Suite build automatically. This is an independent repackaging, not
affiliated with or supported by their authors. Please report problems here, not to them.

Not yet verified on a device by the author of this repository's code; everything that can be tested
without one is (see [Tests](#tests)).

## Install

1. Decky Loader → Settings → General → turn on **Developer mode**.
2. Settings → Developer → **Install Plugin from ZIP File** → `frame-suite.zip` from the
   [latest release](../../releases/latest).
3. Uninstall the stand-alone Decky LSFG-VK, Decky Framegen and HelixSR Manager if you have them: two
   copies would both write the same files. What they set up stays and is picked up (lsfg-vk and its
   profiles, `~/fgmod`, patched games, HelixSR's downloaded releases and settings).

Later updates arrive in the plugin itself: **Chip, versions and updates → Update**. The same page can go
back to an earlier build.

## Boost: one switch per game

Pick a game (the running one is preselected) and turn on **Boost this game**. What happens depends on
the game, because no single method fits all:

| The game | Boost sets up |
|---|---|
| DirectX 12 with DLSS, XeSS, FSR 2 or FSR 3.1 | OptiScaler with the FSR 4 runtime of your chip's profile, and HelixSR next to it if you built it |
| any other Steam game (DirectX 11, Vulkan, …) | an lsfg-vk profile (2×, from the chosen preset) |
| a game added to Steam by hand | nothing: use the LSFG-VK page's Non-Steam tab or HelixSR's Other Stores |

- **Only one frame generator per game.** lsfg-vk and a game's own frame generation are never both set
  up by the switch, and the plugin warns when both end up active.
- **Off undoes exactly what On did.** Something you had set up yourself before (a patched game, an
  lsfg-vk profile) is kept on On and left alone on Off.
- **Launch options are merged, not replaced.** OptiScaler needs `WINEDLLOVERRIDES=dxgi=n,b SteamDeck=0`;
  they are added next to whatever is already there (a frame limiter, `gamemoderun`, your own options)
  and removed again on Off.
- **Anti-cheat:** a game that ships anti-cheat is only changed after you confirm the risk. lsfg-vk does
  not change game files.
- You still choose DLSS / FSR in the game's own graphics settings; no plugin can do that for you.

Per game you can also choose the method yourself, the FSR 4 runtime, the lsfg-vk preset
(Quality / Balanced / Battery) and multiplier, and OptiScaler's menu key.

### Chip profiles

The profile is chosen from the processor name and can be overridden under **Chip, versions and updates**.

| Profile | FSR 4 runtime | lsfg-vk (Balanced) |
|---|---|---|
| Ryzen Z1 Extreme (Legion Go, ROG Ally) | 4.1.1 SDK (FFX 2.3) | 2×, flow scale 0.8, performance mode |
| Any other device | Decky-Framegen's default | the same |

The Z1 Extreme runtime is what the owner of a Legion Go reports working; the lsfg-vk values are starting
points. Use **Measure** to see what is fastest on your own device. A profile is one JSON file in
[`profiles/`](profiles): add one for your chip and open a pull request.

### Is it working?

Each game shows what is installed in it, and, while it runs, **what the game really loaded** (OptiScaler,
the FSR 4 upscaler, HelixSR, the lsfg-vk layer), read from the running process. The plugin also points out:

- two frame generators on one game
- two frame limiters (lsfg-vk's Base FPS cap and the Legion Go Toolbox's Smooth frame rate)
- launch settings another tool replaced, with a button that adds them again
- a game update that restored the original files while the switch is still on

**Measure** counts the frames on screen for 20 seconds (through gamescope, generated frames included) and
keeps the results per game, labelled with what was active, so two setups can be compared in the same scene.

**Remove everything from this game** takes OptiScaler, HelixSR and the lsfg-vk profile out of one game
and restores its files, whichever plugin put them there.

## Setup

**Setup** prepares the three parts once (nothing there touches a game):

1. lsfg-vk. You also need [Lossless Scaling](https://store.steampowered.com/app/993090/Lossless_Scaling/)
   from Steam, switched to its `lsfg-vk` branch.
2. OptiScaler, unpacked to `~/fgmod` with your chip's FSR 4 runtime as the default.
3. HelixSR (optional): its newest stable release is downloaded and built by HelixSR's own setup. Up to
   ten minutes; keep the device plugged in.

## With the Legion Go Toolbox

Frame Suite writes what it set up per game to `~/.config/frame-suite/bridge.json`
(format: [`py_modules/framesuite/bridge.py`](py_modules/framesuite/bridge.py)), for the Toolbox's Smooth
mode and Auto TDP to read: the game's method, and whether frames are multiplied, by how much and where.

- **lsfg-vk games** need nothing: the Toolbox already reads lsfg-vk's own settings.
- **OptiScaler games:** switch on **Frame generation is on in the game** when you enable frame
  generation in the game's settings. Until the Toolbox reads the bridge file, also choose 2× under its
  Smooth frame rate → Frame generation.
- Launch options from both plugins live side by side; neither removes the other's.

## How updates work

`.github/workflows/release.yml` runs every six hours. It asks GitHub for each plugin's *latest release*
(pre-releases never count). On a new one it rebuilds, runs all tests, and only then commits the new pin
(`upstreams.json`), tags and publishes a release. A build that fails publishes nothing and opens an
issue; the last good release stays.

What makes this safe to automate:

- **No upstream source is edited.** Each frontend is built from its own lockfile; the only substitution
  is that `@decky/api` resolves to a small module that prefixes its backend calls
  (`lsfg__…`, `optiscaler__…`, `helix__…`). Each backend is imported as is and sees its own `decky` module.
- **A contract test** (`tests/test_contract.py`) checks every upstream method the switch calls, with its
  parameters, against each new release.
- **Pinned commits:** a release tag that is moved after it was pinned stops the build.
- HelixSR Manager's own "update this plugin" is answered by Frame Suite, so it can never install the
  stand-alone plugin over this one.

## Build it yourself

Needs Node 22, pnpm, Python 3.11+, `jq`, `zip`, `7z`.

```sh
npm ci
node scripts/upstreams.mjs fetch     # the pinned releases, into .work/upstream
node scripts/build.mjs --test        # out/frame-suite.zip
```

## Tests

`python3 -m unittest discover -s tests` (the build runs them against the finished plugin):

- launch-option merging and exact undo, INI editing, chip detection, the bridge file, the live check
- the contract with the three upstream backends
- the switch end to end with the **real** upstream backends on a temporary home folder and a made-up
  Steam library: OptiScaler's real bundle is unpacked and a game is patched and restored byte for byte;
  the real lsfg-vk is installed and gets its profile

Each upstream's own test suite runs as part of the build too.

## Credits and licenses

All credit for the actual technology goes to the upstream projects: decky-lsfg-vk and Decky-Framegen by
Kurt Himebauch (BSD 3-Clause), HelixSR Manager by PeroTuncay (The Unlicense), and through them
[lsfg-vk](https://lsfg-vk.dev/) by PancakeTAS, [OptiScaler](https://github.com/optiscaler/OptiScaler),
Nukem9's dlssg-to-fsr3, FakeMichau's fakenvapi and [HelixSR](https://github.com/lonewolf0622/HelixSR) by
lonewolf0622. Their licenses ship inside the plugin under `upstream/<name>/`. Frame Suite's own code is
MIT; its frame-rate probe comes from the Legion Go Toolbox.

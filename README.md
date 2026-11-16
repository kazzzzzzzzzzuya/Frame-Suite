# Frame Suite

Four Decky plugins in one, plus a per-game switch that sets them up for your device's chip.

| Inside | What it does |
|---|---|
| [MAKO](https://github.com/eugeniosegala/MAKO) | Adaptive frame generation for any game with its own model (no Lossless Scaling needed), scaling, shaders, HDR |
| [decky-lsfg-vk](https://github.com/xXJSONDeruloXx/decky-lsfg-vk) | Lossless Scaling frame generation (lsfg-vk 2.0) for any game |
| [Decky-Framegen](https://github.com/xXJSONDeruloXx/Decky-Framegen) | OptiScaler: FSR 4 / XeSS upscaling and FSR frame generation in DirectX 12 games |
| [HelixSR Manager](https://github.com/PeroTuncay/DeckyHelixSRManager) | HelixSR's upscaler next to FSR 4, inside OptiScaler or in place of a game's FSR 3.1 |

The four plugins run **unmodified**: their full panels are one button away (the tiles on the first
page), and every stable release of any of them produces a new Frame Suite build automatically. This is an independent repackaging, not
affiliated with or supported by their authors. Please report problems here, not to them.

Not yet verified on a device by the author of this repository's code; everything that can be tested
without one is (see [Tests](#tests)).

## Install

1. Decky Loader → Settings → General → turn on **Developer mode**.
2. Settings → Developer → **Install Plugin from ZIP File** → `frame-suite.zip` from the
   [latest release](../../releases/latest).
3. Uninstall the stand-alone MAKO Decky, Decky LSFG-VK, Decky Framegen and HelixSR Manager if you have
   them: two copies would both write the same files. What they set up stays and is picked up (MAKO's
   renderer and profiles, lsfg-vk and its profiles, `~/fgmod`, patched games, HelixSR's downloaded
   releases and settings).
4. **Setup → MAKO → Install** once, for MAKO's renderer.

The first time Frame Suite opens it shows **Getting started**: setup, Boost and the settings worth
knowing, on one page. The button under the tiles on the first page opens it again.

Later updates arrive in the plugin itself: **Chip, versions and updates → Update**. The same page can go
back to an earlier build.

## Boost: one switch per game

Pick a game (the running one is preselected) and turn on **Boost this game**. What happens depends on
the game, because no single method fits all:

| The game | Boost sets up |
|---|---|
| DirectX 12 with DLSS, XeSS, FSR 2 or FSR 3.1 | OptiScaler with the FSR 4 runtime of your chip's profile, and HelixSR next to it if you built it |
| any other game (DirectX 11, Vulkan, added by hand, …) | **MAKO adaptive frame generation** at your chip's target (Z1 Extreme: 72 fps, at most 2× generated); lsfg-vk when MAKO's renderer is not installed |

MAKO recognises a game by its running program, so switch Boost on **while the game runs** and restart it
once. Per game you can change the frame rate on screen and the most generated frames.

### MAKO with an upscaler

Under MAKO's frame generation the game can also get an upscaler. **Settings for this game → Upscaler with
MAKO** offers the same choices as the separate plugins:

| Choice | What goes into the game | In the game, choose |
|---|---|---|
| Off | nothing: MAKO alone | – |
| FSR 4 (OptiScaler, Framegen) | OptiScaler with FSR 4, as Decky-Framegen does it; HelixSR in its menu if built and "Add HelixSR to OptiScaler" is on | DLSS (or FSR / XeSS) |
| HelixSR Scaler | HelixSR's own OptiScaler with HLX DLSS, as HelixSR Manager does it (needs a HelixSR 3.x release built in Setup) | DLSS |
| HelixSR in place of the game's FSR | HLX FSR 4 replaces the game's FSR 3.1 file, as HelixSR Manager does it | FSR |

All of them are for DirectX 12 games and change game files, so the game must be closed. MAKO needs it
running the first time, to recognise it: turn Boost on while it runs, close it, and choose **Add the
upscaler now**. With a MAKO profile already there, both go in at once. Changing the choice takes the old
upscaler out before the new one goes in; Boost off takes out everything. Keep the game's own frame
generation off: MAKO makes the extra frames.

### MAKO's launch option, automatically

MAKO starts a game through its launcher, `~/.local/bin/mako-run`, in the game's launch options. Frame Suite
puts it there for you, right before `%command%` and after anything else on the line, for **every game
MAKO has a profile for**, also profiles made on MAKO's own page. It takes out again what it added when the
profile goes, or when MAKO's renderer is removed (so no game fails to start). A launcher you added yourself
is never touched. This runs while Steam runs, also with the menu closed.

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

**Remove everything from this game** takes OptiScaler, HelixSR, the lsfg-vk profile and MAKO's profile
(and launcher) out of one game and restores its files, whichever plugin put them there.

## Setup

**Setup** prepares the four parts once (nothing there touches a game):

1. MAKO: installs its renderer (adaptive frame generation with its own model; no Lossless Scaling needed).
2. lsfg-vk. You also need [Lossless Scaling](https://store.steampowered.com/app/993090/Lossless_Scaling/)
   from Steam, switched to its `lsfg-vk` branch.
3. OptiScaler, unpacked to `~/fgmod` with your chip's FSR 4 runtime as the default.
4. HelixSR (optional): its newest stable release is downloaded and built by HelixSR's own setup. Up to
   ten minutes; keep the device plugged in.

## With the Legion Go Toolbox

Frame Suite writes what it set up per game to `~/.config/frame-suite/bridge.json`
(format: [`py_modules/framesuite/bridge.py`](py_modules/framesuite/bridge.py)), for the Toolbox's Smooth
mode and Auto TDP (2.8.0 and newer) to read: the game's method, and whether frames are multiplied, by how much and where.

- **lsfg-vk games** need nothing: the Toolbox already reads lsfg-vk's own settings.
- **MAKO games** (Toolbox 2.11.0 and newer) need nothing either. With MAKO's adaptive mode the Toolbox
  takes MAKO's target as the frame rate on screen: Smooth mode sets the screen rate for it and only backs
  MAKO up, Auto TDP finds the least power that keeps that target (MAKO makes up the rest with generated
  frames), and Battery playtime moves only the power limit.
- **OptiScaler games:** switch on **Frame generation is on in the game** when you enable frame
  generation in the game's settings. Toolbox 2.8.0 and newer follow it within seconds with Frame
  generation on *Auto*; with an older Toolbox choose 2× there by hand.
- **Battery playtime** (Toolbox 2.9.0 and newer): for a game with a battery goal the Toolbox asks
  Frame Suite for lsfg-vk through `~/.config/lgo-toolbox/framegen.json`. Frame Suite then gives the
  game an lsfg-vk profile at 1× (off), which lsfg-vk picks up from the game's next start, and switches
  it to 2× while the battery needs it, so the game makes half the frames and the screen still shows
  the same. A profile you made yourself is only switched and put back, never removed; a profile Frame
  Suite made goes again when the goal does. Requests older than three minutes count as off, so a
  stopped Toolbox cannot leave frame generation on. Never for a game whose own frame generation is
  marked on, and not again after **Remove everything from this game**. The switch **Let the Legion
  Go Toolbox use lsfg-vk** (Chip, versions and updates, on by default) turns all of it off and takes
  back what it changed.
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
- the contract with the four upstream backends, and MAKO driven for real: its renderer installed, a profile made for a stand-in running game, the launch option added and taken out again
- the switch end to end with the **real** upstream backends on a temporary home folder and a made-up
  Steam library: OptiScaler's real bundle is unpacked and a game is patched and restored byte for byte;
  the real lsfg-vk is installed and gets its profile

Each upstream's own test suite runs as part of the build too.

## The look

Blue and white, in the style of MAKO's panel: the plugins and pages as a grid of tiles on the first page,
section titles over a blue line, notes in boxes. **R1** hides and shows the explanations on Frame Suite's
own pages (on the plugins' pages R1 stays theirs). **B** goes back to the first page.

## Credits and licenses

All credit for the actual technology goes to the upstream projects: [MAKO](https://github.com/eugeniosegala/MAKO)
by Eugenio Segala (GPL-3.0-or-later), decky-lsfg-vk and Decky-Framegen by
Kurt Himebauch (BSD 3-Clause), HelixSR Manager by PeroTuncay (The Unlicense), and through them
[lsfg-vk](https://lsfg-vk.dev/) by PancakeTAS, [OptiScaler](https://github.com/optiscaler/OptiScaler),
Nukem9's dlssg-to-fsr3, FakeMichau's fakenvapi and [HelixSR](https://github.com/lonewolf0622/HelixSR) by
lonewolf0622. Their licenses ship inside the plugin under `upstream/<name>/`. Frame Suite's own code is
MIT; its frame-rate probe comes from the Legion Go Toolbox. Because it bundles MAKO, the plugin zip as a
whole is distributed under the GPL-3.0-or-later; the complete source to build it is this repository plus
the upstream releases pinned in `upstreams.json`.

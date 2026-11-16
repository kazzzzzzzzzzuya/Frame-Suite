import { ButtonItem, DropdownItem, PanelSection, PanelSectionRow, ProgressBarWithInfo, ToggleField } from "@decky/ui";
import { useQuickAccessVisible } from "@decky/api";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  applyFix, boostOff, boostOn, Change, GameView, getGame, getGames, getLive, Info, measureClear, measureStart,
  measureStatus, MeasureStatus, removeAll, setMenuKey, setOption,
} from "../backend";
import { nav, usePanelShown } from "../nav";
import { launchOptionsExclusive, readLaunchOptions, runningGame, writeLaunchOptions } from "../steam";
import { FaClone, FaDna, FaExpandArrowsAlt, FaForward, FaMicrochip, FaTools } from "react-icons/fa";
import { confirm, Header, InfoBox, Tile, Tiles, toast, when } from "../ui";

const LAST_KEY = "frame-suite:last-game";
const ROUTE_NAME: Record<string, string> = {
  optiscaler: "OptiScaler (FSR 4 in the game)",
  lsfg: "lsfg-vk frame generation",
  mako: "MAKO adaptive frame generation",
};
const ROUTE_SHORT: Record<string, string> = { optiscaler: "OptiScaler", lsfg: "lsfg-vk", mako: "MAKO" };

interface Game { appid: string; name: string; boost?: boolean }

async function launchOptions(appid: string): Promise<string | null> {
  try {
    return await readLaunchOptions(appid);
  } catch {
    return null;
  }
}

const UPSCALER_HELP: Record<string, string> = {
  off: "MAKO's frame generation only; the game renders at its own resolution.",
  optiscaler:
    "OptiScaler's FSR 4 in the game (as Decky-Framegen does it), HelixSR in its menu if built. DirectX 12 games with DLSS, FSR or XeSS.",
  scaler: "HelixSR Scaler (HelixSR's own OptiScaler with HLX DLSS), as HelixSR Manager does it. Needs a HelixSR 3.x release built in Setup.",
  direct: "HelixSR takes the place of the game's own FSR 3.1 file, as HelixSR Manager does it. Games with FSR 3.1 on DirectX 12.",
};

export function Home({ info }: { info: Info }) {
  const [games, setGames] = useState<Game[]>([]);
  const [appid, setAppid] = useState<string | null>(null);
  const [view, setView] = useState<GameView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [measure, setMeasure] = useState<MeasureStatus>({ state: "idle" });
  const current = useRef<string | null>(null);
  // Polled every 2 seconds below: the page stays loaded while the menu is closed.
  const seenRunning = useRef<string | null>(null);
  const [runningId, setRunningId] = useState<string | null>(null);
  const busyRef = useRef(false);
  busyRef.current = busy;

  const profile = info.profiles.find((p) => p.id === info.profile);

  const refresh = useCallback(async (id: string, name?: string) => {
    const lo = await launchOptions(id);
    try {
      const v = await getGame(id, lo, name ?? null);
      if (current.current === id) {
        setView(v);
        setError(null);
      }
    } catch (e) {
      if (current.current === id) setError(`The game's state could not be read: ${e}`);
    }
  }, []);

  useEffect(() => {
    (async () => {
      const list = await getGames().catch(() => [] as Game[]);
      const running = runningGame();
      if (running && !list.some((g) => g.appid === running.appid)) list.unshift(running);
      setGames(list);
      let last: string | null = null;
      try {
        last = window.localStorage.getItem(LAST_KEY);
      } catch {
        /* no storage */
      }
      const first = running?.appid ?? (last && list.some((g) => g.appid === last) ? last : list[0]?.appid) ?? null;
      seenRunning.current = running?.appid ?? null;
      setRunningId(running?.appid ?? null);
      setAppid(first);
    })();
  }, []);

  // The page stays loaded while the menu is closed: look for the running game every 2 seconds,
  // as Steam's own panels do. A game that starts is added and selected; one that ends is shown as ended.
  useEffect(() => {
    const poll = () => {
      const r = runningGame();
      const id = r?.appid ?? null;
      if (id === seenRunning.current) return;
      seenRunning.current = id;
      setRunningId(id);
      if (r) setGames((list) => (list.some((g) => g.appid === r.appid) ? list : [r, ...list]));
      if (r && !busyRef.current && current.current !== r.appid) setAppid(r.appid);
      else if (current.current) void refresh(current.current);   // started or ended: show it
    };
    const timer = setInterval(poll, 2000);
    return () => clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    current.current = appid;
    setView(null);
    if (!appid) return;
    try {
      window.localStorage.setItem(LAST_KEY, appid);
    } catch {
      /* no storage */
    }
    refresh(appid, games.find((g) => g.appid === appid)?.name);
  }, [appid]);

  // A change to a game: the backend does the files, Steam's launch options are set here.
  // One at a time with MAKO's launcher watcher: both read, change and write the launch options.
  const change = (
    title: string,
    call: (lo: string) => Promise<Change>,
    undoOnLaunchFailure = false,
    acked?: (lo: string) => Promise<Change>,
  ) => launchOptionsExclusive(() => changeNow(title, call, undoOnLaunchFailure, acked));
  const changeNow = async (
    title: string,
    call: (lo: string) => Promise<Change>,
    undoOnLaunchFailure = false,
    // Called again after the user accepts the anti-cheat question (Boost by default).
    acked?: (lo: string) => Promise<Change>,
  ) => {
    if (!appid || busy) return;
    setBusy(true);
    try {
      const read = await launchOptions(appid);
      // Only OptiScaler needs the launch options; lsfg-vk works without them.
      const needs = (r?: string | null) => r === "optiscaler" || r === "mako";
      const needed = title !== "Boost" || needs(view?.boost.route) || (!view?.boost.on && needs(view?.plan.route));
      if (read === null && needed) {
        toast(title, "Steam did not hand out this game's launch options, so nothing was changed. Try again in a moment.");
        return;
      }
      const lo = read ?? "";
      let res = await call(lo);
      if (!res.ok && res.need_ack) {
        const ok = await confirm(
          "This game has anti-cheat",
          `${res.anticheat?.join(", ")} was found in this game. Changed game files can get your account banned in online play. Only continue for offline play, or if you know this game allows it.`,
          "I understand the risk",
        );
        if (!ok) return;
        res = acked ? await acked(lo) : await boostOn(appid, view?.name ?? "", lo, true);
      }
      if (!res.ok) {
        toast(title, res.error ?? "It did not work.");
        if (res.blocker?.startsWith("setup-")) nav.go("setup");
        return;
      }
      if (res.launch_changed && res.launch_options !== undefined) {
        try {
          await writeLaunchOptions(appid, res.launch_options);
        } catch (e) {
          if (undoOnLaunchFailure) await boostOff(appid, lo).catch(() => undefined);
          toast(title, `${e instanceof Error ? e.message : e}. ${undoOnLaunchFailure ? "The change was undone." : "Check the game's launch options in its Properties."}`);
          await refresh(appid);
          return;
        }
      }
      if (res.view) setView(res.view);
      const lines = [...(res.done ?? []), ...(res.warnings ?? []).map((w) => `Note: ${w}`)];
      if (lines.length) toast(title, lines.join("\n"));
    } catch (e) {
      toast(title, `Unexpected error: ${e}`);
    } finally {
      setBusy(false);
    }
  };

  const option = async (key: string, value: unknown) => {
    if (!appid || busy) return;
    const res = await setOption(appid, key, value, await launchOptions(appid));
    if (res.view) setView(res.view);
    if (!res.ok) toast("Settings", res.error ?? "Not saved.");
    else if (res.warnings?.length) toast("Settings", res.warnings.join("\n"));
  };

  // The panel stays loaded while the menu is closed: look again whenever it is opened.
  // Decky's answer, or the panel's own (a QuickTab tab: Decky does not know it).
  const deckyVisible = useQuickAccessVisible();
  const panelShown = usePanelShown();
  const visible = deckyVisible || panelShown;
  useEffect(() => {
    if (visible && appid && !busy) refresh(appid);
  }, [visible]);

  // While the menu is open: a game takes a few seconds after Steam starts it before it runs, and
  // what it loads can change. A cheap check every 3 seconds; the full picture when it changes.
  const viewRef = useRef<GameView | null>(null);
  viewRef.current = view;
  useEffect(() => {
    if (!visible) return;
    const timer = setInterval(async () => {
      const id = current.current;
      const v = viewRef.current;
      if (!id || !v || v.appid !== id || busyRef.current) return;
      const l = await getLive(id).catch(() => null);
      if (!l || current.current !== id) return;
      const keys: (keyof typeof l)[] = ["running", "readable", "optiscaler", "fsr4", "helix", "lsfg", "mako"];
      if (keys.some((k) => l[k] !== v.live[k])) void refresh(id);
    }, 3000);
    return () => clearInterval(timer);
  }, [visible, refresh]);

  // measuring
  useEffect(() => {
    if (measure.state !== "running") return;
    const t = setInterval(async () => {
      const s = await measureStatus().catch(() => null);
      if (!s) return;
      setMeasure(s);
      if (s.state !== "running" && appid) {
        if (s.state === "failed") toast("Measure", s.error ?? "No result.");
        refresh(appid);
      }
    }, 1000);
    return () => clearInterval(t);
  }, [measure.state, appid]);

  const gameOptions = games.map((g) => ({
    data: g.appid,
    label: `${g.appid === runningId ? "▶ " : ""}${g.name || `App ${g.appid}`}${g.boost ? "  ✓" : ""}`,
  }));
  const blockers = view?.plan.blockers ?? [];
  const on = !!view?.boost.on;
  const route = on ? view?.boost.route ?? view?.plan.route : view?.plan.route;
  // Controls are not disabled while a change runs: disabling the focused one makes Steam jump to the
  // top of the panel. The handlers ignore input meanwhile.
  const locked = on;
  const sub = (id: string) => info.subs.find((s) => s.id === id);
  const mk = view?.mako.profile ?? null;
  const preset = profile?.presets.find((p) => p.id === view?.options.preset);
  const tiles: Tile[] = [
    { id: "mako", icon: <FaForward />, label: "MAKO", onClick: () => nav.go("mako"), disabled: !sub("mako")?.ok },
    { id: "lsfg", icon: <FaClone />, label: "LSFG-VK", onClick: () => nav.go("lsfg"), disabled: !sub("lsfg")?.ok },
    { id: "optiscaler", icon: <FaExpandArrowsAlt />, label: "Framegen", onClick: () => nav.go("optiscaler"), disabled: !sub("optiscaler")?.ok },
    { id: "helix", icon: <FaDna />, label: "HelixSR", onClick: () => nav.go("helix"), disabled: !sub("helix")?.ok },
    { id: "setup", icon: <FaTools />, label: "Setup", onClick: () => nav.go("setup") },
    { id: "versions", icon: <FaMicrochip />, label: "Chip & versions", onClick: () => nav.go("versions") },
  ];

  return (
    <>
      <PanelSection>
        <PanelSectionRow>
          <DropdownItem
            label="Game"
            rgOptions={gameOptions}
            selectedOption={appid}
            strDefaultLabel={games.length ? "Choose a game" : "No installed games found"}
            onChange={(o) => !busy && setAppid(String(o.data))}
          />
        </PanelSectionRow>
        {error && <InfoBox tone="error">{error}</InfoBox>}

        {view && (
          <div className="fs-card">
            <PanelSectionRow>
              <ToggleField
                label={`Boost ${view.name}`}
                description={`${profile?.label ?? info.profile} → ${ROUTE_NAME[route ?? "lsfg"]}`}
                checked={on}
                disabled={!on && blockers.length > 0}
                onChange={(v) =>
                  v
                    ? change("Boost", (lo) => boostOn(view.appid, view.name, lo, false), true)
                    : change("Boost", (lo) => boostOff(view.appid, lo))
                }
              />
            </PanelSectionRow>
            {!on && <InfoBox>{view.plan.reason}</InfoBox>}
            {!on && blockers.map((b) => (
              <InfoBox key={b.id} tone="warn">{b.text}</InfoBox>
            ))}
            {!on && blockers.some((b) => b.id.startsWith("setup-")) && (
              <PanelSectionRow>
                <ButtonItem layout="below" onClick={() => nav.go("setup")}>Open Setup</ButtonItem>
              </PanelSectionRow>
            )}
            <InfoBox tone={view.summary.active.length ? "good" : "info"}>
              {view.summary.active.length ? `In this game: ${view.summary.active.join(" · ")}` : "Nothing from the four plugins is in this game."}
              {"\n"}
              {view.summary.live}
            </InfoBox>
          </div>
        )}
      </PanelSection>

      <PanelSection>
        <Tiles tiles={tiles} />
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => nav.go("guide")}>Getting started</ButtonItem>
        </PanelSectionRow>
      </PanelSection>

      {view && (view.toolbox || view.conflicts.length > 0 || (on && (route === "optiscaler" || route === "mako"))) && (
        <PanelSection>
          {view.toolbox && (
            <InfoBox tone={view.toolbox.refused ? "warn" : "info"}>
              {view.toolbox.refused
                ? `Legion Go Toolbox battery goal: frame generation not available – ${view.toolbox.refused}`
                : view.toolbox.applied
                  ? `Legion Go Toolbox battery goal: lsfg-vk ${view.toolbox.applied}× is on to save battery.`
                  : `Legion Go Toolbox battery goal: lsfg-vk is ready for this game${view.toolbox.created ? " (off until the battery needs it)" : ""}.`}
            </InfoBox>
          )}
          {on && route === "optiscaler" && (
            <InfoBox>
              In the game's graphics settings choose DLSS (or FSR / XeSS if it has no DLSS). OptiScaler's own menu
              opens with the key shown under Settings below: bind that key to a back button in the game's controller
              layout.
            </InfoBox>
          )}
          {on && route === "mako" && !!view.boost.applied.upscaler && (
            <InfoBox>
              {`Upscaler with MAKO: in the game's graphics settings choose ${
                view.boost.applied.upscaler === "direct" ? "FSR" :
                  view.boost.applied.upscaler === "scaler" ? "DLSS" : "DLSS (or FSR / XeSS if it has no DLSS)"
              } as the upscaler, and keep the game's own frame generation off: MAKO makes the extra frames.`}
            </InfoBox>
          )}
          {on && route === "mako" && (
            <InfoBox>
              MAKO starts with the game's next start (its launcher is in the launch options now). Every other setting
              (scaling, shaders, HDR, fixed frames) is on the MAKO page.
            </InfoBox>
          )}
          {view.conflicts.map((c) => (
            <div key={c.id}>
              <InfoBox tone={c.level === "error" ? "error" : "warn"}>{c.text}</InfoBox>
              {c.fix && (
                <PanelSectionRow>
                  <ButtonItem
                    layout="below"
                    onClick={() =>
                      change("Fix", (lo) => applyFix(view.appid, c.fix!, lo), false,
                        c.fix === "mako-upscale-add" ? (lo) => applyFix(view.appid, "mako-upscale-add-ack", lo) : undefined)
                    }
                  >
                    {c.fix_label ?? "Fix"}
                  </ButtonItem>
                </PanelSectionRow>
              )}
            </div>
          ))}
        </PanelSection>
      )}

      {view && (
        <PanelSection>
          <Header>Settings for this game</Header>
          <PanelSectionRow>
            <DropdownItem
              label="Method"
              description={locked && on ? "Switch Boost off to change this." : undefined}
              disabled={locked}
              rgOptions={[
                { data: "auto", label: `Automatic (${ROUTE_SHORT[view.plan.route]})` },
                { data: "mako", label: "MAKO: adaptive frame generation" },
                { data: "optiscaler", label: "OptiScaler: FSR 4 / HelixSR in the game" },
                { data: "lsfg", label: "lsfg-vk: frame generation for any game" },
              ]}
              selectedOption={view.options.route}
              onChange={(o) => option("route", o.data)}
            />
          </PanelSectionRow>
          {route === "mako" ? (
            <>
              <PanelSectionRow>
                <DropdownItem
                  label="Frame rate on screen"
                  description="MAKO generates just as many frames as needed to hold this. Pick one the screen divides evenly (72 or 144 on the Legion Go, 60 at 60 Hz)."
                  rgOptions={[
                    { data: 0, label: `From the preset (${preset?.mako?.target_fps ?? 60} fps)` },
                    ...[30, 36, 40, 45, 48, 60, 72, 90, 120, 144].map((f) => ({ data: f, label: `${f} fps` })),
                  ]}
                  selectedOption={view.options.mako_target ?? 0}
                  onChange={(o) => option("mako_target", o.data || null)}
                />
              </PanelSectionRow>
              <PanelSectionRow>
                <DropdownItem
                  label="Most generated frames"
                  description="2× keeps at least half the frames real: the least delay and fewest artifacts. 3× and 4× reach the target from fewer real frames."
                  rgOptions={[
                    { data: 0, label: `From the preset (${preset?.mako?.max_multiplier ?? 2}×)` },
                    { data: 2, label: "2×" },
                    { data: 3, label: "3×" },
                    { data: 4, label: "4×" },
                  ]}
                  selectedOption={view.options.mako_max ?? 0}
                  onChange={(o) => option("mako_max", o.data || null)}
                />
              </PanelSectionRow>
              <PanelSectionRow>
                <DropdownItem
                  label="Preset"
                  description="Battery also turns on MAKO's Ultra Performance (lighter, slightly softer)."
                  rgOptions={(profile?.presets ?? []).map((p) => ({ data: p.id, label: p.label }))}
                  selectedOption={view.options.preset}
                  onChange={(o) => option("preset", o.data)}
                />
              </PanelSectionRow>
              <PanelSectionRow>
                <DropdownItem
                  label="Upscaler with MAKO"
                  description={
                    UPSCALER_HELP[view.options.mako_upscaler] +
                    (view.options.mako_upscaler === "off" ? "" : " Changes the game's files: the game must be closed.")
                  }
                  rgOptions={[
                    { data: "off", label: "Off: MAKO alone" },
                    { data: "optiscaler", label: "FSR 4 (OptiScaler, Framegen)" },
                    { data: "scaler", label: "HelixSR Scaler" },
                    { data: "direct", label: "HelixSR in place of the game's FSR" },
                  ]}
                  selectedOption={view.options.mako_upscaler}
                  onChange={(o) => {
                    const mode = o.data as string;
                    if (!on) return void option("mako_upscaler", mode);
                    void change("Upscaler", (lo) => applyFix(view.appid, `mako-upscaler:${mode}`, lo), false,
                      (lo) => applyFix(view.appid, `mako-upscaler-ack:${mode}`, lo));
                  }}
                />
              </PanelSectionRow>
              {view.options.mako_upscaler === "optiscaler" && (
                <PanelSectionRow>
                  <ToggleField
                    label="Add HelixSR to OptiScaler"
                    description={
                      view.helix.built
                        ? "HelixSR's upscaler next to FSR 4 in OptiScaler's menu. Applies the next time the upscaler is put in."
                        : "HelixSR is not built yet (Setup). Until then only FSR 4 is added."
                    }
                    checked={view.options.helix}
                    onChange={(v) => option("helix", v)}
                  />
                </PanelSectionRow>
              )}
              {mk && (
                <InfoBox tone="info">
                  {`MAKO's profile "${mk.profile}": ${
                    !mk.frame_generation_enabled ? "frame generation off" :
                      mk.adaptive ? `adaptive, ${mk.target_fps} fps on screen, up to ${mk.adaptive_max_multiplier}×` : `fixed ${mk.multiplier}×`
                  }.${on && view.boost.applied.mako_created === false ? " It was there before, so it was kept: change it on the MAKO page." : ""}`}
                </InfoBox>
              )}
            </>
          ) : route === "lsfg" ? (
            <>
              <PanelSectionRow>
                <DropdownItem
                  label="Preset"
                  description="Quality tracks motion more finely; Battery costs the least."
                  rgOptions={(profile?.presets ?? []).map((p) => ({ data: p.id, label: p.label }))}
                  selectedOption={view.options.preset}
                  onChange={(o) => option("preset", o.data)}
                />
              </PanelSectionRow>
              <PanelSectionRow>
                <DropdownItem
                  label="Frames"
                  rgOptions={[
                    { data: 0, label: "From the preset (2×)" },
                    { data: 2, label: "2×" },
                    { data: 3, label: "3×" },
                    { data: 4, label: "4×" },
                  ]}
                  selectedOption={view.options.multiplier ?? 0}
                  onChange={(o) => option("multiplier", o.data || null)}
                />
              </PanelSectionRow>
              {on && view.boost.applied.lsfg === "kept" && (
                <InfoBox tone="info">This game already had an lsfg-vk profile, so it was kept. Change it on the LSFG-VK page.</InfoBox>
              )}
            </>
          ) : (
            <>
              <PanelSectionRow>
                <DropdownItem
                  label="FSR 4 runtime"
                  description={locked && on ? "Switch Boost off to change this." : "Turn on OptiScaler's FSR 4 watermark once to confirm it runs."}
                  disabled={locked}
                  rgOptions={info.variants.variants.map((v) => ({ data: v.id, label: v.label }))}
                  selectedOption={view.options.variant}
                  onChange={(o) => option("variant", o.data)}
                />
              </PanelSectionRow>
              <PanelSectionRow>
                <ToggleField
                  label="Add HelixSR"
                  description={
                    view.helix.built
                      ? "Puts HelixSR's upscaler next to FSR 4 in OptiScaler's menu."
                      : "HelixSR is not built yet (Setup). Until then only FSR 4 is added."
                  }
                  checked={view.options.helix}
                  disabled={locked}
                  onChange={(v) => option("helix", v)}
                />
              </PanelSectionRow>
              <PanelSectionRow>
                <ToggleField
                  label="Frame generation is on in the game"
                  description="Tell the plugin when you switch on frame generation in the game's own settings: the Legion Go Toolbox reads this to aim at the doubled frame rate."
                  checked={view.options.fg_in_game}
                  onChange={(v) => option("fg_in_game", v)}
                />
              </PanelSectionRow>
              {view.menu_key !== null && (
                <PanelSectionRow>
                  <DropdownItem
                    label="OptiScaler menu key"
                    description="Handhelds have none of these keys: bind the chosen one to a back button in the game's controller layout."
                    disabled={view.running}
                    rgOptions={[
                      ...info.menu_keys.map((k) => ({ data: k.code, label: k.label })),
                      ...(info.menu_keys.some((k) => k.code === view.menu_key) ? [] : [{ data: view.menu_key, label: `Key ${view.menu_key}` }]),
                    ]}
                    selectedOption={view.menu_key}
                    onChange={async (o) => {
                      const r = await setMenuKey(view.appid, String(o.data));
                      if (!r.ok) toast("Menu key", r.error ?? "Not changed.");
                      refresh(view.appid);
                    }}
                  />
                </PanelSectionRow>
              )}
            </>
          )}
        </PanelSection>
      )}

      {view && (
        <PanelSection>
          <Header>Measure</Header>
          {measure.state === "running" && measure.appid === view.appid ? (
            <PanelSectionRow>
              <ProgressBarWithInfo nProgress={(measure.progress ?? 0) * 100} sOperationText={measure.note || "Measuring the frame rate…"} />
            </PanelSectionRow>
          ) : (
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                disabled={!view.running || measure.state === "running"}
                description={view.running ? "Stand still in a demanding scene. Takes 20 seconds." : "Start the game to measure it."}
                onClick={async () => {
                  const r = await measureStart(view.appid, 20);
                  if (r.ok) setMeasure({ state: "running", appid: view.appid, progress: 0 });
                  else toast("Measure", r.error ?? "Could not start.");
                }}
              >
                Measure the frame rate now
              </ButtonItem>
            </PanelSectionRow>
          )}
          {view.measure.map((m) => (
            <InfoBox key={m.time} tone="info">
              <span style={{ color: "#fff", fontWeight: 700 }}>{m.fps} fps</span>
              {m.low ? ` · slowest frames ${m.low} fps` : ""}
              {`\n${m.label}\n${when(m.time)}`}
            </InfoBox>
          ))}
          {view.measure.length > 0 && (
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={async () => { await measureClear(view.appid); refresh(view.appid); }}>
                Clear results
              </ButtonItem>
            </PanelSectionRow>
          )}
          {view.measure.length === 0 && (
            <InfoBox>Measure once with each setup (same scene) to see which is fastest on this device. The number counts frames on screen, generated ones included.</InfoBox>
          )}
        </PanelSection>
      )}

      {view && (
        <PanelSection>
          <Header>Clean up</Header>
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              description="Removes OptiScaler, HelixSR, the lsfg-vk profile and MAKO's profile from this game and restores its original files."
              onClick={async () => {
                if (await confirm("Remove everything from this game?", `OptiScaler, HelixSR, the lsfg-vk profile and MAKO's profile are taken out of ${view.name}, whichever plugin put them there. The game must be closed.`, "Remove"))
                  change("Clean up", (lo) => removeAll(view.appid, lo));
              }}
            >
              Remove everything from this game
            </ButtonItem>
          </PanelSectionRow>
        </PanelSection>
      )}
    </>
  );
}

import { callable } from "@decky/api";

export interface SubInfo { id: string; title: string; version: string; repo: string; ok: boolean; error: string | null }
export interface ProfileInfo {
  id: string; label: string; source: string; default_preset: string;
  presets: { id: string; label: string; mako?: { target_fps: number; max_multiplier: number; ultra_performance: boolean } | null }[];
}
export interface Info {
  version: string; repo: string; built: string | null;
  chip: { cpu: string; vendor: string; product: string; family: string };
  detected: string; profile: string; profile_chosen: string | null;
  profiles: ProfileInfo[]; subs: SubInfo[];
  variants: { default: string | null; variants: { id: string; label: string }[] };
  menu_keys: { code: string; label: string }[];
  bridge: string;
  /** The Legion Go Toolbox may switch lsfg-vk for its battery goals. */
  toolbox_fg: boolean;
}
export interface ToolboxRecord {
  created: boolean; since: number | null; applied: number | null; refused: string | null; blocked?: boolean;
}
export interface Conflict { id: string; level: "warn" | "error"; text: string; fix?: string; fix_label?: string }
export interface Measurement { fps: number; low: number | null; spread: number; label: string; time: number; seconds: number }
export interface GameOptions {
  preset: string; route: "auto" | "optiscaler" | "lsfg" | "mako"; variant: string | null; helix: boolean;
  fg_in_game: boolean; multiplier: number | null; mako_target: number | null; mako_max: number | null;
}
export interface MakoProfile {
  profile: string; frame_generation_enabled: boolean | null; adaptive: boolean | null; target_fps: number | null;
  adaptive_max_multiplier: number | null; multiplier: number | null; ultra_performance: boolean | null;
  disable_mako: boolean | null;
}
export interface GameView {
  appid: string; name: string; steam: boolean; busy: boolean; running: boolean; acked: boolean;
  live: LiveState;
  boost: { on: boolean; route: string | null; time: number | null; applied: Record<string, unknown> };
  options: GameOptions;
  plan: { route: "optiscaler" | "lsfg" | "mako"; reason: string; blockers: { id: string; text: string }[] };
  optiscaler: { available: boolean; found: boolean; patched: boolean; variant?: string | null; variant_label?: string | null };
  helix: { available: boolean; ok: boolean; built: boolean; active: string | null; inputs: string[] };
  lsfg: { available: boolean; installed: boolean; lossless: boolean; config: Record<string, unknown> | null; base_cap: number };
  anticheat: string[];
  menu_key: string | null;
  conflicts: Conflict[];
  summary: { active: string[]; live: string };
  measure: Measurement[];
  toolbox: ToolboxRecord | null;
  mako: { available: boolean; installed: boolean; wrapper: string | null; profile: MakoProfile | null };
}
export interface Change {
  ok: boolean; error?: string; blocker?: string; need_ack?: boolean; anticheat?: string[];
  launch_options?: string; launch_changed?: boolean; done?: string[]; warnings?: string[]; view?: GameView;
}
export interface SetupState {
  lsfg: { available: boolean; installed: boolean; lossless: boolean };
  optiscaler: { available: boolean; installed: boolean };
  mako: { available: boolean; installed: boolean; wrapper: string | null; version?: string | null };
  helix: {
    available: boolean; downloaded: boolean; built: boolean; active?: string | null; setup_state?: string | null;
    download?: { active?: boolean; bytes?: number; total?: number; phase?: string };
  };
  wizard: { step: string | null; phase: string; error: string | null; tag: string | null };
  variant: string | null;
}
export interface Release { version: string; url: string; sha256: string; published: string | null; notes: string }
export interface Updates { ok: boolean; error?: string; current: string; latest?: string; newer?: boolean; releases: Release[] }
export interface MeasureStatus {
  state: "idle" | "running" | "done" | "failed"; appid?: string; progress?: number; note?: string; error?: string;
  result?: Measurement;
}

export const getInfo = callable<[], Info>("suite_info");
export const setProfile = callable<[id: string | null], Info>("suite_set_profile");
export const getGames = callable<[], { appid: string; name: string; boost?: boolean }[]>("suite_games");
/** launch: the game's launch options, or null when Steam did not hand them out. */
export const getGame = callable<[appid: string, launch: string | null, name: string | null], GameView>("suite_game");
export interface LiveState {
  running: boolean; readable: boolean; optiscaler: boolean; fsr4: boolean; helix: boolean; lsfg: boolean;
  mako?: boolean;
}
export const getLive = callable<[appid: string], LiveState>("suite_live");
export const setOption = callable<[appid: string, key: string, value: unknown, launch: string | null],
  { ok: boolean; error?: string; warnings?: string[]; view?: GameView }>("suite_set_option");
export const boostOn = callable<[appid: string, name: string, launch: string, ack: boolean], Change>("suite_boost_on");
export const boostOff = callable<[appid: string, launch: string], Change>("suite_boost_off");
export const removeAll = callable<[appid: string, launch: string], Change>("suite_remove_all");
export const applyFix = callable<[appid: string, fix: string, launch: string], Change>("suite_fix");
export const setMenuKey = callable<[appid: string, code: string], { ok: boolean; error?: string }>("suite_set_menu_key");
export const getSetup = callable<[], SetupState>("suite_setup");
export const runSetup = callable<[step: string], { ok: boolean; error?: string }>("suite_setup_run");
export const measureStart = callable<[appid: string, seconds: number], { ok: boolean; error?: string }>("suite_measure_start");
export const measureStatus = callable<[], MeasureStatus>("suite_measure_status");
export const measureClear = callable<[appid: string], { ok: boolean }>("suite_measure_clear");
export const prepareUpdate = callable<[], { ok: boolean }>("suite_prepare_update");
export const setToolboxFg = callable<[on: boolean], Info>("suite_set_toolbox_fg");
export const makoLaunchPlan = callable<[], { wrapper: string | null; want: string[]; ours: string[] }>(
  "suite_mako_launch_plan",
);
export const makoLaunchFix = callable<[appid: string, launch: string], { launch_options: string; changed: boolean; ours: boolean }>(
  "suite_mako_launch_fix",
);
export const makoLaunchMark = callable<[appid: string, added: boolean], { ok: boolean }>("suite_mako_launch_mark");
export const getUpdates = callable<[force: boolean], Updates>("suite_updates");

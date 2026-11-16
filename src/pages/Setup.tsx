import { ButtonItem, PanelSection, PanelSectionRow, ProgressBarWithInfo } from "@decky/ui";
import { useCallback, useEffect, useRef, useState } from "react";
import { getSetup, Info, runSetup, SetupState } from "../backend";
import { nav } from "../nav";
import { confirm, Header, InfoBox, toast } from "../ui";

type Step = "mako" | "lsfg" | "optiscaler" | "helix";
const ACTIVE = ["starting", "installing", "looking", "downloading", "building"];
const HELIX_TEXT =
  "HelixSR's newest stable release is downloaded from its GitHub page and built on this device by HelixSR's own setup. " +
  "Depending on the release that setup downloads NVIDIA's DLSS file, a portable Python and Microsoft's shader compiler, " +
  "and can take up to ten minutes. Keep the device plugged in and awake. Nothing is put into any game yet.";

export function Setup({ info }: { info: Info }) {
  const [state, setState] = useState<SetupState | null>(null);
  const queue = useRef<Step[]>([]);
  const variant = info.variants.variants.find((v) => v.id === state?.variant)?.label;

  const load = useCallback(async () => {
    const s = await getSetup().catch(() => null);
    if (s) setState(s);
    return s;
  }, []);

  const start = useCallback(async (step: Step) => {
    const r = await runSetup(step);
    if (!r.ok) {
      queue.current = [];
      toast("Setup", r.error ?? "Could not start.");
    }
    await load();
  }, [load]);

  useEffect(() => {
    load();
    const t = setInterval(async () => {
      const s = await load();
      if (!s || ACTIVE.includes(s.wizard.phase)) return;
      if (s.wizard.phase === "failed") queue.current = [];
      const next = queue.current.shift();
      if (next) start(next);
    }, 1500);
    return () => clearInterval(t);
  }, [load, start]);

  if (!state) return <PanelSection><InfoBox tone="info">Checking what is installed…</InfoBox></PanelSection>;

  const w = state.wizard;
  const running = ACTIVE.includes(w.phase);
  const done: Record<Step, boolean> = {
    mako: state.mako.installed,
    lsfg: state.lsfg.installed,
    optiscaler: state.optiscaler.installed,
    helix: state.helix.built,
  };
  const available: Record<Step, boolean> = {
    mako: state.mako.available,
    lsfg: state.lsfg.available,
    optiscaler: state.optiscaler.available,
    helix: state.helix.available,
  };
  const missing = (["mako", "lsfg", "optiscaler", "helix"] as Step[]).filter((s) => available[s] && !done[s]);

  const go = async (steps: Step[]) => {
    if (steps.includes("helix") && !(await confirm("Download and build HelixSR?", HELIX_TEXT, "Download and build"))) {
      steps = steps.filter((s) => s !== "helix");
    }
    if (!steps.length) return;
    queue.current = steps.slice(1);
    start(steps[0]);
  };

  const progress = (step: Step) => {
    if (!running || w.step !== step) return null;
    const d = state.helix.download;
    const pct = w.phase === "downloading" && d?.total ? Math.round(((d.bytes ?? 0) / d.total) * 100) : undefined;
    const text =
      w.phase === "downloading" ? `Downloading HelixSR ${w.tag ?? ""}` :
      w.phase === "building" ? `Building HelixSR ${w.tag ?? ""} (the HelixSR page shows the log)` :
      w.phase === "looking" ? "Looking for the newest release" : "Installing";
    return (
      <PanelSectionRow>
        <ProgressBarWithInfo nProgress={pct ?? 0} indeterminate={pct === undefined} sOperationText={text} />
      </PanelSectionRow>
    );
  };

  const row = (step: Step, title: string, what: string, extra?: string) => (
    <PanelSection>
      <Header>{title}</Header>
      <InfoBox tone={done[step] ? "good" : available[step] ? "info" : "warn"}>
        {!available[step] ? "This part did not load in this build (see Chip, versions and updates)." : done[step] ? `Ready. ${extra ?? ""}` : what}
      </InfoBox>
      {progress(step)}
      {w.step === step && w.phase === "failed" && <InfoBox tone="error">{w.error}</InfoBox>}
      {available[step] && (!done[step] || step === "optiscaler") && !running && (
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => go([step])}>
            {done[step] ? "Set up again" : step === "helix" ? "Download and build" : "Install"}
          </ButtonItem>
        </PanelSectionRow>
      )}
    </PanelSection>
  );

  return (
    <>
      <PanelSection>
        <InfoBox>
          One-time preparation. Nothing here touches a game: that happens per game with Boost on the first page.
        </InfoBox>
        {missing.length > 1 && !running && (
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={() => go(missing)}>Set up everything that is missing</ButtonItem>
          </PanelSectionRow>
        )}
      </PanelSection>
      {row(
        "mako",
        "1 · MAKO",
        "Installs MAKO's renderer: adaptive frame generation for any game, with its own model (no Lossless Scaling needed).",
        state.mako.version ? `MAKO Renderer ${state.mako.version}.` : "",
      )}
      {row(
        "lsfg",
        "2 · lsfg-vk",
        "Installs the lsfg-vk layer for frame generation in any game.",
        state.lsfg.lossless
          ? "Lossless Scaling was found."
          : "Still needed: Lossless Scaling from the Steam store, installed and switched to its \"lsfg-vk\" branch (LSFG-VK page explains).",
      )}
      {row(
        "optiscaler",
        "3 · OptiScaler",
        `Unpacks OptiScaler and its FSR 4 runtimes into ~/fgmod${variant ? `, with "${variant}" as the default` : ""}.`,
        variant ? `Default FSR 4 runtime: ${variant}.` : "",
      )}
      {row("helix", "4 · HelixSR (optional)", "A second upscaler next to FSR 4, to compare on your own device.", state.helix.active ? `HelixSR ${state.helix.active}.` : "")}
      <PanelSection>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => nav.go("home")}>Back to the games</ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}

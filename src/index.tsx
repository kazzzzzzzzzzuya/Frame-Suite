import { definePlugin, useQuickAccessVisible } from "@decky/api";
import { DialogButton, Focusable, GamepadButton, PanelSection, staticClasses } from "@decky/ui";
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { FaLayerGroup } from "react-icons/fa";
import helixPlugin from "upstream:helix";
import lsfgPlugin from "upstream:lsfg";
import makoPlugin from "upstream:mako";
import optiscalerPlugin from "upstream:optiscaler";
import { getInfo, Info } from "./backend";
import { guideSeen, nav, panel, SubId, usePage } from "./nav";
import { Guide } from "./pages/Guide";
import { Home } from "./pages/Home";
import { Setup } from "./pages/Setup";
import { Versions } from "./pages/Versions";
import { BLUE, InfoHint, infoVisibility, Note, RED, STYLES, useInfoHidden } from "./ui";
import { makoLaunchFix, makoLaunchMark, makoLaunchPlan } from "./backend";
import { launchOptionsExclusive, readLaunchOptions, writeLaunchOptions } from "./steam";

/** MAKO starts a game through its launcher (mako-run) in the game's launch options. Frame Suite puts it
 *  there by itself for every game MAKO has a profile for, also one made on MAKO's own page, and takes
 *  out again what it added when the profile goes (or MAKO's renderer, so no game fails to start).
 *  Runs while Steam runs, also with the menu closed. */
function watchMakoLaunchOptions(): () => void {
  let running = false;
  let lastPlan = "";
  let lastFull = 0;
  const tick = async () => {
    if (running) return;
    running = true;
    try {
      const plan = await makoLaunchPlan();
      const key = JSON.stringify(plan);
      if (key === lastPlan && Date.now() - lastFull < 60000) return;
      lastPlan = key;
      lastFull = Date.now();
      for (const appid of new Set([...plan.want, ...plan.ours])) {
        // Read and write as one step, never between another change's read and write.
        await launchOptionsExclusive(async () => {
          let current: string;
          try {
            current = await readLaunchOptions(appid);
          } catch {
            lastPlan = ""; // Steam did not answer: look again next time
            return;
          }
          const fix = await makoLaunchFix(appid, current);
          if (!fix.changed) return;
          try {
            await writeLaunchOptions(appid, fix.launch_options);
            await makoLaunchMark(appid, fix.ours);
          } catch (e) {
            lastPlan = "";
            console.warn(`[Frame Suite] launch options of ${appid}`, e);
          }
        });
      }
    } catch {
      /* backend not ready yet */
    } finally {
      running = false;
    }
  };
  void tick();
  const timer = setInterval(() => void tick(), 5000);
  return () => clearInterval(timer);
}

interface Upstream { content?: ReactNode; onDismount?: () => void; error?: string }

const TITLES: Record<string, string> = { home: "Frame Suite", setup: "Setup", versions: "Chip, versions, updates", guide: "Getting started" };

function Title({ names }: { names: Record<string, string> }) {
  const page = usePage();
  if (page === "home")
    return (
      <div className={staticClasses.Title} style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <FaLayerGroup style={{ color: BLUE }} />
        Frame Suite
      </div>
    );
  return (
    <Focusable style={{ display: "flex", alignItems: "center", gap: "8px", width: "100%" }}>
      <DialogButton
        style={{ minWidth: 0, width: "36px", height: "28px", padding: 0, flex: "0 0 auto" }}
        onClick={() => nav.go("home")}
      >
        ‹
      </DialogButton>
      <div className={staticClasses.Title} style={{ padding: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {names[page] ?? TITLES[page]}
      </div>
    </Focusable>
  );
}

/** B on any inner page goes back to Frame Suite's own first page instead of closing the menu.
 *  An upstream panel's own inner pages (lsfg-vk's game details) still take B first. The wrapper
 *  is always there, so the page below keeps its state; on the first page B closes the menu as usual. */
function Root({ upstream }: { upstream: Record<SubId, Upstream> }) {
  const page = usePage();
  const inner = page !== "home";
  // B can also close the whole menu (as in a QuickTab tab). Removing the page that holds the focus
  // while Steam closes the menu leaves the menu stuck on screen, so the page changes a moment later,
  // and only if the menu is still open; otherwise the panel reopens where it was.
  // In a QuickTab tab B may also close the whole menu. Look again once a closing menu has left the screen
  // (Steam's slide takes about a quarter of a second) and go back only if the panel is still there: never
  // while the menu closes. Decky's own useQuickAccessVisible does not know a QuickTab tab, so the panel's
  // own element is asked.
  // In Decky's own tab (Decky knows it is open) B never closes the menu: straight back.
  const deckyVisible = useQuickAccessVisible();
  const deckyRef = useRef(deckyVisible);
  deckyRef.current = deckyVisible;
  const goHomeSoon = () => {
    if (deckyRef.current) {
      nav.go("home");
      return;
    }
    window.setTimeout(() => {
      if (panel.shown() && nav.get() !== "home") nav.go("home");
    }, 350);
  };
  const ours = page === "home" || page === "setup" || page === "versions" || page === "guide";
  const hidden = useInfoHidden();
  return (
    <Focusable
      noFocusRing
      className={`fs-root${hidden && ours ? " fs-info-hidden" : ""}`}
      // R1 hides and shows the explanations on Frame Suite's own pages, as MAKO does on its own.
      // On the plugins' pages R1 stays theirs (lsfg-vk switches its tabs with it).
      onButtonDown={(evt: { detail?: { button?: number; is_repeat?: boolean }; stopPropagation?: () => void }) => {
        if (!ours || evt?.detail?.button !== GamepadButton.BUMPER_RIGHT) return;
        evt.stopPropagation?.();
        if (!evt.detail.is_repeat) infoVisibility.toggle();
      }}
      onCancelButton={
        inner
          ? (evt: { stopPropagation?: () => void }) => {
              evt?.stopPropagation?.();
              goHomeSoon();
            }
          : undefined
      }
      onCancelActionDescription={inner ? "Back" : undefined}
    >
      <style>{STYLES}</style>
      {/* 1 px high, so it has a size whenever the panel is on screen (see panel in nav.ts) */}
      <div ref={(el) => panel.attach(el)} style={{ height: 1, marginBottom: -1 }} />
      <PageContent page={page} upstream={upstream} />
      {ours && <InfoHint />}
    </Focusable>
  );
}

function PageContent({ page, upstream }: { page: ReturnType<typeof usePage>; upstream: Record<SubId, Upstream> }) {
  const [info, setInfo] = useState<Info | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getInfo().then(setInfo).catch((e) => setError(String(e)));
  }, []);

  if (page === "lsfg" || page === "optiscaler" || page === "helix" || page === "mako") {
    const up = upstream[page];
    const sub = info?.subs.find((s) => s.id === page);
    if (up.error || (sub && !sub.ok)) {
      return (
        <PanelSection>
          <Note color={RED}>
            This part did not load in this build, so its page cannot be shown.{"\n"}
            {up.error ?? sub?.error}
          </Note>
        </PanelSection>
      );
    }
    // The upstream panel, exactly as its own plugin renders it.
    return <>{up.content}</>;
  }
  if (error) return <PanelSection><Note color={RED}>The plugin's backend did not answer: {error}</Note></PanelSection>;
  if (!info) return <PanelSection><Note>Loading…</Note></PanelSection>;
  if (page === "guide") return <Guide />;
  if (page === "setup") return <Setup info={info} />;
  if (page === "versions") return <Versions info={info} onInfo={setInfo} />;
  return <Home info={info} />;
}

export default definePlugin(() => {
  // Each upstream plugin is started the way Decky would start it; a failing one leaves the others alone.
  const upstream = {} as Record<SubId, Upstream>;
  const names: Record<string, string> = {};
  const factories: [SubId, () => { name?: string; content?: ReactNode; onDismount?: () => void }][] = [
    ["lsfg", lsfgPlugin as never],
    ["optiscaler", optiscalerPlugin as never],
    ["helix", helixPlugin as never],
    ["mako", makoPlugin as never],
  ];
  for (const [id, factory] of factories) {
    try {
      const p = factory();
      upstream[id] = { content: p.content, onDismount: p.onDismount };
      names[id] = p.name ?? id;
    } catch (e) {
      console.error(`[Frame Suite] ${id} frontend failed to start`, e);
      upstream[id] = { error: String(e) };
      names[id] = id;
    }
  }
  const stopWatching = watchMakoLaunchOptions();
  // The first time Frame Suite opens it starts with Getting started.
  if (!guideSeen.get()) nav.go("guide");
  return {
    name: "Frame Suite",
    titleView: <Title names={names} />,
    content: <Root upstream={upstream} />,
    icon: <FaLayerGroup />,
    onDismount() {
      stopWatching();
      for (const up of Object.values(upstream)) {
        try {
          up.onDismount?.();
        } catch (e) {
          console.error("[Frame Suite] upstream onDismount", e);
        }
      }
    },
  };
});

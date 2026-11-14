import { definePlugin } from "@decky/api";
import { DialogButton, Focusable, PanelSection, staticClasses } from "@decky/ui";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { FaLayerGroup } from "react-icons/fa";
import helixPlugin from "upstream:helix";
import lsfgPlugin from "upstream:lsfg";
import optiscalerPlugin from "upstream:optiscaler";
import { getInfo, Info } from "./backend";
import { nav, SubId, usePage } from "./nav";
import { Home } from "./pages/Home";
import { Setup } from "./pages/Setup";
import { Versions } from "./pages/Versions";
import { Note, RED } from "./ui";

interface Upstream { content?: ReactNode; onDismount?: () => void; error?: string }

const TITLES: Record<string, string> = { home: "Frame Suite", setup: "Setup", versions: "Chip, versions, updates" };

function Title({ names }: { names: Record<string, string> }) {
  const page = usePage();
  if (page === "home") return <div className={staticClasses.Title}>Frame Suite</div>;
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

function Root({ upstream }: { upstream: Record<SubId, Upstream> }) {
  const page = usePage();
  const [info, setInfo] = useState<Info | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getInfo().then(setInfo).catch((e) => setError(String(e)));
  }, []);

  if (page === "lsfg" || page === "optiscaler" || page === "helix") {
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
  return {
    name: "Frame Suite",
    titleView: <Title names={names} />,
    content: <Root upstream={upstream} />,
    icon: <FaLayerGroup />,
    onDismount() {
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

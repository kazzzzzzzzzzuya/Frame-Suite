import { ConfirmModal, DialogButton, Field, Focusable, PanelSectionRow, showModal } from "@decky/ui";
import { toaster } from "@decky/api";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";

// Blue and white: Steam's blue for accents, white text, soft blue panels.
export const BLUE = "#3d9bff";
export const BLUE_SOFT = "rgba(61, 155, 255, 0.12)";
export const BLUE_LINE = "rgba(61, 155, 255, 0.45)";
export const WHITE = "#f5f8fc";
export const MUTED = "#a9b7c8";
export const GREEN = "#6fd39a";
export const AMBER = "#f2c14e";
export const RED = "#ff7a7a";

/** Styles for the whole panel (class "fs-root"). With "fs-info-hidden" the explanations go (R1). */
export const STYLES = `
.fs-root .fs-header { text-align: center; font-weight: 700; font-size: 15px; color: ${WHITE};
  padding: 10px 0 6px; margin: 4px 0 6px; border-bottom: 3px solid transparent;
  border-image: linear-gradient(90deg, rgba(61,155,255,0.15), ${BLUE}, rgba(255,255,255,0.85), ${BLUE}, rgba(61,155,255,0.15)) 1; }
.fs-root .fs-info { display: flex; gap: 8px; align-items: flex-start; padding: 8px 10px; margin: 4px 0;
  border-radius: 8px; border: 1px solid ${BLUE_LINE}; border-left: 3px solid ${BLUE}; background: ${BLUE_SOFT};
  color: ${WHITE}; font-size: 12px; line-height: 1.4; white-space: pre-wrap; }
.fs-root .fs-info.warn { border-color: rgba(242,193,78,0.5); border-left-color: ${AMBER}; background: rgba(242,193,78,0.10); }
.fs-root .fs-info.error { border-color: rgba(255,122,122,0.5); border-left-color: ${RED}; background: rgba(255,122,122,0.10); }
.fs-root .fs-info.good { border-color: rgba(111,211,154,0.5); border-left-color: ${GREEN}; background: rgba(111,211,154,0.10); }
.fs-root .fs-info .fs-i { flex: 0 0 auto; width: 16px; height: 16px; border-radius: 50%; border: 1.5px solid currentColor;
  font-size: 10px; font-weight: 700; display: flex; align-items: center; justify-content: center; margin-top: 1px; opacity: 0.85; }
.fs-root .fs-tiles { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; padding: 8px;
  border-radius: 12px; background: rgba(255,255,255,0.03); border: 1px solid ${BLUE_LINE}; margin: 6px 0; }
.fs-root .fs-tile.DialogButton, .fs-root .fs-tile { min-width: 0 !important; height: 62px; padding: 6px 2px !important;
  border-radius: 10px !important; background: rgba(255,255,255,0.05) !important; border: 1px solid rgba(255,255,255,0.10) !important;
  display: flex !important; flex-direction: column; align-items: center; justify-content: center; gap: 4px; color: ${WHITE} !important; }
.fs-root .fs-tile svg { width: 22px; height: 22px; color: ${BLUE}; }
.fs-root .fs-tile .fs-tile-label { font-size: 10px; line-height: 1.1; color: ${MUTED}; text-align: center; }
.fs-root .fs-tile.gpfocus, .fs-root .fs-tile:focus { border: 1.5px solid ${BLUE} !important; background: ${BLUE_SOFT} !important;
  box-shadow: 0 0 10px rgba(61,155,255,0.45); }
.fs-root .fs-tile.gpfocus .fs-tile-label { color: ${WHITE}; }
.fs-root .fs-card { border-radius: 12px; padding: 4px 8px; margin: 6px 0; border: 1px solid ${BLUE_LINE};
  background: linear-gradient(180deg, rgba(61,155,255,0.10), rgba(255,255,255,0.02)); }
.fs-root .fs-hint { position: sticky; bottom: 4px; display: flex; justify-content: flex-end; margin-top: 8px; pointer-events: none; }
.fs-root .fs-hint span { background: rgba(61,155,255,0.85); color: white; font-size: 11px; font-weight: 600;
  padding: 3px 8px; border-radius: 6px; }
.fs-root .fs-hint b { border: 1px solid white; border-radius: 4px; padding: 0 4px; margin-right: 6px; font-size: 10px; }
.fs-root.fs-info-hidden .fs-info.help, .fs-root.fs-info-hidden [class*="FieldDescription"] { display: none !important; }
`;

const INFO_KEY = "frame-suite:info-hidden";
let infoHidden = (() => {
  try {
    return window.localStorage.getItem(INFO_KEY) === "1";
  } catch {
    return false;
  }
})();
const infoListeners = new Set<() => void>();
export const infoVisibility = {
  hidden: () => infoHidden,
  toggle() {
    infoHidden = !infoHidden;
    try {
      window.localStorage.setItem(INFO_KEY, infoHidden ? "1" : "0");
    } catch {
      /* no storage */
    }
    infoListeners.forEach((l) => l());
  },
};
export function useInfoHidden(): boolean {
  const [h, setH] = useState(infoHidden);
  useEffect(() => {
    const l = () => setH(infoHidden);
    infoListeners.add(l);
    return () => {
      infoListeners.delete(l);
    };
  }, []);
  return h;
}

/** A section title, centred, with a blue and white line under it. */
export function Header({ children }: { children: ReactNode }) {
  return <div className="fs-header">{children}</div>;
}

/** An explanation in a box. tone "help" boxes go with R1 (Hide info); the others stay. */
export function InfoBox({ children, tone = "help" }: { children: ReactNode; tone?: "help" | "info" | "warn" | "error" | "good" }) {
  return (
    <PanelSectionRow>
      <Field focusable bottomSeparator="none" padding="none" childrenLayout="below" childrenContainerWidth="max">
        <div className={`fs-info ${tone}`}>
          <span className="fs-i">{tone === "warn" || tone === "error" ? "!" : tone === "good" ? "✓" : "i"}</span>
          <span>{children}</span>
        </div>
      </Field>
    </PanelSectionRow>
  );
}

export interface Tile { id: string; icon: ReactNode; label: string; onClick: () => void; disabled?: boolean }
/** MAKO-style grid of icon buttons, three to a row. */
export function Tiles({ tiles }: { tiles: Tile[] }) {
  return (
    <Focusable className="fs-tiles" flow-children="grid">
      {tiles.map((t) => (
        <DialogButton key={t.id} className="fs-tile" disabled={t.disabled} onClick={t.onClick} aria-label={t.label}>
          {t.icon}
          <span className="fs-tile-label">{t.label}</span>
        </DialogButton>
      ))}
    </Focusable>
  );
}

/** The bottom hint, as MAKO shows it. */
export function InfoHint() {
  const hidden = useInfoHidden();
  return (
    <div className="fs-hint">
      <span>
        <b>R1</b>
        {hidden ? "Show info" : "Hide info"}
      </span>
    </div>
  );
}

/** Kept for short status lines: an info box that always stays. */
export function Note({ children, color }: { children: ReactNode; color?: string }) {
  const tone = color === RED ? "error" : color === AMBER ? "warn" : color === GREEN ? "good" : "info";
  return <InfoBox tone={tone}>{children}</InfoBox>;
}

export const toast = (title: string, body: string) => toaster.toast({ title, body });

export function confirm(title: string, body: ReactNode, okText = "Continue"): Promise<boolean> {
  return new Promise((resolve) => {
    let settled = false;
    const done = (v: boolean) => {
      if (!settled) {
        settled = true;
        resolve(v);
      }
    };
    showModal(
      <ConfirmModal
        strTitle={title}
        strDescription={body}
        strOKButtonText={okText}
        onOK={() => done(true)}
        onCancel={() => done(false)}
        closeModal={() => done(false)}
      />,
    );
  });
}

export const when = (t: number) => new Date(t * 1000).toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });

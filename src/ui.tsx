import { ButtonItem, ConfirmModal, DialogButton, Field, Focusable, PanelSection, PanelSectionRow, showModal } from "@decky/ui";
import { toaster } from "@decky/api";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import { DOT, dotCss } from "./dot";

// Dot theme (see dot.ts): black, white and grey, one red accent, dot-matrix titles.
// The names stay for the callers: BLUE is now the white of marks, GREEN/AMBER/RED the note tones.
export const BLUE = DOT.text;
export const BLUE_SOFT = "rgba(242, 242, 242, 0.06)";
export const BLUE_LINE = DOT.line2;
export const WHITE = DOT.text;
export const MUTED = DOT.mute;
export const GREEN = "#f2f2f2";
export const AMBER = "#ff8a3d";
export const RED = "#ff5a5f";

/** Styles for the whole panel (class "fs-root"), the four plugins' pages included: Steam's own
 *  controls there take the theme too. With "fs-info-hidden" the explanations go (R1). */
export const STYLES = `
${dotCss(".fs-root")}
.fs-root .fs-header { font-family: "LgoDoto", monospace; font-weight: 900; font-size: 20px; letter-spacing: 1px;
  text-transform: uppercase; color: ${WHITE}; padding: 10px 4px 6px; margin: 4px 0 4px; }
.fs-root .fs-info { display: flex; gap: 8px; align-items: flex-start; padding: 9px 12px; margin: 4px 0;
  border-radius: 18px; border: 1px solid ${DOT.line}; background: ${DOT.card};
  color: ${WHITE}; font-size: 12px; line-height: 1.4; white-space: pre-wrap; }
.fs-root .fs-info.warn { border-color: rgba(255,138,61,0.55); }
.fs-root .fs-info.error { border-color: rgba(215,25,33,0.7); }
.fs-root .fs-info.warn .fs-i { color: ${AMBER}; }
.fs-root .fs-info.error .fs-i { color: ${DOT.red}; }
.fs-root .fs-info .fs-i { flex: 0 0 auto; width: 16px; height: 16px; border-radius: 50%; border: 1.5px solid currentColor;
  font-size: 10px; font-weight: 700; display: flex; align-items: center; justify-content: center; margin-top: 1px; }
.fs-root .fs-tiles { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; padding: 0; margin: 8px 0; }
.fs-root .fs-tile.DialogButton, .fs-root .fs-tile { min-width: 0 !important; height: 76px; padding: 6px 2px !important;
  border-radius: 20px !important; background: transparent !important; border: 1px solid ${DOT.line2} !important;
  display: flex !important; flex-direction: column; align-items: center; justify-content: center; gap: 6px; color: ${WHITE} !important; }
.fs-root .fs-tile svg { width: 20px; height: 20px; color: ${WHITE}; }
.fs-root .fs-tile .fs-tile-label { font-size: 10px; line-height: 1.1; letter-spacing: 1px; text-transform: uppercase; color: ${MUTED}; text-align: center; }
.fs-root .fs-tile.gpfocus, .fs-root .fs-tile:focus { background: ${WHITE} !important; border-color: ${WHITE} !important; }
.fs-root .fs-tile.gpfocus svg, .fs-root .fs-tile.gpfocus .fs-tile-label { color: #000 !important; }
.fs-root .fs-card { border-radius: 20px; padding: 4px 10px; margin: 6px 0; border: 1px solid ${DOT.line};
  background: ${DOT.card}; background-image: radial-gradient(#2c2c2c 1px, transparent 1.2px); background-size: 9px 9px; }
.fs-root .fs-hint { position: sticky; bottom: 4px; display: flex; justify-content: center; margin-top: 8px; pointer-events: none; }
.fs-root .fs-hint span { background: #000; color: ${MUTED}; font-size: 10px; letter-spacing: 2px; text-transform: uppercase;
  padding: 3px 10px; border-radius: 10px; border: 1px solid ${DOT.line}; }
.fs-root .fs-hint b { border: 1px solid ${WHITE}; color: ${WHITE}; border-radius: 4px; padding: 0 4px; margin-right: 6px; font-size: 10px; }
.fs-root .fs-label { font-size: 10px; letter-spacing: 2px; text-transform: uppercase; color: ${MUTED}; margin: 10px 4px 2px; }
.fs-root .DialogButton.fs-pill.on { background: ${DOT.red} !important; border-color: ${DOT.red} !important; color: #fff !important; }
.fs-root .fs-fold .DialogButton { border-style: dashed !important; border-radius: 20px !important; text-align: left; }
.fs-root.fs-info-hidden .fs-info.help, .fs-root.fs-info-hidden [class*="FieldDescription"] { display: none !important; }
`;

const INFO_KEY = "frame-suite:info-hidden";
let infoHidden = (() => {
  try {
    return window.localStorage.getItem(INFO_KEY) !== "0";   // hidden until R1 shows them
  } catch {
    return true;
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

/** A closed section: its name and a one-line summary; selecting it shows what is inside.
 *  Open or closed is remembered per section. */
export function Fold({ id, title, summary, children }: { id: string; title: string; summary?: ReactNode; children: ReactNode }) {
  const key = `frame-suite:fold-${id}`;
  const [open, setOpen] = useState(() => {
    try {
      return window.localStorage.getItem(key) === "1";
    } catch {
      return false;
    }
  });
  const toggle = () => {
    setOpen(!open);
    try {
      window.localStorage.setItem(key, open ? "0" : "1");
    } catch {
      /* no storage */
    }
  };
  return (
    <>
      <div className="fs-fold">
        <PanelSection>
          <PanelSectionRow>
            <ButtonItem layout="below" description={open ? undefined : summary} onClick={toggle}>
              {title + (open ? "  ▴" : "  ▾")}
            </ButtonItem>
          </PanelSectionRow>
        </PanelSection>
      </div>
      {open && children}
    </>
  );
}

/** Big dot-matrix readings side by side (label, number, unit). Values that are null are left out. */
export function Readings({ items }: { items: { label: string; value: number | string | null | undefined; unit?: string }[] }) {
  const shown = items.filter((i) => i.value != null && i.value !== "");
  if (!shown.length) return null;
  return (
    <div style={{ display: "flex", gap: 10, padding: "6px 4px 8px" }}>
      {shown.map((i) => (
        <div key={i.label} style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 10, letterSpacing: 1.5, textTransform: "uppercase", color: MUTED, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{i.label}</div>
          <div style={{ fontFamily: "LgoDoto, monospace", fontWeight: 900, fontSize: 26, lineHeight: 1, letterSpacing: 1, marginTop: 3, whiteSpace: "nowrap" }}>
            {i.value}
            {i.unit && <span style={{ fontSize: 13, color: MUTED, marginLeft: 3 }}>{i.unit}</span>}
          </div>
        </div>
      ))}
    </div>
  );
}

/** A row of pill buttons for a few choices; the chosen one is filled red. */
export function Pills({ options, value, onChange }: {
  options: { id: string; label: string }[];
  value: string | null | undefined;
  onChange: (id: string) => void;
}) {
  return (
    <PanelSectionRow>
      <Focusable flow-children="horizontal" style={{ display: "flex", flexWrap: "wrap", gap: 6, padding: "4px 0" }}>
        {options.map((o) => (
          <DialogButton
            key={o.id}
            onClick={() => onChange(o.id)}
            className={o.id === value ? "fs-pill on" : "fs-pill"}
            style={{ width: "auto", minWidth: 0, padding: "4px 12px", fontSize: 12, lineHeight: "18px", flex: "none" }}
          >
            {o.label}
          </DialogButton>
        ))}
      </Focusable>
    </PanelSectionRow>
  );
}

/** A switch row drawn by the theme (Steam's own toggle ignores restyling on some clients and
 *  stayed blue). Same props as Decky's ToggleField: A or a tap flips it. */
export function Toggle({ label, description, checked, disabled, onChange }: {
  label: ReactNode;
  description?: ReactNode;
  checked: boolean;
  disabled?: boolean;
  onChange: (v: boolean) => void;
}) {
  const flip = () => {
    if (!disabled) onChange(!checked);
  };
  return (
    <Field label={label} description={description} focusable highlightOnFocus onActivate={flip} onClick={flip}>
      <span className={`dot-switch${checked ? " on" : ""}${disabled ? " disabled" : ""}`} role="switch" aria-checked={checked} />
    </Field>
  );
}

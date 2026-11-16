// Which page of the panel is showing. Kept outside React so the title bar and
// the content agree, and so the panel reopens where it was closed.
import { useEffect, useState } from "react";

export type SubId = "lsfg" | "optiscaler" | "helix" | "mako";
export type Page = "home" | "setup" | "versions" | "guide" | SubId;

// Whether Getting started was shown once. Kept in the browser's storage, like R1's choice.
const GUIDE_KEY = "frame-suite:guide-seen";
export const guideSeen = {
  get(): boolean {
    try {
      return window.localStorage.getItem(GUIDE_KEY) === "1";
    } catch {
      return true; // no storage: do not push the guide every time
    }
  },
  mark() {
    try {
      window.localStorage.setItem(GUIDE_KEY, "1");
    } catch {
      /* no storage */
    }
  },
};

let page: Page = "home";
const listeners = new Set<() => void>();

export const nav = {
  get: () => page,
  go(next: Page) {
    page = next;
    listeners.forEach((l) => l());
  },
};

export function usePage(): Page {
  const [p, setP] = useState(page);
  useEffect(() => {
    const l = () => setP(page);
    listeners.add(l);
    l();
    return () => {
      listeners.delete(l);
    };
  }, []);
  return p;
}

// Whether Frame Suite's panel is on screen. Decky's useQuickAccessVisible only knows Decky's own tab: in a
// QuickTab tab it stays false. The panel's own element tells in both: on screen means it has a size and
// lies inside the window (a closed menu is moved out of it).
let panelEl: HTMLElement | null = null;
let shown = false;
const shownListeners = new Set<() => void>();
function checkShown(): boolean {
  let v = false;
  // Steam draws the Quick Access menu in a window of its own, not the one this code runs in: ask the
  // panel's own document and window.
  const doc = panelEl?.ownerDocument;
  const win = doc?.defaultView;
  if (panelEl && panelEl.isConnected && doc && win && doc.visibilityState !== "hidden") {
    const r = panelEl.getBoundingClientRect();
    v = r.width > 0 && r.height > 0 && r.right > 0 && r.bottom > 0 &&
      r.left < win.innerWidth && r.top < win.innerHeight;
  }
  if (v !== shown) {
    shown = v;
    shownListeners.forEach((l) => l());
  }
  return v;
}
export const panel = {
  attach(el: HTMLElement | null) {
    panelEl = el;
    checkShown();
  },
  shown: checkShown,
};

export function usePanelShown(): boolean {
  const [v, setV] = useState(shown);
  useEffect(() => {
    const l = () => setV(shown);
    shownListeners.add(l);
    const timer = setInterval(checkShown, 500);
    l();
    return () => {
      shownListeners.delete(l);
      clearInterval(timer);
    };
  }, []);
  return v;
}

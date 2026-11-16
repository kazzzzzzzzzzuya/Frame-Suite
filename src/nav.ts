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

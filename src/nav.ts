// Which page of the panel is showing. Kept outside React so the title bar and
// the content agree, and so the panel reopens where it was closed.
import { useEffect, useState } from "react";

export type SubId = "lsfg" | "optiscaler" | "helix" | "mako";
export type Page = "home" | "setup" | "versions" | SubId;

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

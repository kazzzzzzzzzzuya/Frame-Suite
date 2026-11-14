// The Decky API as one upstream plugin sees it: backend calls and events get
// the plugin's prefix, everything else is Decky's own.
import * as api from "@decky/api";

export function scoped(id: string) {
  const p = `${id}__`;
  return {
    call: ((route: string, ...args: unknown[]) =>
      (api.call as (r: string, ...a: unknown[]) => Promise<unknown>)(p + route, ...args)) as typeof api.call,
    callable: ((route: string) => api.callable(p + route)) as typeof api.callable,
    addEventListener: ((event: string, listener: (...a: unknown[]) => void) =>
      api.addEventListener(p + event, listener)) as typeof api.addEventListener,
    removeEventListener: ((event: string, listener: (...a: unknown[]) => void) =>
      api.removeEventListener(p + event, listener)) as typeof api.removeEventListener,
  };
}

// Steam's own client API: the running game and a game's launch options.
import { Router } from "@decky/ui";

interface AppDetails { strLaunchOptions?: string }
interface Registration { unregister: () => void }
interface SteamApps {
  RegisterForAppDetails: (appId: number, cb: (d: AppDetails) => void) => Registration;
  SetAppLaunchOptions: (appId: number, options: string) => void | Promise<void>;
}

const apps = (): Partial<SteamApps> | undefined =>
  (window as unknown as { SteamClient?: { Apps?: Partial<SteamApps> } }).SteamClient?.Apps;

export function runningGame(): { appid: string; name: string } | null {
  const app = Router.MainRunningApp as { appid?: string | number; display_name?: string } | undefined;
  if (!app || app.appid === undefined || app.appid === null) return null;
  return { appid: String(app.appid), name: app.display_name || `App ${app.appid}` };
}

export function readLaunchOptions(appId: string, timeoutMs = 4000): Promise<string> {
  return new Promise((resolve, reject) => {
    const register = apps()?.RegisterForAppDetails;
    if (!register) {
      reject(new Error("Steam's app details are not available"));
      return;
    }
    let reg: Registration | undefined;
    let done = false;
    const finish = (fn: () => void) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      // the callback can fire before RegisterForAppDetails has returned
      setTimeout(() => {
        try {
          reg?.unregister();
        } catch {
          /* already gone */
        }
      }, 0);
      fn();
    };
    const timer = setTimeout(() => finish(() => reject(new Error("Steam did not answer in time"))), timeoutMs);
    try {
      reg = register(Number(appId), (d) => finish(() => resolve(d?.strLaunchOptions ?? "")));
    } catch (e) {
      finish(() => reject(e instanceof Error ? e : new Error(String(e))));
    }
  });
}

/** Writes a game's launch options and reads them back: Steam gives no answer of its own. */
export async function writeLaunchOptions(appId: string, options: string): Promise<void> {
  const set = apps()?.SetAppLaunchOptions;
  if (!set) throw new Error("Steam's launch options are not available");
  await set(Number(appId), options);
  for (let i = 0; i < 6; i++) {
    await new Promise((r) => setTimeout(r, 250));
    if ((await readLaunchOptions(appId)).trim() === options.trim()) return;
  }
  throw new Error("Steam did not take the new launch options");
}

import { toolboxBoostOff, toolboxBoostOn, toolboxBoostTodo } from "./backend";
import { launchOptionsExclusive, readLaunchOptions, writeLaunchOptions } from "./steam";
import { toast } from "./ui";

/** Smoothest on the Legion Go Toolbox's Game tab: the toolbox asks for Boost in its request
 *  file; the backend says which games to turn on or off (toolbox_boost_todo), and this does it
 *  the way the Boost switch does, since only the frontend can read and write launch options.
 *  Runs while the plugin is loaded, also with the menu closed. */
export function watchToolboxBoosts(): () => void {
  let running = false;
  const told = new Set<string>();       // one message per game and outcome, not every retry

  const act = (appid: string, name: string, on: boolean) =>
    launchOptionsExclusive(async () => {
      let lo: string | null = null;
      try {
        lo = await readLaunchOptions(appid);
      } catch {
        lo = null;
      }
      if (lo === null) return;          // Steam did not answer: next round
      const res = on ? await toolboxBoostOn(appid, name, lo) : await toolboxBoostOff(appid, lo);
      if (res.ok && res.launch_changed && res.launch_options !== undefined) {
        try {
          await writeLaunchOptions(appid, res.launch_options);
        } catch (e) {
          if (on) await toolboxBoostOff(appid, lo).catch(() => undefined);
          toast("Boost", `${name || appid}: the launch options could not be changed (${e}). Undone.`);
          return;
        }
      }
      const key = `${appid}:${on}:${res.ok}`;
      if (told.has(key)) return;
      told.add(key);
      const who = res.view?.name || name || `App ${appid}`;
      toast(
        "Boost",
        res.ok
          ? on
            ? `${who}: on for Smoothest (Legion Go Toolbox). It starts with the game's next start.`
            : `${who}: off again, the game no longer uses Smoothest.`
          : `${who}: ${res.need_ack ? "the game has anti-cheat, so Boost is left for you to turn on." : (res.error ?? "Boost did not work.")}`,
      );
    });

  const tick = async () => {
    if (running) return;
    running = true;
    try {
      const todo = await toolboxBoostTodo();
      for (const g of todo.on) await act(g.appid, g.name, true);
      for (const a of todo.off) await act(a, "", false);
    } catch {
      /* backend not ready yet */
    } finally {
      running = false;
    }
  };
  void tick();
  const id = setInterval(() => void tick(), 8000);
  return () => clearInterval(id);
}

import deckyPlugin from "@decky/rollup";
import { readFileSync } from "node:fs";
import path from "node:path";

const lock = JSON.parse(readFileSync("upstreams.json", "utf8"));

// The three upstream frontends are built first (scripts/build.mjs), each
// importing the Decky API as "suite-api/<id>". Here those names resolve to our
// shims, so the whole plugin holds one connection to Decky.
const cfg = await deckyPlugin({});
cfg.plugins.unshift({
  name: "frame-suite",
  resolveId(source) {
    let m = /^upstream:(\w+)$/.exec(source);
    if (m) {
      // Where each upstream's frontend was built (see scripts/upstreams.mjs).
      const up = lock.upstreams[m[1]];
      const base = up?.release_zip ? `.work/src/${m[1]}/${up.frontend_dir || ""}` : `.work/upstream/${m[1]}`;
      return path.resolve(`${base}/dist/index.js`);
    }
    m = /^suite-api\/(\w+)$/.exec(source);
    if (m) return path.resolve(`src/shims/${m[1]}.ts`);
    return null;
  },
});
export default cfg;

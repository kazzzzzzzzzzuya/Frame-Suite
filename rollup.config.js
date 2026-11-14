import deckyPlugin from "@decky/rollup";
import path from "node:path";

// The three upstream frontends are built first (scripts/build.mjs), each
// importing the Decky API as "suite-api/<id>". Here those names resolve to our
// shims, so the whole plugin holds one connection to Decky.
const cfg = await deckyPlugin({});
cfg.plugins.unshift({
  name: "frame-suite",
  resolveId(source) {
    let m = /^upstream:(\w+)$/.exec(source);
    if (m) return path.resolve(`.work/upstream/${m[1]}/dist/index.js`);
    m = /^suite-api\/(\w+)$/.exec(source);
    if (m) return path.resolve(`src/shims/${m[1]}.ts`);
    return null;
  },
});
export default cfg;

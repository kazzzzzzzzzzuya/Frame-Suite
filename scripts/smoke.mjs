// Loads the built frontend the way Decky does, with a stand-in for Steam's
// globals, and checks the two things the whole design rests on: the plugin
// connects to Decky exactly once, and every backend call of an upstream panel
// leaves with that upstream's prefix.
import path from "node:path";
import { pathToFileURL } from "node:url";

const bundle = path.resolve(process.argv[2] || "out/frame-suite/dist/index.js");
const anything = () => new Proxy(function () {}, {
  get: (_t, k) => (k === Symbol.toPrimitive ? () => "" : k === "then" ? undefined : anything()),
  apply: () => anything(),
  construct: () => anything(),
});
const calls = [];
const declared = [];
const events = [];
let connects = 0;
const api = {
  _version: 2,
  call: (name, ...args) => (calls.push(name), Promise.resolve({})),
  callable: (name) => (declared.push(name), (...args) => (calls.push(name), Promise.resolve({}))),
  addEventListener: (event, fn) => (events.push(event), fn),
  removeEventListener: () => {},
  toaster: { toast: () => {} },
  routerHook: anything(),
  openFilePicker: anything(), executeInTab: anything(), injectCssIntoTab: anything(), removeCssFromTab: anything(),
  fetchNoCors: anything(), getExternalResourceURL: anything(), useQuickAccessVisible: () => true,
};
const store = new Map();
globalThis.window = globalThis;
Object.assign(globalThis, {
  SP_REACT: anything(), SP_REACTDOM: anything(), SP_JSX: anything(), DFL: anything(),
  localStorage: { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) },
  __DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit: {
    connect: (version, name) => {
      connects++;
      if (name !== "Frame Suite") throw new Error(`connected as "${name}"`);
      return api;
    },
  },
});
if (!globalThis.navigator) globalThis.navigator = { language: "en-US" };
if (!globalThis.document) globalThis.document = anything();

const fail = (msg) => {
  console.error(`smoke test failed: ${msg}`);
  process.exit(1);
};
const mod = await import(pathToFileURL(bundle).href);
const plugin = mod.default();
if (connects !== 1) fail(`the plugin connected to Decky ${connects} times, expected once`);
if (plugin.name !== "Frame Suite" || !plugin.content || !plugin.titleView) fail("the plugin definition is incomplete");
if (!events.includes("helix__setup_done")) fail(`HelixSR's event is not prefixed (${events.join(", ")})`);

// Every backend call is declared when its module loads: these are the names that reach Decky.
const count = (prefix) => declared.filter((n) => n.startsWith(prefix)).length;
const stray = declared.filter((n) => !/^(suite_|lsfg__|optiscaler__|helix__)/.test(n));
if (stray.length) fail(`backend calls without a prefix: ${stray.slice(0, 5).join(", ")}`);
for (const [prefix, least] of [["suite_", 10], ["lsfg__", 10], ["optiscaler__", 5], ["helix__", 10]]) {
  if (count(prefix) < least) fail(`only ${count(prefix)} "${prefix}" backend calls declared`);
}
plugin.onDismount?.();
if (process.argv[3]) (await import("node:fs")).writeFileSync(process.argv[3], JSON.stringify([...new Set(declared)].sort(), null, 1));
console.log(`smoke test ok: 1 connection; backend calls suite ${count("suite_")}, lsfg ${count("lsfg__")}, optiscaler ${count("optiscaler__")}, helix ${count("helix__")}; events ${events.join(", ")}`);

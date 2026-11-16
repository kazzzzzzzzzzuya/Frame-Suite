// Builds out/frame-suite.zip from this repository and the pinned upstream
// plugins (fetched by "node scripts/upstreams.mjs fetch").
//
//   node scripts/build.mjs [--test] [--skip-binaries]
//
// Nothing in an upstream's source is edited. Each frontend is built from its
// own lockfile with one build-time substitution: "@decky/api" resolves to a
// module of ours that prefixes its backend calls (src/shims). --test also runs
// each upstream's own test suite.
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  chmodSync, cpSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync,
} from "node:fs";
import path from "node:path";
import { backendDir, frontendDir, readLock } from "./upstreams.mjs";

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const WORK = path.join(ROOT, ".work");
const FOLDER = "frame-suite"; // the plugin's folder in Decky; settings and logs are filed under it
const STAGE = path.join(ROOT, "out", FOLDER);
const args = new Set(process.argv.slice(2));
const RESERVED = new Set(["main.py", "plugin.json", "package.json", "dist", "bin", "py_modules", "upstream",
  "profiles", "upstreams.json", "LICENSE", "README.md"]);

const run = (cmd, argv, cwd, env) => {
  console.log(`  $ ${cmd} ${argv.join(" ")}`);
  execFileSync(cmd, argv, { cwd, stdio: "inherit", env: { ...process.env, ...env } });
};
const json = (p) => JSON.parse(readFileSync(p, "utf8"));
const fail = (msg) => {
  console.error(`\nbuild failed: ${msg}`);
  process.exit(1);
};
const sha256 = (file) => createHash("sha256").update(readFileSync(file)).digest("hex");

const lock = readLock();
const suite = json(path.join(ROOT, "plugin.json"));
const suitePkg = json(path.join(ROOT, "package.json"));
const ids = Object.keys(lock.upstreams);

// ---------------------------------------------------------------- upstream frontends
const originals = {};
for (const id of ids) {
  const up = lock.upstreams[id];
  const dir = frontendDir(id, up);
  const back = backendDir(id);
  if (!existsSync(path.join(back, "main.py")) || !existsSync(path.join(dir, "package.json")))
    fail(`${id} is not checked out; run "node scripts/upstreams.mjs fetch"`);
  console.log(`\n== ${up.title} ${up.tag}`);
  const extra = readdirSync(back).filter((f) => f.endsWith(".py") && f !== "main.py" && !(up.root_modules || []).includes(f));
  if (extra.length) fail(`${id} now has Python files next to main.py (${extra.join(", ")}); the loader must learn about them first`);

  originals[id] = {
    plugin: readFileSync(path.join(back, "plugin.json"), "utf8"),
    pkg: json(path.join(back, "package.json")),
    frontendPlugin: readFileSync(path.join(dir, "plugin.json"), "utf8"),
  };
  if (existsSync(path.join(dir, "pnpm-lock.yaml"))) run("pnpm", ["install", "--frozen-lockfile"], dir);
  else if (existsSync(path.join(dir, "package-lock.json"))) run("npm", ["ci", "--no-audit", "--no-fund"], dir);
  else fail(`${id} has no lockfile`);

  for (const step of up.prebuild || []) run(step[0], step.slice(1), dir);

  // Asset URLs are built from plugin.json's name, so the upstream must be built under ours.
  const pj = JSON.parse(originals[id].frontendPlugin);
  pj.name = suite.name;
  writeFileSync(path.join(dir, "plugin.json"), JSON.stringify(pj, null, 2));
  writeFileSync(path.join(dir, "rollup.suite.mjs"), `
import base from "./rollup.config.js";
const cfg = await base;
cfg.plugins.unshift({
  name: "frame-suite-api",
  resolveId(source) {
    return source === "@decky/api" ? { id: "suite-api/${id}", external: true } : null;
  },
});
export default cfg;
`);
  try {
    rmSync(path.join(dir, "dist"), { recursive: true, force: true });
    run("npx", ["rollup", "-c", "rollup.suite.mjs"], dir);
  } finally {
    writeFileSync(path.join(dir, "plugin.json"), originals[id].frontendPlugin);
    rmSync(path.join(dir, "rollup.suite.mjs"), { force: true });
  }
  const bundle = readFileSync(path.join(dir, "dist", "index.js"), "utf8");
  if (!bundle.includes(`suite-api/${id}`)) fail(`${id}: the built frontend does not import the Decky API through the shim`);
  if (bundle.includes("deckyLoaderAPIInit")) fail(`${id}: the built frontend still connects to Decky by itself`);

  if (args.has("--test")) {
    const test = json(path.join(dir, "package.json")).scripts?.test || "";
    if (!test || test.includes("no test specified")) console.log("  (this plugin has no tests of its own)");
    else run(existsSync(path.join(dir, "pnpm-lock.yaml")) ? "pnpm" : "npm", ["test"], dir);
  }
}

// ---------------------------------------------------------------- our frontend
console.log("\n== Frame Suite frontend");
rmSync(path.join(ROOT, "dist"), { recursive: true, force: true });
run("npx", ["tsc", "--noEmit"], ROOT);
run("npx", ["rollup", "-c"], ROOT);

// ---------------------------------------------------------------- assemble
console.log("\n== assembling");
rmSync(path.join(ROOT, "out"), { recursive: true, force: true });
mkdirSync(STAGE, { recursive: true });
const copy = (from, to) => cpSync(from, to, {
  recursive: true, errorOnExist: true, force: false,
  filter: (src) => !src.endsWith("__pycache__") && !src.endsWith(".pyc"),
});
for (const f of ["main.py", "plugin.json", "LICENSE", "README.md", "profiles"]) {
  copy(path.join(ROOT, f), path.join(STAGE, f));
}
// package.json: ours, plus what a bundled plugin reads from its plugin folder (MAKO: its renderer's
// details, as "bundled_renderer", which Decky's installer leaves alone).
const stagedPkg = JSON.parse(JSON.stringify(suitePkg));
copy(path.join(ROOT, "py_modules", "framesuite"), path.join(STAGE, "py_modules", "framesuite"));
copy(path.join(ROOT, "dist"), path.join(STAGE, "dist"));

const binaries = new Map();
for (const id of ids) {
  const up = lock.upstreams[id];
  const dir = backendDir(id);
  const front = frontendDir(id, up);
  const to = path.join(STAGE, "upstream", id);
  mkdirSync(to, { recursive: true });
  copy(path.join(dir, "main.py"), path.join(to, "main.py"));
  writeFileSync(path.join(to, "plugin.json"), originals[id].plugin);
  copy(path.join(dir, "package.json"), path.join(to, "package.json"));
  for (const f of ["LICENSE", "LICENSE.md", "README.md", "THIRD_PARTY_NOTICES.md", "ASSET_PROVENANCE.md", "third_party_licenses"]) {
    if (existsSync(path.join(dir, f))) copy(path.join(dir, f), path.join(to, f));
  }
  // Modules a plugin imports from its plugin folder (MAKO puts that folder on sys.path itself).
  for (const m of up.root_modules || []) {
    if (RESERVED.has(m) || existsSync(path.join(STAGE, m))) fail(`${id}: "${m}" collides with another file of the plugin`);
    copy(path.join(dir, m), path.join(STAGE, m));
  }
  if (up.bundled_renderer) {
    const rb = originals[id].pkg.remote_binary;
    if (!Array.isArray(rb) || rb.length !== 1) fail(`${id}: expected exactly one remote_binary in its package.json`);
    if (stagedPkg.bundled_renderer) fail(`${id}: a second plugin also needs "bundled_renderer"`);
    stagedPkg.bundled_renderer = rb[0];
  }
  // A plugin shipped as its release zip brings its binaries along (already checked with the zip).
  if (up.release_zip && existsSync(path.join(dir, "bin"))) {
    for (const b of readdirSync(path.join(dir, "bin"))) {
      const target = path.join(STAGE, "bin", b);
      if (existsSync(target)) fail(`${id}: binary "${b}" exists twice`);
      mkdirSync(path.dirname(target), { recursive: true });
      copy(path.join(dir, "bin", b), target);
    }
  }

  // py_modules of all plugins share one folder, as Decky expects it.
  const mods = path.join(dir, "py_modules");
  for (const m of existsSync(mods) ? readdirSync(mods) : []) {
    const target = path.join(STAGE, "py_modules", m);
    if (existsSync(target)) fail(`${id}: Python module "${m}" exists twice`);
    copy(path.join(mods, m), target);
  }
  // "defaults" is what Decky's own packaging puts next to main.py (a release zip has it in place already).
  const defaults = path.join(up.release_zip ? path.join(dir, "__none__") : dir, "defaults");
  for (const d of existsSync(defaults) ? readdirSync(defaults) : []) {
    const target = path.join(STAGE, d);
    if (RESERVED.has(d) || existsSync(target)) fail(`${id}: "defaults/${d}" collides with another file of the plugin`);
    copy(path.join(defaults, d), target);
  }
  // Images the frontends load at run time.
  const assets = path.join(front, "dist", "assets");
  for (const a of existsSync(assets) ? readdirSync(assets) : []) {
    const target = path.join(STAGE, "dist", "assets", a);
    mkdirSync(path.dirname(target), { recursive: true });
    if (existsSync(target) && sha256(target) !== sha256(path.join(assets, a))) fail(`${id}: asset "${a}" exists twice`);
    if (!existsSync(target)) copy(path.join(assets, a), target);
  }
  for (const b of up.release_zip ? [] : originals[id].pkg.remote_binary || []) {
    const known = binaries.get(b.name);
    if (known && known.sha256hash !== b.sha256hash) fail(`${id}: binary "${b.name}" exists twice with different content`);
    binaries.set(b.name, b);
  }
}

// ---------------------------------------------------------------- binaries
// The files Decky's store would download on install ("remote_binary"); a zip install needs them inside.
if (!args.has("--skip-binaries")) {
  const cache = path.join(WORK, "cache");
  mkdirSync(cache, { recursive: true });
  mkdirSync(path.join(STAGE, "bin"), { recursive: true });
  for (const b of binaries.values()) {
    if (!/^[0-9a-f]{64}$/.test(b.sha256hash || "")) fail(`binary "${b.name}" has no SHA-256`);
    const cached = path.join(cache, b.sha256hash);
    if (!existsSync(cached) || sha256(cached) !== b.sha256hash) {
      run("curl", ["-fsSL", "--retry", "4", "--retry-delay", "3", "-o", cached + ".part", b.url], ROOT);
      if (sha256(cached + ".part") !== b.sha256hash) fail(`binary "${b.name}" does not match its SHA-256`);
      cpSync(cached + ".part", cached);
      rmSync(cached + ".part");
    }
    copy(cached, path.join(STAGE, "bin", b.name));
    console.log(`  bin/${b.name} (${(statSync(cached).size / 1048576).toFixed(1)} MB)`);
  }
}

writeFileSync(path.join(STAGE, "package.json"), JSON.stringify(stagedPkg, null, 2) + "\n");

// ---------------------------------------------------------------- stamp, check, zip
const stamped = JSON.parse(JSON.stringify(lock));
for (const up of Object.values(stamped.upstreams)) {
  delete up.prebuild;
  delete up.root_modules;
  delete up.bundled_renderer;
}
stamped.suite_repo = process.env.GITHUB_REPOSITORY || lock.suite_repo;
stamped.suite_version = suitePkg.version;
stamped.built = new Date().toISOString();
writeFileSync(path.join(STAGE, "upstreams.json"), JSON.stringify(stamped, null, 2) + "\n");
for (const f of existsSync(path.join(STAGE, "assets")) ? readdirSync(path.join(STAGE, "assets"), { recursive: true }) : []) {
  if (String(f).endsWith(".sh") || String(f).endsWith(".py")) chmodSync(path.join(STAGE, "assets", String(f)), 0o755);
}

// Decky runs main.py on its own Python, older than the newest: nothing may need newer syntax.
for (const py of ["python3.11", "python3.10"]) {
  try {
    execFileSync(py, ["--version"], { stdio: "ignore" });
  } catch {
    continue;
  }
  run(py, ["-c", `
import compileall, sys
ok = compileall.compile_dir(sys.argv[1], quiet=1, legacy=False, ddir="", maxlevels=20)
sys.exit(0 if ok else 1)`, STAGE], ROOT, { PYTHONDONTWRITEBYTECODE: "1", PYTHONPYCACHEPREFIX: path.join(WORK, "pyc") });
  break;
}
// The frontend, loaded as Decky loads it; the backend calls it declares are then checked against the backend.
run("node", ["scripts/smoke.mjs", path.join(STAGE, "dist", "index.js"), path.join(ROOT, "out", "declared-calls.json")], ROOT);
run("python3", ["-m", "unittest", "discover", "-s", "tests", "-v"], ROOT,
  { FRAME_SUITE_STAGE: STAGE, PYTHONDONTWRITEBYTECODE: "1" });

const zip = path.join(ROOT, "out", `${FOLDER}.zip`);
run("zip", ["-q", "-r", "-X", zip, FOLDER, "-x", "*/__pycache__/*"], path.join(ROOT, "out"));
console.log(`\nbuilt ${path.relative(ROOT, zip)} (${(statSync(zip).size / 1048576).toFixed(1)} MB), version ${suitePkg.version}`);
console.log(ids.map((id) => `  ${lock.upstreams[id].title} ${lock.upstreams[id].tag}`).join("\n"));

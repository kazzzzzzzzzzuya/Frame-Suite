// Keeps upstreams.json (which release of each plugin this build contains) and
// the checkouts under .work in step.
//
//   node scripts/upstreams.mjs check   look for newer stable releases; updates upstreams.json
//   node scripts/upstreams.mjs fetch   check out the pinned releases into .work
//
// "Stable" means a published release that is neither a draft nor a
// pre-release. Repositories that publish more than one product (MAKO: its
// Decky plugin and its renderer) name the right one with "tag_prefix".
//
// Most upstreams are built entirely from source (.work/upstream/<id>). One
// with "release_zip" is built from two pinned pieces: its frontend from source
// (.work/src/<id>/<frontend_dir>, so it can share Frame Suite's connection to
// Decky) and its backend and binaries from its own release zip, checked
// against "zip_sha256" and unpacked to .work/upstream/<id>.
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { appendFileSync, existsSync, mkdirSync, readdirSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const LOCK = path.join(ROOT, "upstreams.json");
const WORK = path.join(ROOT, ".work");

export const readLock = () => JSON.parse(readFileSync(LOCK, "utf8"));
const writeLock = (lock) => writeFileSync(LOCK, JSON.stringify(lock, null, 2) + "\n");
const git = (args, cwd) => execFileSync("git", args, { cwd, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }).trim();
const sha256 = (file) => createHash("sha256").update(readFileSync(file)).digest("hex");

// "plugin-v5.0.10" with prefix "plugin-v" -> "5.0.10"; "v0.14.4" -> "0.14.4".
export const versionOf = (tag, prefix = "") => String(tag).slice(prefix.length).replace(/^v/, "");
// "0.14.4" -> [0, 14, 4]; pre-release suffixes are cut off first.
export const versionKey = (tag) => (String(tag).split("-")[0].match(/\d+/g) || []).map(Number);
export const newer = (a, b) => {
  const [x, y] = [versionKey(a), versionKey(b)];
  for (let i = 0; i < Math.max(x.length, y.length); i++) {
    if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) > (y[i] || 0);
  }
  return false;
};
export const zipName = (up, tag = up.tag) => up.release_zip.replace("{version}", versionOf(tag, up.tag_prefix || ""));
export const frontendDir = (id, up) =>
  up.release_zip ? path.join(WORK, "src", id, up.frontend_dir || "") : path.join(WORK, "upstream", id);
export const backendDir = (id) => path.join(WORK, "upstream", id);

/** The newest stable release among `releases` (GitHub's list) with the prefix, or null. */
export function pickRelease(releases, prefix = "") {
  let best = null;
  for (const r of Array.isArray(releases) ? releases : []) {
    if (!r || r.draft || r.prerelease || typeof r.tag_name !== "string") continue;
    if (!r.tag_name.startsWith(prefix)) continue;
    if (!/^\d+(\.\d+)*$/.test(versionOf(r.tag_name, prefix))) continue;
    if (!best || newer(versionOf(r.tag_name, prefix), versionOf(best.tag_name, prefix))) best = r;
  }
  return best;
}

async function github(url) {
  const headers = { Accept: "application/vnd.github+json", "User-Agent": "frame-suite-build" };
  const token = process.env.GITHUB_TOKEN || process.env.GH_TOKEN;
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(url, { headers });
  if (!res.ok) throw new Error(`${url}: GitHub answered ${res.status}`);
  return res.json();
}

async function latestRelease(up) {
  const releases = up.tag_prefix
    ? await github(`https://api.github.com/repos/${up.repo}/releases?per_page=50`)
    : [await github(`https://api.github.com/repos/${up.repo}/releases/latest`)];
  const rel = pickRelease(releases, up.tag_prefix || "");
  if (!rel) throw new Error(`${up.repo}: no stable release${up.tag_prefix ? ` named ${up.tag_prefix}*` : ""}`);
  return rel;
}

async function check() {
  const lock = readLock();
  const changes = [];
  for (const [id, up] of Object.entries(lock.upstreams)) {
    const rel = await latestRelease(up);
    const prefix = up.tag_prefix || "";
    if (rel.tag_name === up.tag) {
      console.log(`${id}: ${up.tag} is current`);
    } else if (!newer(versionOf(rel.tag_name, prefix), versionOf(up.tag, prefix))) {
      // A withdrawn release makes "latest" point at an older one: stay where we are.
      console.log(`${id}: latest stable is ${rel.tag_name}, not newer than ${up.tag}; kept`);
    } else {
      console.log(`${id}: ${up.tag} -> ${rel.tag_name}`);
      changes.push({ id, title: up.title, from: up.tag, to: rel.tag_name, url: rel.html_url });
      up.tag = rel.tag_name;
      delete up.commit; // set again by "fetch"
      if (up.release_zip) {
        // GitHub's own checksum of the asset, where it gives one; else "fetch" pins what it downloads.
        const asset = (rel.assets || []).find((a) => a.name === zipName(up));
        if (!asset) throw new Error(`${id}: release ${rel.tag_name} has no ${zipName(up)}`);
        const digest = String(asset.digest || "");
        if (digest.startsWith("sha256:")) up.zip_sha256 = digest.slice(7);
        else delete up.zip_sha256;
      }
    }
  }
  if (changes.length) writeLock(lock);
  const summary = changes.map((c) => `- ${c.title} ${c.from} → [${c.to}](${c.url})`).join("\n");
  if (process.env.GITHUB_OUTPUT) {
    appendFileSync(process.env.GITHUB_OUTPUT, `changed=${changes.length ? "true" : "false"}\n`);
    appendFileSync(process.env.GITHUB_OUTPUT, `summary<<EOF_SUMMARY\n${summary}\nEOF_SUMMARY\n`);
    appendFileSync(process.env.GITHUB_OUTPUT, `title=${changes.map((c) => `${c.title} ${c.to}`).join(", ")}\n`);
  }
  return changes;
}

function checkout(dir, up, id) {
  let have = null;
  try {
    have = existsSync(path.join(dir, ".git")) ? git(["rev-parse", "HEAD"], dir) : null;
  } catch {
    have = null;
  }
  if (!have || !up.commit || have !== up.commit) {
    rmSync(dir, { recursive: true, force: true });
    mkdirSync(path.dirname(dir), { recursive: true });
    git(["clone", "--quiet", "--depth", "1", "--branch", up.tag, `https://github.com/${up.repo}.git`, dir], ROOT);
    have = git(["rev-parse", "HEAD"], dir);
  }
  if (up.commit && have !== up.commit) {
    // The tag was moved after it was pinned: a human should look before this ships.
    throw new Error(`${id}: tag ${up.tag} now points at ${have}, pinned was ${up.commit}`);
  }
  return have;
}

function unpackZip(id, up) {
  const cache = path.join(WORK, "cache");
  mkdirSync(cache, { recursive: true });
  const name = zipName(up);
  const url = `https://github.com/${up.repo}/releases/download/${up.tag}/${name}`;
  const cached = up.zip_sha256 ? path.join(cache, up.zip_sha256) : null;
  let file = cached && existsSync(cached) && sha256(cached) === up.zip_sha256 ? cached : null;
  if (!file) {
    const part = path.join(cache, `${id}.zip.part`);
    execFileSync("curl", ["-fsSL", "--retry", "4", "--retry-delay", "3", "-o", part, url], { stdio: "inherit" });
    const got = sha256(part);
    if (up.zip_sha256 && got !== up.zip_sha256) throw new Error(`${id}: ${name} does not match its pinned SHA-256`);
    up.zip_sha256 = got;
    file = path.join(cache, got);
    renameSync(part, file);
  }
  const dir = backendDir(id);
  const stampFile = path.join(dir, ".frame-suite-zip");
  if (existsSync(stampFile) && readFileSync(stampFile, "utf8") === up.zip_sha256) return;
  const tmp = `${dir}.tmp`;
  rmSync(tmp, { recursive: true, force: true });
  mkdirSync(tmp, { recursive: true });
  execFileSync("unzip", ["-q", file, "-d", tmp], { stdio: "inherit" });
  const tops = readdirSync(tmp);
  if (tops.length !== 1) throw new Error(`${id}: ${name} should hold one folder, holds ${tops.join(", ")}`);
  rmSync(dir, { recursive: true, force: true });
  renameSync(path.join(tmp, tops[0]), dir);
  rmSync(tmp, { recursive: true, force: true });
  if (!existsSync(path.join(dir, "main.py"))) throw new Error(`${id}: ${name} has no main.py`);
  writeFileSync(stampFile, up.zip_sha256);
}

function fetchAll() {
  const lock = readLock();
  let dirty = false;
  for (const [id, up] of Object.entries(lock.upstreams)) {
    const src = up.release_zip ? path.join(WORK, "src", id) : backendDir(id);
    const had = up.commit;
    const have = checkout(src, up, id);
    if (!had) {
      up.commit = have;
      dirty = true;
    }
    if (up.release_zip) {
      const pinned = up.zip_sha256;
      unpackZip(id, up);
      if (up.zip_sha256 !== pinned) dirty = true;
    }
    console.log(`${id}: ${up.repo} ${up.tag} (${have.slice(0, 10)})${up.release_zip ? ` + ${zipName(up)}` : ""}`);
  }
  if (dirty) writeLock(lock);
}

const cmd = process.argv[2];
if (import.meta.url === `file://${process.argv[1]}`) {
  try {
    if (cmd === "check") await check();
    else if (cmd === "fetch") fetchAll();
    else {
      console.error("usage: upstreams.mjs check | fetch");
      process.exit(2);
    }
  } catch (e) {
    console.error(`error: ${e.message}`);
    process.exit(1);
  }
}

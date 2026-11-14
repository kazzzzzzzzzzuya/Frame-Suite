// Keeps upstreams.json (which release of each plugin this build contains) and
// the checkouts under .work/upstream in step.
//
//   node scripts/upstreams.mjs check   look for newer stable releases; updates upstreams.json
//   node scripts/upstreams.mjs fetch   check out the pinned releases into .work/upstream
//
// "Stable" is GitHub's "latest release" of each repository: drafts and
// pre-releases never count.
import { execFileSync } from "node:child_process";
import { appendFileSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const LOCK = path.join(ROOT, "upstreams.json");
const WORK = path.join(ROOT, ".work", "upstream");

export const readLock = () => JSON.parse(readFileSync(LOCK, "utf8"));
const writeLock = (lock) => writeFileSync(LOCK, JSON.stringify(lock, null, 2) + "\n");
const git = (args, cwd) => execFileSync("git", args, { cwd, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }).trim();

// "v0.14.4" -> [0, 14, 4]; pre-release suffixes are cut off first.
export const versionKey = (tag) => (String(tag).split("-")[0].match(/\d+/g) || []).map(Number);
export const newer = (a, b) => {
  const [x, y] = [versionKey(a), versionKey(b)];
  for (let i = 0; i < Math.max(x.length, y.length); i++) {
    if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) > (y[i] || 0);
  }
  return false;
};

async function latestRelease(repo) {
  const headers = { Accept: "application/vnd.github+json", "User-Agent": "frame-suite-build" };
  const token = process.env.GITHUB_TOKEN || process.env.GH_TOKEN;
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`https://api.github.com/repos/${repo}/releases/latest`, { headers });
  if (!res.ok) throw new Error(`${repo}: GitHub answered ${res.status}`);
  const rel = await res.json();
  if (rel.draft || rel.prerelease || !rel.tag_name) throw new Error(`${repo}: latest release is not a stable one`);
  return { tag: rel.tag_name, url: rel.html_url, notes: (rel.body || "").trim() };
}

async function check() {
  const lock = readLock();
  const changes = [];
  for (const [id, up] of Object.entries(lock.upstreams)) {
    const rel = await latestRelease(up.repo);
    if (rel.tag === up.tag) {
      console.log(`${id}: ${up.tag} is current`);
    } else if (!newer(rel.tag, up.tag)) {
      // A withdrawn release makes "latest" point at an older one: stay where we are.
      console.log(`${id}: latest stable is ${rel.tag}, not newer than ${up.tag}; kept`);
    } else {
      console.log(`${id}: ${up.tag} -> ${rel.tag}`);
      changes.push({ id, title: up.title, from: up.tag, to: rel.tag, url: rel.url });
      up.tag = rel.tag;
      delete up.commit; // set again by "fetch"
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

function fetchAll() {
  const lock = readLock();
  mkdirSync(WORK, { recursive: true });
  let dirty = false;
  for (const [id, up] of Object.entries(lock.upstreams)) {
    const dir = path.join(WORK, id);
    let have = null;
    try {
      have = existsSync(path.join(dir, ".git")) ? git(["rev-parse", "HEAD"], dir) : null;
    } catch {
      have = null;
    }
    if (!have || (up.commit && have !== up.commit) || !up.commit) {
      rmSync(dir, { recursive: true, force: true });
      git(["clone", "--quiet", "--depth", "1", "--branch", up.tag, `https://github.com/${up.repo}.git`, dir], ROOT);
      have = git(["rev-parse", "HEAD"], dir);
    }
    if (up.commit && have !== up.commit) {
      // The tag was moved after it was pinned: a human should look before this ships.
      throw new Error(`${id}: tag ${up.tag} now points at ${have}, pinned was ${up.commit}`);
    }
    if (!up.commit) {
      up.commit = have;
      dirty = true;
    }
    console.log(`${id}: ${up.repo} ${up.tag} (${have.slice(0, 10)})`);
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

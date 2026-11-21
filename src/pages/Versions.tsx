import { ButtonItem, DropdownItem, PanelSection, PanelSectionRow } from "@decky/ui";
import { useEffect, useState } from "react";
import { getUpdates, Info, prepareUpdate, Release, setProfile, setToolboxFg, Updates } from "../backend";
import { confirm, GREEN, Header, Note, RED, toast, Toggle } from "../ui";

const PLUGIN_NAME = "Frame Suite"; // must equal plugin.json "name": Decky finds the installed plugin by it
const UPDATE = 2;
const DOWNGRADE = 3;

async function install(r: Release, type: number) {
  const fn = window.DeckyBackend?.callable?.("utilities/install_plugin");
  if (!fn) {
    toast("Update", "Decky's installer is not reachable from here. Download the zip from the release page and use Decky → Developer → Install Plugin from ZIP File.");
    return;
  }
  try {
    // Decky removes the old build first and runs its uninstall hooks: tell the backend this is an update.
    await prepareUpdate().catch(() => undefined);
    await fn(r.url, PLUGIN_NAME, r.version, r.sha256 ?? "", type);
  } catch (e) {
    toast("Update", `Decky could not start the installation: ${e}`);
  }
}

export function Versions({ info, onInfo }: { info: Info; onInfo: (i: Info) => void }) {
  const [updates, setUpdates] = useState<Updates | null>(null);
  const [checking, setChecking] = useState(false);

  const check = async (force: boolean) => {
    setChecking(true);
    setUpdates(await getUpdates(force).catch((e) => ({ ok: false, error: String(e), current: info.version, releases: [] })));
    setChecking(false);
  };
  useEffect(() => {
    check(false);
  }, []);

  const detected = info.profiles.find((p) => p.id === info.detected);
  const active = info.profiles.find((p) => p.id === info.profile);
  const others = (updates?.releases ?? []).filter((r) => r.version !== info.version);
  const isOlder = (v: string) => {
    const k = (x: string) => (x.match(/\d+/g) ?? []).slice(0, 4).map(Number);
    const [a, b] = [k(v), k(info.version)];
    for (let i = 0; i < 4; i++) if ((a[i] ?? 0) !== (b[i] ?? 0)) return (a[i] ?? 0) < (b[i] ?? 0);
    return false;
  };

  return (
    <>
      <PanelSection>
        <Header>Chip</Header>
        <Note>{info.chip.cpu || "Unknown processor"}{info.chip.product ? `\n${info.chip.vendor} ${info.chip.product}` : ""}</Note>
        <PanelSectionRow>
          <DropdownItem
            label="Settings profile"
            rgOptions={[
              { data: "", label: `Automatic (${detected?.label ?? info.detected})` },
              ...info.profiles.map((p) => ({ data: p.id, label: p.label })),
            ]}
            selectedOption={info.profile_chosen ?? ""}
            onChange={async (o) => onInfo(await setProfile(o.data ? String(o.data) : null))}
          />
        </PanelSectionRow>
        {active?.source && <Note>{active.source}</Note>}
        <Note>A profile only decides what Boost sets up for games you switch on from now on.</Note>
      </PanelSection>

      <PanelSection>
        <Header>What is inside</Header>
        <Note>Frame Suite {info.version}{info.built ? `\nBuilt ${new Date(info.built).toLocaleDateString()}` : ""}</Note>
        {info.subs.map((s) => (
          <Note key={s.id} color={s.ok ? undefined : RED}>
            {s.title} {s.version}{`\n${s.repo}`}{s.ok ? "" : `\nDid not load: ${s.error}`}
          </Note>
        ))}
      </PanelSection>

      <PanelSection>
        <Header>Updates</Header>
        {updates?.ok && updates.newer && (
          <>
            <Note color={GREEN}>Frame Suite {updates.latest} is available.{updates.releases[0]?.notes ? `\n${updates.releases[0].notes}` : ""}</Note>
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => install(updates.releases[0], UPDATE)}>Update to {updates.latest}</ButtonItem>
            </PanelSectionRow>
          </>
        )}
        {updates?.ok && !updates.newer && <Note>Up to date ({updates.current}). A new build appears here after any of the four plugins publishes a stable release.</Note>}
        {updates && !updates.ok && <Note color={RED}>{updates.error}</Note>}
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={checking} onClick={() => check(true)}>{checking ? "Checking…" : "Check for updates"}</ButtonItem>
        </PanelSectionRow>
        {updates?.ok && others.length > 0 && (
          <PanelSectionRow>
            <DropdownItem
              label="Install another version"
              description="Pick one and confirm. Your settings and everything set up in games stay."
              strDefaultLabel="Choose a version"
              rgOptions={others.map((r) => ({
                data: r.version,
                label: `${r.version}${r.version === updates.latest ? " · latest" : ""}${isOlder(r.version) ? " · older" : ""}${
                  r.published ? ` · ${new Date(r.published).toLocaleDateString(undefined, { day: "numeric", month: "short" })}` : ""
                }`,
              }))}
              selectedOption={null}
              onChange={async (o) => {
                const r = others.find((x) => x.version === o.data);
                if (!r) return;
                const back = isOlder(r.version);
                if (await confirm(
                  back ? `Go back to ${r.version}?` : `Install ${r.version}?`,
                  `Decky installs ${r.version} over ${info.version}. Your settings and everything set up in games stay.`,
                  "Install",
                ))
                  install(r, back ? DOWNGRADE : UPDATE);
              }}
            />
          </PanelSectionRow>
        )}
      </PanelSection>

      <PanelSection>
        <Header>For other plugins</Header>
        <Note>What Boost set up per game is written to{`\n${info.bridge}\n`}for tools like the Legion Go Toolbox to read.</Note>
        <PanelSectionRow>
          <Toggle
            label="Let the Legion Go Toolbox use lsfg-vk"
            description="For its battery goals: lsfg-vk is prepared for those games (off until needed, ready from their next start) and switched on while the battery needs it, so the game makes half the frames and the screen still shows the same. Off takes back everything it changed."
            checked={info.toolbox_fg}
            onChange={async (v) => onInfo(await setToolboxFg(v))}
          />
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}

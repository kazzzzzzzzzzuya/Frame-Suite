import { ButtonItem, DropdownItem, PanelSection, PanelSectionRow } from "@decky/ui";
import { useEffect, useState } from "react";
import { getUpdates, Info, Release, setProfile, Updates } from "../backend";
import { confirm, GREEN, Note, RED, toast } from "../ui";

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
  const older = (updates?.releases ?? []).filter((r) => r.version !== info.version && r.version !== updates?.latest).slice(0, 4);

  return (
    <>
      <PanelSection title="Chip">
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

      <PanelSection title="What is inside">
        <Note>Frame Suite {info.version}{info.built ? `\nBuilt ${new Date(info.built).toLocaleDateString()}` : ""}</Note>
        {info.subs.map((s) => (
          <Note key={s.id} color={s.ok ? undefined : RED}>
            {s.title} {s.version}{`\n${s.repo}`}{s.ok ? "" : `\nDid not load: ${s.error}`}
          </Note>
        ))}
      </PanelSection>

      <PanelSection title="Updates">
        {updates?.ok && updates.newer && (
          <>
            <Note color={GREEN}>Frame Suite {updates.latest} is available.{updates.releases[0]?.notes ? `\n${updates.releases[0].notes}` : ""}</Note>
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => install(updates.releases[0], UPDATE)}>Update to {updates.latest}</ButtonItem>
            </PanelSectionRow>
          </>
        )}
        {updates?.ok && !updates.newer && <Note>Up to date ({updates.current}). A new build appears here after any of the three plugins publishes a stable release.</Note>}
        {updates && !updates.ok && <Note color={RED}>{updates.error}</Note>}
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={checking} onClick={() => check(true)}>{checking ? "Checking…" : "Check for updates"}</ButtonItem>
        </PanelSectionRow>
        {older.map((r) => (
          <PanelSectionRow key={r.version}>
            <ButtonItem
              layout="below"
              description={r.published ? `Published ${new Date(r.published).toLocaleDateString()}` : undefined}
              onClick={async () => {
                if (await confirm(`Go back to ${r.version}?`, "Decky installs that earlier build over this one. Your settings and everything set up in games stay.", "Install"))
                  install(r, DOWNGRADE);
              }}
            >
              Go back to {r.version}
            </ButtonItem>
          </PanelSectionRow>
        ))}
      </PanelSection>

      <PanelSection title="For other plugins">
        <Note>What Boost set up per game is written to{`\n${info.bridge}\n`}for tools like the Legion Go Toolbox to read.</Note>
      </PanelSection>
    </>
  );
}

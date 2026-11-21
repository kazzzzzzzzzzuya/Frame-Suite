import { ButtonItem, PanelSection, PanelSectionRow } from "@decky/ui";
import { useEffect, useState } from "react";
import { getSetup, SetupState } from "../backend";
import { guideSeen, nav } from "../nav";
import { Header, InfoBox } from "../ui";

/** Getting started: shown by itself the first time Frame Suite opens, and again from the first page.
 *  Steps that are already done get a tick. Its boxes stay when R1 hides the other explanations. */
export function Guide() {
  const [setup, setSetup] = useState<SetupState | null>(null);
  useEffect(() => {
    getSetup().then(setSetup).catch(() => undefined);
    guideSeen.mark();
  }, []);
  const ready = setup ? setup.mako.installed || setup.lsfg.installed || setup.optiscaler.installed : false;

  return (
    <>
      <PanelSection>
        <InfoBox tone="info">
          Frame Suite makes games look smoother and run faster. It holds MAKO, lsfg-vk, OptiScaler (FSR 4) and HelixSR,
          and picks the right one for each game and for your chip with one switch: Boost.
        </InfoBox>
      </PanelSection>

      <PanelSection>
        <Header>1 · Set up once</Header>
        <InfoBox tone={ready ? "good" : "info"}>
          {ready ? "Done. " : ""}Open Setup and choose "Set up everything that is missing". It installs MAKO's renderer,
          lsfg-vk and OptiScaler. HelixSR is optional. lsfg-vk also needs Lossless Scaling from the Steam store; MAKO
          does not.
        </InfoBox>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => nav.go("setup")}>Open Setup</ButtonItem>
        </PanelSectionRow>
        <InfoBox tone="warn">
          Uninstall the separate MAKO, LSFG-VK, Decky-Framegen and HelixSR Manager plugins if you have them: two copies get in each
          other's way.
        </InfoBox>
      </PanelSection>

      <PanelSection>
        <Header>2 · Boost a game</Header>
        <InfoBox tone="info">
          Pick the game on the first page (a running game is picked for you) and switch Frame generation on (Frame
          Suite calls it Boost). It says what it chose and why:{"\n"}
          • MAKO (most games): start the game first, switch it on, then restart the game once.{"\n"}
          • FSR 4 (games with DLSS, FSR or XeSS): close the game first, its files are changed. Then choose DLSS in the
          game's graphics settings.{"\n"}
          If something is still missing, a note under the switch says what to do.
        </InfoBox>
      </PanelSection>

      <PanelSection>
        <Header>3 · Adjust, or not</Header>
        <InfoBox tone="info">
          The defaults fit your chip. Quality and Upscaler are right under the switch; everything else ("Frame rate on
          screen": 72 is even on the Legion Go's 144 Hz screen, "Most generated frames") is under Expert on the first
          page. Launch options are written and removed for you. Switching it off puts the game back as it was.
        </InfoBox>
        <InfoBox tone="info">
          With LeGo Decky Toolbox installed there is nothing to link: choosing Smoothest for a game on its Game tab
          switches frame generation on here by itself, and its power and frame-rate settings follow what Frame Suite
          does in each game.
        </InfoBox>
      </PanelSection>

      <PanelSection>
        <Header>Good to know</Header>
        <InfoBox tone="info">
          R1 shows and hides the explanations on Frame Suite's pages (hidden at first). B goes back to the first page. New versions are
          offered on Chip &amp; versions, where an older one can also be put back.
        </InfoBox>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => nav.go("home")}>Go to the games</ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}

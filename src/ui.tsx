import { ConfirmModal, Field, PanelSectionRow, showModal } from "@decky/ui";
import { toaster } from "@decky/api";
import type { ReactNode } from "react";

export const GREEN = "#59bf40";
export const AMBER = "#e0b040";
export const RED = "#e06060";

export function Note({ children, color }: { children: ReactNode; color?: string }) {
  return (
    <PanelSectionRow>
      <Field focusable bottomSeparator="none" padding="none" childrenLayout="below" childrenContainerWidth="max">
        <div style={{ fontSize: "0.82em", lineHeight: 1.35, color: color ?? "#b8bcbf", whiteSpace: "pre-wrap", padding: "4px 0" }}>
          {children}
        </div>
      </Field>
    </PanelSectionRow>
  );
}

export const toast = (title: string, body: string) => toaster.toast({ title, body });

export function confirm(title: string, body: ReactNode, okText = "Continue"): Promise<boolean> {
  return new Promise((resolve) => {
    let settled = false;
    const done = (v: boolean) => {
      if (!settled) {
        settled = true;
        resolve(v);
      }
    };
    showModal(
      <ConfirmModal
        strTitle={title}
        strDescription={body}
        strOKButtonText={okText}
        onOK={() => done(true)}
        onCancel={() => done(false)}
        closeModal={() => done(false)}
      />,
    );
  });
}

export const when = (t: number) => new Date(t * 1000).toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });

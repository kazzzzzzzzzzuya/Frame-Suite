// "@decky/api" for the bundled upstream plugin "lsfg" (see scoped.ts).
import { scoped } from "./scoped";

export * from "@decky/api";
const s = scoped("lsfg");
export const call = s.call;
export const callable = s.callable;
export const addEventListener = s.addEventListener;
export const removeEventListener = s.removeEventListener;

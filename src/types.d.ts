declare module "upstream:*" {
  import type { Plugin } from "@decky/api";
  const factory: () => Plugin;
  export default factory;
}

interface Window {
  DeckyBackend?: { callable?: (route: string) => (...args: unknown[]) => Promise<unknown> };
}

// Types the renderer's install leaves out (no @types/react-dom there), and CSS imports esbuild bundles.
declare module "react-dom/client" {
  import type { ReactNode } from "react";
  export function createRoot(el: Element): { render(node: ReactNode): void; unmount(): void };
}
declare module "*.css";

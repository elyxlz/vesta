import { test as base } from "@playwright/test";

export interface VisualOptions {
  theme: "dark" | "light";
}

export const test = base.extend<VisualOptions>({
  theme: ["dark", { option: true }],
});

export { expect } from "@playwright/test";

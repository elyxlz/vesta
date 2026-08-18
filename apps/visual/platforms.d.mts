export type PlatformId =
  | "ios"
  | "android"
  | "android-galaxy"
  | "ios-dark"
  | "android-dark"
  | "android-galaxy-dark"
  | "web"
  | "desktop"
  | "web-narrow"
  | "web-dark"
  | "desktop-dark"
  | "web-narrow-dark";
export type RunnerId = "ios" | "android" | "android-galaxy" | "web";
export type FamilyId = "mobile" | "web";
export type Theme = "light" | "dark";
export type Frame = "phone" | "browser" | "desktop-window" | "phone-browser";

export interface PlatformDefinition {
  label: string;
  family: FamilyId;
  theme: Theme;
  frame: Frame;
  runner: RunnerId;
}
export interface RunnerDefinition {
  label: string;
  workspace: string;
  script: string;
  args: string[];
  gentleArgs: string[];
  reportDirectory: string;
}
export interface FamilyDefinition {
  label: string;
  registry: string;
}

export const visualRoot: string;
export const appsRoot: string;
export const PLATFORMS: Record<PlatformId, PlatformDefinition>;
export const RUNNERS: Record<RunnerId, RunnerDefinition>;
export const FAMILIES: Record<FamilyId, FamilyDefinition>;
export function platformFamily(id: string): FamilyId;
export function runnerOf(id: string): RunnerId;
export function platformsOfFamily(family: FamilyId): PlatformId[];
export function themedSibling(id: string, theme: Theme): PlatformId | null;

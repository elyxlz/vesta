import type { FamilyId, PlatformId } from "./platforms.d.mts";

export interface RegistryScenario {
  id: string;
  title: string;
  description: string;
  group: string;
  screenshot: string;
  family: FamilyId;
  platforms?: PlatformId[];
  [state: string]: unknown;
}
export interface Registry {
  version: 1;
  family: FamilyId;
  appId?: string;
  flows?: string[];
  scenarios: RegistryScenario[];
}
export function validateRegistry(
  manifest: unknown,
  family: FamilyId,
  options?: { flowRoot?: string },
): Registry;
export function loadRegistry(family: FamilyId): Promise<Registry>;
export function loadAllRegistries(): Promise<Record<FamilyId, Registry>>;
export function scenarioOnPlatform(
  scenario: { platforms?: string[] },
  platform: string,
): boolean;
export function scenariosForPlatform(
  registry: Registry,
  platform: string,
): RegistryScenario[];
export function excludedNote(scenario: { platforms?: string[] }): string;

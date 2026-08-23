export interface ScenarioInputs {
  files: string[];
  extras: string[];
}
export function alwaysOnInputs(): Promise<string[]>;
export function drivesFileFor(id: string): Promise<string>;
export function scenarioInputs(
  id: string,
  card: unknown,
): Promise<ScenarioInputs>;

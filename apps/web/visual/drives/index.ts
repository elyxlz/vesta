import type { Scenario } from "../harness/scenario-state";
import { ONBOARDING } from "./onboarding";

// Every web scenario by id: the state it starts from, how to reach it, and how
// to know it settled. scenarios.json carries the matching card for each id.
export const SCENARIOS: Record<string, Scenario> = {
  ...ONBOARDING,
};

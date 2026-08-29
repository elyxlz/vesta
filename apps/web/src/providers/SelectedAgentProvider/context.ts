import { createContext, useContext } from "react";
import type { BackupInfo } from "@/api";
import type { AgentRequest } from "@/stores/use-agent-ops";
import type { AgentActivityState } from "@vesta/core";
import type { AgentRow } from "@/lib/types";
import type { OrbVisualState } from "@vesta/core";

// Context + hook live here, separate from the SelectedAgentProvider component, so
// the SelectedAgentContext identity is stable across Fast Refresh. Co-locating them
// with the component made every edit re-create the context, detaching mounted
// consumers ("useSelectedAgent must be used within SelectedAgentProvider" on hot
// reload).
export interface SelectedAgentContextValue {
  name: string;
  agent: AgentRow;
  agentState: AgentActivityState;
  setAgentState: (state: AgentActivityState) => void;

  operation: AgentRequest;
  error: string;
  statusLabel: string;
  orbState: OrbVisualState;
  isBusy: boolean;

  start: () => void;
  stop: () => void;
  restart: () => Promise<void>;
  backup: () => void;
  backups: BackupInfo[];
  // The last read failed. An empty list alone cannot say whether the agent has no snapshots.
  backupsFailed: boolean;
  refreshBackups: () => Promise<void>;
  restore: (backupId: string) => void;
  removeBackup: (backupId: string) => Promise<void>;
  remove: () => Promise<void>;
}

export const SelectedAgentContext =
  createContext<SelectedAgentContextValue | null>(null);

export function useSelectedAgent() {
  const context = useContext(SelectedAgentContext);
  if (!context) {
    throw new Error(
      "useSelectedAgent must be used within SelectedAgentProvider",
    );
  }
  return context;
}

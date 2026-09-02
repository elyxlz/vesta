import { createContext, useContext } from "react";
import type { BackupInfo } from "@/api";
import type { AgentRequest } from "@/stores/use-agent-ops";
import type { OrbVisualState, AgentRow } from "@vesta/core";

export interface SelectedAgentContextValue {
  name: string;
  agent: AgentRow;

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

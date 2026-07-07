import { createContext, useContext } from "react";
import type { BackupInfo } from "@/api";
import type { AgentOperation } from "@/stores/use-agent-ops";
import type { AgentInfo, AgentActivityState } from "@/lib/types";
import type { OrbVisualState } from "@/components/Orb/styles";

// Context + hook live here, separate from the SelectedAgentProvider component, so
// the SelectedAgentContext identity is stable across Fast Refresh. Co-locating them
// with the component made every edit re-create the context, detaching mounted
// consumers ("useSelectedAgent must be used within SelectedAgentProvider" on hot
// reload).
export interface SelectedAgentContextValue {
  name: string;
  agent: AgentInfo;
  agentState: AgentActivityState;
  setAgentState: (state: AgentActivityState) => void;

  operation: AgentOperation;
  error: string;
  statusLabel: string;
  orbState: OrbVisualState;
  isBusy: boolean;

  start: () => void;
  stop: () => void;
  restart: () => Promise<void>;
  rebuild: () => void;
  backup: () => void;
  backups: BackupInfo[];
  refreshBackups: () => Promise<void>;
  restore: (backupId: string) => void;
  removeBackup: (backupId: string) => void;
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

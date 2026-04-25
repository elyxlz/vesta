import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import {
  startAgent,
  stopAgent,
  restartAgent,
  rebuildAgent,
  createBackup,
  listBackups,
  restoreBackup,
  deleteBackup,
  deleteAgent,
  type BackupInfo,
} from "@/api";
import { useAgentOps, type AgentOperation } from "@/stores/use-agent-ops";
import type { AgentInfo, AgentActivityState } from "@/lib/types";
import {
  getAgentVisualStatus,
  type OrbVisualState,
} from "@/components/Orb/styles";

interface SelectedAgentContextValue {
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
  restart: () => void;
  rebuild: () => void;
  backup: () => void;
  backups: BackupInfo[];
  refreshBackups: () => Promise<void>;
  restore: (backupId: string) => void;
  removeBackup: (backupId: string) => void;
  remove: () => Promise<void>;
}

const SelectedAgentContext = createContext<SelectedAgentContextValue | null>(
  null,
);

export function SelectedAgentProvider({
  agent,
  children,
}: {
  agent: AgentInfo;
  children: ReactNode;
}) {
  const name = agent.name;
  const [agentState, setAgentState] = useState<AgentActivityState>(
    agent.activityState,
  );

  const withOp = useAgentOps((s) => s.withOp);
  const removeAgentOp = useAgentOps((s) => s.removeAgent);
  const opState = useAgentOps((s) => s.getOp(name));
  const isBusy = opState.operation !== "idle";

  const { label: statusLabel, orbState } = getAgentVisualStatus(
    agent,
    opState.operation,
    opState.error,
    agentState,
  );

  const start = () => {
    withOp(
      name,
      "starting",
      async () => {
        await startAgent(name);
      },
      "start failed",
    );
  };

  const stop = () => {
    withOp(
      name,
      "stopping",
      async () => {
        await stopAgent(name);
      },
      "stop failed",
    );
  };

  const restart = () => {
    withOp(
      name,
      "starting",
      async () => {
        await restartAgent(name);
      },
      "restart failed",
    );
  };

  const rebuild = () => {
    withOp(
      name,
      "rebuilding",
      async () => {
        await rebuildAgent(name);
      },
      "rebuild failed",
    );
  };

  const [backups, setBackups] = useState<BackupInfo[]>([]);

  const refreshBackups = async () => {
    if (!name) return;
    try {
      setBackups(await listBackups(name));
    } catch {
      /* ignore */
    }
  };

  useEffect(() => {
    refreshBackups();
  }, [name]);

  const backup = () => {
    withOp(
      name,
      "backing-up",
      async () => {
        await createBackup(name);
        await refreshBackups();
      },
      "backup failed",
    );
  };

  const restore = (backupId: string) => {
    withOp(
      name,
      "restoring",
      async () => {
        await restoreBackup(name, backupId);
        await refreshBackups();
      },
      "restore failed",
    );
  };

  const removeBackup = (backupId: string) => {
    withOp(
      name,
      "deleting",
      async () => {
        await deleteBackup(name, backupId);
        await refreshBackups();
      },
      "delete backup failed",
    );
  };

  const remove = async () => {
    await withOp(name, "deleting", () => deleteAgent(name), "delete failed");
    removeAgentOp(name);
  };

  const value: SelectedAgentContextValue = {
    name,
    agent,
    agentState,
    setAgentState,
    operation: opState.operation,
    error: opState.error,
    statusLabel,
    orbState,
    isBusy,
    start,
    stop,
    restart,
    rebuild,
    backup,
    backups,
    refreshBackups,
    restore,
    removeBackup,
    remove,
  };

  return (
    <SelectedAgentContext.Provider value={value}>
      {children}
    </SelectedAgentContext.Provider>
  );
}

export function useSelectedAgent() {
  const context = useContext(SelectedAgentContext);
  if (!context) {
    throw new Error(
      "useSelectedAgent must be used within SelectedAgentProvider",
    );
  }
  return context;
}

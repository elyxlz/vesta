import { useEffect, useState, type ReactNode } from "react";
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
import { useRestartPending } from "@/stores/use-restart-pending";
import type { AgentInfo, AgentActivityState } from "@/lib/types";
import { getAgentVisualStatus } from "@/components/Orb/styles";
import { SelectedAgentContext } from "./context";
import type { SelectedAgentContextValue } from "./context";

export { useSelectedAgent } from "./context";

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
  const clearRestartPending = useRestartPending((s) => s.clearPending);
  const opState = useAgentOps((s) => s.getOp(name));
  const isBusy = opState.operation !== "idle";

  const { label: statusLabel, orbState } = getAgentVisualStatus(
    agent,
    opState.operation,
    opState.error,
    agentState,
  );

  const op =
    (operation: AgentOperation, run: () => Promise<unknown>, failure: string) =>
    () =>
      withOp(
        name,
        operation,
        async () => {
          await run();
        },
        failure,
      );

  const start = op("starting", () => startAgent(name), "start failed");
  const stop = op("stopping", () => stopAgent(name), "stop failed");
  // A restart/rebuild applies any pending saved changes, so clear the "restart to apply" reminder on
  // success (the run callback throws on failure, so a failed restart keeps the reminder). This is the
  // single owner of clearing it, whichever surface (navbar button, agent menu) triggers the restart.
  const restart = op(
    "starting",
    async () => {
      await restartAgent(name);
      clearRestartPending(name);
    },
    "restart failed",
  );
  const rebuild = op(
    "rebuilding",
    async () => {
      await rebuildAgent(name);
      clearRestartPending(name);
    },
    "rebuild failed",
  );

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
    if (!name) return;
    let ignore = false;
    listBackups(name)
      .then((b) => {
        if (!ignore) setBackups(b);
      })
      .catch(() => {});
    return () => {
      ignore = true;
    };
  }, [name]);

  const backup = op(
    "backing-up",
    async () => {
      await createBackup(name);
      await refreshBackups();
    },
    "backup failed",
  );

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

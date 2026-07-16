import { useEffect, useState, type ReactNode } from "react";
import {
  startAgent,
  stopAgent,
  restartAgent,
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
import { errorMessage } from "@/lib/utils";
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
  // A restart applies any pending saved changes, so clear the "restart to apply" reminder on
  // success (the run callback throws on failure, so a failed op keeps the reminder). For most reasons
  // reconcile (use-restart-pending) is the owner — it clears the flag once the agent is observed to
  // restart by any path — and this optimistic clear only hides the ~3s status-poll latency so the
  // button vanishes immediately instead of flickering back. For host-access, which reconcile leaves
  // alone (its mount needs a recreate a boot-time change can't confirm), this button IS the owner:
  // it runs restartAgent, which recreates on mount drift and thus actually applies the grant.
  const applyPending = (
    operation: AgentOperation,
    run: () => Promise<unknown>,
    failure: string,
  ) =>
    op(
      operation,
      async () => {
        await run();
        clearRestartPending(name);
      },
      failure,
    );
  const restart = applyPending(
    "starting",
    () => restartAgent(name),
    "restart failed",
  );
  const [backups, setBackups] = useState<BackupInfo[]>([]);

  const refreshBackups = async () => {
    try {
      setBackups(await listBackups(name));
    } catch {
      /* ignore */
    }
  };

  useEffect(() => {
    let ignore = false;
    listBackups(name)
      .then((fetched) => {
        if (!ignore) setBackups(fetched);
      })
      .catch(() => {
        /* ignore */
      });
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
    void withOp(
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
    void withOp(
      name,
      "deleting",
      async () => {
        await deleteBackup(name, backupId);
        await refreshBackups();
      },
      "delete backup failed",
    );
  };

  // Delete is terminal: unlike the other ops it hands off to the agent's
  // disappearance, not to a new status. So it holds "deleting" on success and
  // lets reconcile drop the op when the agent leaves the list, rather than
  // clearing to idle and flashing the card back to the gray stopped orb.
  const remove = async () => {
    const ops = useAgentOps.getState();
    if (ops.getOp(name).operation !== "idle") return;
    ops.setOp(name, "deleting");
    try {
      await deleteAgent(name);
    } catch (e) {
      ops.setOp(name, "idle", errorMessage(e, "delete failed"));
    }
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
    start: () => void start(),
    stop: () => void stop(),
    restart,
    backup: () => void backup(),
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

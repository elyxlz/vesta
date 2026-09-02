import { useCallback, type ReactNode } from "react";
import { useResource } from "@vesta/core/react";
import { useAgentOps, type AgentRequest } from "@/stores/use-agent-ops";
import { useRestartPending } from "@/stores/use-restart-pending";
import type { AgentRow } from "@vesta/core";
import { errorMessage } from "@/lib/utils";
import { getAgentVisualStatus } from "@/components/Orb/styles";
import { SelectedAgentContext } from "./context";
import type { SelectedAgentContextValue } from "./context";
import {
  createBackup,
  deleteAgent,
  deleteBackup,
  listBackups,
  restartAgent,
  restoreBackup,
  startAgent,
  stopAgent,
} from "@vesta/core";
import { httpClient } from "@/api/client";

export function SelectedAgentProvider({
  agent,
  children,
}: {
  agent: AgentRow;
  children: ReactNode;
}) {
  const name = agent.name;

  const withOp = useAgentOps((s) => s.withOp);
  const clearRestartPending = useRestartPending((s) => s.clearPending);
  const opState = useAgentOps((s) => s.getOp(name));
  // Long-running work started anywhere disables the actions here too, not just work this tab began.
  const isBusy = opState.operation !== "idle" || agent.operation !== null;

  const { label: statusLabel, orbState } = getAgentVisualStatus(
    agent,
    opState.operation,
    opState.error,
    agent.activityState,
  );

  const op =
    (operation: AgentRequest, run: () => Promise<unknown>, failure: string) =>
    () =>
      withOp(
        name,
        operation,
        async () => {
          await run();
        },
        failure,
      );

  const start = op(
    "starting",
    () => startAgent(httpClient, name),
    "start failed",
  );
  const stop = op("stopping", () => stopAgent(httpClient, name), "stop failed");
  // A restart applies any pending saved changes, so clear the "restart to apply" reminder on
  // success (the run callback throws on failure, so a failed op keeps the reminder). For most reasons
  // reconcile (use-restart-pending) is the owner — it clears the flag once the agent is observed to
  // restart by any path — and this optimistic clear only hides the ~3s status-poll latency so the
  // button vanishes immediately instead of flickering back. For host-access, which reconcile leaves
  // alone (its mount needs a recreate a boot-time change can't confirm), this button IS the owner:
  // it runs restartAgent, which recreates on mount drift and thus actually applies the grant.
  const applyPending = (
    operation: AgentRequest,
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
    () => restartAgent(httpClient, name),
    "restart failed",
  );
  // An empty list and a list that never arrived look identical, so the dialog reports a failed
  // read instead of "no snapshots yet". `reload` keeps one identity, so the dialog can re-read
  // the list every time it opens without looping.
  const {
    data: backupList,
    error: backupsError,
    reload,
  } = useResource(name, (key) => listBackups(httpClient, key));
  const backups = backupList ?? [];
  const backupsFailed = backupsError !== null;
  const refreshBackups = useCallback(() => {
    reload();
    return Promise.resolve();
  }, [reload]);

  const backup = op(
    "backing-up",
    async () => {
      await createBackup(httpClient, name);
      await refreshBackups();
    },
    "backup failed",
  );

  const restore = (backupId: string) => {
    void withOp(
      name,
      "restoring",
      async () => {
        await restoreBackup(httpClient, name, backupId);
        await refreshBackups();
      },
      "restore failed",
    );
  };

  // Deleting a snapshot is not an agent lifecycle operation (vestad publishes none for it), so it
  // stays off the agent op that "backing-up"/"restoring" ride: the dialog owns its own pending
  // state, and the agent orb never reads as "deleting" while a snapshot is removed.
  const removeBackup = async (backupId: string) => {
    await deleteBackup(httpClient, name, backupId);
    await refreshBackups();
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
      await deleteAgent(httpClient, name);
    } catch (e) {
      ops.setOp(name, "idle", errorMessage(e, "delete failed"));
    }
  };

  const value: SelectedAgentContextValue = {
    name,
    agent,
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
    backupsFailed,
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

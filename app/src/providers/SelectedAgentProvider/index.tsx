import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useParams } from "react-router-dom";
import {
  agentStatus,
  startAgent,
  stopAgent,
  restartAgent,
  rebuildAgent,
  backupAgent,
  restoreAgent,
  deleteAgent,
  waitForReady,
  waitForStopped,
} from "@/api";
import { useAgentOps, type AgentOperation } from "@/stores/use-agent-ops";
import type { AgentInfo, AgentActivityState } from "@/lib/types";

interface SelectedAgentContextValue {
  name: string;
  agent: AgentInfo | null;
  agentState: AgentActivityState;
  setAgentState: (state: AgentActivityState) => void;

  operation: AgentOperation;
  error: string;
  isBusy: boolean;

  refreshAgent: () => Promise<void>;
  start: () => void;
  stop: () => void;
  restart: () => void;
  rebuild: () => void;
  backup: () => void;
  restore: () => void;
  remove: () => Promise<void>;
}

const SelectedAgentContext = createContext<SelectedAgentContextValue | null>(null);

const POLL_INTERVAL = 5000;

export function SelectedAgentProvider({ children }: { children: ReactNode }) {
  const { name: routeName } = useParams<{ name: string }>();
  const name = routeName ?? "";

  const [agent, setAgent] = useState<AgentInfo | null>(null);
  const [agentState, setAgentState] = useState<AgentActivityState>("idle");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const withOp = useAgentOps((s) => s.withOp);
  const removeAgentOp = useAgentOps((s) => s.removeAgent);
  const opState = useAgentOps((s) => s.getOp(name));
  const isBusy = useAgentOps((s) => s.busyAgentName() !== null);

  const refreshAgent = useCallback(async () => {
    if (!name) return;
    try {
      setAgent(await agentStatus(name));
    } catch { /* poll will catch up */ }
  }, [name]);

  useEffect(() => {
    if (!name) return;
    const fetchStatus = async () => {
      if (opState.operation !== "idle") return;
      try {
        setAgent(await agentStatus(name));
      } catch {
        // ignore
      }
    };
    fetchStatus();
    pollRef.current = setInterval(fetchStatus, POLL_INTERVAL);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [name, opState.operation]);

  const start = useCallback(() => {
    withOp(name, "starting", async () => {
      await startAgent(name);
      await waitForReady(name);
      await refreshAgent();
    }, "start failed");
  }, [name, withOp, refreshAgent]);

  const stop = useCallback(() => {
    withOp(name, "stopping", async () => {
      await stopAgent(name);
      await waitForStopped(name);
      await refreshAgent();
    }, "stop failed");
  }, [name, withOp, refreshAgent]);

  const restart = useCallback(() => {
    withOp(name, "starting", async () => {
      await restartAgent(name);
      await waitForReady(name);
      await refreshAgent();
    }, "restart failed");
  }, [name, withOp, refreshAgent]);

  const rebuild = useCallback(() => {
    withOp(name, "rebuilding", async () => {
      await rebuildAgent(name);
      await waitForReady(name);
      await refreshAgent();
    }, "rebuild failed");
  }, [name, withOp, refreshAgent]);

  const backup = useCallback(() => {
    withOp(name, "backing-up", () => backupAgent(name), "backup failed");
  }, [name, withOp]);

  const restore = useCallback(() => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".tar.gz,.gz";
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) return;
      await withOp(
        name,
        "restoring",
        () => restoreAgent(file, name, true),
        "restore failed",
      );
    };
    input.click();
  }, [name, withOp]);

  const remove = useCallback(async () => {
    await withOp(name, "deleting", () => deleteAgent(name), "delete failed");
    removeAgentOp(name);
  }, [name, withOp, removeAgentOp]);

  const value: SelectedAgentContextValue = {
    name,
    agent,
    agentState,
    setAgentState,
    operation: opState.operation,
    error: opState.error,
    isBusy,
    refreshAgent,
    start,
    stop,
    restart,
    rebuild,
    backup,
    restore,
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
    throw new Error("useSelectedAgent must be used within SelectedAgentProvider");
  }
  return context;
}

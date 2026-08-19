export interface RunStatus {
  state: "capturing" | "ready" | "error";
  runner: string;
  message: string;
  detail: string;
  startedAt: string | null;
  updatedAt: string;
  pid?: number;
}
export function processAlive(pid: number): boolean;
export function runStatusPath(runner: string, directory?: string): string;
export function publishRunStatus(
  state: RunStatus["state"],
  options: { runner: string; message?: string; detail?: string; startedAt?: string | null },
  directory?: string,
): Promise<void>;
export function liveStatuses(
  statuses: (RunStatus | null)[],
  isAlive?: (pid: number) => boolean,
): RunStatus[];
export function currentRunStatus(directory?: string): Promise<{ statuses: RunStatus[] }>;

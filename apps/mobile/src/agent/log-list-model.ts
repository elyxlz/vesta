const MAX_LOG_LINES = 5000;

export interface LogLine {
  id: number;
  text: string;
}

export function addLatestLogLine(
  current: LogLine[],
  line: LogLine,
): LogLine[] {
  return [line, ...current].slice(0, MAX_LOG_LINES);
}

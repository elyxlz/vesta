import { useEffect, useRef, useState } from "react";
import { Copy, RefreshCw } from "lucide-react";
import { streamGatewayLogs, stopGatewayLogs } from "@/api/gateway";
import { LOG_SCROLLBACK_LINES } from "@/lib/log-stream-policy";
import { useLogWindow } from "@/lib/use-log-window";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import type { LogEvent } from "@/lib/types";
import { GatewayLogsViewerStyles as styles, LogLevelColors } from "./styles";

// vestad writes plain-text logs as `<timestamp>  <LEVEL>  <message>`. Split that
// shape so the viewer can dim the timestamp and color the level; anything that
// doesn't match (continuations, "error:" lines) renders as-is.
const LOG_LINE_RE = /^(\S+)\s+(TRACE|DEBUG|INFO|WARN|ERROR)\s+([\s\S]*)$/;

function LogLine({ text }: { text: string }) {
  const match = LOG_LINE_RE.exec(text);
  const [, timestamp, level, rest] = match ?? [];
  if (timestamp === undefined || level === undefined || rest === undefined) {
    return <div style={styles.line}>{text || " "}</div>;
  }
  return (
    <div style={styles.line}>
      <span style={styles.timestamp}>{timestamp}</span>{" "}
      <span style={{ ...styles.level, color: LogLevelColors[level] }}>
        {level}
      </span>{" "}
      {rest}
    </div>
  );
}

interface GatewayLogsViewerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

// Copy grabs only the most recent lines — enough to paste into a bug report without
// dumping a whole follow session's worth of output.
const COPY_TAIL_LINES = 200;

interface GatewayLogLine {
  id: number;
  text: string;
}

export function GatewayLogsViewer({
  open,
  onOpenChange,
}: GatewayLogsViewerProps) {
  const [lines, setLines] = useState<GatewayLogLine[]>([]);
  const [follow, setFollow] = useState(true);
  const [refreshEpoch, setRefreshEpoch] = useState(0);
  const scrollRef = useRef<HTMLDivElement>(null);
  const nextIdRef = useRef(0);
  const { visibleCount, onScroll } = useLogWindow({
    parentRef: scrollRef,
    count: lines.length,
    newestId: lines.at(-1)?.id,
  });

  useEffect(() => {
    if (!open) return;
    setLines([]);
    nextIdRef.current = 0;
    let active = true;

    const append = (text: string) =>
      setLines((prev) => {
        const next = [...prev, { id: nextIdRef.current++, text }];
        return next.length > LOG_SCROLLBACK_LINES
          ? next.slice(-LOG_SCROLLBACK_LINES)
          : next;
      });

    const handleEvent = (event: LogEvent) => {
      if (!active) return;
      switch (event.kind) {
        case "Line":
          append(event.text);
          break;
        case "Error":
          append(event.message);
          break;
        case "End":
          break;
      }
    };

    // Resolves when the stream ends; every failure arrives as an Error event instead.
    void streamGatewayLogs(follow, handleEvent);

    return () => {
      active = false;
      stopGatewayLogs();
    };
  }, [open, follow, refreshEpoch]);

  const handleCopy = () => {
    void navigator.clipboard.writeText(
      lines
        .slice(-COPY_TAIL_LINES)
        .map((line) => line.text)
        .join("\n"),
    );
  };

  const visible = lines.slice(-visibleCount);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[60vh] w-[60vw] max-w-[60vw] flex-col sm:max-w-[60vw]">
        <DialogHeader>
          <DialogTitle>Gateway logs</DialogTitle>
          <DialogDescription className="sr-only">
            Recent vestad gateway logs
          </DialogDescription>
        </DialogHeader>

        <div className="flex items-center justify-between gap-3">
          <label className="flex items-center gap-2 text-sm">
            <Switch checked={follow} onCheckedChange={setFollow} />
            Follow tail
          </label>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setRefreshEpoch((epoch) => epoch + 1)}
            >
              <RefreshCw /> Refresh
            </Button>
            <Button variant="outline" size="sm" onClick={handleCopy}>
              <Copy /> Copy
            </Button>
          </div>
        </div>

        <div ref={scrollRef} onScroll={onScroll} style={styles.scroll}>
          {lines.length === 0 ? (
            <span style={styles.empty}>No logs yet.</span>
          ) : (
            visible.map((line) => <LogLine key={line.id} text={line.text} />)
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

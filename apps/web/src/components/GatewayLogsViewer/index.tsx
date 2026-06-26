import { useCallback, useEffect, useRef, useState } from "react";
import { Copy, RefreshCw } from "lucide-react";
import { streamGatewayLogs, stopGatewayLogs } from "@/api/gateway";
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
  if (!match) {
    return <div style={styles.line}>{text || " "}</div>;
  }
  const [, timestamp, level, rest] = match;
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

const AUTOSCROLL_THRESHOLD_PX = 40;
// Copy grabs only the most recent lines — enough to paste into a bug report without
// dumping a whole follow session's worth of output.
const COPY_TAIL_LINES = 200;

export function GatewayLogsViewer({
  open,
  onOpenChange,
}: GatewayLogsViewerProps) {
  const [lines, setLines] = useState<string[]>([]);
  const [follow, setFollow] = useState(true);
  const [refreshEpoch, setRefreshEpoch] = useState(0);
  const linesEndRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const shouldAutoScrollRef = useRef(true);

  useEffect(() => {
    if (!open) return;
    setLines([]);
    shouldAutoScrollRef.current = true;
    let active = true;

    const handleEvent = (event: LogEvent) => {
      if (!active) return;
      switch (event.kind) {
        case "Line":
          setLines((prev) => [...prev, event.text]);
          break;
        case "Error":
          setLines((prev) => [...prev, event.message]);
          break;
        case "End":
          break;
      }
    };

    streamGatewayLogs(follow, handleEvent).catch(() => {});

    return () => {
      active = false;
      stopGatewayLogs();
    };
  }, [open, follow, refreshEpoch]);

  useEffect(() => {
    if (shouldAutoScrollRef.current && linesEndRef.current) {
      linesEndRef.current.scrollIntoView({ behavior: "auto" });
    }
  }, [lines]);

  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const dist = el.scrollHeight - el.scrollTop - el.clientHeight;
    shouldAutoScrollRef.current = dist < AUTOSCROLL_THRESHOLD_PX;
  }, []);

  const handleCopy = () => {
    void navigator.clipboard.writeText(
      lines.slice(-COPY_TAIL_LINES).join("\n"),
    );
  };

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

        <div ref={scrollRef} onScroll={handleScroll} style={styles.scroll}>
          {lines.length === 0 ? (
            <span style={styles.empty}>No logs yet.</span>
          ) : (
            lines.map((line, index) => <LogLine key={index} text={line} />)
          )}
          <div ref={linesEndRef} />
        </div>
      </DialogContent>
    </Dialog>
  );
}

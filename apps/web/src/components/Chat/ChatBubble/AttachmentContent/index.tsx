import { useEffect, useRef, useState } from "react";
import {
  Ban,
  Download,
  File,
  FileText,
  Film,
  Maximize2,
  Music,
  RotateCcw,
} from "lucide-react";
import {
  ApiError,
  appChatAttachmentPath,
  attachmentKind,
  formatBytes,
  type AttachmentKind,
  type ChatAttachment,
} from "@vesta/core";
import { apiFetch } from "@/api/client";
import { useAuthedSrc } from "@/hooks/use-authed-src";
import { downloadAttachment } from "@/lib/download";
import { useToastStore } from "@/stores/use-toast";
import { useAgentSocket } from "@/providers/AgentSocketProvider";
import { cn } from "@/lib/utils";

// One attachment block inside a chat bubble, routed by kind: images open the in-chat viewer,
// videos play inline with an expand handoff, audio plays inline, and everything else is a
// download tile. A blob freed by the agent's cleanup serves 410, rendered as the terminal
// "no longer available" tile on every kind.

export interface OpenViewerRequest {
  attachment: ChatAttachment;
  startTime?: number;
}

const TILE_ICON: Record<AttachmentKind, typeof File> = {
  image: FileText,
  video: Film,
  audio: Music,
  file: File,
};

// Bubble media is capped to a phone-photo footprint; pre-sizing from the metadata dimensions
// keeps the chat scroll stable while bytes load.
const MEDIA_CLASS = "block max-h-[400px] max-w-[320px] rounded-xl";

function mediaAspect(attachment: ChatAttachment): React.CSSProperties {
  if (!attachment.width || !attachment.height) return {};
  return {
    aspectRatio: `${String(attachment.width)} / ${String(attachment.height)}`,
    width: Math.min(attachment.width, 320),
  };
}

type MediaPhase = "loading" | "loaded" | "removed" | "error";

// An <img> error carries no status, so the phase probe asks the endpoint: a 410 is the terminal
// removed state, anything else a retryable load failure.
async function probePhase(agent: string, id: string): Promise<MediaPhase> {
  try {
    await apiFetch(appChatAttachmentPath(agent, id));
    return "error";
  } catch (error) {
    return error instanceof ApiError && error.status === 410
      ? "removed"
      : "error";
  }
}

function RemovedTile({ attachment }: { attachment: ChatAttachment }) {
  return (
    <div className="flex items-center gap-2.5 rounded-xl bg-background/40 px-3 py-2 text-muted-foreground">
      <Ban className="size-4 shrink-0" />
      <span className="flex min-w-0 flex-col">
        <span className="max-w-52 truncate text-sm">{attachment.name}</span>
        <span className="text-xs">
          {formatBytes(attachment.size)} · no longer available
        </span>
      </span>
    </div>
  );
}

function ImageBlock({
  agent,
  attachment,
  onOpen,
}: {
  agent: string;
  attachment: ChatAttachment;
  onOpen?: (request: OpenViewerRequest) => void;
}) {
  const [phase, setPhase] = useState<MediaPhase>("loading");
  const [generation, setGeneration] = useState(0);
  const src = useAuthedSrc(appChatAttachmentPath(agent, attachment.id));

  // A load that failed on a bad link retries itself once each time the gateway reconnects; the
  // removed state is terminal and never retried.
  const { connected } = useAgentSocket();
  const phaseRef = useRef(phase);
  phaseRef.current = phase;
  useEffect(() => {
    if (!connected || phaseRef.current !== "error") return;
    setGeneration((current) => current + 1);
    setPhase("loading");
  }, [connected]);

  if (phase === "removed") return <RemovedTile attachment={attachment} />;
  if (phase === "error") {
    return (
      <button
        type="button"
        onClick={() => {
          setGeneration((current) => current + 1);
          setPhase("loading");
        }}
        className="flex items-center gap-2.5 rounded-xl bg-background/40 px-3 py-2 text-muted-foreground"
      >
        <RotateCcw className="size-4 shrink-0" />
        <span className="flex min-w-0 flex-col text-left">
          <span className="max-w-52 truncate text-sm">{attachment.name}</span>
          <span className="text-xs">couldn't load · tap to retry</span>
        </span>
      </button>
    );
  }
  return (
    <button
      type="button"
      aria-label={`view ${attachment.name}`}
      onClick={() => onOpen?.({ attachment })}
      className="relative overflow-hidden rounded-xl"
      style={mediaAspect(attachment)}
    >
      {src !== null && (
        <img
          key={generation}
          src={src}
          alt={attachment.name}
          loading="lazy"
          className={cn(MEDIA_CLASS, "size-full object-cover")}
          onLoad={() => {
            setPhase("loaded");
          }}
          onError={() => {
            void probePhase(agent, attachment.id).then(setPhase);
          }}
        />
      )}
      {phase === "loading" && (
        <span
          className="absolute inset-0 block min-h-24 min-w-40 animate-pulse rounded-xl bg-muted"
          aria-hidden
        />
      )}
    </button>
  );
}

function SizeBadge({ size, hidden }: { size: number; hidden: boolean }) {
  if (hidden) return null;
  return (
    <span className="pointer-events-none absolute bottom-1.5 left-1.5 rounded-full bg-background/70 px-2 py-0.5 text-[10px] text-foreground/80">
      {formatBytes(size)}
    </span>
  );
}

function VideoBlock({
  agent,
  attachment,
  onOpen,
}: {
  agent: string;
  attachment: ChatAttachment;
  onOpen?: (request: OpenViewerRequest) => void;
}) {
  const [played, setPlayed] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const src = useAuthedSrc(appChatAttachmentPath(agent, attachment.id));
  return (
    <span
      className="relative block overflow-hidden rounded-xl"
      style={mediaAspect(attachment)}
    >
      {src !== null && (
        <video
          ref={videoRef}
          src={src}
          controls
          preload="metadata"
          className={cn(MEDIA_CLASS, "size-full bg-black/20 object-contain")}
          onPlay={() => {
            setPlayed(true);
          }}
        />
      )}
      <SizeBadge size={attachment.size} hidden={played} />
      {onOpen && (
        <button
          type="button"
          aria-label={`expand ${attachment.name}`}
          onClick={() => {
            // Best-effort playback handoff: the viewer's copy resumes near this position.
            const video = videoRef.current;
            video?.pause();
            onOpen({ attachment, startTime: video?.currentTime ?? 0 });
          }}
          className="absolute top-1.5 right-1.5 rounded-full bg-background/70 p-1.5 text-foreground/80 hover:bg-background/90"
        >
          <Maximize2 className="size-3.5" />
        </button>
      )}
    </span>
  );
}

function AudioBlock({
  agent,
  attachment,
}: {
  agent: string;
  attachment: ChatAttachment;
}) {
  const src = useAuthedSrc(appChatAttachmentPath(agent, attachment.id));
  return (
    <span className="flex flex-col gap-0.5">
      {src !== null && (
        <audio src={src} controls className="h-10 max-w-[280px]" />
      )}
      <span className="px-1 text-xs text-muted-foreground">
        {attachment.name} · {formatBytes(attachment.size)}
      </span>
    </span>
  );
}

type DownloadPhase = "idle" | "fetching" | "saved" | "removed";

function FileBlock({
  agent,
  attachment,
}: {
  agent: string;
  attachment: ChatAttachment;
}) {
  const [phase, setPhase] = useState<DownloadPhase>("idle");
  const [received, setReceived] = useState(0);

  if (phase === "removed") return <RemovedTile attachment={attachment} />;

  const Icon = TILE_ICON[attachmentKind(attachment.mime)];
  const start = () => {
    setPhase("fetching");
    setReceived(0);
    downloadAttachment(agent, attachment, setReceived).then(
      () => {
        setPhase("saved");
      },
      (error: unknown) => {
        if (error instanceof ApiError && error.status === 410) {
          setPhase("removed");
          return;
        }
        setPhase("idle");
        useToastStore
          .getState()
          .show("error", `couldn't download ${attachment.name}`);
      },
    );
  };

  const detail =
    phase === "fetching"
      ? `${formatBytes(received)} of ${formatBytes(attachment.size)}`
      : phase === "saved"
        ? `${formatBytes(attachment.size)} · saved`
        : formatBytes(attachment.size);

  return (
    <button
      type="button"
      aria-label={`download ${attachment.name}`}
      disabled={phase === "fetching"}
      onClick={start}
      className="flex items-center gap-2.5 rounded-xl bg-background/40 px-3 py-2 text-left hover:bg-background/60"
    >
      <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
        <Icon className="size-4.5" />
      </span>
      <span className="flex min-w-0 flex-col">
        <span className="max-w-52 truncate text-sm font-medium">
          {attachment.name}
        </span>
        <span className="text-xs text-muted-foreground">{detail}</span>
      </span>
      <Download className="ml-1 size-4 shrink-0 text-muted-foreground" />
    </button>
  );
}

export function AttachmentContent({
  agent,
  attachment,
  onOpen,
}: {
  agent: string;
  attachment: ChatAttachment;
  onOpen?: (request: OpenViewerRequest) => void;
}) {
  const kind = attachmentKind(attachment.mime);
  if (kind === "image")
    return <ImageBlock agent={agent} attachment={attachment} onOpen={onOpen} />;
  if (kind === "video")
    return <VideoBlock agent={agent} attachment={attachment} onOpen={onOpen} />;
  if (kind === "audio")
    return <AudioBlock agent={agent} attachment={attachment} />;
  return <FileBlock agent={agent} attachment={attachment} />;
}

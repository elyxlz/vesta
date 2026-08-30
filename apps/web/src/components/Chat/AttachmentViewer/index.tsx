import {
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { Dialog as DialogPrimitive } from "radix-ui";
import { AnimatePresence, motion } from "motion/react";
import { Download, X } from "lucide-react";
import {
  ApiError,
  appChatAttachmentPath,
  attachmentKind,
  formatBytes,
  type ChatAttachment,
} from "@vesta/core";
import { Button } from "@/components/ui/button";
import { useAuthedSrc } from "@/hooks/use-authed-src";
import { downloadAttachment } from "@/lib/download";
import { useToastStore } from "@/stores/use-toast";
import { stepTransition } from "@/lib/motion";
import { cn } from "@/lib/utils";
import type { OpenViewerRequest } from "../ChatBubble/AttachmentContent";
import {
  panBy,
  resetZoom,
  toggleZoom,
  zoomAt,
  type Size,
  type ZoomState,
} from "./viewer-zoom";

// The in-chat attachment viewer: "full screen" within the Chat card only (an absolute overlay,
// deliberately portal-less so the roster and navbar stay visible around the local scrim). Radix
// Dialog primitives composed without their Portal give the focus trap, Esc handling, and dialog
// semantics while the content stays contained. Images zoom (cursor-anchored wheel, which is also
// how a trackpad pinch arrives, double-click toggle, drag pan); videos hand playback over from the
// inline bubble and keep the browser's native controls.

const WHEEL_ZOOM_RATE = 0.002;
const PINCH_ZOOM_RATE = 0.01;
// The media caps at this fraction of the container, so the scrim always frames it.
const MEDIA_FRACTION = "88%";

function ZoomableImage({
  src,
  name,
  zoom,
  onZoom,
}: {
  src: string;
  name: string;
  zoom: ZoomState;
  onZoom: (
    fold: (current: ZoomState, container: Size, content: Size) => ZoomState,
  ) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const dragRef = useRef<{ x: number; y: number } | null>(null);

  // React attaches wheel listeners passively, so the zoom handler binds directly to keep
  // preventDefault (the chat behind must not scroll while zooming).
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const bounds = container.getBoundingClientRect();
      const cursor = {
        x: event.clientX - bounds.left - bounds.width / 2,
        y: event.clientY - bounds.top - bounds.height / 2,
      };
      const factor = Math.exp(
        -event.deltaY * (event.ctrlKey ? PINCH_ZOOM_RATE : WHEEL_ZOOM_RATE),
      );
      onZoom((current, containerSize, contentSize) =>
        zoomAt(current, cursor, factor, containerSize, contentSize),
      );
    };
    container.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      container.removeEventListener("wheel", onWheel);
    };
  }, [onZoom]);

  const onDoubleClick = (event: React.MouseEvent) => {
    const container = containerRef.current;
    if (!container) return;
    const bounds = container.getBoundingClientRect();
    const cursor = {
      x: event.clientX - bounds.left - bounds.width / 2,
      y: event.clientY - bounds.top - bounds.height / 2,
    };
    onZoom((current, containerSize, contentSize) =>
      toggleZoom(current, cursor, containerSize, contentSize),
    );
  };

  const onPointerDown = (event: ReactPointerEvent) => {
    if (zoom.scale <= 1) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = { x: event.clientX, y: event.clientY };
  };
  const onPointerMove = (event: ReactPointerEvent) => {
    const last = dragRef.current;
    if (!last) return;
    const dx = event.clientX - last.x;
    const dy = event.clientY - last.y;
    dragRef.current = { x: event.clientX, y: event.clientY };
    onZoom((current, containerSize, contentSize) =>
      panBy(current, dx, dy, containerSize, contentSize),
    );
  };
  const endDrag = () => {
    dragRef.current = null;
  };

  return (
    <div
      ref={containerRef}
      data-viewer-stage
      className="flex size-full items-center justify-center overflow-hidden"
      onDoubleClick={onDoubleClick}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
    >
      <img
        ref={imageRef}
        src={src}
        alt={name}
        draggable={false}
        data-zoom-scale={zoom.scale}
        style={{
          maxWidth: MEDIA_FRACTION,
          maxHeight: MEDIA_FRACTION,
          transform: `translate(${String(zoom.x)}px, ${String(zoom.y)}px) scale(${String(zoom.scale)})`,
        }}
        className={cn(
          "rounded-2xl object-contain shadow-lg select-none",
          zoom.scale > 1
            ? "cursor-grab active:cursor-grabbing"
            : "cursor-zoom-in",
        )}
      />
    </div>
  );
}

function viewerGeometry(stage: HTMLElement | null): {
  container: Size;
  content: Size;
} {
  const image = stage?.querySelector("img");
  return {
    container: {
      width: stage?.clientWidth ?? 1,
      height: stage?.clientHeight ?? 1,
    },
    // offsetWidth ignores the transform, so this is the fitted (scale 1) content size.
    content: {
      width: image?.offsetWidth ?? 1,
      height: image?.offsetHeight ?? 1,
    },
  };
}

export function AttachmentViewer({
  agent,
  request,
  onClose,
}: {
  agent: string;
  request: OpenViewerRequest | null;
  onClose: () => void;
}) {
  const attachment = request?.attachment ?? null;
  const [zoom, setZoom] = useState<ZoomState>(resetZoom);
  const shellRef = useRef<HTMLDivElement>(null);
  const src = useAuthedSrc(
    attachment ? appChatAttachmentPath(agent, attachment.id) : null,
  );

  // Zoom is per opening: a fresh attachment starts fitted.
  const openedId = attachment?.id;
  useEffect(() => {
    setZoom(resetZoom());
  }, [openedId]);

  const onZoom = (
    fold: (current: ZoomState, container: Size, content: Size) => ZoomState,
  ) => {
    const stage =
      shellRef.current?.querySelector<HTMLElement>("[data-viewer-stage]") ??
      null;
    const { container, content } = viewerGeometry(stage);
    setZoom((current) => fold(current, container, content));
  };

  const save = (target: ChatAttachment) => {
    downloadAttachment(agent, target).catch((error: unknown) => {
      const removed = error instanceof ApiError && error.status === 410;
      useToastStore
        .getState()
        .show(
          "error",
          removed
            ? `${target.name} is no longer available`
            : `couldn't download ${target.name}`,
        );
    });
  };

  return (
    <AnimatePresence>
      {attachment && (
        <DialogPrimitive.Root
          open
          onOpenChange={(open) => {
            if (!open) onClose();
          }}
        >
          <DialogPrimitive.Content
            asChild
            onEscapeKeyDown={onClose}
            onInteractOutside={(event) => {
              event.preventDefault();
            }}
          >
            <motion.div
              ref={shellRef}
              initial={{ opacity: 0, scale: 0.96 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.98 }}
              transition={stepTransition.transition}
              className="absolute inset-0 z-40 flex flex-col"
            >
              <DialogPrimitive.Title className="sr-only">
                {attachment.name}
              </DialogPrimitive.Title>
              <DialogPrimitive.Description className="sr-only">
                attachment viewer
              </DialogPrimitive.Description>
              <button
                type="button"
                aria-label="close viewer"
                tabIndex={-1}
                onClick={onClose}
                className="absolute inset-0 cursor-default bg-background/80"
              />
              <div className="pointer-events-none relative z-10 flex flex-1 flex-col">
                <div className="pointer-events-auto flex items-center justify-end gap-1 p-2">
                  <Button
                    type="button"
                    size="icon"
                    variant="ghost"
                    aria-label={`download ${attachment.name}`}
                    onClick={() => {
                      save(attachment);
                    }}
                    className="size-8 rounded-full"
                  >
                    <Download />
                  </Button>
                  <Button
                    type="button"
                    size="icon"
                    variant="ghost"
                    aria-label="close"
                    onClick={onClose}
                    className="size-8 rounded-full"
                  >
                    <X />
                  </Button>
                </div>
                <div className="pointer-events-auto min-h-0 flex-1">
                  {attachmentKind(attachment.mime) === "video" ? (
                    <div className="flex size-full items-center justify-center">
                      {src !== null && (
                        <video
                          src={src}
                          controls
                          autoPlay
                          onLoadedMetadata={(event) => {
                            if (request?.startTime)
                              event.currentTarget.currentTime =
                                request.startTime;
                          }}
                          style={{
                            maxWidth: MEDIA_FRACTION,
                            maxHeight: MEDIA_FRACTION,
                          }}
                          className="rounded-2xl shadow-lg"
                        />
                      )}
                    </div>
                  ) : (
                    src !== null && (
                      <ZoomableImage
                        src={src}
                        name={attachment.name}
                        zoom={zoom}
                        onZoom={onZoom}
                      />
                    )
                  )}
                </div>
                <div className="pointer-events-auto flex justify-center p-2.5">
                  <span className="max-w-[80%] truncate rounded-full bg-popover/90 px-3 py-1 text-xs text-muted-foreground shadow-sm">
                    {attachment.name}
                    {attachment.width && attachment.height
                      ? ` · ${String(attachment.width)}×${String(attachment.height)}`
                      : ""}
                    {" · "}
                    {formatBytes(attachment.size)}
                  </span>
                </div>
              </div>
            </motion.div>
          </DialogPrimitive.Content>
        </DialogPrimitive.Root>
      )}
    </AnimatePresence>
  );
}

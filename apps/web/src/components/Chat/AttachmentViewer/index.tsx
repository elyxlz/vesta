import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import { Dialog as DialogPrimitive } from "radix-ui";
import { AnimatePresence, motion } from "motion/react";
import { Download, X } from "lucide-react";
import {
  appChatAttachmentPath,
  attachmentKind,
  formatBytes,
  type ChatAttachment,
} from "@vesta/core";
import { Button } from "@/components/ui/button";
import { useAuthedSrc } from "@/hooks/use-authed-src";
import { stepTransition } from "@/lib/motion";
import { cn } from "@/lib/utils";
import type { OpenViewerRequest } from "../ChatBubble/AttachmentContent";
import { ProgressRing } from "../ProgressRing";
import { useDownload, useDownloadsStore } from "@/stores/use-downloads";
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

function AttachmentCaption({ attachment }: { attachment: ChatAttachment }) {
  return (
    <figcaption className="max-w-full shrink-0 truncate rounded-full bg-popover/90 px-3 py-1 text-xs text-muted-foreground shadow-sm">
      {attachment.name}
      {attachment.width && attachment.height
        ? ` · ${String(attachment.width)}×${String(attachment.height)}`
        : ""}
      {" · "}
      {formatBytes(attachment.size)}
    </figcaption>
  );
}

// Owns its zoom/pan state and its own geometry (offsetWidth ignores the transform, so it reads
// the fitted scale-1 size); the parent resets everything by keying this component on the
// attachment id. The image is its own viewport, so the caption below it hugs its real bottom edge.
function ZoomableImage({
  src,
  name,
  caption,
}: {
  src: string;
  name: string;
  caption: ReactNode;
}) {
  const imageRef = useRef<HTMLImageElement>(null);
  const dragRef = useRef<{ x: number; y: number } | null>(null);
  const [zoom, setZoom] = useState<ZoomState>(resetZoom);

  const fold = useCallback(
    (
      apply: (
        current: ZoomState,
        cursor: { x: number; y: number },
        container: Size,
        content: Size,
      ) => ZoomState,
      clientX: number,
      clientY: number,
    ) => {
      const image = imageRef.current;
      if (!image) return;
      const bounds = image.getBoundingClientRect();
      const cursor = {
        x: clientX - bounds.left - bounds.width / 2,
        y: clientY - bounds.top - bounds.height / 2,
      };
      // Container and content are the same box: a fitted image never pans, a zoomed one pans its overhang.
      const size = { width: image.offsetWidth, height: image.offsetHeight };
      setZoom((current) => apply(current, cursor, size, size));
    },
    [],
  );

  // React attaches wheel listeners passively, so the zoom handler binds directly to keep
  // preventDefault (the chat behind must not scroll while zooming). `fold` is stable, so the
  // non-passive listener binds once per mount.
  useEffect(() => {
    const image = imageRef.current;
    if (!image) return;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const factor = Math.exp(
        -event.deltaY * (event.ctrlKey ? PINCH_ZOOM_RATE : WHEEL_ZOOM_RATE),
      );
      fold(
        (current, cursor, containerSize, contentSize) =>
          zoomAt(current, cursor, factor, containerSize, contentSize),
        event.clientX,
        event.clientY,
      );
    };
    image.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      image.removeEventListener("wheel", onWheel);
    };
  }, [fold]);

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
    fold(
      (current, _cursor, containerSize, contentSize) =>
        panBy(current, dx, dy, containerSize, contentSize),
      event.clientX,
      event.clientY,
    );
  };
  const endDrag = () => {
    dragRef.current = null;
  };

  return (
    <figure className="flex size-full min-h-0 flex-col items-center justify-center gap-2.5 overflow-hidden">
      <img
        ref={imageRef}
        src={src}
        alt={name}
        draggable={false}
        data-viewer-stage
        data-zoom-scale={zoom.scale}
        onDoubleClick={(event) => {
          fold(toggleZoom, event.clientX, event.clientY);
        }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        style={{
          transform: `translate(${String(zoom.x)}px, ${String(zoom.y)}px) scale(${String(zoom.scale)})`,
        }}
        className={cn(
          "min-h-0 max-w-full rounded-2xl object-contain shadow-lg select-none",
          zoom.scale > 1
            ? "cursor-grab active:cursor-grabbing"
            : "cursor-zoom-in",
        )}
      />
      {caption}
    </figure>
  );
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
  const src = useAuthedSrc(
    attachment ? appChatAttachmentPath(agent, attachment.id) : null,
  );
  const download = useDownload(attachment?.id ?? "");
  const startDownload = useDownloadsStore((state) => state.start);

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
            onInteractOutside={(event) => {
              event.preventDefault();
            }}
          >
            <motion.div
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
                className="absolute inset-0 cursor-default bg-background/95"
              />
              <div className="pointer-events-none relative z-10 flex flex-1 flex-col">
                <div className="pointer-events-auto flex items-center justify-end gap-1 p-2">
                  <Button
                    type="button"
                    size="icon"
                    variant="ghost"
                    aria-label={`download ${attachment.name}`}
                    disabled={download?.phase === "fetching"}
                    onClick={() => {
                      startDownload(agent, attachment);
                    }}
                    className="size-8 rounded-full"
                  >
                    {download?.phase === "fetching" ? (
                      <ProgressRing
                        progress={download.received / download.total}
                      />
                    ) : (
                      <Download />
                    )}
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
                <div className="pointer-events-auto min-h-0 flex-1 px-6 pb-4">
                  {attachmentKind(attachment.mime) === "video" ? (
                    <figure className="flex size-full min-h-0 flex-col items-center justify-center gap-2.5">
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
                          className="min-h-0 max-w-full rounded-2xl object-contain shadow-lg"
                        />
                      )}
                      <AttachmentCaption attachment={attachment} />
                    </figure>
                  ) : (
                    src !== null && (
                      <ZoomableImage
                        key={attachment.id}
                        src={src}
                        name={attachment.name}
                        caption={<AttachmentCaption attachment={attachment} />}
                      />
                    )
                  )}
                </div>
              </div>
            </motion.div>
          </DialogPrimitive.Content>
        </DialogPrimitive.Root>
      )}
    </AnimatePresence>
  );
}

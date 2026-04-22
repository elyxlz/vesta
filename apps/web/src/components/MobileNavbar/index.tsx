import { useCallback, useEffect, useRef, useState } from "react";
import {
  motion,
  useMotionTemplate,
  useTransform,
  type MotionValue,
} from "motion/react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { LayoutDashboard, MessageSquare } from "lucide-react";
import { cn } from "@/lib/utils";
import { useMeasuredHeight } from "@/hooks/use-measured-height";
import { useLayout } from "@/stores/use-layout";

export function MobileNavbar({ progress }: { progress: MotionValue<number> }) {
  const navigate = useNavigate();
  const { name } = useParams<{ name: string }>();
  const location = useLocation();
  const pillRef = useRef<HTMLDivElement | null>(null);
  const dashboardRef = useRef<HTMLButtonElement | null>(null);
  const chatRef = useRef<HTMLButtonElement | null>(null);
  const setBottomBarHeight = useLayout((s) => s.setBottomBarHeight);
  const wrapperRef = useMeasuredHeight(setBottomBarHeight);
  const [pillNode, setPillNode] = useState<HTMLDivElement | null>(null);
  const [tabMetrics, setTabMetrics] = useState({
    overlayWidth: 0,
    startLeft: 4,
    startWidth: 0,
    startTop: 4,
    endLeft: 0,
  });

  const pillMeasureRef = useCallback((node: HTMLDivElement | null) => {
    pillRef.current = node;
    setPillNode(node);
  }, []);

  const updatePillMetrics = useCallback(() => {
    const node = pillRef.current;
    const dashboardNode = dashboardRef.current;
    const chatNode = chatRef.current;
    if (!node || !dashboardNode || !chatNode) return;

    const nodeRect = node.getBoundingClientRect();
    const overlayLeft = nodeRect.left + node.clientLeft;
    const overlayTop = nodeRect.top + node.clientTop;
    const dashRect = dashboardNode.getBoundingClientRect();
    const chatRect = chatNode.getBoundingClientRect();

    setTabMetrics({
      overlayWidth: node.clientWidth,
      startLeft: dashRect.left - overlayLeft,
      startWidth: dashRect.width,
      startTop: dashRect.top - overlayTop,
      endLeft: chatRect.left - overlayLeft,
    });
  }, []);

  const base = name ? `/agent/${encodeURIComponent(name)}` : "";
  const chatPath = `${base}/chat`;
  const isDashboard = location.pathname === base;
  const isChat = location.pathname === chatPath;
  const pillLeft = useTransform(
    progress,
    [0, 1],
    [tabMetrics.startLeft, tabMetrics.endLeft],
  );
  const pillRight = useTransform(
    progress,
    [0, 1],
    [
      tabMetrics.overlayWidth - tabMetrics.startLeft - tabMetrics.startWidth,
      tabMetrics.overlayWidth - tabMetrics.endLeft - tabMetrics.startWidth,
    ],
  );
  const pillClipPath = useMotionTemplate`inset(${tabMetrics.startTop}px ${pillRight}px ${tabMetrics.startTop}px ${pillLeft}px round 16px)`;

  useEffect(() => {
    if (!pillNode) return;

    updatePillMetrics();

    const observer = new ResizeObserver(() => {
      updatePillMetrics();
    });

    observer.observe(pillNode);
    if (dashboardRef.current) observer.observe(dashboardRef.current);
    if (chatRef.current) observer.observe(chatRef.current);

    return () => observer.disconnect();
  }, [pillNode, updatePillMetrics]);

  if (!name) return null;

  const renderButtons = ({
    active,
    interactive,
  }: {
    active: boolean;
    interactive: boolean;
  }) => (
    <>
      <button
        type="button"
        ref={interactive ? dashboardRef : undefined}
        onClick={interactive ? () => navigate(base) : undefined}
        aria-current={isDashboard ? "page" : undefined}
        tabIndex={interactive ? undefined : -1}
        className={cn(
          "flex h-9 items-center justify-center gap-2 rounded-2xl px-3 text-sm font-medium",
          active ? "text-white" : "text-muted-foreground",
        )}
      >
        <LayoutDashboard className="size-4" />
        <span>dashboard</span>
      </button>
      <button
        type="button"
        ref={interactive ? chatRef : undefined}
        onClick={interactive ? () => navigate(chatPath) : undefined}
        aria-current={isChat ? "page" : undefined}
        tabIndex={interactive ? undefined : -1}
        className={cn(
          "flex h-9 items-center justify-center gap-2 rounded-2xl px-3 text-sm font-medium",
          active ? "text-white" : "text-muted-foreground",
        )}
      >
        <MessageSquare className="size-4" />
        <span>chat</span>
      </button>
    </>
  );

  return (
    <div
      ref={wrapperRef}
      className="absolute bottom-0 left-0 right-0 z-40 flex justify-center px-3 pt-1"
      style={{ paddingBottom: "var(--safe-area-pb, 0.75rem)" }}
    >
      <div
        ref={pillMeasureRef}
        className="relative flex w-fit gap-0.5 overflow-hidden rounded-4xl bg-card p-1 text-card-foreground shadow-md ring-1 ring-foreground/5 dark:ring-foreground/10"
      >
        <div className="relative flex w-full gap-0.5">
          {renderButtons({ active: false, interactive: true })}
        </div>
        <motion.div
          className="pointer-events-none absolute inset-0 z-10 rounded-3xl bg-primary p-1"
          style={{ clipPath: pillClipPath }}
        >
          <div className="flex w-full gap-0.5">
            {renderButtons({ active: true, interactive: false })}
          </div>
        </motion.div>
      </div>
    </div>
  );
}

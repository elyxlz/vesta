import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useMotionValue } from "motion/react";
import { useNavigate } from "react-router-dom";
import {
  agentVisualStatus,
  feedUnseen,
  type LoggedUserNotification,
} from "@vesta/core";
import {
  useFocused,
  useNotificationFeed,
  useNotificationsPill,
  useViewing,
} from "@vesta/core/react";
import { useOptionalController } from "@/providers/ControllerProvider/context";
import { useGateway } from "@/providers/GatewayProvider/context";
import {
  NotificationsPillContext,
  PILL_BUTTON_SIZE,
  type HistorySurface,
} from "./context";

const HISTORY_PAGE_SIZE = 50;

// Owns every piece of the notifications pill's state, mounted once above the
// route layouts (NavigationGuard): the queue survives page navigation even
// though the navbars, and the pill in them, remount per layout. The pill
// component in the navbar is rendering only.
export function NotificationsPillProvider({
  children,
}: {
  children: ReactNode;
}) {
  const controller = useOptionalController();
  // The viewed agent and focus come from the controller, the one owner every consumer reads.
  const viewedAgent = useViewing(controller);
  const focused = useFocused(controller);
  const [surface, setSurface] = useState<HistorySurface>("none");
  const historyOpen = surface !== "none";

  const { agents, userNotificationsSeenAt, lastUserNotificationAt } =
    useGateway();
  const { feed, open, close, loadOlder } = useNotificationFeed(controller, {
    pageSize: HISTORY_PAGE_SIZE,
    viewedAgent,
    focused,
  });

  // One catch-up session spans both surfaces: it opens with the first surface
  // (holding the watermark) and closes with the last, which is when the feed
  // marks seen. Handing off popover to dialog changes the surface, not the
  // session.
  const showSurface = useCallback(
    (next: HistorySurface) => {
      if (next === surface) return;
      if (surface === "none") open(userNotificationsSeenAt);
      if (next === "none") close(lastUserNotificationAt);
      setSurface(next);
    },
    [surface, open, close, userNotificationsSeenAt, lastUserNotificationAt],
  );

  // The bell's dot is derived, never stored: anything logged past the synced
  // watermark that the user has not already read in the chat, so another device
  // catching up clears it here too. It hides the moment a history surface opens
  // (the user is looking); the synced truth catches up when the session closes
  // and marks seen.
  const unseen =
    feedUnseen(feed, lastUserNotificationAt, userNotificationsSeenAt) &&
    !historyOpen;

  const agentsRef = useRef(agents);
  useEffect(() => {
    agentsRef.current = agents;
  }, [agents]);

  const { current, dismiss } = useNotificationsPill(controller, {
    viewedAgent,
    orbStateFor: (name) => {
      const row = agentsRef.current.find((agent) => agent.name === name);
      if (!row) return null;
      const request = controller?.requests.get(row.name).request ?? "idle";
      return agentVisualStatus(row, request, row.activityState).orbState;
    },
    // While the history is on screen, arrivals skip the pill's animations and
    // just appear at the top of the list (the feed takes them in regardless).
    paused: historyOpen,
  });

  const morphWidth = useMotionValue(PILL_BUTTON_SIZE);
  const morphHeight = useMotionValue(PILL_BUTTON_SIZE);

  // Navigation lives here, inside the router, so the pill component can render
  // on routerless surfaces (the version-gate screens) without crashing.
  const navigate = useNavigate();
  const openAgent = useCallback(
    (agent: string) => {
      dismiss();
      void navigate(agent ? `/agent/${encodeURIComponent(agent)}` : "/");
    },
    [dismiss, navigate],
  );
  const openEntry = useCallback(
    (entry: LoggedUserNotification) => {
      showSurface("none");
      void navigate(
        entry.agent ? `/agent/${encodeURIComponent(entry.agent)}` : "/",
      );
    },
    [navigate, showSurface],
  );

  // Memoized so a provider re-render with unchanged pill state (a roster
  // delta refreshing agentsRef) does not re-render every consumer.
  const value = useMemo(
    () => ({
      current,
      dismiss,
      unseen,
      feed,
      loadOlder,
      surface,
      showSurface,
      openAgent,
      openEntry,
      morph: { width: morphWidth, height: morphHeight },
    }),
    [
      current,
      dismiss,
      unseen,
      feed,
      loadOlder,
      surface,
      showSurface,
      openAgent,
      openEntry,
      morphWidth,
      morphHeight,
    ],
  );

  return (
    <NotificationsPillContext.Provider value={value}>
      {children}
    </NotificationsPillContext.Provider>
  );
}

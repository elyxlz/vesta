import { useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useMotionValue } from "motion/react";
import { useMatch, useNavigate } from "react-router-dom";
import {
  fetchUserNotifications,
  type LoggedUserNotification,
  type PillContent,
} from "@vesta/core";
import { useNotificationsPill } from "@vesta/core/react";
import { ControllerContext } from "@/providers/ControllerProvider/context";
import { useGateway } from "@/providers/GatewayProvider/context";
import { getAgentVisualStatus } from "@/components/Orb/styles";
import { useAgentOps } from "@/stores/use-agent-ops";
import { httpClient } from "@/api/client";
import {
  NotificationsPillContext,
  PILL_BUTTON_SIZE,
  type NotificationHistory,
} from "./context";

export { useNotificationsPillState } from "./context";

const HISTORY_PAGE_SIZE = 50;
// A near-instant fetch still shows the skeletons for at least this long, so
// they read as a loading state instead of a flash.
const HISTORY_MIN_LOADING_MS = 500;

// The dialog/popover's shared view of the durable log: handler-driven paging
// with a minimum skeleton hold, and an explicit failed state (an older gateway
// without GET /notifications reads as "couldn't load", never as empty).
function useNotificationHistory(): NotificationHistory {
  const [history, setHistory] = useState<LoggedUserNotification[]>([]);
  const [exhausted, setExhausted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);

  // allSettled (never all) so a failing fetch still waits out the skeletons'
  // minimum hold instead of short-circuiting past it.
  const loadPage = (before?: number) => {
    setLoading(true);
    const minimumHold = new Promise((resolve) =>
      setTimeout(resolve, HISTORY_MIN_LOADING_MS),
    );
    const source = fetchUserNotifications(httpClient, {
      before,
      limit: HISTORY_PAGE_SIZE,
    });
    void Promise.allSettled([source, minimumHold]).then(([result]) => {
      if (result.status === "fulfilled") {
        const page = result.value;
        loadedRef.current = true;
        setExhausted(page.length < HISTORY_PAGE_SIZE);
        setHistory((existing) =>
          before === undefined ? page : [...existing, ...page],
        );
      } else {
        setFailed(true);
      }
      setLoading(false);
    });
  };

  // Loading UI exists only for the first-ever fetch: later opens show the
  // cached list instantly and refresh it quietly in the background
  // (stale-while-revalidate); a failed refresh keeps the cache.
  const loadedRef = useRef(false);
  const ensure = () => {
    if (!loadedRef.current) {
      setHistory([]);
      setExhausted(false);
      setFailed(false);
      loadPage();
      return;
    }
    fetchUserNotifications(httpClient, { limit: HISTORY_PAGE_SIZE })
      .then((page) => {
        setExhausted(page.length < HISTORY_PAGE_SIZE);
        setHistory(page);
      })
      .catch(() => undefined);
  };

  // A notification arriving while the history is on screen appears at the top
  // of the list, stamped now. Synthetic ids count down from the top of the
  // safe range so they never collide with the log's ids or the "load older"
  // cursor (which pages from the oldest fetched entry).
  const syntheticIdRef = useRef(Number.MAX_SAFE_INTEGER);
  const prepend = (item: PillContent) => {
    const entry: LoggedUserNotification = {
      ...item,
      id: syntheticIdRef.current--,
      at: Math.floor(Date.now() / 1000),
    };
    setHistory((existing) => [entry, ...existing]);
  };

  return { history, exhausted, loading, failed, loadPage, ensure, prepend };
}

// Owns every piece of the notifications pill's state, mounted once above the
// route layouts (NavigationGuard): the queue survives page navigation even
// though the navbars, and the pill in them, remount per layout. The pill
// component in the navbar is rendering only.
export function NotificationsPillProvider({
  children,
}: {
  children: ReactNode;
}) {
  const controller = useContext(ControllerContext);
  const agentMatch = useMatch({ path: "/agent/:name", end: false });
  const viewedAgent = agentMatch?.params.name ?? null;
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const historyOpen = popoverOpen || dialogOpen;
  const feed = useNotificationHistory();

  // The compact (mobile) bell's dot: raised by any arrival while no history
  // surface is open, cleared by opening one.
  const [unseen, setUnseen] = useState(false);
  const openPopover = (open: boolean) => {
    setPopoverOpen(open);
    if (open) setUnseen(false);
  };
  const openDialog = (open: boolean) => {
    setDialogOpen(open);
    if (open) setUnseen(false);
  };

  const { agents } = useGateway();
  const agentsRef = useRef(agents);
  useEffect(() => {
    agentsRef.current = agents;
  }, [agents]);

  const { current, dismiss } = useNotificationsPill(controller, {
    viewedAgent,
    orbStateFor: (name) => {
      const row = agentsRef.current.find((agent) => agent.name === name);
      if (!row) return null;
      const operation = useAgentOps.getState().getOp(row.name).operation;
      return getAgentVisualStatus(row, operation, "", row.activityState)
        .orbState;
    },
    // While the history is on screen, arrivals skip the pill's animations and
    // just appear at the top of the list.
    paused: historyOpen,
    onNotification: (item) => {
      if (historyOpen) feed.prepend(item);
      else setUnseen(true);
    },
  });

  const morphWidth = useMotionValue(PILL_BUTTON_SIZE);
  const morphHeight = useMotionValue(PILL_BUTTON_SIZE);

  // Navigation lives here, inside the router, so the pill component can render
  // on routerless surfaces (the version-gate screens) without crashing.
  const navigate = useNavigate();
  const openAgent = (agent: string) => {
    dismiss();
    void navigate(agent ? `/agent/${encodeURIComponent(agent)}` : "/");
  };
  const openEntry = (entry: LoggedUserNotification) => {
    setPopoverOpen(false);
    setDialogOpen(false);
    void navigate(
      entry.agent ? `/agent/${encodeURIComponent(entry.agent)}` : "/",
    );
  };

  return (
    <NotificationsPillContext.Provider
      value={{
        current,
        dismiss,
        unseen,
        feed,
        popoverOpen,
        setPopoverOpen: openPopover,
        dialogOpen,
        setDialogOpen: openDialog,
        openAgent,
        openEntry,
        morph: { width: morphWidth, height: morphHeight },
      }}
    >
      {children}
    </NotificationsPillContext.Provider>
  );
}

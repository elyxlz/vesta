import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  type ReactNode,
} from "react";
import { StyleSheet, View } from "react-native";
import type { AgentActivityState, AgentStatus } from "@vesta/core";

export type BootDestination = "connect" | "home" | "agent";

export interface BootTargetFrame {
  x: number;
  y: number;
  width: number;
  height: number;
  status: AgentStatus;
  activityState?: AgentActivityState;
}

interface BootTransitionValue {
  active: boolean;
  reportTarget: (destination: BootDestination, frame: BootTargetFrame) => void;
  targetVisible: boolean;
}

const BootTransitionContext = createContext<BootTransitionValue | null>(null);
const BootTransitionTargetFrozenContext = createContext(false);

export function BootTransitionProvider({
  active,
  children,
  onTarget,
  targetVisible = false,
}: {
  active: boolean;
  children: ReactNode;
  onTarget: (destination: BootDestination, frame: BootTargetFrame) => void;
  targetVisible?: boolean;
}) {
  const value = useMemo(
    () => ({ active, reportTarget: onTarget, targetVisible }),
    [active, onTarget, targetVisible],
  );
  return (
    <BootTransitionContext.Provider value={value}>
      {children}
    </BootTransitionContext.Provider>
  );
}

export function BootTransitionTarget({
  activityState,
  children,
  destination,
  enabled = true,
  status,
}: {
  activityState?: AgentActivityState;
  children: ReactNode;
  destination: BootDestination;
  enabled?: boolean;
  status: AgentStatus;
}) {
  const transition = useContext(BootTransitionContext);
  const view = useRef<View>(null);

  const measure = useCallback(() => {
    if (!transition?.active || !enabled) return;
    view.current?.measureInWindow((x, y, width, height) => {
      if (width <= 0 || height <= 0) return;
      transition.reportTarget(destination, {
        x,
        y,
        width,
        height,
        status,
        ...(activityState ? { activityState } : {}),
      });
    });
  }, [activityState, destination, enabled, status, transition]);

  useEffect(() => {
    if (!transition?.active || !enabled) return;
    const frame = requestAnimationFrame(measure);
    return () => cancelAnimationFrame(frame);
  }, [enabled, measure, transition?.active]);

  return (
    <View
      ref={view}
      collapsable={false}
      onLayout={measure}
      style={
        transition?.active && enabled && !transition.targetVisible
          ? styles.hidden
          : null
      }
    >
      <BootTransitionTargetFrozenContext.Provider
        value={Boolean(transition?.active && enabled)}
      >
        {children}
      </BootTransitionTargetFrozenContext.Provider>
    </View>
  );
}

export function useBootTransitionTargetFrozen(): boolean {
  return useContext(BootTransitionTargetFrozenContext);
}

const styles = StyleSheet.create({
  hidden: { opacity: 0 },
});

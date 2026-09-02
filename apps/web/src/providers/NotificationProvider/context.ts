import { createContext, useContext } from "react";

export interface NotificationContextValue {
  notifyAssistant: (agentName: string, text: string) => void;
  // The agent whose chat the user is actively viewing. Its tap suppresses
  // direct firing so that AgentSocketProvider can instead fire after the UI's
  // typing delay, keeping notification and visible-text in sync.
  setChattingAgent: (agentName: string | null) => void;
}

export const NotificationContext =
  createContext<NotificationContextValue | null>(null);

export function useNotifications(): NotificationContextValue {
  return (
    useContext(NotificationContext) ?? {
      notifyAssistant: () => {
        /* noop */
      },
      setChattingAgent: () => {
        /* noop */
      },
    }
  );
}

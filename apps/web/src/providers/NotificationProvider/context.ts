import { createContext, useContext } from "react";

export interface NotificationContextValue {
  notifyAssistant: (agentName: string, text: string) => void;
}

export const NotificationContext =
  createContext<NotificationContextValue | null>(null);

export function useNotifications(): NotificationContextValue {
  return (
    useContext(NotificationContext) ?? {
      notifyAssistant: () => {
        /* noop */
      },
    }
  );
}

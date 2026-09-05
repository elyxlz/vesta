import { createContext, useContext } from "react";

export interface NotificationContextValue {
  // A reply landing in a room: `sender` titles the notification, `room` tags it and decides where
  // a click lands.
  notifyAssistant: (sender: string, text: string, room: string) => void;
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

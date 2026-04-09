import { useEffect, useRef } from "react";

export const SERVICE_UPDATE_EVENT = "vesta-service-update";

export function useServiceUpdate(
  service: string,
  callback: (action: "registered" | "updated" | "removed") => void,
) {
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  useEffect(() => {
    const handler = (e: Event) => {
      if (!(e instanceof CustomEvent)) return;
      const detail = e.detail as { service?: string; action?: string };
      if (detail.service !== service) return;
      callbackRef.current(
        detail.action as "registered" | "updated" | "removed",
      );
    };
    window.addEventListener(SERVICE_UPDATE_EVENT, handler);
    return () => window.removeEventListener(SERVICE_UPDATE_EVENT, handler);
  }, [service]);
}

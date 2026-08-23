import { createContext, useContext } from "react";

// Lets a page hold the agent pager still while a touch is down on a control
// that must not start a page swipe, such as the chat composer.
export type PagerScrollLock = (locked: boolean) => void;

const PagerScrollLockContext = createContext<PagerScrollLock>(() => undefined);

export const PagerScrollLockProvider = PagerScrollLockContext.Provider;

export function usePagerScrollLock(): PagerScrollLock {
  return useContext(PagerScrollLockContext);
}

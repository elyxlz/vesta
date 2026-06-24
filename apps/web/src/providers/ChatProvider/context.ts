import {
  createContext,
  useContext,
  type Dispatch,
  type SetStateAction,
} from "react";
import { useChat } from "./use-chat";

// Context + hook live here, separate from the ChatProvider component, so the
// ChatContext identity is stable across Fast Refresh. Co-locating them with the
// component made every edit re-create the context, detaching mounted consumers
// ("useChatContext must be used within ChatProvider" on hot reload).
export type ChatContextValue = ReturnType<typeof useChat> & {
  showToolCalls: boolean;
  setShowToolCalls: Dispatch<SetStateAction<boolean>>;
};

export const ChatContext = createContext<ChatContextValue | null>(null);

export function useChatContext() {
  const context = useContext(ChatContext);
  if (!context) {
    throw new Error("useChatContext must be used within ChatProvider");
  }
  return context;
}

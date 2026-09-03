import {
  useCallback,
  useEffect,
  useEffectEvent,
  useState,
  useSyncExternalStore,
} from "react";
import type {
  ChatAttachment,
  ChatSession,
  InputMethod,
  Tree,
} from "@vesta/core";
import { chatSocketPath, createChatSession } from "@vesta/core";
import { useChatSession, useReplica, useSyncState } from "@vesta/core/react";
import { useController } from "@/providers/ControllerProvider/context";
import { naturalPacingFor } from "@/stores/use-preferences";
import { useVoice } from "@/stores/use-voice";

function idsEqual(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((value, i) => value === b[i]);
}

interface UseAgentSocketOptions {
  name: string | null;
  active: boolean;
  onAssistantMessage?: (text: string) => void;
  onPrefetch?: (text: string) => void;
}

// A slot whose occupant the effect owns, read through useSyncExternalStore: the session is
// created by the effect whose cleanup closes it, so the two lifetimes cannot diverge.
function createSessionSlot() {
  let current: ChatSession | null = null;
  const listeners = new Set<() => void>();
  return {
    get: () => current,
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    set: (next: ChatSession | null) => {
      current = next;
      for (const listener of listeners) listener();
    },
  };
}

// The web adapter over core's chat session: it injects the platform ports (the session's
// token-stamped socket URL, the browser id maker, the pacing preference joined to the voice mode)
// and subscribes. The session owns the socket, the seed, the pacing queue, and the send path.
export function useAgentSocketState({
  name,
  active,
  onAssistantMessage,
  onPrefetch,
}: UseAgentSocketOptions) {
  const controller = useController();
  const onReply = useEffectEvent((text: string) => onAssistantMessage?.(text));
  const prefetch = useEffectEvent((text: string) => onPrefetch?.(text));
  const [slot] = useState(createSessionSlot);
  const session = useSyncExternalStore(slot.subscribe, slot.get);

  useEffect(() => {
    if (!active || !name) return;
    const agent = name;
    const created = createChatSession(
      {
        http: controller.http,
        agent,
        buildUrl: () => controller.session.websocketUrl(chatSocketPath(agent)),
        makeId: () => crypto.randomUUID(),
        // A voice conversation is duplex: the reply is spoken the moment it lands, not typed out.
        naturalPacing: () =>
          naturalPacingFor(agent) &&
          useVoice.getState().recordingMode !== "conversation",
      },
      { onReply, onPrefetch: prefetch },
    );
    slot.set(created);
    return () => {
      created.close();
      slot.set(null);
    };
  }, [active, name, controller, slot]);

  const state = useChatSession(session);
  const connected = useSyncState(controller) === "open";

  const pendingSelector = useCallback(
    (tree: Tree | null): string[] =>
      name
        ? (tree?.agents[name]?.notifications.pending ?? []).flatMap((n) =>
            n.notif_id ? [n.notif_id] : [],
          )
        : [],
    [name],
  );
  const pendingNotifications = useReplica(
    controller.replica,
    pendingSelector,
    idsEqual,
  );

  const send = useCallback(
    (
      text: string,
      inputMethod: InputMethod = "typed",
      attachments?: ChatAttachment[],
    ): boolean => {
      const live = slot.get();
      if (!live) return false;
      live.send(text, inputMethod, attachments);
      return true;
    },
    [slot],
  );
  const retry = useCallback(
    (
      intentId: string,
      text: string,
      inputMethod: InputMethod = "typed",
      attachments?: ChatAttachment[],
    ) => {
      slot.get()?.retry(intentId, text, inputMethod, attachments);
    },
    [slot],
  );
  const loadMore = useCallback(
    () => slot.get()?.loadMore() ?? Promise.resolve(),
    [slot],
  );
  const trimHistory = useCallback(() => {
    slot.get()?.trimHistory();
  }, [slot]);
  const reportSpeaking = useCallback(
    (speaking: boolean) => {
      slot.get()?.reportSpeaking(speaking);
    },
    [slot],
  );

  return {
    messages: state.chat.messages,
    isTyping: state.typing,
    connected,
    historyLoaded: state.chat.historyLoaded,
    pendingNotifications,
    hasMore: state.chat.cursor !== null,
    loadingMore: state.loadingMore,
    loadMore,
    trimHistory,
    send,
    retry,
    reportSpeaking,
  };
}

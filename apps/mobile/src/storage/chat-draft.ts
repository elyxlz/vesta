import AsyncStorage from "@react-native-async-storage/async-storage";

// Unsent composer drafts, keyed per agent. Backgrounding tears the controller down and unmounts
// the chat view (component state is lost), so the draft lives in storage and survives app
// switches and relaunches alike.
const CHAT_DRAFT_KEY_PREFIX = "vesta.chat-draft.v1.";

function draftKey(agent: string): string {
  return `${CHAT_DRAFT_KEY_PREFIX}${agent}`;
}

export function readChatDraft(agent: string): Promise<string | null> {
  return AsyncStorage.getItem(draftKey(agent));
}

export function writeChatDraft(agent: string, text: string): Promise<void> {
  return text
    ? AsyncStorage.setItem(draftKey(agent), text)
    : AsyncStorage.removeItem(draftKey(agent));
}

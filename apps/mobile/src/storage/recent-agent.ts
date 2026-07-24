import AsyncStorage from "@react-native-async-storage/async-storage";

const LAST_USED_AGENT_KEY = "vesta.last-used-agent.v1";

export function readLastUsedAgent(): Promise<string | null> {
  return AsyncStorage.getItem(LAST_USED_AGENT_KEY);
}

export function writeLastUsedAgent(name: string): Promise<void> {
  return AsyncStorage.setItem(LAST_USED_AGENT_KEY, name);
}

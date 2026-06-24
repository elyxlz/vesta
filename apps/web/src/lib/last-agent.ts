// The most recently opened agent, so the home carousel can center it on return.
const LAST_AGENT_KEY = "vesta:last-agent";

export function getLastAgent(): string | null {
  return localStorage.getItem(LAST_AGENT_KEY);
}

export function setLastAgent(name: string): void {
  localStorage.setItem(LAST_AGENT_KEY, name);
}

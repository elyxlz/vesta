// The desktop panel's remembered layout choice, per agent: collapsed chat with
// the dashboard full-page. Expanded is the default, so it stores only the
// collapsed state and expanding removes the key.
const KEY_PREFIX = "vesta:chat-collapsed:";

export function getChatCollapsed(name: string): boolean {
  return localStorage.getItem(KEY_PREFIX + name) !== null;
}

export function setChatCollapsed(name: string, collapsed: boolean): void {
  if (collapsed) localStorage.setItem(KEY_PREFIX + name, "1");
  else localStorage.removeItem(KEY_PREFIX + name);
}

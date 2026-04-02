import { create } from "zustand";

export type View =
  | "loading"
  | "connect"
  | "home"
  | "create-agent"
  | "agent-detail"
  | "agent-chat"
  | "agent-console";

interface NavigationState {
  view: View;
  selectedAgent: string | null;

  setView: (view: View) => void;
  navigateToAgent: (name: string) => void;
  navigateToChat: (name: string) => void;
  navigateToConsole: (name: string) => void;
  navigateHome: () => void;
  navigateToCreate: () => void;
  navigateToConnect: () => void;
}

function viewToPath(view: View, agent: string | null): string {
  switch (view) {
    case "connect": return "/connect";
    case "create-agent": return "/new";
    case "agent-detail": return `/agent/${agent}`;
    case "agent-chat": return `/agent/${agent}/chat`;
    case "agent-console": return `/agent/${agent}/console`;
    case "home": return "/";
    default: return "/";
  }
}

function push(view: View, agent: string | null) {
  const path = viewToPath(view, agent);
  if (window.location.pathname !== path) {
    history.pushState({ view, agent }, "", path);
  }
}

export function parseUrl(): { view: View; agent: string | null } {
  const path = window.location.pathname;

  if (path === "/connect") return { view: "connect", agent: null };
  if (path === "/new") return { view: "create-agent", agent: null };

  const agentChat = path.match(/^\/agent\/([^/]+)\/chat$/);
  if (agentChat) return { view: "agent-chat", agent: agentChat[1] };

  const agentConsole = path.match(/^\/agent\/([^/]+)\/console$/);
  if (agentConsole) return { view: "agent-console", agent: agentConsole[1] };

  const agentDetail = path.match(/^\/agent\/([^/]+)$/);
  if (agentDetail) return { view: "agent-detail", agent: agentDetail[1] };

  return { view: "home", agent: null };
}

export const useNavigation = create<NavigationState>((set) => ({
  view: "loading",
  selectedAgent: null,

  setView: (view) => set({ view }),

  navigateToAgent: (name) => {
    push("agent-detail", name);
    set({ view: "agent-detail", selectedAgent: name });
  },

  navigateToChat: (name) => {
    push("agent-chat", name);
    set({ view: "agent-chat", selectedAgent: name });
  },

  navigateToConsole: (name) => {
    push("agent-console", name);
    set({ view: "agent-console", selectedAgent: name });
  },

  navigateHome: () => {
    push("home", null);
    set({ view: "home", selectedAgent: null });
  },

  navigateToCreate: () => {
    push("create-agent", null);
    set({ view: "create-agent", selectedAgent: null });
  },

  navigateToConnect: () => {
    push("connect", null);
    set({ view: "connect", selectedAgent: null });
  },
}));

// Handle browser back/forward
window.addEventListener("popstate", () => {
  const { view, agent } = parseUrl();
  useNavigation.setState({ view, selectedAgent: agent });
});

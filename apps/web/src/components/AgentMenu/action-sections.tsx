import {
  Archive,
  ArrowLeftRight,
  Globe,
  KeyRound,
  Play,
  RefreshCw,
  ScrollText,
  Settings,
  SlidersHorizontal,
  Square,
  Trash2,
} from "lucide-react";

export interface AgentActionsInput {
  isRunning: boolean;
  showAliveActions?: boolean;
  isBusy: boolean;
  onLogs?: () => void;
  onServices?: () => void;
  onToggle: () => void;
  onRestart: () => void;
  onBackup: () => void;
  onAuthenticate?: () => void;
  isAuthenticated?: boolean;
  onAppSettings?: () => void;
  onAgentSettings?: () => void;
  onSwitchGateway?: () => void;
  onDelete?: () => void;
}

export interface ActionItem {
  key: string;
  icon: React.ReactNode;
  label: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
  variant?: "default" | "secondary" | "destructive";
}

export interface ActionSection {
  key: string;
  title: string;
  items: ActionItem[];
}

export function buildActionSections(input: AgentActionsInput): ActionSection[] {
  const sections: ActionSection[] = [];

  if (input.isRunning) {
    const toolItems: ActionItem[] = [];
    if (input.onLogs) {
      toolItems.push({
        key: "logs",
        icon: <ScrollText data-icon="inline-start" />,
        label: "logs",
        onClick: input.onLogs,
      });
    }
    if (input.onServices) {
      toolItems.push({
        key: "services",
        icon: <Globe data-icon="inline-start" />,
        label: "services",
        onClick: input.onServices,
      });
    }
    if (toolItems.length > 0) {
      sections.push({ key: "view", title: "tools", items: toolItems });
    }
  }

  const controlItems: ActionItem[] = [
    {
      key: "toggle",
      icon: input.isRunning ? (
        <Square data-icon="inline-start" />
      ) : (
        <Play data-icon="inline-start" />
      ),
      label: input.isRunning ? "stop" : "start",
      onClick: input.onToggle,
      disabled: input.isBusy,
    },
  ];
  if (input.isRunning) {
    controlItems.push({
      key: "restart",
      icon: <RefreshCw data-icon="inline-start" />,
      label: "restart",
      onClick: input.onRestart,
      disabled: input.isBusy,
    });
  }
  controlItems.push({
    key: "backup",
    icon: <Archive data-icon="inline-start" />,
    label: "backups",
    onClick: input.onBackup,
    disabled: input.isBusy,
  });
  if (input.onAuthenticate) {
    controlItems.push({
      key: "authenticate",
      icon: <KeyRound data-icon="inline-start" />,
      label: input.isAuthenticated ? "switch provider" : "sign in",
      onClick: input.onAuthenticate,
    });
  }
  if (input.onSwitchGateway) {
    controlItems.push({
      key: "switch-gateway",
      icon: <ArrowLeftRight data-icon="inline-start" />,
      label: "switch gateway",
      onClick: input.onSwitchGateway,
    });
  }
  sections.push({ key: "controls", title: "controls", items: controlItems });

  const generalItems = buildOtherItems(input);
  if (generalItems.length > 0) {
    sections.push({ key: "general", title: "other", items: generalItems });
  }

  return sections;
}

// The "Other" section's items, each present only when its handler is supplied.
function buildOtherItems(input: AgentActionsInput): ActionItem[] {
  const items: ActionItem[] = [];
  if (input.onAgentSettings) {
    items.push({
      key: "agent-settings",
      icon: <SlidersHorizontal data-icon="inline-start" />,
      label: "agent settings",
      onClick: input.onAgentSettings,
    });
  }
  if (input.onAppSettings) {
    items.push({
      key: "app-settings",
      icon: <Settings data-icon="inline-start" />,
      label: "app settings",
      onClick: input.onAppSettings,
    });
  }
  if (input.onDelete) {
    items.push({
      key: "delete",
      icon: <Trash2 data-icon="inline-start" />,
      label: "delete",
      onClick: input.onDelete,
      disabled: input.isBusy,
      variant: "destructive",
    });
  }
  return items;
}

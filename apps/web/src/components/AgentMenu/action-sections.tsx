import {
  Archive,
  Bug,
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
  onLogs: () => void;
  onToggle: () => void;
  onRestart: () => void;
  onBackup: () => void;
  onAuthenticate?: () => void;
  isAuthenticated?: boolean;
  onAppSettings?: () => void;
  onAgentSettings?: () => void;
  onDelete?: () => void;
  onDebugInfo?: () => void;
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
    sections.push({
      key: "view",
      title: "Tools",
      items: [
        {
          key: "logs",
          icon: <ScrollText data-icon="inline-start" />,
          label: "logs",
          onClick: input.onLogs,
        },
      ],
    });
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
    label: "backup",
    onClick: input.onBackup,
    disabled: input.isBusy,
  });
  sections.push({ key: "controls", title: "Controls", items: controlItems });

  const generalItems: ActionItem[] = [];
  if (input.onAgentSettings) {
    generalItems.push({
      key: "agent-settings",
      icon: <SlidersHorizontal data-icon="inline-start" />,
      label: "agent settings",
      onClick: input.onAgentSettings,
    });
  }
  if (input.onAppSettings) {
    generalItems.push({
      key: "app-settings",
      icon: <Settings data-icon="inline-start" />,
      label: "app settings",
      onClick: input.onAppSettings,
    });
  }
  if (input.onDebugInfo) {
    generalItems.push({
      key: "debug",
      icon: <Bug data-icon="inline-start" />,
      label: "debug info",
      onClick: input.onDebugInfo,
    });
  }
  if (input.onAuthenticate) {
    generalItems.push({
      key: "authenticate",
      icon: <KeyRound data-icon="inline-start" />,
      label: input.isAuthenticated ? "switch provider" : "sign in",
      onClick: input.onAuthenticate,
    });
  }
  if (input.onDelete) {
    generalItems.push({
      key: "delete",
      icon: <Trash2 data-icon="inline-start" />,
      label: "delete",
      onClick: input.onDelete,
      disabled: input.isBusy,
      variant: "destructive",
    });
  }
  if (generalItems.length > 0) {
    sections.push({ key: "general", title: "Other", items: generalItems });
  }

  return sections;
}

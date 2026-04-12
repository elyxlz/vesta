/* eslint-disable react-refresh/only-export-components */
import {
  Archive,
  Bug,
  KeyRound,
  Play,
  RefreshCw,
  ScrollText,
  Settings,
  Square,
  Trash2,
  Wrench,
  Hammer,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { MenuSection } from "@/components/ui/menu-section";

export interface AgentActionsInput {
  isRunning: boolean;
  showAliveActions?: boolean;
  isBusy: boolean;
  showToolCalls: boolean;
  onLogs: () => void;
  onToolCalls: () => void;
  onToggle: () => void;
  onRestart: () => void;
  onRebuild: () => void;
  onBackup: () => void;
  onAuthenticate?: () => void;
  onOpenSettings?: () => void;
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

  if (input.onAuthenticate) {
    sections.push({
      key: "setup",
      title: "Setup",
      items: [
        {
          key: "authenticate",
          icon: <KeyRound data-icon="inline-start" />,
          label: "authenticate",
          onClick: input.onAuthenticate,
          variant: "default",
        },
      ],
    });
  }

  const viewItems: ActionItem[] = [];
  if (input.showAliveActions) {
    viewItems.push({
      key: "logs",
      icon: <ScrollText data-icon="inline-start" />,
      label: "logs",
      onClick: input.onLogs,
    });
  }
  viewItems.push({
    key: "tool-calls",
    icon: <Wrench data-icon="inline-start" />,
    label: input.showToolCalls ? "hide tool calls" : "show tool calls",
    onClick: input.onToolCalls,
  });
  sections.push({ key: "view", title: "View", items: viewItems });

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
    controlItems.push(
      {
        key: "restart",
        icon: <RefreshCw data-icon="inline-start" />,
        label: "restart",
        onClick: input.onRestart,
        disabled: input.isBusy,
      },
      {
        key: "rebuild",
        icon: <Hammer data-icon="inline-start" />,
        label: "rebuild",
        onClick: input.onRebuild,
        disabled: input.isBusy,
      },
    );
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
  if (input.onOpenSettings) {
    generalItems.push({
      key: "settings",
      icon: <Settings data-icon="inline-start" />,
      label: "settings",
      onClick: input.onOpenSettings,
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
    sections.push({ key: "general", title: "General", items: generalItems });
  }

  return sections;
}

export function AgentActions({
  wrapper: Wrapper = PassThrough,
  ...input
}: AgentActionsInput & {
  wrapper?: React.ComponentType<{ children: React.ReactNode }>;
}) {
  const sections = buildActionSections(input);

  return (
    <div className="flex flex-col gap-4">
      {sections.map((section) => (
        <MenuSection key={section.key} title={section.title}>
          {section.items.map((item) => (
            <Wrapper key={item.key}>
              <Button
                variant={item.variant ?? "secondary"}
                className="w-full justify-start"
                disabled={item.disabled}
                onClick={item.onClick}
              >
                {item.icon}
                {item.label}
              </Button>
            </Wrapper>
          ))}
        </MenuSection>
      ))}
    </div>
  );
}

function PassThrough({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

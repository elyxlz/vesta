import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/DropdownMenu";
import { buildActionSections } from "./action-sections";
import type { MenuProps } from "./types";

export function DesktopMenu({ state, open, onOpenChange, trigger }: MenuProps) {
  const sections = buildActionSections({
    isRunning: state.isRunning,
    showAliveActions: state.showAliveActions,
    isBusy: state.isBusy,
    onLogs: state.onLogs,
    onServices: state.onServices,
    onToggle: state.onToggle,
    onRestart: state.onRestart,
    onBackup: state.onBackup,
    onAppSettings: state.onAppSettings,
    onAgentSettings: state.onAgentSettings,
    onSwitchGateway: state.onSwitchGateway,
  });

  return (
    <DropdownMenu open={open} onOpenChange={onOpenChange}>
      <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
      <DropdownMenuContent align="end" side="bottom" className="min-w-[180px]">
        {sections.map((section, _i) => (
          <div key={section.key}>
            <DropdownMenuLabel className="text-xs text-muted-foreground font-medium">
              {section.title}
            </DropdownMenuLabel>
            {section.items.map((item) => (
              <DropdownMenuItem
                key={item.key}
                disabled={item.disabled}
                onClick={item.onClick}
                variant={
                  item.variant === "destructive" ? "destructive" : undefined
                }
              >
                <item.icon data-icon="inline-start" />
                {item.label}
              </DropdownMenuItem>
            ))}
          </div>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

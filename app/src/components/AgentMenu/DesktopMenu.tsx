import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { buildActionSections } from "./AgentActions";
import type { MenuProps } from "./types";

export function DesktopMenu({ state, open, onOpenChange, trigger }: MenuProps) {
  const sections = buildActionSections({
    isRunning: state.isRunning,
    showAliveActions: state.showAliveActions,
    isBusy: state.isBusy,
    showToolCalls: state.showToolCalls,
    onLogs: state.onLogs,
    onToolCalls: state.onToolCalls,
    onToggle: state.onToggle,
    onRestart: state.onRestart,
    onRebuild: state.onRebuild,
    onBackup: state.onBackup,
    onOpenSettings: state.onOpenSettings,
    onDebugInfo: state.onDebugInfo,
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
                {item.icon}
                {item.label}
              </DropdownMenuItem>
            ))}
          </div>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

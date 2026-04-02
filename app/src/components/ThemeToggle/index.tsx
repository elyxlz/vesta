import { Sun, Moon, Monitor } from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useTheme, type Theme } from "@/stores/use-theme";
import { cn } from "@/lib/utils";

const CYCLE: Theme[] = ["system", "light", "dark"];

export function ThemeToggle() {
  const theme = useTheme((s) => s.theme);
  const setTheme = useTheme((s) => s.setTheme);

  const next = () => {
    const idx = CYCLE.indexOf(theme);
    setTheme(CYCLE[(idx + 1) % CYCLE.length]);
  };

  const icon =
    theme === "light" ? (
      <Sun size={13} />
    ) : theme === "dark" ? (
      <Moon size={13} />
    ) : (
      <Monitor size={13} />
    );

  const label =
    theme === "light" ? "light" : theme === "dark" ? "dark" : "system";

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          onClick={next}
          className={cn(
            "p-1.5 rounded-md transition-colors",
            "text-muted hover:text-foreground hover:bg-accent",
          )}
        >
          {icon}
        </button>
      </TooltipTrigger>
      <TooltipContent side="top">{label}</TooltipContent>
    </Tooltip>
  );
}

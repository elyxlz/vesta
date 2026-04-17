import { Sun, Moon, Monitor } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useTheme } from "@/providers/ThemeProvider";

type Theme = "dark" | "light" | "system";
const CYCLE: Theme[] = ["system", "light", "dark"];

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();

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
        <Button variant="ghost" size="icon" onClick={next}>
          {icon}
        </Button>
      </TooltipTrigger>
      <TooltipContent side="top">{label}</TooltipContent>
    </Tooltip>
  );
}

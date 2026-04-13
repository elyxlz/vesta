import { Mic, Sun, PanelLeft } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Kbd } from "@/components/ui/kbd";
import { MenuSection } from "@/components/ui/menu-section";
import {
  useSpacebarMode,
  type SpacebarMode,
} from "@/providers/KeybindProvider";

const isMac =
  typeof navigator !== "undefined" &&
  /Mac|iPhone|iPad/.test(navigator.userAgent);

interface Keybind {
  icon: React.ReactNode;
  label: string;
  keys: React.ReactNode;
}

const keybinds: Keybind[] = [
  {
    icon: <Mic className="size-3.5" />,
    label: "toggle voice",
    keys: <Kbd>Space</Kbd>,
  },
  {
    icon: <Sun className="size-3.5" />,
    label: "toggle theme",
    keys: <Kbd>D</Kbd>,
  },
  {
    icon: <PanelLeft className="size-3.5" />,
    label: "toggle sidebar",
    keys: (
      <span className="inline-flex items-center gap-0.5">
        <Kbd>{isMac ? "⌘" : "Ctrl"}</Kbd>
        <Kbd>B</Kbd>
      </span>
    ),
  },
];

const modeOptions: { value: SpacebarMode; label: string }[] = [
  { value: "toggle", label: "toggle" },
  { value: "hold", label: "hold" },
];

export function KeybindsCard() {
  const [spacebarMode, setSpacebarMode] = useSpacebarMode();

  return (
    <Card size="sm">
      <CardContent>
        <MenuSection title="Keybinds">
          <div className="flex flex-col gap-1.5">
            {keybinds.map((bind) => (
              <div key={bind.label}>
                <div className="flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm text-muted-foreground">
                  {bind.icon}
                  <span className="flex-1">{bind.label}</span>
                  {bind.keys}
                </div>
                {bind.label === "toggle voice" && (
                  <div className="flex items-center justify-end gap-2 px-2 py-1.5">
                    <span className="text-xs text-muted-foreground">
                      activation
                    </span>
                    <div className="inline-flex rounded-md bg-muted p-0.5">
                      {modeOptions.map((opt) => (
                        <button
                          key={opt.value}
                          className={`rounded-sm px-2.5 py-1 text-xs transition-colors ${
                            spacebarMode === opt.value
                              ? "bg-background text-foreground shadow-sm"
                              : "text-muted-foreground hover:text-foreground"
                          }`}
                          onClick={() => setSpacebarMode(opt.value)}
                        >
                          {opt.label}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </MenuSection>
      </CardContent>
    </Card>
  );
}

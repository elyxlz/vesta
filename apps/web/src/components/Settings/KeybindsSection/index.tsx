import { Mic, Sun, PanelLeft } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Kbd } from "@/components/ui/kbd";
import { MenuSection } from "@/components/ui/menu-section";

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
    label: "dictate",
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

export function KeybindsCard() {
  return (
    <Card size="sm">
      <CardContent>
        <MenuSection title="keybinds">
          <div className="flex flex-col gap-1.5">
            {keybinds.map((bind) => (
              <div
                key={bind.label}
                className="flex items-center gap-2.5 rounded-md px-2 py-1.5 text-base text-muted-foreground"
              >
                {bind.icon}
                <span className="flex-1">{bind.label}</span>
                {bind.keys}
              </div>
            ))}
          </div>
        </MenuSection>
      </CardContent>
    </Card>
  );
}

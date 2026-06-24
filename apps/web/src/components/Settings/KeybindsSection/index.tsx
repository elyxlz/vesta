import { Hand, Mic, Sun, PanelLeft } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Kbd } from "@/components/ui/kbd";
import { MenuSection } from "@/components/ui/menu-section";
import {
  useVoiceActivation,
  type VoiceActivationMode,
} from "@/stores/use-voice-activation";

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
    label: "voice activation",
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

const modeOptions: { value: VoiceActivationMode; label: string }[] = [
  { value: "toggle", label: "toggle" },
  { value: "hold", label: "hold" },
];

export function KeybindsCard() {
  const activation = useVoiceActivation((s) => s.mode);
  const setActivation = useVoiceActivation((s) => s.setMode);

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
                {bind.label === "voice activation" && (
                  <div className="flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm text-muted-foreground">
                    <Hand className="size-3.5" />
                    <span className="flex-1">activation mode</span>
                    <div className="inline-flex rounded-md bg-muted p-0.5">
                      {modeOptions.map((opt) => (
                        <button
                          key={opt.value}
                          className={`rounded-sm px-2.5 py-1 text-xs transition-colors ${
                            activation === opt.value
                              ? "bg-background text-foreground shadow-sm"
                              : "text-muted-foreground hover:text-foreground"
                          }`}
                          onClick={() => setActivation(opt.value)}
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

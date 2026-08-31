import { Maximize2, PanelRightClose, Volume2, VolumeX } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { ButtonGroup } from "@/components/ui/button-group";
import { cn } from "@/lib/utils";
import { useLayout } from "@/stores/use-layout";
import { useVoice } from "@/stores/use-voice";

interface ChatHeaderActionsProps {
  fullscreen?: boolean;
  // Recede in perspective with the chat while a conversation runs.
  receded?: boolean;
  onCollapse?: () => void;
  agentName: string;
}

export function ChatHeaderActions({
  fullscreen,
  receded,
  onCollapse,
  agentName,
}: ChatHeaderActionsProps) {
  const navigate = useNavigate();
  const speechEnabled = useVoice((s) => s.speechEnabled);
  const navbarHeight = useLayout((s) => s.navbarHeight);

  if (fullscreen && !speechEnabled) return null;

  // The fullscreen chat sits under the absolute navbar, so the actions start below it.
  return (
    <div
      className={cn(
        "absolute right-3 z-10 [will-change:transform] transition-transform ease-[cubic-bezier(0.32,0.72,0,1)]",
        receded ? "duration-500 -translate-y-16" : "duration-300",
      )}
      style={{ top: fullscreen ? navbarHeight + 12 : 12 }}
    >
      <ButtonGroup>
        {speechEnabled && <SpeechButton />}
        {!fullscreen && (
          <>
            <Button
              variant="outline"
              size="icon-sm"
              className="text-muted-foreground"
              onClick={() => {
                void navigate(`/agent/${agentName}/chat`);
              }}
            >
              <Maximize2 />
            </Button>
            <Button
              variant="outline"
              size="icon-sm"
              className="text-muted-foreground"
              onClick={onCollapse}
            >
              <PanelRightClose />
            </Button>
          </>
        )}
      </ButtonGroup>
    </div>
  );
}

// A per-device mute of spoken replies: red while muted. A conversation speaks regardless, so
// this only silences the ambient read-aloud outside one.
function SpeechButton() {
  const muted = useVoice((s) => s.muted);
  const speaking = useVoice((s) => s.isSpeaking);
  const toggleMuted = useVoice((s) => s.toggleMuted);

  return (
    <Button
      variant="outline"
      size="icon-sm"
      aria-pressed={muted}
      aria-label={muted ? "unmute voice" : "mute voice"}
      title={muted ? "unmute voice" : "mute voice"}
      className={cn(
        muted
          ? "text-red-500 hover:text-red-600"
          : cn("text-muted-foreground", speaking && "text-foreground"),
      )}
      onClick={toggleMuted}
    >
      {muted ? <VolumeX /> : <Volume2 />}
    </Button>
  );
}

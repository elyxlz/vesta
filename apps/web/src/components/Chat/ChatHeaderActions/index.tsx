import { Maximize2, PanelRightClose, Volume2, VolumeX } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { ButtonGroup } from "@/components/ui/button-group";
import { cn } from "@/lib/utils";
import { setTtsEnabled } from "@/lib/voice";
import { useVoice } from "@/stores/use-voice";

interface ChatHeaderActionsProps {
  fullscreen?: boolean;
  onCollapse?: () => void;
  agentName: string;
}

export function ChatHeaderActions({
  fullscreen,
  onCollapse,
  agentName,
}: ChatHeaderActionsProps) {
  const navigate = useNavigate();
  const ttsConfigured = useVoice((s) => s.ttsStatus?.configured ?? false);

  if (fullscreen && !ttsConfigured) return null;

  return (
    <div className="absolute right-3 top-3 z-10">
      <ButtonGroup>
        {ttsConfigured && <SpeechButton agentName={agentName} />}
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

// Mutes and unmutes the agent's voice. Muting also cuts the reply being read out, and the
// store's patch is the optimistic write, with a failed save re-read from the agent.
function SpeechButton({ agentName }: { agentName: string }) {
  const enabled = useVoice((s) => s.speechEnabled);
  const speaking = useVoice((s) => s.isSpeaking);
  const { patchTts, refreshVoiceStatus, stopSpeech } = useVoice.getState();

  const toggle = () => {
    const next = !enabled;
    if (!next) stopSpeech();
    patchTts({ enabled: next });
    setTtsEnabled(agentName, next).catch(() => {
      refreshVoiceStatus();
    });
  };

  return (
    <Button
      variant="outline"
      size="icon-sm"
      aria-pressed={enabled}
      aria-label={enabled ? "mute voice" : "unmute voice"}
      title={enabled ? "mute voice" : "unmute voice"}
      className={cn(
        "text-muted-foreground",
        enabled && speaking && "text-foreground",
      )}
      onClick={toggle}
    >
      {enabled ? <Volume2 /> : <VolumeX />}
    </Button>
  );
}

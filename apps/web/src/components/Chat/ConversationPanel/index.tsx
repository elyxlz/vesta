import { useEffect, useRef } from "react";
import { motion as m } from "motion/react";
import { Mic, MicOff, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Orb } from "@/components/Orb";
import { cn } from "@/lib/utils";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useVoice } from "@/stores/use-voice";

const ORB_SIZE = 168;

function phaseLabel({
  listening,
  micMuted,
  isSpeaking,
  thinking,
}: {
  listening: boolean;
  micMuted: boolean;
  isSpeaking: boolean;
  thinking: boolean;
}): string {
  if (!listening) return "connecting…";
  if (isSpeaking) return "speaking";
  if (micMuted) return "muted";
  if (thinking) return "thinking";
  return "listening";
}

// The live conversation surface the composer morphs into: the agent's real status orb with
// voice motion overlaid, and one row of controls. Same width as the composer by construction.
export function ConversationPanel({ morphed }: { morphed: boolean }) {
  // The session is already torn down while this panel plays its exit, so what it renders is
  // held at the last live values: reading the reset store would flash "connecting" on the
  // way out.
  const live = useVoice((s) => s.recordingMode === "conversation");
  const { orbState, statusLabel } = useSelectedAgent();
  const listening = useVoice((s) => s.listening);
  const liveTranscript = useVoice((s) => s.liveTranscript);
  const micMuted = useVoice((s) => s.micMuted);
  const isSpeaking = useVoice((s) => s.isSpeaking);
  const stopVoice = useVoice((s) => s.stopVoice);
  const toggleMicMuted = useVoice((s) => s.toggleMicMuted);

  const thinking = orbState === "thinking";
  // Your words take the pill over as you speak, the freshest one bold so the eye can ride the
  // stream; between turns the pill falls back to the phase.
  const transcript = liveTranscript.trim();
  const livePhase = phaseLabel({ listening, micMuted, isSpeaking, thinking });
  // The status decides the look; the voice phase only decides the motion. A muted mic or a
  // still-dialing session holds the orb still rather than pretending to listen.
  const liveMotion = isSpeaking
    ? ("talking" as const)
    : listening && !micMuted
      ? ("listening" as const)
      : undefined;
  const lastShownRef = useRef({
    transcript: "",
    phase: livePhase,
    motion: liveMotion,
  });
  useEffect(() => {
    if (live)
      lastShownRef.current = {
        transcript,
        phase: livePhase,
        motion: liveMotion,
      };
  });
  const shown = live
    ? { transcript, phase: livePhase, motion: liveMotion }
    : lastShownRef.current;
  const motion = shown.motion;
  const lastSpace = shown.transcript.lastIndexOf(" ");
  const spokenHead =
    lastSpace === -1 ? "" : shown.transcript.slice(0, lastSpace + 1);
  const spokenTail =
    lastSpace === -1 ? shown.transcript : shown.transcript.slice(lastSpace + 1);

  return (
    <div className="flex h-full flex-col items-center justify-end gap-4 px-4 pt-3 pb-4">
      {/* The orb slides up and in first; the action bar follows a beat behind. */}
      {/* The pill has finished growing before `morphed` flips, so this slide is no longer
          masked by the container's clip reveal. Staggered: orb first, bar a beat behind. */}
      <m.div
        initial={{ opacity: 0, y: 96 }}
        animate={morphed ? { opacity: 1, y: 0 } : { opacity: 0, y: 96 }}
        exit={{
          opacity: 0,
          y: 96,
          transition: { duration: 0.27, ease: [0.32, 0.72, 0, 1] },
        }}
        transition={{ duration: 0.55, ease: [0.32, 0.72, 0, 1] }}
        className="flex justify-center"
      >
        <Orb
          state={orbState}
          motion={motion}
          size={ORB_SIZE}
          label={statusLabel}
        />
      </m.div>
      <m.div
        initial={{ opacity: 0, y: 28 }}
        animate={morphed ? { opacity: 1, y: 0 } : { opacity: 0, y: 28 }}
        exit={{
          opacity: 0,
          y: 28,
          transition: { duration: 0.19, ease: [0.32, 0.72, 0, 1] },
        }}
        transition={{ delay: 0.015, duration: 0.38, ease: [0.32, 0.72, 0, 1] }}
        className="relative z-10 flex w-full items-end"
      >
        <Button
          type="button"
          size="icon"
          variant="outline"
          onClick={toggleMicMuted}
          aria-pressed={micMuted}
          aria-label={micMuted ? "unmute microphone" : "mute microphone"}
          className={cn(
            "size-10 rounded-full [&_svg]:size-4.5",
            micMuted && "bg-red-500 text-white hover:bg-red-600",
          )}
        >
          {micMuted ? <MicOff /> : <Mic />}
        </Button>
        <div className="flex min-w-0 flex-1 justify-center px-3">
          {/* Two lines at most, clipped from the top, so the newest words are always the
              visible ones while a long turn streams in. */}
          <div className="w-full min-w-0 rounded-2xl bg-muted px-4 py-1.5">
            <div
              className={cn(
                "flex max-h-[2lh] flex-col justify-end overflow-hidden text-sm break-words text-muted-foreground",
                shown.transcript ? "text-left" : "text-center",
              )}
            >
              {shown.transcript ? (
                <span>
                  {spokenHead}
                  <span className="font-semibold text-foreground">
                    {spokenTail}
                  </span>
                </span>
              ) : (
                shown.phase
              )}
            </div>
          </div>
        </div>
        <Button
          type="button"
          size="icon"
          variant="outline"
          onClick={stopVoice}
          aria-label="end conversation"
          title="end conversation"
          className="size-10 rounded-full [&_svg]:size-4.5"
        >
          <X />
        </Button>
      </m.div>
    </div>
  );
}

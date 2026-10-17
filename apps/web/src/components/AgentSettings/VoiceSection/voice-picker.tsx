// The voice select of a provider whose voices carry a preview clip: a grid of voices, each
// with a play button for its sample.
import { useEffect, useRef, useState } from "react";
import { Play, Square } from "lucide-react";
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible";
import type { SettingDef } from "@/lib/voice";
import { CollapsibleChevronButton } from "./collapsible-chevron-button";

export function VoicePicker({
  setting,
  onChange,
}: {
  setting: SettingDef;
  onChange: (v: string) => void;
}) {
  const options = setting.options ?? [];
  const [playingId, setPlayingId] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    return () => {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }
    };
  }, []);

  const selectedId = typeof setting.value === "string" ? setting.value : null;
  const selectedOption = options.find((o) => o.value === selectedId);

  const select = (opt: { value: string }) => {
    onChange(opt.value);
  };

  const playPreview = (opt: { value: string; preview?: string }) => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    if (playingId === opt.value) {
      setPlayingId(null);
      return;
    }
    if (!opt.preview) return;
    const audio = new Audio(opt.preview);
    audio.onended = () => setPlayingId(null);
    audio.play().catch(() => {
      if (audioRef.current === audio) audioRef.current = null;
      setPlayingId((current) => (current === opt.value ? null : current));
    });
    audioRef.current = audio;
    setPlayingId(opt.value);
  };

  return (
    <Collapsible>
      <CollapsibleChevronButton>
        {setting.label}:{" "}
        <span className="text-foreground font-medium">
          {selectedOption?.label ?? "Unknown"}
        </span>
      </CollapsibleChevronButton>

      <CollapsibleContent>
        <div className="grid grid-cols-4 sm:grid-cols-5 gap-2 pt-2">
          {options.map((opt) => {
            const selected = opt.value === selectedId;
            const playing = playingId === opt.value;
            return (
              <div key={opt.value} className="group relative">
                <button
                  className={`flex flex-col items-center gap-1.5 rounded-lg p-2 transition-colors cursor-pointer w-full ${
                    selected
                      ? "bg-primary/10 ring-1 ring-ring"
                      : "hover:bg-muted"
                  }`}
                  onClick={() => select(opt)}
                  aria-pressed={selected}
                >
                  <div
                    className={`size-9 rounded-full flex items-center justify-center text-sm font-medium ${
                      selected
                        ? "bg-primary text-primary-foreground"
                        : "bg-muted text-muted-foreground"
                    }`}
                  >
                    {opt.label[0]}
                  </div>
                  <span
                    className={`text-xs leading-tight text-center truncate max-w-full ${
                      selected
                        ? "text-primary font-medium"
                        : "text-muted-foreground"
                    }`}
                  >
                    {opt.label}
                  </span>
                  {typeof opt.description === "string" && opt.description && (
                    <span className="text-xs leading-tight text-center text-muted-foreground truncate max-w-full">
                      {opt.description}
                    </span>
                  )}
                </button>
                {opt.preview && (
                  <button
                    aria-label={playing ? "Stop preview" : "Play preview"}
                    className="absolute top-2 left-1/2 -translate-x-1/2 size-9 rounded-full bg-black/40 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 flex items-center justify-center cursor-pointer transition-opacity"
                    onClick={(e) => {
                      e.stopPropagation();
                      playPreview(opt);
                    }}
                  >
                    {playing ? (
                      <Square className="size-3 text-white" />
                    ) : (
                      <Play className="size-3 text-white ml-0.5" />
                    )}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

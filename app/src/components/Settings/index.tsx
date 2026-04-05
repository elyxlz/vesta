import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { Settings as SettingsIcon, Sun, Moon, Monitor, LogOut, Mic, Volume2, Play, Square, ChevronDown } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Field, FieldContent, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Separator } from "@/components/ui/separator";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useTheme, type Theme } from "@/stores/use-theme";
import { useSettings } from "@/stores/use-settings";
import { useAuth } from "@/providers/AuthProvider";
import { getConnection } from "@/lib/connection";
import { fetchVoices, type VoiceCatalogue, type VoiceInfo } from "@/lib/voice";
import { useVoiceStatus } from "@/hooks/use-voice-status";
import { sendChatEvent } from "@/hooks/use-chat";
import { StatusPill } from "@/components/StatusPill";

const EOT_DEBOUNCE_MS = 400;

export function Settings() {
  const { name: agentName } = useParams<{ name: string }>();
  const [open, setOpen] = useState(false);
  const theme = useTheme((s) => s.theme);
  const setTheme = useTheme((s) => s.setTheme);
  const { reachable, disconnect } = useAuth();
  const voiceAutoSend = useSettings((s) => s.voiceAutoSend);
  const speechEnabled = useSettings((s) => s.speechEnabled);
  const setSetting = useSettings((s) => s.set);
  const [playingVoice, setPlayingVoice] = useState<string | null>(null);
  const previewAudioRef = useRef<HTMLAudioElement | null>(null);

  const { status, refresh: refreshStatus } = useVoiceStatus(open ? (agentName ?? null) : null);
  const [catalogue, setCatalogue] = useState<VoiceCatalogue | null>(null);
  const [catalogueError, setCatalogueError] = useState<string | null>(null);
  const [pendingVoiceId, setPendingVoiceId] = useState<string | null>(null);

  const sttKeyMissing = status?.stt.configured === false;
  const ttsKeyMissing = status?.tts.configured === false;

  // Force speech off if TTS isn't available on this agent.
  useEffect(() => {
    if (ttsKeyMissing && speechEnabled) {
      setSetting("speechEnabled", false);
    }
  }, [ttsKeyMissing, speechEnabled, setSetting]);

  // Fetch voice catalogue when dialog open + TTS configured.
  useEffect(() => {
    if (!open || !agentName || ttsKeyMissing || !status?.tts.configured) {
      setCatalogue(null);
      return;
    }
    const ctrl = new AbortController();
    setCatalogueError(null);
    fetchVoices(agentName, ctrl.signal)
      .then((cat) => { if (!ctrl.signal.aborted) setCatalogue(cat); })
      .catch((err) => {
        if (ctrl.signal.aborted) return;
        setCatalogueError(err instanceof Error ? err.message : "Failed to load voices");
      });
    return () => ctrl.abort();
  }, [open, agentName, ttsKeyMissing, status?.tts.configured]);

  // EOT slider local state (debounced writes via system_message).
  const [localEotThreshold, setLocalEotThreshold] = useState(0.8);
  const [localEotTimeoutMs, setLocalEotTimeoutMs] = useState(10000);
  useEffect(() => {
    if (status?.stt.eot_threshold !== undefined) setLocalEotThreshold(status.stt.eot_threshold);
    if (status?.stt.eot_timeout_ms !== undefined) setLocalEotTimeoutMs(status.stt.eot_timeout_ms);
  }, [status?.stt.eot_threshold, status?.stt.eot_timeout_ms]);

  const eotThresholdTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const eotTimeoutMsTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const scheduleEotThresholdUpdate = (value: number) => {
    if (eotThresholdTimer.current) clearTimeout(eotThresholdTimer.current);
    eotThresholdTimer.current = setTimeout(() => {
      sendChatEvent({
        type: "system_message",
        text: `User set EOT threshold to ${value.toFixed(2)}. Run voice_keys.py set-eot --threshold ${value.toFixed(2)}.`,
      });
      setTimeout(refreshStatus, 2000);
    }, EOT_DEBOUNCE_MS);
  };

  const scheduleEotTimeoutUpdate = (value: number) => {
    if (eotTimeoutMsTimer.current) clearTimeout(eotTimeoutMsTimer.current);
    eotTimeoutMsTimer.current = setTimeout(() => {
      sendChatEvent({
        type: "system_message",
        text: `User set EOT timeout to ${value} ms. Run voice_keys.py set-eot --timeout-ms ${value}.`,
      });
      setTimeout(refreshStatus, 2000);
    }, EOT_DEBOUNCE_MS);
  };

  const playPreview = (voice: VoiceInfo) => {
    if (previewAudioRef.current) {
      previewAudioRef.current.pause();
      previewAudioRef.current = null;
    }
    if (playingVoice === voice.id) {
      setPlayingVoice(null);
      return;
    }
    if (!voice.preview) return;
    const audio = new Audio(voice.preview);
    audio.onended = () => setPlayingVoice(null);
    audio.play();
    previewAudioRef.current = audio;
    setPlayingVoice(voice.id);
  };

  const selectVoice = (voice: VoiceInfo) => {
    setPendingVoiceId(voice.id);
    sendChatEvent({
      type: "system_message",
      text: `User selected voice '${voice.name}' (voice_id: ${voice.id}). Run voice_keys.py set-voice --id ${voice.id}.`,
    });
    setTimeout(() => { refreshStatus(); setPendingVoiceId(null); }, 2500);
  };

  const selectedVoiceId = pendingVoiceId ?? catalogue?.selected_voice_id ?? null;

  const hostname = (() => {
    const conn = getConnection();
    if (!conn) return "";
    try {
      return new URL(conn.url).hostname;
    } catch {
      return conn.url;
    }
  })();

  const sttUsage = status?.stt.usage as { results?: { hours?: number }[] } | undefined;
  const sttBalance = status?.stt.balance as { balances?: { amount?: number; units?: string }[] } | undefined;
  const ttsUsage = status?.tts.usage as { character_count?: number; character_limit?: number } | undefined;

  const sttHours = sttUsage?.results
    ? sttUsage.results.reduce((acc, r) => acc + (r.hours ?? 0), 0)
    : null;
  const sttBalanceStr = sttBalance?.balances?.[0]
    ? formatBalance(sttBalance.balances[0])
    : null;

  return (
    <>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => setOpen(true)}
          >
            <SettingsIcon />
          </Button>
        </TooltipTrigger>
        <TooltipContent>settings</TooltipContent>
      </Tooltip>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Settings</DialogTitle>
            <DialogDescription className="sr-only">
              Application settings
            </DialogDescription>
          </DialogHeader>

          <Field orientation="vertical" className="sm:flex-row sm:items-center">
            <FieldLabel>Theme</FieldLabel>
            <ToggleGroup
              type="single"
              value={theme}
              onValueChange={(value) => {
                if (value) setTheme(value as Theme);
              }}
              variant="outline"
              spacing={2}
            >
              <ToggleGroupItem value="system">
                <Monitor />
                System
              </ToggleGroupItem>
              <ToggleGroupItem value="light">
                <Sun />
                Light
              </ToggleGroupItem>
              <ToggleGroupItem value="dark">
                <Moon />
                Dark
              </ToggleGroupItem>
            </ToggleGroup>
          </Field>

          <Separator />

          <Field orientation="vertical" className="gap-3">
            <FieldLabel>Voice</FieldLabel>

            <Field orientation="horizontal" className="items-center justify-between">
              <FieldContent>
                <FieldLabel className="flex items-center gap-2 text-sm">
                  <Mic className="size-4 text-muted-foreground" />
                  Auto-send on pause
                </FieldLabel>
                <FieldDescription className={sttKeyMissing ? "text-amber-600 dark:text-amber-500" : undefined}>
                  {sttKeyMissing
                    ? "Voice input not configured — ask the agent to set it up"
                    : "Send message automatically when you stop speaking"}
                </FieldDescription>
              </FieldContent>
              <Switch
                checked={voiceAutoSend && !sttKeyMissing}
                disabled={sttKeyMissing}
                onCheckedChange={(v) => setSetting("voiceAutoSend", v)}
              />
            </Field>

            {!sttKeyMissing && status?.stt.configured && (
              <Collapsible>
                <CollapsibleTrigger asChild>
                  <Button variant="ghost" size="sm" className="w-full justify-start gap-2 px-0 text-sm text-muted-foreground hover:text-foreground">
                    <ChevronDown className="size-4 transition-transform [[data-state=closed]_&]:-rotate-90" />
                    Advanced transcription
                  </Button>
                </CollapsibleTrigger>
                <CollapsibleContent>
                  <div className="flex flex-col gap-3 pt-2 px-6">
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-muted-foreground">Usage this month</span>
                      <span className="text-foreground tabular-nums">
                        {sttHours !== null && sttBalanceStr !== null
                          ? `${sttHours.toFixed(2)} h used · ${sttBalanceStr} left`
                          : "—"}
                      </span>
                    </div>

                    <div className="flex flex-col gap-1.5">
                      <div className="flex items-center justify-between">
                        <span className="text-sm text-foreground">End-of-turn sensitivity</span>
                        <span className="text-[10px] text-muted-foreground/70 tabular-nums">{localEotThreshold.toFixed(2)}</span>
                      </div>
                      <Slider
                        min={0.3}
                        max={0.95}
                        step={0.05}
                        value={[localEotThreshold]}
                        onValueChange={([v]) => { setLocalEotThreshold(v); scheduleEotThresholdUpdate(v); }}
                      />
                      <p className="text-xs text-muted-foreground">Lower finalizes turns faster; higher waits longer</p>
                    </div>

                    <div className="flex flex-col gap-1.5">
                      <div className="flex items-center justify-between">
                        <span className="text-sm text-foreground">Max silence timeout</span>
                        <span className="text-[10px] text-muted-foreground/70 tabular-nums">{(localEotTimeoutMs / 1000).toFixed(1)}s</span>
                      </div>
                      <Slider
                        min={2000}
                        max={15000}
                        step={500}
                        value={[localEotTimeoutMs]}
                        onValueChange={([v]) => { setLocalEotTimeoutMs(v); scheduleEotTimeoutUpdate(v); }}
                      />
                      <p className="text-xs text-muted-foreground">Max silence before forcing end of turn</p>
                    </div>
                  </div>
                </CollapsibleContent>
              </Collapsible>
            )}

            <Field orientation="horizontal" className="items-center justify-between">
              <FieldContent>
                <FieldLabel className="flex items-center gap-2 text-sm">
                  <Volume2 className="size-4 text-muted-foreground" />
                  Read responses aloud
                </FieldLabel>
                <FieldDescription className={ttsKeyMissing ? "text-amber-600 dark:text-amber-500" : undefined}>
                  {ttsKeyMissing
                    ? "Voice output not configured — ask the agent to set it up"
                    : "Speak agent replies using text-to-speech"}
                </FieldDescription>
              </FieldContent>
              <Switch
                checked={speechEnabled && !ttsKeyMissing}
                disabled={ttsKeyMissing}
                onCheckedChange={(v) => setSetting("speechEnabled", v)}
              />
            </Field>

            {speechEnabled && !ttsKeyMissing && (
              <>
                <div className="flex items-center justify-between text-xs px-6">
                  <span className="text-muted-foreground">Usage this month</span>
                  <span className="text-foreground tabular-nums">
                    {ttsUsage && typeof ttsUsage.character_count === "number" && typeof ttsUsage.character_limit === "number"
                      ? `${ttsUsage.character_count.toLocaleString()} / ${ttsUsage.character_limit.toLocaleString()} chars`
                      : "—"}
                  </span>
                </div>
                {catalogue && (
                  <VoicePicker
                    voices={catalogue.voices}
                    selectedId={selectedVoiceId}
                    playingId={playingVoice}
                    onSelect={selectVoice}
                    onPreview={playPreview}
                  />
                )}
                {catalogueError && (
                  <p className="text-xs text-destructive px-6">{catalogueError}</p>
                )}
              </>
            )}
          </Field>

          <Separator />

          <div className="flex flex-col sm:flex-row sm:items-center gap-3">
            <div className="flex-1 flex items-center gap-2 text-sm text-muted-foreground">
              <StatusPill showHostname={false} /> {reachable ? "Connected to" : "Cannot reach"} <span className="font-medium text-foreground">{hostname}</span>
            </div>
            <Button
              variant="outline"
              className="w-full sm:w-auto shrink-0"
              onClick={() => {
                setOpen(false);
                disconnect();
              }}
            >
              <LogOut data-icon="inline-start" />
              Disconnect
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

function formatBalance(b: { amount?: number; units?: string }): string {
  const amount = b.amount ?? 0;
  const units = (b.units ?? "").toLowerCase();
  if (units === "usd") return `$${amount.toFixed(2)}`;
  if (units === "hour" || units === "hours") return `${amount.toFixed(2)} h`;
  return `${amount.toFixed(2)} ${b.units ?? ""}`;
}

function VoicePicker({
  voices,
  selectedId,
  playingId,
  onSelect,
  onPreview,
}: {
  voices: VoiceInfo[];
  selectedId: string | null;
  playingId: string | null;
  onSelect: (voice: VoiceInfo) => void;
  onPreview: (voice: VoiceInfo) => void;
}) {
  const selectedVoice = voices.find((v) => v.id === selectedId);

  return (
    <Collapsible>
      <CollapsibleTrigger asChild>
        <Button variant="ghost" size="sm" className="w-full justify-start gap-2 px-0 text-sm text-muted-foreground hover:text-foreground">
          <ChevronDown className="size-4 transition-transform [[data-state=closed]_&]:-rotate-90" />
          Voice: <span className="text-foreground font-medium">{selectedVoice?.name ?? "Unknown"}</span>
        </Button>
      </CollapsibleTrigger>

      <CollapsibleContent>
        <div className="grid grid-cols-4 sm:grid-cols-5 gap-2 pt-2">
          {voices.map((voice) => {
            const selected = voice.id === selectedId;
            const playing = playingId === voice.id;
            return (
              <button
                key={voice.id}
                className={`group relative flex flex-col items-center gap-1.5 rounded-lg p-2 transition-colors cursor-pointer ${
                  selected
                    ? "bg-primary/10 ring-1 ring-primary/30"
                    : "hover:bg-muted"
                }`}
                onClick={() => onSelect(voice)}
              >
                <div className={`relative size-9 rounded-full flex items-center justify-center text-xs font-medium ${
                  selected
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-muted-foreground"
                }`}>
                  {voice.name[0]}
                  {voice.preview && (
                    <span
                      role="button"
                      tabIndex={-1}
                      aria-label={playing ? "Stop preview" : "Play preview"}
                      className="absolute inset-0 size-full rounded-full bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center cursor-pointer"
                      onClick={(e) => { e.stopPropagation(); onPreview(voice); }}
                    >
                      {playing
                        ? <Square className="size-3 text-white" />
                        : <Play className="size-3 text-white ml-0.5" />
                      }
                    </span>
                  )}
                </div>
                <span className={`text-[10px] leading-tight text-center truncate max-w-full ${
                  selected ? "text-primary font-medium" : "text-muted-foreground"
                }`}>
                  {voice.name}
                </span>
              </button>
            );
          })}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

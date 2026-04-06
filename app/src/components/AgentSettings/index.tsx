import { useCallback, useEffect, useRef, useState } from "react";
import { Mic, Volume2, Play, Square, ChevronDown } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Field, FieldContent, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Separator } from "@/components/ui/separator";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import {
  fetchSttUsage, fetchTtsUsage,
  setSttEnabled, setSttAutoSend, setSttEot,
  setTtsEnabled, setTtsVoice,
  type SttUsage, type TtsUsage, type VoiceInfo,
} from "@/lib/voice";
import { useOptimisticToggle } from "@/hooks/use-optimistic-toggle";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";

const EOT_DEBOUNCE_MS = 400;

export function AgentSettings({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { name: agentName, sttStatus, ttsStatus, refreshVoiceStatus } = useSelectedAgent();

  // --- STT state ---
  const sttConfigured = sttStatus?.configured ?? false;
  const sttProvider = sttStatus?.provider ?? null;

  const [sttEnabled, toggleSttEnabled] = useOptimisticToggle(
    sttStatus?.enabled, true,
    (v) => { if (agentName) setSttEnabled(agentName, v).catch(console.warn); },
  );
  const [autoSend, toggleAutoSend] = useOptimisticToggle(
    sttStatus?.auto_send, true,
    (v) => { if (agentName) setSttAutoSend(agentName, v).catch(console.warn); },
  );

  const [localEotThreshold, setLocalEotThreshold] = useState(0.8);
  const [localEotTimeoutMs, setLocalEotTimeoutMs] = useState(10000);
  useEffect(() => {
    if (sttStatus?.eot_threshold !== undefined) setLocalEotThreshold(sttStatus.eot_threshold);
    if (sttStatus?.eot_timeout_ms !== undefined) setLocalEotTimeoutMs(sttStatus.eot_timeout_ms);
  }, [sttStatus?.eot_threshold, sttStatus?.eot_timeout_ms]);

  const eotThresholdTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const eotTimeoutMsTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const scheduleEotThresholdUpdate = (value: number) => {
    if (eotThresholdTimer.current) clearTimeout(eotThresholdTimer.current);
    eotThresholdTimer.current = setTimeout(() => {
      if (agentName) setSttEot(agentName, { threshold: value }).catch(console.warn);
    }, EOT_DEBOUNCE_MS);
  };
  const scheduleEotTimeoutUpdate = (value: number) => {
    if (eotTimeoutMsTimer.current) clearTimeout(eotTimeoutMsTimer.current);
    eotTimeoutMsTimer.current = setTimeout(() => {
      if (agentName) setSttEot(agentName, { timeout_ms: value }).catch(console.warn);
    }, EOT_DEBOUNCE_MS);
  };

  const [sttUsageData, setSttUsageData] = useState<SttUsage | null>(null);
  const loadSttUsage = useCallback(() => {
    if (agentName) fetchSttUsage(agentName).then(setSttUsageData).catch(console.warn);
  }, [agentName]);
  const sttUsage = sttUsageData?.usage;
  const sttBalance = sttUsageData?.balance;
  const sttHours = sttUsage?.results ? sttUsage.results.reduce((acc, r) => acc + (r.hours ?? 0), 0) : null;
  const sttBalanceStr = sttBalance?.balances?.[0] ? formatBalance(sttBalance.balances[0]) : null;

  // --- TTS state ---
  const ttsConfigured = ttsStatus?.configured ?? false;
  const ttsProvider = ttsStatus?.provider ?? null;

  const [ttsEnabled, toggleTtsEnabled] = useOptimisticToggle(
    ttsStatus?.enabled, false,
    (v) => { if (agentName) setTtsEnabled(agentName, v).catch(console.warn); },
  );

  const voiceList = ttsStatus?.voices ?? [];
  const [pendingVoiceId, setPendingVoiceId] = useState<string | null>(null);
  const [playingVoice, setPlayingVoice] = useState<string | null>(null);
  const previewAudioRef = useRef<HTMLAudioElement | null>(null);
  const selectedVoiceId = pendingVoiceId ?? ttsStatus?.selected_voice_id ?? null;

  const selectVoice = (voice: VoiceInfo) => {
    if (!agentName) return;
    setPendingVoiceId(voice.id);
    setTtsVoice(agentName, voice.id)
      .then(() => refreshVoiceStatus())
      .catch(console.warn)
      .finally(() => setPendingVoiceId(null));
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

  const [ttsUsageData, setTtsUsageData] = useState<TtsUsage | null>(null);
  const loadTtsUsage = useCallback(() => {
    if (agentName) fetchTtsUsage(agentName).then(setTtsUsageData).catch(console.warn);
  }, [agentName]);
  const ttsChars = ttsUsageData?.usage;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Agent Settings</DialogTitle>
          <DialogDescription className="sr-only">Voice configuration for {agentName}</DialogDescription>
        </DialogHeader>

        {/* Speech to Text */}
        <Field orientation="vertical" className="gap-3">
          <Field orientation="horizontal" className="items-center justify-between">
            <FieldContent>
              <FieldLabel className="flex items-center gap-2">
                <Mic className="size-4 text-muted-foreground" />
                Speech to Text
                {sttProvider && <span className="text-xs text-muted-foreground font-normal">{sttProvider}</span>}
              </FieldLabel>
            </FieldContent>
            <Switch
              checked={sttEnabled && sttConfigured}
              disabled={!sttConfigured}
              onCheckedChange={toggleSttEnabled}
            />
          </Field>

          {!sttConfigured ? (
            <p className="text-xs text-amber-600 dark:text-amber-500">Not configured — ask the agent to set it up</p>
          ) : sttEnabled ? (
            <>
              <Field orientation="horizontal" className="items-center justify-between">
                <FieldContent>
                  <FieldLabel className="text-sm">Auto-send on pause</FieldLabel>
                  <FieldDescription>Send message automatically when you stop speaking</FieldDescription>
                </FieldContent>
                <Switch checked={autoSend} onCheckedChange={toggleAutoSend} />
              </Field>

              <Collapsible>
                <CollapsibleTrigger asChild>
                  <Button variant="ghost" size="sm" className="w-full justify-start gap-2 px-0 text-sm text-muted-foreground hover:text-foreground">
                    <ChevronDown className="size-4 transition-transform [[data-state=closed]_&]:-rotate-90" />
                    Configuration
                  </Button>
                </CollapsibleTrigger>
                <CollapsibleContent>
                  <div className="flex flex-col gap-3 pt-2 px-6">
                    <div className="flex flex-col gap-1.5">
                      <div className="flex items-center justify-between">
                        <span className="text-sm text-foreground">End-of-turn sensitivity</span>
                        <span className="text-[10px] text-muted-foreground/70 tabular-nums">{localEotThreshold.toFixed(2)}</span>
                      </div>
                      <Slider
                        min={0.3} max={0.95} step={0.05}
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
                        min={2000} max={15000} step={500}
                        value={[localEotTimeoutMs]}
                        onValueChange={([v]) => { setLocalEotTimeoutMs(v); scheduleEotTimeoutUpdate(v); }}
                      />
                      <p className="text-xs text-muted-foreground">Max silence before forcing end of turn</p>
                    </div>
                  </div>
                </CollapsibleContent>
              </Collapsible>

              <Collapsible onOpenChange={(isOpen) => { if (isOpen) loadSttUsage(); }}>
                <CollapsibleTrigger asChild>
                  <Button variant="ghost" size="sm" className="w-full justify-start gap-2 px-0 text-sm text-muted-foreground hover:text-foreground">
                    <ChevronDown className="size-4 transition-transform [[data-state=closed]_&]:-rotate-90" />
                    Usage
                  </Button>
                </CollapsibleTrigger>
                <CollapsibleContent>
                  <div className="flex items-center justify-between text-xs px-6 pt-2">
                    <span className="text-muted-foreground">Hours this month</span>
                    <span className="text-foreground tabular-nums">
                      {sttHours !== null && sttBalanceStr !== null
                        ? `${sttHours.toFixed(2)} h used · ${sttBalanceStr} left`
                        : "—"}
                    </span>
                  </div>
                </CollapsibleContent>
              </Collapsible>
            </>
          ) : null}
        </Field>

        <Separator />

        {/* Text to Speech */}
        <Field orientation="vertical" className="gap-3">
          <Field orientation="horizontal" className="items-center justify-between">
            <FieldContent>
              <FieldLabel className="flex items-center gap-2">
                <Volume2 className="size-4 text-muted-foreground" />
                Text to Speech
                {ttsProvider && <span className="text-xs text-muted-foreground font-normal">{ttsProvider}</span>}
              </FieldLabel>
            </FieldContent>
            <Switch
              checked={ttsEnabled && ttsConfigured}
              disabled={!ttsConfigured}
              onCheckedChange={toggleTtsEnabled}
            />
          </Field>

          {!ttsConfigured ? (
            <p className="text-xs text-amber-600 dark:text-amber-500">Not configured — ask the agent to set it up</p>
          ) : ttsEnabled ? (
            <>
              {voiceList.length > 0 && (
                <VoicePicker
                  voices={voiceList}
                  selectedId={selectedVoiceId}
                  playingId={playingVoice}
                  onSelect={selectVoice}
                  onPreview={playPreview}
                />
              )}

              <Collapsible onOpenChange={(isOpen) => { if (isOpen) loadTtsUsage(); }}>
                <CollapsibleTrigger asChild>
                  <Button variant="ghost" size="sm" className="w-full justify-start gap-2 px-0 text-sm text-muted-foreground hover:text-foreground">
                    <ChevronDown className="size-4 transition-transform [[data-state=closed]_&]:-rotate-90" />
                    Usage
                  </Button>
                </CollapsibleTrigger>
                <CollapsibleContent>
                  <div className="flex items-center justify-between text-xs px-6 pt-2">
                    <span className="text-muted-foreground">Characters this month</span>
                    <span className="text-foreground tabular-nums">
                      {ttsChars && typeof ttsChars.character_count === "number" && typeof ttsChars.character_limit === "number"
                        ? `${ttsChars.character_count.toLocaleString()} / ${ttsChars.character_limit.toLocaleString()}`
                        : "—"}
                    </span>
                  </div>
                </CollapsibleContent>
              </Collapsible>
            </>
          ) : null}
        </Field>
      </DialogContent>
    </Dialog>
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
                  selected ? "bg-primary/10 ring-1 ring-primary/30" : "hover:bg-muted"
                }`}
                onClick={() => onSelect(voice)}
              >
                <div className={`relative size-9 rounded-full flex items-center justify-center text-xs font-medium ${
                  selected ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"
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
                      {playing ? <Square className="size-3 text-white" /> : <Play className="size-3 text-white ml-0.5" />}
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

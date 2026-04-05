import { useRef, useState } from "react";
import { Settings as SettingsIcon, Sun, Moon, Monitor, LogOut, Mic, Volume2, Play, Square, ChevronDown, Plus, X } from "lucide-react";
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
import { Input } from "@/components/ui/input";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useTheme, type Theme } from "@/stores/use-theme";
import { useSettings } from "@/stores/use-settings";
import { useAuth } from "@/providers/AuthProvider";
import { getConnection } from "@/lib/connection";
import { VOICES } from "@/lib/elevenlabs";
import { StatusPill } from "@/components/StatusPill";

export function Settings() {
  const [open, setOpen] = useState(false);
  const theme = useTheme((s) => s.theme);
  const setTheme = useTheme((s) => s.setTheme);
  const { reachable, disconnect } = useAuth();
  const voiceAutoSend = useSettings((s) => s.voiceAutoSend);
  const speechEnabled = useSettings((s) => s.speechEnabled);
  const ttsVoiceId = useSettings((s) => s.ttsVoiceId);
  const sttEotThreshold = useSettings((s) => s.sttEotThreshold);
  const sttEotTimeoutMs = useSettings((s) => s.sttEotTimeoutMs);
  const customVoices = useSettings((s) => s.customVoices);
  const addCustomVoice = useSettings((s) => s.addCustomVoice);
  const removeCustomVoice = useSettings((s) => s.removeCustomVoice);
  const setSetting = useSettings((s) => s.set);
  const [playingVoice, setPlayingVoice] = useState<string | null>(null);
  const previewAudioRef = useRef<HTMLAudioElement | null>(null);

  const allVoices = [
    ...VOICES,
    ...customVoices.map((v) => ({ id: v.id, name: v.name, preview: "", custom: true as const })),
  ];

  const playPreview = (voice: { id: string; preview: string }) => {
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

  const hostname = (() => {
    const conn = getConnection();
    if (!conn) return "";
    try {
      return new URL(conn.url).hostname;
    } catch {
      return conn.url;
    }
  })();

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
                <FieldDescription>Send message automatically when you stop speaking</FieldDescription>
              </FieldContent>
              <Switch
                checked={voiceAutoSend}
                onCheckedChange={(v) => setSetting("voiceAutoSend", v)}
              />
            </Field>

            <Collapsible>
              <CollapsibleTrigger asChild>
                <Button variant="ghost" size="sm" className="w-full justify-start gap-2 px-0 text-sm text-muted-foreground hover:text-foreground">
                  <ChevronDown className="size-4 transition-transform [[data-state=closed]_&]:-rotate-90" />
                  Advanced transcription
                </Button>
              </CollapsibleTrigger>
              <CollapsibleContent>
                <div className="flex flex-col gap-3 pt-2 px-6">
                  <div className="flex flex-col gap-1.5">
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-foreground">End-of-turn sensitivity</span>
                      <span className="text-[10px] text-muted-foreground/70 tabular-nums">{sttEotThreshold.toFixed(2)}</span>
                    </div>
                    <Slider
                      min={0.3}
                      max={0.95}
                      step={0.05}
                      value={[sttEotThreshold]}
                      onValueChange={([v]) => setSetting("sttEotThreshold", v)}
                    />
                    <p className="text-xs text-muted-foreground">Lower finalizes turns faster; higher waits longer</p>
                  </div>

                  <div className="flex flex-col gap-1.5">
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-foreground">Max silence timeout</span>
                      <span className="text-[10px] text-muted-foreground/70 tabular-nums">{(sttEotTimeoutMs / 1000).toFixed(1)}s</span>
                    </div>
                    <Slider
                      min={2000}
                      max={15000}
                      step={500}
                      value={[sttEotTimeoutMs]}
                      onValueChange={([v]) => setSetting("sttEotTimeoutMs", v)}
                    />
                    <p className="text-xs text-muted-foreground">Max silence before forcing end of turn</p>
                  </div>
                </div>
              </CollapsibleContent>
            </Collapsible>

            <Field orientation="horizontal" className="items-center justify-between">
              <FieldContent>
                <FieldLabel className="flex items-center gap-2 text-sm">
                  <Volume2 className="size-4 text-muted-foreground" />
                  Read responses aloud
                </FieldLabel>
                <FieldDescription>Speak agent replies using text-to-speech</FieldDescription>
              </FieldContent>
              <Switch
                checked={speechEnabled}
                onCheckedChange={(v) => setSetting("speechEnabled", v)}
              />
            </Field>

            {speechEnabled && (
              <VoicePicker
                voices={allVoices}
                selectedId={ttsVoiceId}
                playingId={playingVoice}
                onSelect={(id) => setSetting("ttsVoiceId", id)}
                onPreview={playPreview}
                onAddCustom={addCustomVoice}
                onRemoveCustom={removeCustomVoice}
              />
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

type PickerVoice = { id: string; name: string; preview: string; custom?: boolean };

function VoicePicker({
  voices,
  selectedId,
  playingId,
  onSelect,
  onPreview,
  onAddCustom,
  onRemoveCustom,
}: {
  voices: PickerVoice[];
  selectedId: string;
  playingId: string | null;
  onSelect: (id: string) => void;
  onPreview: (voice: PickerVoice) => void;
  onAddCustom: (voice: { id: string; name: string }) => void;
  onRemoveCustom: (id: string) => void;
}) {
  const selectedVoice = voices.find((v) => v.id === selectedId);
  const [newId, setNewId] = useState("");
  const [newName, setNewName] = useState("");

  const submitCustom = () => {
    const id = newId.trim();
    const name = newName.trim();
    if (!id || !name) return;
    onAddCustom({ id, name });
    onSelect(id);
    setNewId("");
    setNewName("");
  };

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
                onClick={() => onSelect(voice.id)}
              >
                {voice.custom && (
                  <span
                    role="button"
                    tabIndex={-1}
                    aria-label="Remove custom voice"
                    className="absolute top-1 right-1 size-4 rounded-full bg-muted-foreground/20 hover:bg-destructive hover:text-destructive-foreground opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center cursor-pointer"
                    onClick={(e) => { e.stopPropagation(); onRemoveCustom(voice.id); }}
                  >
                    <X className="size-2.5" />
                  </span>
                )}
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

        <div className="flex flex-col gap-2 pt-3">
          <p className="text-xs text-muted-foreground">Add a custom ElevenLabs voice by ID</p>
          <div className="flex gap-2">
            <Input
              placeholder="Name"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              className="flex-1"
              onKeyDown={(e) => { if (e.key === "Enter") submitCustom(); }}
            />
            <Input
              placeholder="Voice ID"
              value={newId}
              onChange={(e) => setNewId(e.target.value)}
              className="flex-[2]"
              onKeyDown={(e) => { if (e.key === "Enter") submitCustom(); }}
            />
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={submitCustom}
              disabled={!newId.trim() || !newName.trim()}
            >
              <Plus className="size-4" />
              Add
            </Button>
          </div>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

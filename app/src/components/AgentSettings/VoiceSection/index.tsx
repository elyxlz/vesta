import { useEffect, useRef, useState } from "react";
import { Mic, Volume2, ChevronDown, Play, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldLabel,
} from "@/components/ui/field";
import { Card, CardContent } from "@/components/ui/card";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import {
  fetchSttUsage,
  fetchTtsUsage,
  setSttEnabled,
  setTtsEnabled,
  setVoiceSetting,
  type SettingDef,
  type SttStatus,
  type TtsStatus,
  type SttUsage,
  type TtsUsage,
} from "@/lib/voice";
import { useOptimisticToggle } from "@/hooks/use-optimistic-toggle";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useVoice } from "@/stores/use-voice";

const DEBOUNCE_MS = 400;

function formatBalance(b: { amount?: number; units?: string }): string {
  const amount = b.amount ?? 0;
  const units = (b.units ?? "").toLowerCase();
  if (units === "usd") return `$${amount.toFixed(2)}`;
  if (units === "hour" || units === "hours") return `${amount.toFixed(2)} h`;
  return `${amount.toFixed(2)} ${b.units ?? ""}`;
}

// --- Exported cards ---

export function SttCard() {
  const { name: agentName } = useSelectedAgent();
  const { sttStatus, patchStt, refreshVoiceStatus } = useVoice();
  const configured = sttStatus?.configured ?? false;

  const [enabled, toggleEnabled] = useOptimisticToggle(
    sttStatus?.enabled,
    true,
    (v) => {
      patchStt({ enabled: v });
      if (agentName)
        setSttEnabled(agentName, v).catch(() => refreshVoiceStatus());
    },
  );

  const [usageData, setUsageData] = useState<SttUsage | null>(null);
  const loadUsage = () => {
    if (agentName)
      fetchSttUsage(agentName).then(setUsageData).catch(console.warn);
  };
  const hours = usageData?.usage?.results
    ? usageData.usage.results.reduce((acc, r) => acc + (r.hours ?? 0), 0)
    : null;
  const balanceStr = usageData?.balance?.balances?.[0]
    ? formatBalance(usageData.balance.balances[0])
    : null;

  return (
    <Card size="sm">
      <CardContent>
        <DomainSection
          icon={<Mic className="size-4 text-muted-foreground" />}
          title="speech to text"
          configured={configured}
          provider={sttStatus?.provider ?? null}
          enabled={enabled}
          onToggleEnabled={toggleEnabled}
          settings={sttStatus?.settings}
          domain="stt"
          agentName={agentName}
          onSettingChange={(settings) =>
            patchStt({ settings } as Partial<SttStatus>)
          }
          usageContent={
            <UsageCollapsible onOpen={loadUsage}>
              <div className="flex items-center justify-between text-xs px-6 pt-2">
                <span className="text-muted-foreground">hours this month</span>
                <span className="text-foreground tabular-nums">
                  {hours !== null && balanceStr !== null
                    ? `${hours.toFixed(2)} h used · ${balanceStr} left`
                    : "—"}
                </span>
              </div>
            </UsageCollapsible>
          }
        />
      </CardContent>
    </Card>
  );
}

export function TtsCard() {
  const { name: agentName } = useSelectedAgent();
  const { ttsStatus, patchTts, refreshVoiceStatus } = useVoice();
  const configured = ttsStatus?.configured ?? false;

  const [enabled, toggleEnabled] = useOptimisticToggle(
    ttsStatus?.enabled,
    false,
    (v) => {
      patchTts({ enabled: v });
      if (agentName)
        setTtsEnabled(agentName, v).catch(() => refreshVoiceStatus());
    },
  );

  const [usageData, setUsageData] = useState<TtsUsage | null>(null);
  const loadUsage = () => {
    if (agentName)
      fetchTtsUsage(agentName).then(setUsageData).catch(console.warn);
  };
  const chars = usageData?.usage;

  return (
    <Card size="sm">
      <CardContent>
        <DomainSection
          icon={<Volume2 className="size-4 text-muted-foreground" />}
          title="text to speech"
          configured={configured}
          provider={ttsStatus?.provider ?? null}
          enabled={enabled}
          onToggleEnabled={toggleEnabled}
          settings={ttsStatus?.settings}
          domain="tts"
          agentName={agentName}
          onSettingChange={(settings) =>
            patchTts({ settings } as Partial<TtsStatus>)
          }
          usageContent={
            <UsageCollapsible onOpen={loadUsage}>
              <div className="flex items-center justify-between text-xs px-6 pt-2">
                <span className="text-muted-foreground">
                  characters this month
                </span>
                <span className="text-foreground tabular-nums">
                  {chars &&
                  typeof chars.character_count === "number" &&
                  typeof chars.character_limit === "number"
                    ? `${chars.character_count.toLocaleString()} / ${chars.character_limit.toLocaleString()}`
                    : "—"}
                </span>
              </div>
            </UsageCollapsible>
          }
        />
      </CardContent>
    </Card>
  );
}

// --- Shared usage collapsible ---

function UsageCollapsible({
  onOpen,
  children,
}: {
  onOpen: () => void;
  children: React.ReactNode;
}) {
  return (
    <Collapsible onOpenChange={(isOpen) => { if (isOpen) onOpen(); }}>
      <CollapsibleTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="w-full justify-start gap-2 px-0 text-sm text-muted-foreground hover:text-foreground"
        >
          <ChevronDown className="size-4 transition-transform [[data-state=closed]_&]:-rotate-90" />
          usage
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent>{children}</CollapsibleContent>
    </Collapsible>
  );
}

// --- Domain section ---

function DomainSection({
  icon,
  title,
  configured,
  provider,
  enabled,
  onToggleEnabled,
  settings,
  domain,
  agentName,
  onSettingChange,
  usageContent,
}: {
  icon: React.ReactNode;
  title: string;
  configured: boolean;
  provider: string | null;
  enabled: boolean;
  onToggleEnabled: (v: boolean) => void;
  settings?: SettingDef[];
  domain: "stt" | "tts";
  agentName: string | null;
  onSettingChange: (settings: SettingDef[]) => void;
  usageContent: React.ReactNode;
}) {
  return (
    <Field orientation="vertical" className="gap-3">
      <Field orientation="horizontal" className="items-center justify-between">
        <FieldContent>
          <FieldLabel className="flex items-center gap-2">
            {icon}
            {title}
            {provider && (
              <span className="text-xs text-muted-foreground font-normal">
                {provider}
              </span>
            )}
          </FieldLabel>
        </FieldContent>
        <Switch
          checked={enabled && configured}
          disabled={!configured}
          onCheckedChange={onToggleEnabled}
        />
      </Field>

      {!configured ? (
        <p className="text-xs text-warning">
          not configured — ask the agent to set it up
        </p>
      ) : enabled ? (
        <>
          {settings && settings.length > 0 && (
            <DynamicSettings
              settings={settings}
              domain={domain}
              agentName={agentName}
              onSettingChange={onSettingChange}
            />
          )}
          {usageContent}
        </>
      ) : null}
    </Field>
  );
}

// --- Dynamic settings renderer ---

function DynamicSettings({
  settings,
  domain,
  agentName,
  onSettingChange,
}: {
  settings: SettingDef[];
  domain: "stt" | "tts";
  agentName: string | null;
  onSettingChange: (settings: SettingDef[]) => void;
}) {
  const updateSetting = (key: string, value: unknown) => {
    if (agentName) {
      setVoiceSetting(agentName, domain, key, value).then((status) => {
        if (status.settings) onSettingChange(status.settings);
      });
    }
  };

  const boolSettings = settings.filter((s) => s.type === "bool");
  const numberSettings = settings.filter((s) => s.type === "number");
  const selectSettings = settings.filter((s) => s.type === "select");

  return (
    <>
      {boolSettings.map((s) => (
        <BoolSetting
          key={s.key}
          setting={s}
          onChange={(v) => updateSetting(s.key, v)}
        />
      ))}

      {selectSettings.map((s) => (
        <SelectSetting
          key={s.key}
          setting={s}
          onChange={(v) => updateSetting(s.key, v)}
        />
      ))}

      {numberSettings.length > 0 && (
        <Collapsible>
          <CollapsibleTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              className="w-full justify-start gap-2 px-0 text-sm text-muted-foreground hover:text-foreground"
            >
              <ChevronDown className="size-4 transition-transform [[data-state=closed]_&]:-rotate-90" />
              configuration
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="flex flex-col gap-3 pt-2 px-6">
              {numberSettings.map((s) => (
                <NumberSetting
                  key={s.key}
                  setting={s}
                  onChange={(v) => updateSetting(s.key, v)}
                />
              ))}
            </div>
          </CollapsibleContent>
        </Collapsible>
      )}
    </>
  );
}

// --- Individual setting renderers ---

function BoolSetting({
  setting,
  onChange,
}: {
  setting: SettingDef;
  onChange: (v: boolean) => void;
}) {
  const [value, toggle] = useOptimisticToggle(
    setting.value as boolean | undefined,
    (setting.default as boolean) ?? false,
    onChange,
  );
  return (
    <Field orientation="horizontal" className="items-center justify-between">
      <FieldContent>
        <FieldLabel className="text-sm">{setting.label}</FieldLabel>
        {setting.description && (
          <FieldDescription>{setting.description}</FieldDescription>
        )}
      </FieldContent>
      <Switch checked={value} onCheckedChange={toggle} />
    </Field>
  );
}

function NumberSetting({
  setting,
  onChange,
}: {
  setting: SettingDef;
  onChange: (v: number) => void;
}) {
  const [localValue, setLocalValue] = useState(
    (setting.value as number) ?? (setting.default as number) ?? 0,
  );
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (setting.value !== undefined) setLocalValue(setting.value as number);
  }, [setting.value]);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  const handleChange = (v: number) => {
    setLocalValue(v);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => onChange(v), DEBOUNCE_MS);
  };

  const formatValue = (v: number) => {
    if (setting.unit === "ms") return `${(v / 1000).toFixed(1)}s`;
    return v.toFixed(2);
  };

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between">
        <span className="text-sm text-foreground">{setting.label}</span>
        <span className="text-[10px] text-muted-foreground/70 tabular-nums">
          {formatValue(localValue)}
        </span>
      </div>
      <Slider
        min={setting.min ?? 0}
        max={setting.max ?? 1}
        step={setting.step ?? 0.01}
        value={[localValue]}
        onValueChange={([v]) => handleChange(v)}
      />
      {setting.description && (
        <p className="text-xs text-muted-foreground">{setting.description}</p>
      )}
    </div>
  );
}

function SelectSetting({
  setting,
  onChange,
}: {
  setting: SettingDef;
  onChange: (v: string) => void;
}) {
  const options = setting.options ?? [];
  const hasPreview = options.some((o) => o.preview);

  if (hasPreview) {
    return <VoicePicker setting={setting} onChange={onChange} />;
  }

  return (
    <Collapsible>
      <CollapsibleTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="w-full justify-start gap-2 px-0 text-sm text-muted-foreground hover:text-foreground"
        >
          <ChevronDown className="size-4 transition-transform [[data-state=closed]_&]:-rotate-90" />
          {setting.label}:{" "}
          <span className="text-foreground font-medium">
            {options.find((o) => o.value === setting.value)?.label ?? "Unknown"}
          </span>
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="flex flex-col gap-1 pt-2 px-6">
          {options.map((opt) => (
            <button
              key={opt.value}
              className={`text-left text-sm px-2 py-1 rounded ${opt.value === setting.value ? "bg-primary/10 text-primary" : "hover:bg-muted text-foreground"}`}
              onClick={() => onChange(opt.value)}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

// --- Voice picker (rich select with previews) ---

function VoicePicker({
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

  const selectedId = (setting.value as string) ?? null;
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
    audio.play();
    audioRef.current = audio;
    setPlayingId(opt.value);
  };

  return (
    <Collapsible>
      <CollapsibleTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="w-full justify-start gap-2 px-0 text-sm text-muted-foreground hover:text-foreground"
        >
          <ChevronDown className="size-4 transition-transform [[data-state=closed]_&]:-rotate-90" />
          {setting.label}:{" "}
          <span className="text-foreground font-medium">
            {selectedOption?.label ?? "Unknown"}
          </span>
        </Button>
      </CollapsibleTrigger>

      <CollapsibleContent>
        <div className="grid grid-cols-4 sm:grid-cols-5 gap-2 pt-2">
          {options.map((opt) => {
            const selected = opt.value === selectedId;
            const playing = playingId === opt.value;
            return (
              <button
                key={opt.value}
                className={`group relative flex flex-col items-center gap-1.5 rounded-lg p-2 transition-colors cursor-pointer ${
                  selected
                    ? "bg-primary/10 ring-1 ring-primary/30"
                    : "hover:bg-muted"
                }`}
                onClick={() => select(opt)}
              >
                <div
                  className={`relative size-9 rounded-full flex items-center justify-center text-xs font-medium ${
                    selected
                      ? "bg-primary text-primary-foreground"
                      : "bg-muted text-muted-foreground"
                  }`}
                >
                  {opt.label[0]}
                  {opt.preview && (
                    <span
                      role="button"
                      tabIndex={-1}
                      aria-label={playing ? "Stop preview" : "Play preview"}
                      className="absolute inset-0 size-full rounded-full bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center cursor-pointer"
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
                    </span>
                  )}
                </div>
                <span
                  className={`text-[10px] leading-tight text-center truncate max-w-full ${
                    selected
                      ? "text-primary font-medium"
                      : "text-muted-foreground"
                  }`}
                >
                  {opt.label}
                </span>
                {typeof opt.description === "string" && opt.description && (
                  <span className="text-[9px] leading-tight text-center text-muted-foreground/60 truncate max-w-full">
                    {opt.description}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

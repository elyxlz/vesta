import { useCallback, useEffect, useRef, useState } from "react";
import { Mic, Volume2, Play, Square, ChevronDown, Activity, RefreshCw, ArrowLeft } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Field, FieldContent, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import {
  fetchSttUsage, fetchTtsUsage,
  setSttEnabled, setTtsEnabled, setVoiceSetting,
  type SettingDef, type SttStatus, type TtsStatus,
  type SttUsage, type TtsUsage,
} from "@/lib/voice";
import type { RateLimit, Utilization } from "@/api/agents";
import { useOptimisticToggle } from "@/hooks/use-optimistic-toggle";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useVoice } from "@/providers/VoiceProvider";
import { useSettings } from "@/stores/use-settings";

const DEBOUNCE_MS = 400;

export function AgentSettings() {
  const navigate = useNavigate();
  const { name: agentName } = useSelectedAgent();
  const { sttStatus, ttsStatus, patchStt, patchTts, refreshVoiceStatus } = useVoice();

  // --- STT state ---
  const sttConfigured = sttStatus?.configured ?? false;

  const [sttEnabled, toggleSttEnabled] = useOptimisticToggle(
    sttStatus?.enabled, true,
    (v) => { patchStt({ enabled: v }); if (agentName) setSttEnabled(agentName, v).catch(() => refreshVoiceStatus()); },
  );

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

  const [ttsEnabled, toggleTtsEnabled] = useOptimisticToggle(
    ttsStatus?.enabled, false,
    (v) => { patchTts({ enabled: v }); if (agentName) setTtsEnabled(agentName, v).catch(() => refreshVoiceStatus()); },
  );

  const [ttsUsageData, setTtsUsageData] = useState<TtsUsage | null>(null);
  const loadTtsUsage = useCallback(() => {
    if (agentName) fetchTtsUsage(agentName).then(setTtsUsageData).catch(console.warn);
  }, [agentName]);
  const ttsChars = ttsUsageData?.usage;

  // --- Plan usage ---
  const utilizationMap = useSettings((s) => s.utilization);
  const usageLoading = useSettings((s) => s.usageLoading);
  const usageError = useSettings((s) => s.usageError);
  const refreshUsageAction = useSettings((s) => s.refreshUsage);
  const utilization = agentName ? utilizationMap[agentName] ?? null : null;
  const refreshUsage = useCallback(() => {
    if (agentName) refreshUsageAction(agentName);
  }, [agentName, refreshUsageAction]);
  useEffect(() => {
    if (agentName && !utilization && !usageError) refreshUsage();
  }, [agentName, utilization, usageError, refreshUsage]);

  return (
    <div className="flex flex-col flex-1 min-h-0 overflow-y-auto pt-2">
      <div className="py-10 flex items-center justify-center min-h-11">
        <h1 className="text-lg font-semibold">agent settings</h1>
      </div>

      <div className="flex flex-col gap-6 max-w-lg mx-auto w-full">
        {/* Plan Usage */}
        <PlanUsageSection
          utilization={utilization}
          loading={usageLoading}
          error={usageError}
          onRefresh={refreshUsage}
        />

        <Separator />

        {/* Speech to Text */}
        <DomainSection
          icon={<Mic className="size-4 text-muted-foreground" />}
          title="speech to text"
          configured={sttConfigured}
          provider={sttStatus?.provider ?? null}
          enabled={sttEnabled}
          onToggleEnabled={toggleSttEnabled}
          settings={sttStatus?.settings}
          domain="stt"
          agentName={agentName}
          onSettingChange={(settings) => patchStt({ settings } as Partial<SttStatus>)}
          onRefresh={refreshVoiceStatus}
          usageContent={
            <Collapsible onOpenChange={(isOpen) => { if (isOpen) loadSttUsage(); }}>
              <CollapsibleTrigger asChild>
                <Button variant="ghost" size="sm" className="w-full justify-start gap-2 px-0 text-sm text-muted-foreground hover:text-foreground">
                  <ChevronDown className="size-4 transition-transform [[data-state=closed]_&]:-rotate-90" />
                  usage
                </Button>
              </CollapsibleTrigger>
              <CollapsibleContent>
                <div className="flex items-center justify-between text-xs px-6 pt-2">
                  <span className="text-muted-foreground">hours this month</span>
                  <span className="text-foreground tabular-nums">
                    {sttHours !== null && sttBalanceStr !== null
                      ? `${sttHours.toFixed(2)} h used · ${sttBalanceStr} left`
                      : "—"}
                  </span>
                </div>
              </CollapsibleContent>
            </Collapsible>
          }
        />

        <Separator />

        {/* Text to Speech */}
        <DomainSection
          icon={<Volume2 className="size-4 text-muted-foreground" />}
          title="text to speech"
          configured={ttsConfigured}
          provider={ttsStatus?.provider ?? null}
          enabled={ttsEnabled}
          onToggleEnabled={toggleTtsEnabled}
          settings={ttsStatus?.settings}
          domain="tts"
          agentName={agentName}
          onSettingChange={(settings) => patchTts({ settings } as Partial<TtsStatus>)}
          onRefresh={refreshVoiceStatus}
          usageContent={
            <Collapsible onOpenChange={(isOpen) => { if (isOpen) loadTtsUsage(); }}>
              <CollapsibleTrigger asChild>
                <Button variant="ghost" size="sm" className="w-full justify-start gap-2 px-0 text-sm text-muted-foreground hover:text-foreground">
                  <ChevronDown className="size-4 transition-transform [[data-state=closed]_&]:-rotate-90" />
                  usage
                </Button>
              </CollapsibleTrigger>
              <CollapsibleContent>
                <div className="flex items-center justify-between text-xs px-6 pt-2">
                  <span className="text-muted-foreground">characters this month</span>
                  <span className="text-foreground tabular-nums">
                    {ttsChars && typeof ttsChars.character_count === "number" && typeof ttsChars.character_limit === "number"
                      ? `${ttsChars.character_count.toLocaleString()} / ${ttsChars.character_limit.toLocaleString()}`
                      : "—"}
                  </span>
                </div>
              </CollapsibleContent>
            </Collapsible>
          }
        />
      </div>
    </div>
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
  onRefresh,
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
  onRefresh: () => void;
  usageContent: React.ReactNode;
}) {
  return (
    <Field orientation="vertical" className="gap-3">
      <Field orientation="horizontal" className="items-center justify-between">
        <FieldContent>
          <FieldLabel className="flex items-center gap-2">
            {icon}
            {title}
            {provider && <span className="text-xs text-muted-foreground font-normal">{provider}</span>}
          </FieldLabel>
        </FieldContent>
        <Switch
          checked={enabled && configured}
          disabled={!configured}
          onCheckedChange={onToggleEnabled}
        />
      </Field>

      {!configured ? (
        <p className="text-xs text-amber-600 dark:text-amber-500">not configured — ask the agent to set it up</p>
      ) : enabled ? (
        <>
          {settings && settings.length > 0 && (
            <DynamicSettings
              settings={settings}
              domain={domain}
              agentName={agentName}
              onSettingChange={onSettingChange}
              onRefresh={onRefresh}
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
  onRefresh,
}: {
  settings: SettingDef[];
  domain: "stt" | "tts";
  agentName: string | null;
  onSettingChange: (settings: SettingDef[]) => void;
  onRefresh: () => void;
}) {
  const updateSetting = useCallback((key: string, value: unknown) => {
    onSettingChange(settings.map(s => s.key === key ? { ...s, value } : s));
    if (agentName) {
      setVoiceSetting(agentName, domain, key, value).catch(() => onRefresh());
    }
  }, [settings, domain, agentName, onSettingChange, onRefresh]);

  // Split settings: select settings get their own collapsibles, others go in a Configuration section
  const boolSettings = settings.filter(s => s.type === "bool");
  const numberSettings = settings.filter(s => s.type === "number");
  const selectSettings = settings.filter(s => s.type === "select");

  return (
    <>
      {boolSettings.map(s => (
        <BoolSetting key={s.key} setting={s} onChange={v => updateSetting(s.key, v)} />
      ))}

      {selectSettings.map(s => (
        <SelectSetting key={s.key} setting={s} onChange={v => updateSetting(s.key, v)} onRefresh={onRefresh} />
      ))}

      {numberSettings.length > 0 && (
        <Collapsible>
          <CollapsibleTrigger asChild>
            <Button variant="ghost" size="sm" className="w-full justify-start gap-2 px-0 text-sm text-muted-foreground hover:text-foreground">
              <ChevronDown className="size-4 transition-transform [[data-state=closed]_&]:-rotate-90" />
              configuration
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="flex flex-col gap-3 pt-2 px-6">
              {numberSettings.map(s => (
                <NumberSetting key={s.key} setting={s} onChange={v => updateSetting(s.key, v)} />
              ))}
            </div>
          </CollapsibleContent>
        </Collapsible>
      )}
    </>
  );
}

// --- Individual setting renderers ---

function BoolSetting({ setting, onChange }: { setting: SettingDef; onChange: (v: boolean) => void }) {
  const [value, toggle] = useOptimisticToggle(
    setting.value as boolean | undefined, setting.default as boolean ?? false,
    onChange,
  );
  return (
    <Field orientation="horizontal" className="items-center justify-between">
      <FieldContent>
        <FieldLabel className="text-sm">{setting.label}</FieldLabel>
        {setting.description && <FieldDescription>{setting.description}</FieldDescription>}
      </FieldContent>
      <Switch checked={value} onCheckedChange={toggle} />
    </Field>
  );
}

function NumberSetting({ setting, onChange }: { setting: SettingDef; onChange: (v: number) => void }) {
  const [localValue, setLocalValue] = useState(setting.value as number ?? setting.default as number ?? 0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (setting.value !== undefined) setLocalValue(setting.value as number);
  }, [setting.value]);

  useEffect(() => {
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
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
        <span className="text-[10px] text-muted-foreground/70 tabular-nums">{formatValue(localValue)}</span>
      </div>
      <Slider
        min={setting.min ?? 0}
        max={setting.max ?? 1}
        step={setting.step ?? 0.01}
        value={[localValue]}
        onValueChange={([v]) => handleChange(v)}
      />
      {setting.description && <p className="text-xs text-muted-foreground">{setting.description}</p>}
    </div>
  );
}

function SelectSetting({ setting, onChange, onRefresh }: { setting: SettingDef; onChange: (v: string) => void; onRefresh: () => void }) {
  const options = setting.options ?? [];
  const hasPreview = options.some(o => o.preview);

  if (hasPreview) {
    return <VoicePicker setting={setting} onChange={onChange} onRefresh={onRefresh} />;
  }

  return (
    <Collapsible>
      <CollapsibleTrigger asChild>
        <Button variant="ghost" size="sm" className="w-full justify-start gap-2 px-0 text-sm text-muted-foreground hover:text-foreground">
          <ChevronDown className="size-4 transition-transform [[data-state=closed]_&]:-rotate-90" />
          {setting.label}: <span className="text-foreground font-medium">
            {options.find(o => o.value === setting.value)?.label ?? "Unknown"}
          </span>
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="flex flex-col gap-1 pt-2 px-6">
          {options.map(opt => (
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

function VoicePicker({ setting, onChange, onRefresh }: { setting: SettingDef; onChange: (v: string) => void; onRefresh: () => void }) {
  const options = setting.options ?? [];
  const [pendingId, setPendingId] = useState<string | null>(null);
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

  const selectedId = pendingId ?? (setting.value as string) ?? null;
  const selectedOption = options.find(o => o.value === selectedId);

  const select = (opt: { value: string }) => {
    setPendingId(opt.value);
    onChange(opt.value);
    onRefresh();
    setPendingId(null);
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
        <Button variant="ghost" size="sm" className="w-full justify-start gap-2 px-0 text-sm text-muted-foreground hover:text-foreground">
          <ChevronDown className="size-4 transition-transform [[data-state=closed]_&]:-rotate-90" />
          {setting.label}: <span className="text-foreground font-medium">{selectedOption?.label ?? "Unknown"}</span>
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
                className={`group relative flex flex-col items-center gap-1.5 rounded-lg p-2 transition-colors cursor-pointer ${selected ? "bg-primary/10 ring-1 ring-primary/30" : "hover:bg-muted"
                  }`}
                onClick={() => select(opt)}
              >
                <div className={`relative size-9 rounded-full flex items-center justify-center text-xs font-medium ${selected ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"
                  }`}>
                  {opt.label[0]}
                  {opt.preview && (
                    <span
                      role="button"
                      tabIndex={-1}
                      aria-label={playing ? "Stop preview" : "Play preview"}
                      className="absolute inset-0 size-full rounded-full bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center cursor-pointer"
                      onClick={(e) => { e.stopPropagation(); playPreview(opt); }}
                    >
                      {playing ? <Square className="size-3 text-white" /> : <Play className="size-3 text-white ml-0.5" />}
                    </span>
                  )}
                </div>
                <span className={`text-[10px] leading-tight text-center truncate max-w-full ${selected ? "text-primary font-medium" : "text-muted-foreground"
                  }`}>
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

function formatBalance(b: { amount?: number; units?: string }): string {
  const amount = b.amount ?? 0;
  const units = (b.units ?? "").toLowerCase();
  if (units === "usd") return `$${amount.toFixed(2)}`;
  if (units === "hour" || units === "hours") return `${amount.toFixed(2)} h`;
  return `${amount.toFixed(2)} ${b.units ?? ""}`;
}

// --- Plan usage ---

function UsageBar({ label, limit }: { label: string; limit: RateLimit }) {
  const pct = limit.utilization != null ? Math.min(limit.utilization, 100) : null;
  const resetsAt = limit.resets_at ? formatResetsAt(limit.resets_at) : null;

  if (pct == null) return null;

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">{label}</span>
        <span className="text-xs text-muted-foreground tabular-nums">{pct.toFixed(0)}%</span>
      </div>
      <Progress value={pct} className="h-1.5" />
      {resetsAt && <span className="text-[10px] text-muted-foreground/60">Resets {resetsAt}</span>}
    </div>
  );
}

function PlanUsageSection({ utilization, loading, error, onRefresh }: {
  utilization: Utilization | null;
  loading: boolean;
  error: boolean;
  onRefresh: () => void;
}) {
  const bars: { label: string; limit: RateLimit }[] = [];
  if (utilization?.five_hour) bars.push({ label: "current session", limit: utilization.five_hour });
  if (utilization?.seven_day) bars.push({ label: "current week", limit: utilization.seven_day });
  if (utilization?.seven_day_sonnet) bars.push({ label: "current week (sonnet)", limit: utilization.seven_day_sonnet });
  if (utilization?.seven_day_opus) bars.push({ label: "current week (opus)", limit: utilization.seven_day_opus });

  return (
    <Field orientation="vertical" className="gap-3">
      <Field orientation="horizontal" className="items-center justify-between">
        <FieldContent>
          <FieldLabel className="flex items-center gap-2">
            <Activity className="size-4 text-muted-foreground" />
            plan usage
          </FieldLabel>
        </FieldContent>
        <button onClick={onRefresh} className="text-muted-foreground hover:text-foreground transition-colors cursor-pointer">
          <RefreshCw className={`size-3.5 ${loading ? "animate-spin" : ""}`} />
        </button>
      </Field>

      {loading ? (
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-3 w-8" />
          </div>
          <Skeleton className="h-1.5 w-full" />
        </div>
      ) : error ? (
        <p className="text-xs text-muted-foreground">failed to load usage data</p>
      ) : bars.length === 0 && !utilization?.extra_usage ? (
        <p className="text-xs text-muted-foreground">no usage data available</p>
      ) : (
        <div className="flex flex-col gap-2.5">
          {bars.map(b => <UsageBar key={b.label} label={b.label} limit={b.limit} />)}
          {utilization?.extra_usage && utilization.extra_usage.is_enabled && (
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">extra credits</span>
              <span className="text-foreground tabular-nums">
                {utilization.extra_usage.used_credits != null && utilization.extra_usage.monthly_limit != null
                  ? `$${(utilization.extra_usage.used_credits / 100).toFixed(2)} / $${(utilization.extra_usage.monthly_limit / 100).toFixed(2)}`
                  : "—"}
              </span>
            </div>
          )}
        </div>
      )}
    </Field>
  );
}

function formatResetsAt(iso: string): string {
  const diff = new Date(iso).getTime() - Date.now();
  if (diff <= 0) return "now";
  const hours = Math.floor(diff / 3_600_000);
  const mins = Math.floor((diff % 3_600_000) / 60_000);
  if (hours > 0) return `in ${hours}h ${mins}m`;
  return `in ${mins}m`;
}

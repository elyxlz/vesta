import { useState } from "react";
import { AudioLines, Mic, Volume2 } from "lucide-react";
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldLabel,
} from "@/components/ui/field";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import {
  fetchSttUsage,
  fetchTtsUsage,
  setSttEnabled,
  setTtsEnabled,
  setVoiceSetting,
  type SttUsage,
  type TtsUsage,
} from "@/lib/voice";
import { useOptimisticToggle } from "./use-optimistic-toggle";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider/context";
import { useVoice } from "@/stores/use-voice";
import {
  usePreferences,
  type VoiceActivationMode,
} from "@/stores/use-preferences";
import { UsageCollapsible, DomainSection } from "./domain-section";

function formatBalance(b: { amount?: number; units?: string }): string {
  const amount = b.amount ?? 0;
  const units = (b.units ?? "").toLowerCase();
  if (units === "usd") return `$${amount.toFixed(2)}`;
  if (units === "hour" || units === "hours") return `${amount.toFixed(2)} h`;
  return `${amount.toFixed(2)} ${b.units ?? ""}`;
}

// Combined hours + balance line, or a placeholder dash until both halves have loaded.
function sttUsageSummary(usageData: SttUsage | null): string {
  const results = usageData?.usage?.results;
  const balance = usageData?.balance?.balances?.[0];
  if (!results || !balance) return "—";
  const hours = results.reduce((acc, r) => acc + (r.hours ?? 0), 0);
  return `${hours.toFixed(2)} h used · ${formatBalance(balance)} left`;
}

// --- Exported cards ---

const ACTIVATION_OPTIONS: { value: VoiceActivationMode; label: string }[] = [
  { value: "toggle", label: "toggle" },
  { value: "hold", label: "hold" },
];

// How dictation behaves, apart from which provider transcribes it.
export function DictationCard() {
  const { name: agentName } = useSelectedAgent();
  const { sttStatus, patchStt, refreshVoiceStatus } = useVoice();
  const activation = usePreferences((s) => s.voiceActivation);
  const update = usePreferences((s) => s.update);
  const setActivation = (voiceActivation: VoiceActivationMode) => {
    update({ voiceActivation });
  };

  const interruptSetting = sttStatus?.settings?.find(
    (s) => s.key === "interrupt_tts",
  );
  const interruptValue =
    typeof interruptSetting?.value === "boolean"
      ? interruptSetting.value
      : true;

  const setInterrupt = (value: boolean) => {
    if (!sttStatus?.settings || !agentName) return;
    patchStt({
      settings: sttStatus.settings.map((s) =>
        s.key === "interrupt_tts" ? { ...s, value } : s,
      ),
    });
    setVoiceSetting(agentName, "stt", "interrupt_tts", value).catch(() =>
      refreshVoiceStatus(),
    );
  };

  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>
          <Mic className="size-4 text-muted-foreground" />
          dictation
        </CardTitle>
      </CardHeader>
      <CardContent>
        <Field orientation="vertical" className="gap-3">
          <Field
            orientation="horizontal"
            className="items-center justify-between"
          >
            <FieldContent>
              <FieldLabel>activation</FieldLabel>
              <FieldDescription>
                hold the mic to talk, or tap once to start and again to send
              </FieldDescription>
            </FieldContent>
            <div className="inline-flex rounded-md bg-muted p-0.5">
              {ACTIVATION_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  aria-pressed={activation === opt.value}
                  className={`rounded-sm px-2.5 py-1 text-sm transition-colors ${
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
          </Field>
          {interruptSetting && (
            <Field
              orientation="horizontal"
              className="items-center justify-between"
            >
              <FieldContent>
                <FieldLabel>interrupt speech on talk</FieldLabel>
                <FieldDescription>
                  stop text-to-speech playback when you start speaking
                </FieldDescription>
              </FieldContent>
              <Switch checked={interruptValue} onCheckedChange={setInterrupt} />
            </Field>
          )}
        </Field>
      </CardContent>
    </Card>
  );
}

// How a conversation behaves; a conversation always speaks back and always barges in.
export function ConversationCard() {
  const autoEnd = useVoice((s) => s.conversationAutoEnd);
  const setAutoEnd = useVoice((s) => s.setConversationAutoEnd);
  const yieldToUser = useVoice((s) => s.conversationYield);
  const setYieldToUser = useVoice((s) => s.setConversationYield);

  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>
          <AudioLines className="size-4 text-muted-foreground" />
          conversation
        </CardTitle>
      </CardHeader>
      <CardContent>
        <Field orientation="vertical" className="gap-3">
          <Field
            orientation="horizontal"
            className="items-center justify-between"
          >
            <FieldContent>
              <FieldLabel>never interrupt you</FieldLabel>
              <FieldDescription>
                hold replies while you are talking, so Vesta waits for your
                whole thought
              </FieldDescription>
            </FieldContent>
            <Switch checked={yieldToUser} onCheckedChange={setYieldToUser} />
          </Field>
          <Field
            orientation="horizontal"
            className="items-center justify-between"
          >
            <FieldContent>
              <FieldLabel>end after silence</FieldLabel>
              <FieldDescription>
                end a conversation on its own after fifteen minutes without you
                speaking
              </FieldDescription>
            </FieldContent>
            <Switch checked={autoEnd} onCheckedChange={setAutoEnd} />
          </Field>
        </Field>
      </CardContent>
    </Card>
  );
}

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
  return (
    <DomainSection
      icon={<Mic className="size-4 text-muted-foreground" />}
      title="speech to text"
      configured={configured}
      provider={sttStatus?.provider ?? null}
      enabled={enabled}
      onToggleEnabled={toggleEnabled}
      settings={sttStatus?.settings?.filter((s) => s.key !== "interrupt_tts")}
      domain="stt"
      agentName={agentName}
      onSettingChange={(settings) => patchStt({ settings })}
      usageContent={
        <UsageCollapsible onOpen={loadUsage}>
          <div className="flex items-center justify-between text-sm px-6 pt-2">
            <span className="text-muted-foreground">hours this month</span>
            <span className="text-foreground tabular-nums">
              {sttUsageSummary(usageData)}
            </span>
          </div>
        </UsageCollapsible>
      }
    />
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
      onSettingChange={(settings) => patchTts({ settings })}
      usageContent={
        <UsageCollapsible onOpen={loadUsage}>
          <div className="flex items-center justify-between text-sm px-6 pt-2">
            <span className="text-muted-foreground">characters this month</span>
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
  );
}

// --- Shared collapsible trigger ---

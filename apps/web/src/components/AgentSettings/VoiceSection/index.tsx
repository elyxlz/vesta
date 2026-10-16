import { AudioLines, Mic, Scale, Volume2 } from "lucide-react";
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldLabel,
} from "@/components/ui/field";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import {
  selectVoiceProvider,
  setJudgeEnabled,
  setSttEnabled,
  setTtsEnabled,
} from "@/lib/voice";
import { DynamicSettings } from "./setting-controls";
import { useOptimisticToggle } from "./use-optimistic-toggle";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider/context";
import { useVoice } from "@/stores/use-voice";
import {
  usePreferences,
  type VoiceActivationMode,
} from "@/stores/use-preferences";
import { UsageCollapsible, DomainSection } from "./domain-section";

// --- Exported cards ---

const ACTIVATION_OPTIONS: { value: VoiceActivationMode; label: string }[] = [
  { value: "toggle", label: "toggle" },
  { value: "hold", label: "hold" },
];

// How dictation behaves, apart from which provider transcribes it.
export function DictationCard() {
  const activation = usePreferences((s) => s.voiceActivation);
  const update = usePreferences((s) => s.update);
  const setActivation = (voiceActivation: VoiceActivationMode) => {
    update({ voiceActivation });
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
        </Field>
      </CardContent>
    </Card>
  );
}

// How a conversation behaves. A conversation always speaks back, and the voice engine holds
// a reply while the user has the floor.
export function ConversationCard() {
  const { name: agentName } = useSelectedAgent();
  const autoEnd = useVoice((s) => s.conversationAutoEnd);
  const setAutoEnd = useVoice((s) => s.setConversationAutoEnd);
  const behaviors = useVoice((s) => s.behaviors);
  const setBehaviors = useVoice((s) => s.setBehaviors);

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
          {behaviors && (
            <DynamicSettings
              settings={behaviors.settings}
              section="behavior"
              agentName={agentName}
              onSettingChange={(settings) => setBehaviors({ settings })}
            />
          )}
          <Field
            orientation="horizontal"
            className="items-center justify-between"
          >
            <FieldContent>
              <FieldLabel className="text-base">end after silence</FieldLabel>
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

  return (
    <DomainSection
      icon={<Mic className="size-4 text-muted-foreground" />}
      title="speech to text"
      configured={configured}
      provider={sttStatus?.provider ?? null}
      connected={sttStatus?.connected ?? []}
      onUseProvider={(provider) => {
        if (!agentName) return;
        selectVoiceProvider(agentName, "stt", provider)
          .then(patchStt)
          .catch(() => refreshVoiceStatus());
      }}
      enabled={enabled}
      onToggleEnabled={toggleEnabled}
      settings={sttStatus?.settings}
      domain="stt"
      agentName={agentName}
      onSettingChange={(settings) => patchStt({ settings })}
      usageContent={
        <UsageCollapsible
          key={sttStatus?.provider}
          agentName={agentName}
          domain="stt"
        />
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

  return (
    <DomainSection
      icon={<Volume2 className="size-4 text-muted-foreground" />}
      title="text to speech"
      configured={configured}
      provider={ttsStatus?.provider ?? null}
      connected={ttsStatus?.connected ?? []}
      onUseProvider={(provider) => {
        if (!agentName) return;
        selectVoiceProvider(agentName, "tts", provider)
          .then(patchTts)
          .catch(() => refreshVoiceStatus());
      }}
      enabled={enabled}
      onToggleEnabled={toggleEnabled}
      settings={ttsStatus?.settings}
      domain="tts"
      agentName={agentName}
      onSettingChange={(settings) => patchTts({ settings })}
      usageContent={
        <UsageCollapsible
          key={ttsStatus?.provider}
          agentName={agentName}
          domain="tts"
        />
      }
    />
  );
}

// The judge is the optional third role. While a reply plays it decides who the user's words are
// for, which costs the user's live words going to its provider, so the card says so before
// the switch is turned on. An agent connects one; the app only turns it on and off.
export function JudgeCard() {
  const { name: agentName } = useSelectedAgent();
  const judgeStatus = useVoice((s) => s.judgeStatus);
  const setJudgeStatus = useVoice((s) => s.setJudgeStatus);
  const refreshVoiceStatus = useVoice((s) => s.refreshVoiceStatus);
  const configured = judgeStatus?.configured ?? false;

  const [enabled, toggleEnabled] = useOptimisticToggle(
    judgeStatus?.enabled,
    false,
    (v) => {
      if (!judgeStatus || !agentName) return;
      setJudgeStatus({ ...judgeStatus, enabled: v });
      setJudgeEnabled(agentName, v).catch(() => refreshVoiceStatus());
    },
  );

  // An agent whose voice service has no judge role shows no card.
  if (!judgeStatus) return null;
  const provider = judgeStatus.provider;
  return (
    <DomainSection
      icon={<Scale className="size-4 text-muted-foreground" />}
      title="judge"
      description={
        configured && provider
          ? `decides who your words are for while a reply plays: a short stop cuts the reply, and talk to another person stays out. while it is on, your live words go to ${provider}.`
          : "optional. decides who your words are for while a reply plays, so talk to another person stays out. ask the agent to connect one."
      }
      configured={configured}
      provider={provider}
      connected={judgeStatus.connected ?? []}
      onUseProvider={(name) => {
        if (!agentName) return;
        selectVoiceProvider(agentName, "judge", name)
          .then(setJudgeStatus)
          .catch(() => refreshVoiceStatus());
      }}
      enabled={enabled}
      onToggleEnabled={toggleEnabled}
      settings={judgeStatus.settings}
      domain="judge"
      agentName={agentName}
      onSettingChange={(settings) =>
        setJudgeStatus({ ...judgeStatus, settings })
      }
      usageContent={null}
    />
  );
}

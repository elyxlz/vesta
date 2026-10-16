import type { ReactNode } from "react";
import { Alert, StyleSheet, View } from "react-native";
import { voiceUsageSummary } from "@vesta/core";
import type { VoiceDomain, VoiceStatus } from "@vesta/core";
import { useAgent } from "@/agent/AgentProvider";
import {
  useVoiceChange,
  useVoiceUsage,
  useVoiceSettings,
  type VoiceChange,
} from "@/agent/settings/voice-actions";
import { VoiceSetting } from "@/agent/settings/voice-setting";
import { Card } from "@/components/ui/Card";
import { FormRow, SwitchRow } from "@/components/ui/Form";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/States";
import { Quote, Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";

const DOMAIN_TITLES: Record<VoiceDomain, string> = {
  stt: "Speech to text",
  tts: "Text to speech",
  judge: "Judge",
};

const ENABLED_DETAILS: Record<VoiceDomain, string> = {
  stt: "Use live transcription in chat.",
  tts: "Speak new replies when available.",
  judge: "Let the judge read your words while a reply plays.",
};

// The usage row mounts only for a role that is configured and on, so no other role asks its
// provider.
function UsageRow({
  domain,
  provider,
}: {
  domain: "stt" | "tts";
  provider: string | null;
}) {
  const usage = useVoiceUsage(domain, provider);
  return <FormRow label="Usage" value={voiceUsageSummary(usage.data)} />;
}

function DomainCard({
  domain,
  status,
  about,
  onChange,
  busy,
}: {
  domain: VoiceDomain;
  status: VoiceStatus;
  // What the role does, for a role the user must choose with care.
  about?: ReactNode;
  onChange: (change: VoiceChange, onSettled?: () => void) => void;
  busy: boolean;
}) {
  const { colors } = usePreferences();
  const title = DOMAIN_TITLES[domain];
  const connected = status.connected ?? [];
  const live = status.configured && status.enabled !== false;
  // With two or more providers connected to the role, the card offers the switch.
  const chooseProvider = () => {
    Alert.alert("Provider", `Choose who does ${title.toLowerCase()}.`, [
      ...connected.map((provider) => ({
        text: provider,
        onPress: () => onChange({ type: "provider", domain, provider }),
      })),
      { text: "Cancel", style: "cancel" },
    ]);
  };
  return (
    <Card>
      <View>
        <Text family="heading" style={[styles.title, { color: colors.text }]}>
          {title}
        </Text>
        <Text style={[styles.provider, { color: colors.secondaryText }]}>
          {status.provider ?? "not configured"}
        </Text>
      </View>
      {about ? (
        <Text style={[styles.about, { color: colors.secondaryText }]}>
          {about}
        </Text>
      ) : null}
      <SwitchRow
        label={status.configured ? "Enabled" : "Needs configuration"}
        detail={
          status.configured
            ? ENABLED_DETAILS[domain]
            : "Ask the agent to configure this voice service."
        }
        value={live}
        disabled={!status.configured || busy}
        onValueChange={(value) => onChange({ type: "enabled", domain, value })}
      />
      {live && connected.length > 1 ? (
        <FormRow
          label="Provider"
          value={status.provider ?? undefined}
          onPress={chooseProvider}
        />
      ) : null}
      {live && domain !== "judge" ? (
        <UsageRow domain={domain} provider={status.provider} />
      ) : null}
      {live
        ? (status.settings ?? []).map((setting) => (
            <VoiceSetting
              key={setting.key}
              setting={setting}
              section={domain}
              onSave={(section, key, value, onSettled) =>
                onChange(
                  { type: "setting", domain: section, key, value },
                  onSettled,
                )
              }
              busy={busy}
            />
          ))
        : null}
    </Card>
  );
}

export function VoiceSection() {
  const { name } = useAgent();
  const { settings, hasVoiceService } = useVoiceSettings();
  const change = useVoiceChange();
  const { colors } = usePreferences();
  const apply = (next: VoiceChange, onSettled?: () => void) =>
    change.mutate(next, { onSettled });

  if (!hasVoiceService) {
    return (
      <EmptyState
        title="Voice is not set up yet"
        detail={
          <>
            {name} can talk and listen once voice is set up. Just ask in chat,
            for example <Quote>“set up voice”</Quote> or{" "}
            <Quote>“let me talk to you”</Quote>.
          </>
        }
      />
    );
  }

  if (settings.isLoading) {
    return <LoadingState label="Loading voice services…" />;
  }
  if (!settings.data) {
    return (
      <ErrorState
        message={
          settings.error instanceof Error
            ? settings.error.message
            : "Voice settings are unavailable."
        }
        retry={() => void settings.refetch()}
      />
    );
  }

  const { stt, tts, judge, behaviors } = settings.data;
  return (
    <>
      <DomainCard
        domain="stt"
        status={stt}
        busy={change.isPending}
        onChange={apply}
      />
      <DomainCard
        domain="tts"
        status={tts}
        busy={change.isPending}
        onChange={apply}
      />
      {judge ? (
        <DomainCard
          domain="judge"
          status={judge}
          about={
            <>
              While a reply plays, the judge decides who your words are for: a
              short <Quote>“stop”</Quote> cuts the reply, an{" "}
              <Quote>“mhm”</Quote> does not, and talk to another person in the
              room stays out of the conversation. While it is on, your live
              words and the line {name} is saying go to{" "}
              {judge.provider ?? "its provider"}.
            </>
          }
          busy={change.isPending}
          onChange={apply}
        />
      ) : null}
      {behaviors?.settings.length ? (
        <Card>
          <Text family="heading" style={[styles.title, { color: colors.text }]}>
            Behavior
          </Text>
          {behaviors.settings.map((setting) => (
            <VoiceSetting
              key={setting.key}
              setting={setting}
              section="behavior"
              onSave={(section, key, value, onSettled) =>
                apply(
                  { type: "setting", domain: section, key, value },
                  onSettled,
                )
              }
              busy={change.isPending}
            />
          ))}
        </Card>
      ) : null}
    </>
  );
}

const styles = StyleSheet.create({
  title: { fontSize: 19, fontWeight: "500" },
  provider: { fontSize: 13, marginTop: 2 },
  about: { fontSize: 14, lineHeight: 20 },
});

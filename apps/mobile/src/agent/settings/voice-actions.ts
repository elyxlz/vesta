import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchVoiceSettings,
  fetchVoiceUsage,
  selectVoiceProvider,
  setVoiceBehavior,
  setVoiceEnabled,
  setVoiceSetting,
  type VoiceDomain,
  type VoiceSettingsData,
  type VoiceStatus,
} from "@vesta/core";
import { useAgent } from "@/agent/AgentProvider";
import type { SettingSection } from "@/agent/settings/voice-settings-model";
import { useToast } from "@/components/native-toast";
import { useSession } from "@/session/SessionProvider";

// The usage routes ask the provider's own API, so an answer serves this long before a refetch
// and a failed call is not tried again.
const USAGE_STALE_MS = 5 * 60 * 1000;

export type VoiceChange =
  | { type: "enabled"; domain: VoiceDomain; value: boolean }
  | { type: "provider"; domain: VoiceDomain; provider: string }
  | { type: "setting"; domain: SettingSection; key: string; value: unknown };

// The voice page and the option list read one query, so the list opens on what the page loaded.
export function useVoiceSettings() {
  const { api } = useSession();
  const { name, agent } = useAgent();
  // The voice service registers itself once the agent has set voice up; until then the proxy has
  // nothing to serve, so the page explains instead of asking.
  const hasVoiceService = Boolean(agent && "voice" in agent.services);
  const settings = useQuery({
    queryKey: ["voice", name],
    enabled: hasVoiceService,
    queryFn: () => fetchVoiceSettings(api, name),
  });
  return { settings, hasVoiceService };
}

// The answer of a change to one role, as the part of the page data it replaces.
function rolePatch(
  domain: VoiceDomain,
  status: VoiceStatus,
): Partial<VoiceSettingsData> {
  if (domain === "stt") return { stt: status };
  if (domain === "tts") return { tts: status };
  return { judge: status };
}

// One change to the voice service. Each route answers with the new state of what it changed,
// which the page takes as it is; a failed change reloads the page data.
export function useVoiceChange() {
  const queryClient = useQueryClient();
  const { api } = useSession();
  const { name } = useAgent();
  const { showError } = useToast();
  return useMutation({
    mutationFn: async (
      change: VoiceChange,
    ): Promise<Partial<VoiceSettingsData>> => {
      if (change.type === "enabled")
        return rolePatch(
          change.domain,
          await setVoiceEnabled(api, name, change.domain, change.value),
        );
      if (change.type === "provider")
        return rolePatch(
          change.domain,
          await selectVoiceProvider(api, name, change.domain, change.provider),
        );
      if (change.domain === "behavior")
        return {
          behaviors: await setVoiceBehavior(
            api,
            name,
            change.key,
            change.value,
          ),
        };
      return rolePatch(
        change.domain,
        await setVoiceSetting(
          api,
          name,
          change.domain,
          change.key,
          change.value,
        ),
      );
    },
    onSuccess: (patch) => {
      queryClient.setQueryData<VoiceSettingsData>(["voice", name], (data) =>
        data ? { ...data, ...patch } : data,
      );
    },
    onError: (error) => {
      showError(error, "Could not save the voice setting");
      void queryClient.invalidateQueries({ queryKey: ["voice", name] });
    },
  });
}

// The usage of a role's provider. The key names the provider, so a switch to another one asks
// again, and it stays outside the ["voice", name] key that every saved change invalidates.
export function useVoiceUsage(domain: "stt" | "tts", provider: string | null) {
  const { api } = useSession();
  const { name } = useAgent();
  return useQuery({
    queryKey: ["voice-usage", name, domain, provider],
    queryFn: () => fetchVoiceUsage(api, name, domain),
    staleTime: USAGE_STALE_MS,
    retry: false,
  });
}

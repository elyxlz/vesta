import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchSttUsage,
  fetchTtsUsage,
  fetchVoiceBehaviors,
  fetchVoiceStatus,
  selectVoiceProvider,
  setVoiceBehavior,
  setVoiceEnabled,
  setVoiceSetting,
  type VoiceDomain,
  type VoiceStatus,
} from "@vesta/core";
import { useAgent } from "@/agent/AgentProvider";
import { ApiError } from "@/api/client";
import type {
  SettingSection,
  VoiceSettingsData,
} from "@/agent/settings/voice-settings-model";
import { useToast } from "@/components/native-toast";
import { useSession } from "@/session/SessionProvider";

// The usage routes ask the provider's own API, so an answer serves this long before a refetch
// and a failed call is not tried again.
const USAGE_STALE_MS = 5 * 60 * 1000;
const NOT_FOUND = 404;

export type VoiceChange =
  | { type: "enabled"; domain: VoiceDomain; value: boolean }
  | { type: "provider"; domain: VoiceDomain; provider: string }
  | { type: "setting"; domain: SettingSection; key: string; value: unknown };

// A voice service with no judge route answers 404, which reads as no judge.
function judgeOrNone(error: unknown): VoiceStatus | null {
  if (error instanceof ApiError && error.status === NOT_FOUND) return null;
  throw error;
}

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
    queryFn: async (): Promise<VoiceSettingsData> => {
      const [stt, tts, judge, behaviors] = await Promise.all([
        fetchVoiceStatus(api, name, "stt"),
        fetchVoiceStatus(api, name, "tts"),
        fetchVoiceStatus(api, name, "judge").catch(judgeOrNone),
        // An agent whose voice service has no behaviors route shows no behavior card.
        fetchVoiceBehaviors(api, name).catch(() => null),
      ]);
      return { stt, tts, judge, behaviors };
    },
  });
  return { settings, hasVoiceService };
}

// One change to the voice service. It stays pending until the page holds the new state, so a
// caller that leaves on success returns to what it saved.
export function useVoiceChange() {
  const queryClient = useQueryClient();
  const { api } = useSession();
  const { name } = useAgent();
  const { showError } = useToast();
  return useMutation({
    mutationFn: async (change: VoiceChange) => {
      if (change.type === "enabled") {
        await setVoiceEnabled(api, name, change.domain, change.value);
      } else if (change.type === "provider") {
        await selectVoiceProvider(api, name, change.domain, change.provider);
      } else if (change.domain === "behavior") {
        await setVoiceBehavior(api, name, change.key, change.value);
      } else {
        await setVoiceSetting(
          api,
          name,
          change.domain,
          change.key,
          change.value,
        );
      }
    },
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["voice", name] }),
    onError: (error) => showError(error, "Could not save the voice setting"),
  });
}

// The usage of a role's provider. The key names the provider, so a switch to another one asks
// again, and it stays outside the ["voice", name] key that every saved change invalidates.
export function useSttUsage(provider: string | null) {
  const { api } = useSession();
  const { name } = useAgent();
  return useQuery({
    queryKey: ["voice-usage", name, "stt", provider],
    queryFn: () => fetchSttUsage(api, name),
    staleTime: USAGE_STALE_MS,
    retry: false,
  });
}

export function useTtsUsage(provider: string | null) {
  const { api } = useSession();
  const { name } = useAgent();
  return useQuery({
    queryKey: ["voice-usage", name, "tts", provider],
    queryFn: () => fetchTtsUsage(api, name),
    staleTime: USAGE_STALE_MS,
    retry: false,
  });
}

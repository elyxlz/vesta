import { useEffect, type ReactNode } from "react";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider/context";
import { useVoice } from "@/stores/use-voice";
import {
  fetchSttStatus,
  fetchTtsStatus,
  fetchVoiceBehaviors,
  preloadAudio,
} from "@/lib/voice";

export function VoiceStoreEffects({ children }: { children: ReactNode }) {
  const { name: agentName, agent } = useSelectedAgent();
  const services = agent.services;
  const voiceRev = services.voice?.rev;
  const hasVoice = "voice" in services;

  const _setAgentContext = useVoice((s) => s._setAgentContext);
  const _setSttStatus = useVoice((s) => s._setSttStatus);
  const _setTtsStatus = useVoice((s) => s._setTtsStatus);
  const setBehaviors = useVoice((s) => s.setBehaviors);
  const _setVoiceError = useVoice((s) => s._setVoiceError);
  const _cleanup = useVoice((s) => s._cleanup);
  const voiceError = useVoice((s) => s.voiceError);

  // Sync agent context into store
  useEffect(() => {
    _setAgentContext(agentName || null, services, voiceRev);
  }, [agentName, services, voiceRev, _setAgentContext]);

  // Fetch voice status when agent/services change
  useEffect(() => {
    if (!agentName || !hasVoice) {
      _setSttStatus(null);
      _setTtsStatus(null);
      setBehaviors(null);
      return;
    }

    const ctrl = new AbortController();
    Promise.all([
      fetchSttStatus(agentName, ctrl.signal),
      fetchTtsStatus(agentName, ctrl.signal),
      fetchVoiceBehaviors(agentName, ctrl.signal),
    ])
      .then(([stt, tts, behaviors]) => {
        if (ctrl.signal.aborted) return;
        _setSttStatus(stt);
        _setTtsStatus(tts);
        setBehaviors(behaviors);
      })
      .catch(() => {
        /* ignore */
      });

    return () => ctrl.abort();
  }, [
    agentName,
    hasVoice,
    voiceRev,
    _setSttStatus,
    _setTtsStatus,
    setBehaviors,
  ]);

  // Preload worklet module when STT is available
  const sttAvailable = useVoice((s) => s.sttAvailable);
  useEffect(() => {
    if (sttAvailable) void preloadAudio();
  }, [sttAvailable]);

  // Auto-dismiss errors after 5s
  useEffect(() => {
    if (!voiceError) return;
    const timer = setTimeout(() => _setVoiceError(null), 5000);
    return () => clearTimeout(timer);
  }, [voiceError, _setVoiceError]);

  // Cleanup transcriber on unmount
  useEffect(() => {
    return () => _cleanup();
  }, [_cleanup]);

  return <>{children}</>;
}

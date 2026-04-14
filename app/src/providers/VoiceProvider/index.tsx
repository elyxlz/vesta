import { useEffect, type ReactNode } from "react";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useVoice } from "@/stores/use-voice";
import { fetchSttStatus, fetchTtsStatus, preloadAudio } from "@/lib/voice";

export function VoiceStoreEffects({ children }: { children: ReactNode }) {
  const { name: agentName, agent } = useSelectedAgent();
  const services = agent.services;
  const voiceRev = agent.services?.voice?.rev;

  const _setAgentContext = useVoice((s) => s._setAgentContext);
  const _setSttStatus = useVoice((s) => s._setSttStatus);
  const _setTtsStatus = useVoice((s) => s._setTtsStatus);
  const _setVoiceError = useVoice((s) => s._setVoiceError);
  const _cleanup = useVoice((s) => s._cleanup);
  const voiceError = useVoice((s) => s.voiceError);

  // Sync agent context into store
  useEffect(() => {
    _setAgentContext(agentName || null, services ?? {}, voiceRev);
  }, [agentName, services, voiceRev, _setAgentContext]);

  // Fetch voice status when agent/services change
  useEffect(() => {
    if (!agentName) {
      _setSttStatus(null);
      _setTtsStatus(null);
      return;
    }

    const hasVoice = "voice" in (services ?? {});
    if (!hasVoice) {
      _setSttStatus(null);
      _setTtsStatus(null);
      return;
    }

    const ctrl = new AbortController();
    Promise.all([
      fetchSttStatus(agentName, ctrl.signal),
      fetchTtsStatus(agentName, ctrl.signal),
    ])
      .then(([stt, tts]) => {
        if (ctrl.signal.aborted) return;
        _setSttStatus(stt);
        _setTtsStatus(tts);
      })
      .catch(() => {});

    return () => ctrl.abort();
  }, [agentName, services, voiceRev, _setSttStatus, _setTtsStatus]);

  // Preload worklet module when STT is available
  const sttAvailable = useVoice((s) => s.sttAvailable);
  useEffect(() => {
    if (sttAvailable) preloadAudio();
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

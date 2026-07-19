import { requireNativeModule } from "expo";

interface VestaAudioSessionModule {
  setRecordingHapticsEnabledAsync(enabled: boolean): Promise<void>;
  transcriptHapticAsync(): Promise<void>;
}

const audioSession =
  requireNativeModule<VestaAudioSessionModule>("VestaAudioSession");

export async function setRecordingHapticsEnabled(
  enabled: boolean,
): Promise<void> {
  await audioSession.setRecordingHapticsEnabledAsync(enabled);
}

export async function triggerTranscriptHaptic(): Promise<void> {
  await audioSession.transcriptHapticAsync();
}

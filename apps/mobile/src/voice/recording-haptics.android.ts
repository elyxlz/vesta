import * as Haptics from "expo-haptics";

// Android never suppresses haptics while the microphone records, so the
// iOS-only AVAudioSession toggle in VestaAudioSession has no counterpart
// here and expo-haptics covers the transcript pulse natively.
export async function setRecordingHapticsEnabled(
  _enabled: boolean,
): Promise<void> {}

export async function triggerTranscriptHaptic(): Promise<void> {
  await Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Soft);
}

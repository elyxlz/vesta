import { requireOptionalNativeModule } from "expo";

interface VestaVoiceServiceModule {
  startForegroundServiceAsync(title: string, body: string): Promise<void>;
  stopForegroundServiceAsync(): Promise<void>;
}

const voiceService =
  requireOptionalNativeModule<VestaVoiceServiceModule>("VestaVoiceService");

export async function startVoiceForegroundService(
  title: string,
  body: string,
): Promise<void> {
  await voiceService?.startForegroundServiceAsync(title, body);
}

export async function stopVoiceForegroundService(): Promise<void> {
  await voiceService?.stopForegroundServiceAsync();
}

import { requireOptionalNativeModule } from "expo";

interface VestaAudioSessionModule {
  setHandsFreeSessionActiveAsync(active: boolean): Promise<void>;
}

const audioSession =
  requireOptionalNativeModule<VestaAudioSessionModule>("VestaAudioSession");

export async function setHandsFreeSessionActive(
  active: boolean,
): Promise<void> {
  await audioSession?.setHandsFreeSessionActiveAsync(active);
}

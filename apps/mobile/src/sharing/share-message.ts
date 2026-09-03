import { Share } from "react-native";
import { requireOptionalNativeModule } from "expo";

interface VestaShareModule {
  shareMessageAsync(
    message: string,
    title: string,
  ): Promise<{
    completed: boolean;
    activityType: string | null;
  }>;
}

const nativeShare = requireOptionalNativeModule<VestaShareModule>("VestaShare");

export async function shareVestaMessage(message: string): Promise<void> {
  if (nativeShare) {
    await nativeShare.shareMessageAsync(message, "Vesta");
    return;
  }

  await Share.share(
    { message, title: "Vesta" },
    { dialogTitle: "Share from Vesta", subject: "Vesta" },
  );
}

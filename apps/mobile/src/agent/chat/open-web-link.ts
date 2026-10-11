import { requireOptionalNativeModule } from "expo";
import * as WebBrowser from "expo-web-browser";

interface VestaOpenLinkModule {
  openInOwningAppAsync(url: string): Promise<boolean>;
}

const nativeOpenLink =
  requireOptionalNativeModule<VestaOpenLinkModule>("VestaOpenLink");

export async function openWebLink(url: string): Promise<void> {
  if (await nativeOpenLink?.openInOwningAppAsync(url)) return;
  await WebBrowser.openBrowserAsync(url);
}

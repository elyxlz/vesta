import { native } from "@/lib/native";

export async function openExternalUrl(url: string): Promise<void> {
  await native.openExternal(url);
}

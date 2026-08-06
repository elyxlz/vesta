import { blocksProtectedContent } from "@/privacy/model";
import { usePrivacy } from "@/privacy/privacy-provider";

export function usePrivacyBlocked(): boolean {
  const privacy = usePrivacy();
  return blocksProtectedContent(
    privacy.hydrated,
    privacy.locked,
    privacy.initializationError !== null,
  );
}

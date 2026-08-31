import type { Ionicons } from "@expo/vector-icons";
import type { AttachmentKind } from "@vesta/core";

// One Ionicons glyph per attachment kind, shared by the composer chips and the bubble tiles.
export const ATTACHMENT_KIND_ICON: Record<
  AttachmentKind,
  keyof typeof Ionicons.glyphMap
> = {
  image: "image-outline",
  video: "film-outline",
  audio: "musical-notes-outline",
  file: "document-outline",
};

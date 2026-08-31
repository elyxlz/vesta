import { File, FileText, Film, Music } from "lucide-react";
import type { AttachmentKind } from "@vesta/core";

// The one kind-to-icon mapping, shared by the bubble tiles and the composer chips. Images
// normally render their own thumbnail; FileText is the no-preview fallback.
export const ATTACHMENT_KIND_ICON: Record<AttachmentKind, typeof File> = {
  image: FileText,
  video: Film,
  audio: Music,
  file: File,
};

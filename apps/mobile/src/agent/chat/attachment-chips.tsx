import { memo } from "react";
import { Pressable, ScrollView, StyleSheet, View } from "react-native";
import { Image } from "expo-image";
import Svg, { Circle } from "react-native-svg";
import { Ionicons } from "@expo/vector-icons";
import {
  attachmentKind,
  draftTotalBytes,
  formatBytes,
  type AttachmentKind,
  type DraftAttachment,
  type UploadErrorReason,
} from "@vesta/core";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";

// The composer's draft chips: one per picked file, always showing name and size, with the upload
// state as a determinate ring (uploading), an offline badge (waiting, auto-resumes), or a retry
// affordance (terminal error). A totals line appears with two or more.

const THUMB_SIZE = 40;
const RING_SIZE = 22;
const RING_STROKE = 2.5;

const KIND_ICON: Record<AttachmentKind, keyof typeof Ionicons.glyphMap> = {
  image: "image-outline",
  video: "film-outline",
  audio: "musical-notes-outline",
  file: "document-outline",
};

const ERROR_LABEL: Record<UploadErrorReason, string> = {
  too_large: "Too large",
  unsupported_agent: "Agent needs an update",
  failed: "Upload failed",
  aborted: "Cancelled",
};

function ProgressRing({
  progress,
  color,
}: {
  progress: number;
  color: string;
}) {
  const radius = (RING_SIZE - RING_STROKE) / 2;
  const circumference = 2 * Math.PI * radius;
  return (
    <Svg
      width={RING_SIZE}
      height={RING_SIZE}
      style={{ transform: [{ rotate: "-90deg" }] }}
    >
      <Circle
        cx={RING_SIZE / 2}
        cy={RING_SIZE / 2}
        r={radius}
        stroke={color}
        strokeOpacity={0.25}
        strokeWidth={RING_STROKE}
        fill="none"
      />
      <Circle
        cx={RING_SIZE / 2}
        cy={RING_SIZE / 2}
        r={radius}
        stroke={color}
        strokeWidth={RING_STROKE}
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={circumference * (1 - progress)}
        fill="none"
      />
    </Svg>
  );
}

function chipStatus(draft: DraftAttachment): string {
  if (draft.status === "error") return ERROR_LABEL[draft.error ?? "failed"];
  if (draft.status === "waiting") return "Waiting for network";
  return formatBytes(draft.size);
}

export const AttachmentChips = memo(function AttachmentChips({
  drafts,
  previewUri,
  onRetry,
  onRemove,
}: {
  drafts: DraftAttachment[];
  previewUri: (localId: string) => string | null;
  onRetry: (localId: string) => void;
  onRemove: (localId: string) => void;
}) {
  const { colors } = usePreferences();
  if (drafts.length === 0) return null;
  return (
    <View style={styles.wrap}>
      <ScrollView
        horizontal
        keyboardShouldPersistTaps="handled"
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.row}
      >
        {drafts.map((draft) => {
          const preview = previewUri(draft.localId);
          const failed = draft.status === "error";
          return (
            <View
              key={draft.localId}
              style={[
                styles.chip,
                {
                  backgroundColor: colors.input,
                  borderColor: failed ? colors.danger : colors.border,
                },
              ]}
            >
              <View style={styles.thumb}>
                {preview !== null ? (
                  <Image
                    source={{ uri: preview }}
                    style={styles.thumbImage}
                    contentFit="cover"
                  />
                ) : (
                  <View
                    style={[
                      styles.thumbImage,
                      styles.thumbFallback,
                      { backgroundColor: colors.card },
                    ]}
                  >
                    <Ionicons
                      name={KIND_ICON[attachmentKind(draft.mime)]}
                      size={18}
                      color={colors.secondaryText}
                    />
                  </View>
                )}
                {(draft.status === "uploading" ||
                  draft.status === "waiting") && (
                  <View style={styles.thumbOverlay}>
                    {draft.status === "waiting" ? (
                      <Ionicons
                        name="cloud-offline-outline"
                        size={16}
                        color="white"
                      />
                    ) : (
                      <ProgressRing progress={draft.progress} color="white" />
                    )}
                  </View>
                )}
              </View>
              <View style={styles.chipBody}>
                <Text
                  numberOfLines={1}
                  style={[styles.chipName, { color: colors.text }]}
                >
                  {draft.name}
                </Text>
                <Text
                  numberOfLines={1}
                  style={[
                    styles.chipStatus,
                    { color: failed ? colors.danger : colors.secondaryText },
                  ]}
                >
                  {chipStatus(draft)}
                </Text>
              </View>
              {failed && (
                <Pressable
                  accessibilityLabel={`Retry uploading ${draft.name}`}
                  accessibilityRole="button"
                  hitSlop={8}
                  onPress={() => {
                    onRetry(draft.localId);
                  }}
                  style={styles.chipAction}
                >
                  <Ionicons name="refresh" size={15} color={colors.text} />
                </Pressable>
              )}
              <Pressable
                accessibilityLabel={`Remove ${draft.name}`}
                accessibilityRole="button"
                hitSlop={8}
                onPress={() => {
                  onRemove(draft.localId);
                }}
                style={styles.chipAction}
              >
                <Ionicons name="close" size={15} color={colors.secondaryText} />
              </Pressable>
            </View>
          );
        })}
      </ScrollView>
      {drafts.length > 1 && (
        <Text style={[styles.totals, { color: colors.secondaryText }]}>
          {drafts.length} files · {formatBytes(draftTotalBytes(drafts))}
        </Text>
      )}
    </View>
  );
});

const styles = StyleSheet.create({
  wrap: { paddingBottom: 6 },
  row: { gap: 8, paddingHorizontal: 2 },
  chip: {
    flexDirection: "row",
    alignItems: "center",
    borderRadius: 14,
    borderWidth: StyleSheet.hairlineWidth,
    padding: 5,
    paddingRight: 8,
    gap: 8,
    maxWidth: 250,
  },
  thumb: { width: THUMB_SIZE, height: THUMB_SIZE },
  thumbImage: { width: THUMB_SIZE, height: THUMB_SIZE, borderRadius: 10 },
  thumbFallback: { alignItems: "center", justifyContent: "center" },
  thumbOverlay: {
    position: "absolute",
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    borderRadius: 10,
    backgroundColor: "rgba(0,0,0,0.35)",
    alignItems: "center",
    justifyContent: "center",
  },
  chipBody: { flexShrink: 1 },
  chipName: { fontSize: 12, fontWeight: "600", maxWidth: 150 },
  chipStatus: { fontSize: 11 },
  chipAction: {
    width: 24,
    height: 24,
    borderRadius: 12,
    alignItems: "center",
    justifyContent: "center",
  },
  totals: { fontSize: 11, paddingTop: 4, paddingLeft: 4 },
});

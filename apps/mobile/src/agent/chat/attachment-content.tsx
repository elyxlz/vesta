import { useEffect, useRef, useState } from "react";
import { Pressable, StyleSheet, View } from "react-native";
import { Image } from "expo-image";
import { useAudioPlayer, useAudioPlayerStatus } from "expo-audio";
import { Ionicons } from "@expo/vector-icons";
import {
  attachmentKind,
  chatAttachmentPath,
  formatBytes,
  type ChatAttachment,
} from "@vesta/core";
import type { ApiClient } from "@/api/client";
import { probeAttachmentStatus } from "@/lib/attachment-probe";
import { useAuthedMediaUri } from "@/lib/authed-media-uri";
import { expoSaveIo } from "@/lib/expo-save-io";
import { AttachmentRemovedError, saveAttachment } from "@/lib/save-attachment";
import { Text } from "@/components/ui/Typography";
import { useToast } from "@/components/native-toast";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { ATTACHMENT_KIND_ICON } from "@/agent/chat/attachment-icons";
import {
  mediaSize,
  throttledProgress,
} from "@/agent/chat/attachment-media-model";

// One attachment block inside a chat bubble, routed by kind: images render inline and open the
// viewer, videos are a poster tile into the viewer, audio plays inline, and everything else is a
// save tile into the share sheet. A blob freed by the agent's cleanup serves 410, rendered as
// the terminal "no longer available" tile on every kind.

export interface OpenViewerRequest {
  attachment: ChatAttachment;
}

type MediaPhase = "loading" | "loaded" | "removed" | "error";

interface BlockContext {
  api: ApiClient;
  agent: string;
  user: boolean;
  // Android only: reopens the message menu, which the block's own Pressable would otherwise
  // swallow the long-press from.
  onLongPress?: () => void;
}

// Tiles sit inside a saturated accent bubble (user) or a card bubble (agent), so the palette is
// picked per side rather than from one theme slot.
function tilePalette(
  user: boolean,
  colors: {
    input: string;
    text: string;
    secondaryText: string;
    accentText: string;
  },
) {
  return {
    background: user ? "rgba(0,0,0,0.14)" : colors.input,
    text: user ? colors.accentText : colors.text,
    secondary: user ? colors.accentText : colors.secondaryText,
    secondaryOpacity: user ? 0.72 : 1,
  };
}

function Tile({
  context,
  icon,
  name,
  detail,
  onPress,
  onLongPress,
  accessibilityLabel,
  trailing,
}: {
  context: BlockContext;
  icon: keyof typeof Ionicons.glyphMap;
  name: string;
  detail: string;
  onPress?: () => void;
  onLongPress?: () => void;
  accessibilityLabel: string;
  trailing?: keyof typeof Ionicons.glyphMap;
}) {
  const { colors } = usePreferences();
  const palette = tilePalette(context.user, colors);
  return (
    <Pressable
      accessibilityLabel={accessibilityLabel}
      accessibilityRole="button"
      disabled={!onPress && !onLongPress}
      onPress={onPress}
      onLongPress={onLongPress}
      style={({ pressed }) => [
        styles.tile,
        { backgroundColor: palette.background, opacity: pressed ? 0.72 : 1 },
      ]}
    >
      <Ionicons
        name={icon}
        size={19}
        color={palette.secondary}
        style={{ opacity: palette.secondaryOpacity }}
      />
      <View style={styles.tileBody}>
        <Text
          numberOfLines={1}
          style={[styles.tileName, { color: palette.text }]}
        >
          {name}
        </Text>
        <Text
          numberOfLines={1}
          style={[
            styles.tileDetail,
            { color: palette.secondary, opacity: palette.secondaryOpacity },
          ]}
        >
          {detail}
        </Text>
      </View>
      {trailing ? (
        <Ionicons
          name={trailing}
          size={16}
          color={palette.secondary}
          style={{ opacity: palette.secondaryOpacity }}
        />
      ) : null}
    </Pressable>
  );
}

function RemovedTile({
  context,
  attachment,
}: {
  context: BlockContext;
  attachment: ChatAttachment;
}) {
  return (
    <Tile
      context={context}
      icon="ban-outline"
      name={attachment.name}
      detail={`${formatBytes(attachment.size)} · no longer available`}
      accessibilityLabel={`${attachment.name}, no longer available`}
      onLongPress={context.onLongPress}
    />
  );
}

function ImageBlock({
  context,
  attachment,
  onOpen,
}: {
  context: BlockContext;
  attachment: ChatAttachment;
  onOpen: (request: OpenViewerRequest) => void;
}) {
  const { colors } = usePreferences();
  const [phase, setPhase] = useState<MediaPhase>("loading");
  // Each retry bumps the epoch: the authed uri rebuilds with a fresh token, so a retry after
  // token expiry dials fresh instead of remounting the same stale source.
  const [epoch, setEpoch] = useState(0);
  const uri = useAuthedMediaUri(
    context.api,
    chatAttachmentPath(context.agent, attachment.id),
    epoch,
  );
  const size = mediaSize(attachment);

  if (phase === "removed")
    return <RemovedTile context={context} attachment={attachment} />;
  if (phase === "error") {
    return (
      <Tile
        context={context}
        icon="refresh"
        name={attachment.name}
        detail="couldn't load · tap to retry"
        accessibilityLabel={`Retry loading ${attachment.name}`}
        onPress={() => {
          setEpoch((current) => current + 1);
          setPhase("loading");
        }}
        onLongPress={context.onLongPress}
      />
    );
  }
  return (
    <Pressable
      accessibilityLabel={`View ${attachment.name}`}
      accessibilityRole="imagebutton"
      onPress={() => {
        onOpen({ attachment });
      }}
      onLongPress={context.onLongPress}
      style={[styles.media, size, { backgroundColor: colors.input }]}
    >
      {uri !== null && (
        <Image
          // The cache key pins on the id: the uri's token rotates, the bytes never do.
          source={{ uri, cacheKey: attachment.id }}
          contentFit="cover"
          style={StyleSheet.absoluteFill}
          onLoad={() => {
            setPhase("loaded");
          }}
          onError={() => {
            // An image error carries no status; a bodyless HEAD tells removed from transient.
            void probeAttachmentStatus(
              context.api,
              chatAttachmentPath(context.agent, attachment.id),
            )
              .then((status) => {
                setPhase(status === 410 ? "removed" : "error");
              })
              .catch(() => {
                setPhase("error");
              });
          }}
        />
      )}
    </Pressable>
  );
}

function VideoBlock({
  onLongPress,
  attachment,
  onOpen,
}: {
  onLongPress?: () => void;
  attachment: ChatAttachment;
  onOpen: (request: OpenViewerRequest) => void;
}) {
  const size = mediaSize(attachment);
  return (
    <Pressable
      accessibilityLabel={`Play ${attachment.name}`}
      accessibilityRole="button"
      onPress={() => {
        onOpen({ attachment });
      }}
      onLongPress={onLongPress}
      style={[styles.media, styles.videoPoster, size]}
    >
      <View style={styles.playBadge}>
        <Ionicons name="play" size={22} color="white" />
      </View>
      <Text numberOfLines={1} style={styles.videoMeta}>
        {attachment.name} · {formatBytes(attachment.size)}
      </Text>
    </Pressable>
  );
}

function AudioBlock({
  context,
  attachment,
}: {
  context: BlockContext;
  attachment: ChatAttachment;
}) {
  // The native player mounts only after the first tap: a voice-note-heavy history would
  // otherwise construct a buffering player (and, on Android, a MediaSession) per visible row.
  const [active, setActive] = useState(false);
  const [removed, setRemoved] = useState(false);
  if (removed) return <RemovedTile context={context} attachment={attachment} />;
  if (!active) {
    return (
      <Tile
        context={context}
        icon="play"
        name={attachment.name}
        detail={audioIdleDetail(attachment)}
        accessibilityLabel={`Play ${attachment.name}`}
        onPress={() => {
          setActive(true);
        }}
        onLongPress={context.onLongPress}
      />
    );
  }
  return (
    <ActiveAudioTile
      context={context}
      attachment={attachment}
      onRemoved={() => {
        setRemoved(true);
      }}
    />
  );
}

function audioIdleDetail(attachment: ChatAttachment): string {
  return `${formatBytes(attachment.size)}${attachment.duration_secs ? ` · ${Math.round(attachment.duration_secs)}s` : ""}`;
}

function ActiveAudioTile({
  context,
  attachment,
  onRemoved,
}: {
  context: BlockContext;
  attachment: ChatAttachment;
  onRemoved: () => void;
}) {
  const uri = useAuthedMediaUri(
    context.api,
    chatAttachmentPath(context.agent, attachment.id),
  );
  const player = useAudioPlayer(uri ? { uri } : null);
  const status = useAudioPlayerStatus(player);
  // The tap that mounted this tile meant "play": start once the source has loaded.
  const autoplayed = useRef(false);
  useEffect(() => {
    if (!status.isLoaded || autoplayed.current) return;
    autoplayed.current = true;
    player.play();
  }, [player, status.isLoaded]);
  const detail = status.playing
    ? `${Math.floor(status.currentTime)}s / ${Math.floor(status.duration)}s`
    : audioIdleDetail(attachment);
  return (
    <Tile
      context={context}
      icon={status.playing ? "pause" : "play"}
      name={attachment.name}
      detail={detail}
      accessibilityLabel={
        status.playing ? `Pause ${attachment.name}` : `Play ${attachment.name}`
      }
      onPress={() => {
        if (status.playing) {
          player.pause();
          return;
        }
        if (!status.isLoaded) {
          // The player load failed silently; a bodyless HEAD tells removed from transient.
          void probeAttachmentStatus(
            context.api,
            chatAttachmentPath(context.agent, attachment.id),
          )
            .then((probed) => {
              if (probed === 410) onRemoved();
            })
            .catch(() => undefined);
          return;
        }
        // A finished player sits at the end; replay from the top.
        if (status.currentTime >= status.duration && status.duration > 0)
          player.seekTo(0);
        player.play();
      }}
      onLongPress={context.onLongPress}
    />
  );
}

type SavePhase = "idle" | "fetching" | "removed";

function FileBlock({
  context,
  attachment,
}: {
  context: BlockContext;
  attachment: ChatAttachment;
}) {
  const { showError } = useToast();
  const [phase, setPhase] = useState<SavePhase>("idle");
  const [received, setReceived] = useState(0);

  if (phase === "removed")
    return <RemovedTile context={context} attachment={attachment} />;

  const start = () => {
    setPhase("fetching");
    setReceived(0);
    saveAttachment(
      expoSaveIo(context.api),
      context.agent,
      attachment,
      (bytes) => {
        setReceived((previous) =>
          throttledProgress(previous, bytes, attachment.size),
        );
      },
    ).then(
      () => {
        setPhase("idle");
      },
      (error: unknown) => {
        if (error instanceof AttachmentRemovedError) {
          setPhase("removed");
          return;
        }
        setPhase("idle");
        showError(`Couldn't download ${attachment.name}`);
      },
    );
  };

  const detail =
    phase === "fetching"
      ? `${formatBytes(received)} of ${formatBytes(attachment.size)}`
      : formatBytes(attachment.size);

  return (
    <Tile
      context={context}
      icon={ATTACHMENT_KIND_ICON[attachmentKind(attachment.mime)]}
      name={attachment.name}
      detail={detail}
      accessibilityLabel={`Save ${attachment.name}`}
      onPress={phase === "fetching" ? undefined : start}
      onLongPress={context.onLongPress}
      trailing="download-outline"
    />
  );
}

export function AttachmentContent({
  api,
  agent,
  user,
  attachment,
  onOpen,
  onLongPress,
}: {
  api: ApiClient;
  agent: string;
  user: boolean;
  attachment: ChatAttachment;
  onOpen: (request: OpenViewerRequest) => void;
  onLongPress?: () => void;
}) {
  const context: BlockContext = { api, agent, user, onLongPress };
  const kind = attachmentKind(attachment.mime);
  if (kind === "image")
    return (
      <ImageBlock context={context} attachment={attachment} onOpen={onOpen} />
    );
  if (kind === "video")
    return (
      <VideoBlock
        onLongPress={onLongPress}
        attachment={attachment}
        onOpen={onOpen}
      />
    );
  if (kind === "audio")
    return <AudioBlock context={context} attachment={attachment} />;
  return <FileBlock context={context} attachment={attachment} />;
}

const styles = StyleSheet.create({
  tile: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    borderRadius: 12,
    paddingHorizontal: 11,
    paddingVertical: 8,
    maxWidth: 260,
    marginVertical: 2,
  },
  tileBody: { flexShrink: 1, minWidth: 0 },
  tileName: { fontSize: 14, fontWeight: "600" },
  tileDetail: { fontSize: 12 },
  media: {
    borderRadius: 12,
    overflow: "hidden",
    marginVertical: 2,
  },
  videoPoster: {
    backgroundColor: "rgba(0,0,0,0.55)",
    alignItems: "center",
    justifyContent: "center",
  },
  playBadge: {
    width: 46,
    height: 46,
    borderRadius: 23,
    backgroundColor: "rgba(0,0,0,0.45)",
    alignItems: "center",
    justifyContent: "center",
  },
  videoMeta: {
    position: "absolute",
    bottom: 8,
    left: 10,
    right: 10,
    fontSize: 11,
    color: "rgba(255,255,255,0.85)",
  },
});

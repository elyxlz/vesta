import { useState } from "react";
import {
  Modal,
  Pressable,
  StyleSheet,
  View,
  useWindowDimensions,
} from "react-native";
import {
  Gesture,
  GestureDetector,
  GestureHandlerRootView,
} from "react-native-gesture-handler";
import Animated, {
  runOnJS,
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from "react-native-reanimated";
import { Image } from "expo-image";
import { VideoView, useVideoPlayer } from "expo-video";
import { Ionicons } from "@expo/vector-icons";
import {
  appChatAttachmentPath,
  attachmentKind,
  formatBytes,
  type ChatAttachment,
} from "@vesta/core";
import type { ApiClient } from "@/api/client";
import { useAuthedMediaUri } from "@/lib/authed-media-uri";
import { expoSaveIo } from "@/lib/expo-save-io";
import { saveAttachment } from "@/lib/save-attachment";
import { Text } from "@/components/ui/Typography";
import { useToast } from "@/components/native-toast";
import type { OpenViewerRequest } from "@/agent/chat/attachment-content";
import {
  DISMISS_DRAG_PX,
  clampPan,
  fittedSize,
  panBy,
  resetTransform,
  toggleZoom,
  zoomAt,
  type Size,
  type ViewerTransform,
} from "@/agent/chat/viewer-gesture";

// The fullscreen media viewer: pinch-zoom + pan + double-tap for images (all on the UI thread
// through the pure viewer-gesture model), native-controls video, swipe-down or tap-away
// dismiss, and the share sheet. Keyed by attachment id, so switching media resets everything.

const DISMISS_MS = 160;

function ZoomableImage({
  uri,
  attachment,
  container,
  onClose,
}: {
  uri: string | null;
  attachment: ChatAttachment;
  container: Size;
  onClose: () => void;
}) {
  const media =
    attachment.width && attachment.height
      ? { width: attachment.width, height: attachment.height }
      : container;
  const fitted = fittedSize(container, media);
  const transform = useSharedValue<ViewerTransform>(resetTransform());
  const gestureStart = useSharedValue<ViewerTransform>(resetTransform());
  const dismissY = useSharedValue(0);

  const pinch = Gesture.Pinch()
    .onStart(() => {
      gestureStart.set(transform.get());
    })
    .onUpdate((event) => {
      const start = gestureStart.get();
      transform.set(
        zoomAt(
          start,
          {
            x: event.focalX - container.width / 2,
            y: event.focalY - container.height / 2,
          },
          event.scale,
          container,
          fitted,
        ),
      );
    })
    .onEnd(() => {
      transform.set(clampPan(transform.get(), container, fitted));
    });

  const pan = Gesture.Pan()
    .maxPointers(1)
    .onStart(() => {
      gestureStart.set(transform.get());
    })
    .onUpdate((event) => {
      const start = gestureStart.get();
      if (start.scale > 1.01) {
        transform.set(
          panBy(
            start,
            event.translationX,
            event.translationY,
            container,
            fitted,
          ),
        );
        return;
      }
      // Fitted: a downward drag tracks toward dismissal instead of panning.
      dismissY.set(Math.max(0, event.translationY));
    })
    .onEnd(() => {
      if (dismissY.get() > DISMISS_DRAG_PX) {
        dismissY.set(withTiming(container.height, { duration: DISMISS_MS }));
        runOnJS(onClose)();
        return;
      }
      dismissY.set(withTiming(0, { duration: DISMISS_MS }));
    });

  const doubleTap = Gesture.Tap()
    .numberOfTaps(2)
    .onEnd((event) => {
      transform.set(
        toggleZoom(
          transform.get(),
          {
            x: event.x - container.width / 2,
            y: event.y - container.height / 2,
          },
          container,
          fitted,
        ),
      );
    });

  const gesture = Gesture.Simultaneous(
    pinch,
    Gesture.Exclusive(doubleTap, pan),
  );
  const animatedStyle = useAnimatedStyle(() => {
    const current = transform.get();
    return {
      transform: [
        { translateX: current.x },
        { translateY: current.y + dismissY.get() },
        { scale: current.scale },
      ],
    };
  });

  return (
    <GestureDetector gesture={gesture}>
      <Animated.View style={[styles.mediaLayer, animatedStyle]}>
        {uri !== null && (
          <Image
            source={{ uri }}
            contentFit="contain"
            style={{ width: fitted.width, height: fitted.height }}
          />
        )}
      </Animated.View>
    </GestureDetector>
  );
}

function VideoPlayback({ uri }: { uri: string }) {
  const player = useVideoPlayer({ uri }, (instance) => {
    instance.play();
  });
  return (
    <VideoView
      player={player}
      style={styles.video}
      contentFit="contain"
      nativeControls
    />
  );
}

export function AttachmentViewer({
  api,
  agent,
  request,
  onClose,
}: {
  api: ApiClient;
  agent: string;
  request: OpenViewerRequest | null;
  onClose: () => void;
}) {
  const { width, height } = useWindowDimensions();
  const { showError } = useToast();
  const [sharing, setSharing] = useState(false);
  const attachment = request?.attachment ?? null;
  const uri = useAuthedMediaUri(
    api,
    attachment ? appChatAttachmentPath(agent, attachment.id) : null,
  );
  if (attachment === null) return null;
  const kind = attachmentKind(attachment.mime);

  const share = () => {
    setSharing(true);
    saveAttachment(expoSaveIo(api), agent, attachment)
      .catch((error: unknown) => {
        showError(error, `Couldn't share ${attachment.name}`);
      })
      .finally(() => {
        setSharing(false);
      });
  };

  return (
    <Modal
      visible
      transparent
      animationType="fade"
      onRequestClose={onClose}
      supportedOrientations={["portrait", "landscape"]}
    >
      <GestureHandlerRootView style={styles.root}>
        <View style={styles.scrim}>
          {kind === "video" ? (
            uri !== null ? (
              <VideoPlayback uri={uri} />
            ) : null
          ) : (
            <ZoomableImage
              key={attachment.id}
              uri={uri}
              attachment={attachment}
              container={{ width, height }}
              onClose={onClose}
            />
          )}
          <View style={styles.topBar}>
            <Pressable
              accessibilityLabel="Close viewer"
              accessibilityRole="button"
              hitSlop={8}
              onPress={onClose}
              style={styles.barButton}
            >
              <Ionicons name="close" size={22} color="white" />
            </Pressable>
            <Pressable
              accessibilityLabel={`Share ${attachment.name}`}
              accessibilityRole="button"
              disabled={sharing}
              hitSlop={8}
              onPress={share}
              style={[styles.barButton, sharing && styles.barButtonBusy]}
            >
              <Ionicons name="share-outline" size={21} color="white" />
            </Pressable>
          </View>
          <View pointerEvents="none" style={styles.caption}>
            <Text numberOfLines={1} style={styles.captionName}>
              {attachment.name}
            </Text>
            <Text style={styles.captionDetail}>
              {formatBytes(attachment.size)}
            </Text>
          </View>
        </View>
      </GestureHandlerRootView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  scrim: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.92)",
    alignItems: "center",
    justifyContent: "center",
  },
  mediaLayer: { alignItems: "center", justifyContent: "center" },
  video: { width: "100%", height: "70%" },
  topBar: {
    position: "absolute",
    top: 54,
    right: 16,
    left: 16,
    flexDirection: "row",
    justifyContent: "space-between",
  },
  barButton: {
    width: 38,
    height: 38,
    borderRadius: 19,
    backgroundColor: "rgba(0,0,0,0.45)",
    alignItems: "center",
    justifyContent: "center",
  },
  barButtonBusy: { opacity: 0.5 },
  caption: {
    position: "absolute",
    bottom: 40,
    right: 24,
    left: 24,
    alignItems: "center",
  },
  captionName: { color: "white", fontSize: 14, fontWeight: "600" },
  captionDetail: { color: "rgba(255,255,255,0.65)", fontSize: 12 },
});

import { Alert } from "react-native";
import {
  captureFromCamera,
  openPermissionSettings,
  pickDocuments,
  pickFromLibrary,
  type PickedAsset,
  type PickResult,
} from "@/attachments/pick";

// The attach entry: three sources behind the native menu that opens from the composer's plus
// button, each feeding the same draft pipeline. A camera permanently denied offers the Settings
// app instead of failing silently.

export const ATTACH_ACTIONS = [
  {
    id: "library",
    title: "Photo & Video Library",
    image: "photo.on.rectangle",
  },
  { id: "camera", title: "Take Photo or Video", image: "camera" },
  { id: "file", title: "File", image: "doc" },
] as const;

type AttachActionId = (typeof ATTACH_ACTIONS)[number]["id"];

const PICKERS: Record<AttachActionId, () => Promise<PickResult>> = {
  library: pickFromLibrary,
  camera: captureFromCamera,
  file: pickDocuments,
};

async function deliver(
  result: PickResult,
  onAssets: (assets: PickedAsset[]) => void,
): Promise<void> {
  if (result.status === "picked") {
    onAssets(result.assets);
    return;
  }
  if (result.status === "blocked") {
    Alert.alert(
      "Camera access needed",
      "Turn on camera access for Vesta in Settings to take photos and videos.",
      [
        { text: "Not now", style: "cancel" },
        { text: "Open Settings", onPress: openPermissionSettings },
      ],
    );
  }
}

export function runAttachAction(
  id: string,
  onAssets: (assets: PickedAsset[]) => void,
): void {
  const action = ATTACH_ACTIONS.find((entry) => entry.id === id);
  if (!action) return;
  void PICKERS[action.id]().then((result) => deliver(result, onAssets));
}

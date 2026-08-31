import { ActionSheetIOS, Alert } from "react-native";
import {
  captureFromCamera,
  openPermissionSettings,
  pickDocuments,
  pickFromLibrary,
  type PickedAsset,
  type PickResult,
} from "@/attachments/pick";

// The attach entry: three sources behind one native menu (the iOS action sheet, an alert-style
// chooser on Android), each feeding the same draft pipeline. A camera permanently denied offers
// the Settings app instead of failing silently.

const OPTIONS = [
  "Photo & Video Library",
  "Take Photo or Video",
  "File",
  "Cancel",
] as const;

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

export function showAttachMenu(
  onAssets: (assets: PickedAsset[]) => void,
): void {
  const run = (pick: () => Promise<PickResult>) => {
    void pick().then((result) => deliver(result, onAssets));
  };
  if (process.env.EXPO_OS === "ios") {
    ActionSheetIOS.showActionSheetWithOptions(
      { options: [...OPTIONS], cancelButtonIndex: 3 },
      (index) => {
        if (index === 0) run(pickFromLibrary);
        else if (index === 1) run(captureFromCamera);
        else if (index === 2) run(pickDocuments);
      },
    );
    return;
  }
  // Android's Alert renders at most 3 buttons, so cancel is the outside tap, not a button.
  Alert.alert(
    "Add attachment",
    undefined,
    [
      { text: OPTIONS[0], onPress: () => run(pickFromLibrary) },
      { text: OPTIONS[1], onPress: () => run(captureFromCamera) },
      { text: OPTIONS[2], onPress: () => run(pickDocuments) },
    ],
    { cancelable: true },
  );
}

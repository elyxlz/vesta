import * as DocumentPicker from "expo-document-picker";
import * as ImagePicker from "expo-image-picker";
import { Linking } from "react-native";
import { MAX_ATTACHMENTS_PER_MESSAGE } from "@vesta/core";

// The three ways a file enters the composer: the photo/video library (a permissionless system
// picker on both platforms), the camera (permission-gated, prompt-once with an open-Settings
// path when permanently denied), and the document picker (Storage Access Framework, no
// permission). Every source normalizes to one asset shape; bytes come later via assetToBlob,
// whose Blob is the size truth (picker-reported sizes can lie for content:// uris).

export interface PickedAsset {
  uri: string;
  name: string;
  mime: string;
  width?: number;
  height?: number;
  durationSecs?: number;
}

export type PickResult =
  | { status: "picked"; assets: PickedAsset[] }
  | { status: "cancelled" }
  // The OS will not prompt again; the caller offers the Settings app instead.
  | { status: "blocked" };

const FALLBACK_MIME = "application/octet-stream";

function assetName(uri: string, name: string | null | undefined): string {
  if (name) return name;
  const last = uri.split("/").at(-1);
  return last && last.length > 0 ? last : "file";
}

function fromImagePicker(asset: ImagePicker.ImagePickerAsset): PickedAsset {
  return {
    uri: asset.uri,
    name: assetName(asset.uri, asset.fileName),
    mime: asset.mimeType ?? FALLBACK_MIME,
    ...(asset.width ? { width: asset.width } : {}),
    ...(asset.height ? { height: asset.height } : {}),
    // The picker reports milliseconds; the wire carries seconds.
    ...(asset.duration ? { durationSecs: asset.duration / 1000 } : {}),
  };
}

export async function pickFromLibrary(): Promise<PickResult> {
  const result = await ImagePicker.launchImageLibraryAsync({
    mediaTypes: ["images", "videos"],
    allowsMultipleSelection: true,
    selectionLimit: MAX_ATTACHMENTS_PER_MESSAGE,
    quality: 1,
  });
  if (result.canceled) return { status: "cancelled" };
  return { status: "picked", assets: result.assets.map(fromImagePicker) };
}

export async function captureFromCamera(): Promise<PickResult> {
  const existing = await ImagePicker.getCameraPermissionsAsync();
  if (!existing.granted) {
    if (!existing.canAskAgain) return { status: "blocked" };
    const asked = await ImagePicker.requestCameraPermissionsAsync();
    if (!asked.granted)
      return asked.canAskAgain
        ? { status: "cancelled" }
        : { status: "blocked" };
  }
  const result = await ImagePicker.launchCameraAsync({
    mediaTypes: ["images", "videos"],
    quality: 1,
  });
  if (result.canceled) return { status: "cancelled" };
  return { status: "picked", assets: result.assets.map(fromImagePicker) };
}

export async function pickDocuments(): Promise<PickResult> {
  const result = await DocumentPicker.getDocumentAsync({
    multiple: true,
    copyToCacheDirectory: true,
  });
  if (result.canceled) return { status: "cancelled" };
  return {
    status: "picked",
    assets: result.assets.map((asset) => ({
      uri: asset.uri,
      name: assetName(asset.uri, asset.name),
      mime: asset.mimeType ?? FALLBACK_MIME,
    })),
  };
}

// React Native's fetch reads file:// and content:// uris into a native-backed, sliceable Blob,
// which is exactly what the shared chunked upload engine consumes.
export async function assetToBlob(asset: PickedAsset): Promise<Blob> {
  const response = await fetch(asset.uri);
  return response.blob();
}

export function openPermissionSettings(): void {
  void Linking.openSettings();
}

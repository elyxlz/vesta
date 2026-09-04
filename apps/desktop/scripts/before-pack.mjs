// electron-builder beforePack hook: runs after production dependencies are collected and before
// the app is packed into the asar. It bundles the sandboxed preload and compiles the macOS
// CoreLocation helper. beforePack, not beforeBuild: beforeBuild governs dependency installation,
// and defining it makes electron-builder skip collecting node_modules into the asar.
import buildNative from "./build-native.mjs";
import { bundlePreload } from "./bundle-preload.mjs";

export default async function beforePack(context) {
  await bundlePreload();
  buildNative(context);
}

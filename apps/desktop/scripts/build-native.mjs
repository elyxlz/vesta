// electron-builder beforePack hook: compile the macOS CoreLocation helper
// (native/vesta-location.swift) into native/vesta-location, which electron-builder then ships
// beside the web bundle in Resources and signs with the app. macOS only; other platforms have
// no helper and skip it. The helper's embedded Info.plist stamps it with the app's identity so
// CoreLocation prompts and grants under the app, never a separate entry.
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const nativeDir = fileURLToPath(new URL("../native", import.meta.url));

export default function buildNative(context) {
  if (context.electronPlatformName !== "darwin") return;
  const archs = archNames(context.arch);
  const output = path.join(nativeDir, "vesta-location");
  const source = path.join(nativeDir, "vesta-location.swift");
  const plist = path.join(nativeDir, "vesta-location.plist");
  const slices = archs.map((arch) => {
    const slice = `${output}.${arch}`;
    execFileSync("swiftc", [
      "-O",
      "-target",
      `${arch}-apple-macosx11.0`,
      source,
      "-o",
      slice,
      "-Xlinker",
      "-sectcreate",
      "-Xlinker",
      "__TEXT",
      "-Xlinker",
      "__info_plist",
      "-Xlinker",
      plist,
    ]);
    return slice;
  });
  execFileSync("lipo", ["-create", ...slices, "-output", output]);
}

// electron-builder's Arch enum: 0 ia32, 1 x64, 2 armv7l, 3 arm64, 4 universal.
function archNames(arch) {
  if (arch === 4) return ["arm64", "x86_64"];
  if (arch === 1) return ["x86_64"];
  return ["arm64"];
}

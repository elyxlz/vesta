// electron-builder afterPack hook: fail the build if the packed app is broken, so a bad artifact
// can never ship. Two releases shipped broken past config-only checks: one dropped the whole
// node_modules tree from the asar (the app crashed with "Cannot find module 'electron-updater'"),
// one shipped an un-bundled preload that threw in the sandbox (the app rendered the web UI). This
// reads the real asar every build, in CI and locally, and throws on either failure.
import asar from "@electron/asar";
import path from "node:path";

const RELATIVE_REQUIRE = /(?:require\(|from\s*)["']\.\.?\//;

export default function verifyPack(context) {
  const asarPath =
    context.electronPlatformName === "darwin"
      ? path.join(
          context.appOutDir,
          `${context.packager.appInfo.productFilename}.app`,
          "Contents",
          "Resources",
          "app.asar",
        )
      : path.join(context.appOutDir, "resources", "app.asar");

  const files = asar.listPackage(asarPath);
  if (!files.some((file) => file.startsWith("/node_modules/electron-updater"))) {
    throw new Error(
      `packaged asar is missing production node_modules (electron-updater): ${asarPath}`,
    );
  }

  const preload = asar
    .extractFile(asarPath, path.join("dist-electron", "preload.js"))
    .toString("utf8");
  if (RELATIVE_REQUIRE.test(preload)) {
    throw new Error(
      "packaged preload is not bundled: a relative require survives and throws in the sandbox",
    );
  }
  if (!preload.includes('exposeInMainWorld("vestaNative"')) {
    throw new Error("packaged preload does not expose vestaNative");
  }
}

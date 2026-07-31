const path = require("node:path");
const { getDefaultConfig } = require("expo/metro-config");

const mobileRoot = path.resolve(__dirname, "..");
const config = getDefaultConfig(mobileRoot);
const privacyProviderFixture = path.resolve(
  __dirname,
  "harness/privacy-provider.tsx",
);
const privacyProviderConsumers = new Set([
  path.join(mobileRoot, "src/privacy/privacy-gate.tsx"),
  path.join(mobileRoot, "src/privacy/privacy-sheet.tsx"),
]);
const harnessModules = new Map([
  [
    "@/storage/recent-gateways",
    path.resolve(__dirname, "harness/recent-gateways.ts"),
  ],
  [
    "@/privacy/privacy-provider",
    privacyProviderFixture,
  ],
  [
    "@/api/auth",
    path.resolve(__dirname, "harness/auth.ts"),
  ],
  [
    "@/components/BootSplash",
    path.resolve(__dirname, "harness/boot-splash.tsx"),
  ],
  [
    "@/components/AgentOrb",
    path.resolve(__dirname, "harness/agent-orb.tsx"),
  ],
  [
    "react-native-reanimated",
    path.resolve(__dirname, "harness/reanimated.js"),
  ],
]);
const defaultResolveRequest = config.resolver.resolveRequest;

config.resolver.resolveRequest = (context, moduleName, platform) => {
  if (
    moduleName === "./privacy-provider" &&
    privacyProviderConsumers.has(context.originModulePath)
  ) {
    return { type: "sourceFile", filePath: privacyProviderFixture };
  }
  const fixture = harnessModules.get(moduleName);
  if (fixture) return { type: "sourceFile", filePath: fixture };
  return (defaultResolveRequest ?? context.resolveRequest)(
    context,
    moduleName,
    platform,
  );
};

module.exports = config;

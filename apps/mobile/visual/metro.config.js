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
const settingsRoute = path.join(mobileRoot, "app/settings.tsx");
const agentHoldsFixture = path.resolve(__dirname, "harness/agent-holds.ts");
const harnessModules = new Map([
  [
    "@/storage/recent-gateways",
    path.resolve(__dirname, "harness/recent-gateways.ts"),
  ],
  ["@/privacy/privacy-provider", privacyProviderFixture],
  ["@/api/auth", path.resolve(__dirname, "harness/auth.ts")],
  [
    "@/components/BootSplash",
    path.resolve(__dirname, "harness/boot-splash.tsx"),
  ],
  ["@/components/AgentOrb", path.resolve(__dirname, "harness/agent-orb.tsx")],
  [
    "@/components/DashboardWebView",
    path.resolve(__dirname, "harness/dashboard-web-view.tsx"),
  ],
  [
    "@/session/SessionProvider",
    path.resolve(__dirname, "harness/session-provider.tsx"),
  ],
  [
    "@/session/RosterProvider",
    path.resolve(__dirname, "harness/roster-provider.tsx"),
  ],
  [
    "@/controller/ControllerProvider",
    path.resolve(__dirname, "harness/controller-provider.tsx"),
  ],
  ["@/holds/agent-holds", agentHoldsFixture],
  [
    "@/agent/agent-log-stream",
    path.resolve(__dirname, "harness/agent-log-stream.ts"),
  ],
  [
    "@/releases/release-notes-query",
    path.resolve(__dirname, "harness/release-notes-query.ts"),
  ],
  ["react-native-reanimated", path.resolve(__dirname, "harness/reanimated.js")],
  ["expo-web-browser", path.resolve(__dirname, "harness/web-browser.ts")],
  ["@/controller/rn-socket", path.resolve(__dirname, "harness/rn-socket.ts")],
  ["expo-router/stack", path.resolve(__dirname, "harness/stack.js")],
]);
const defaultResolveRequest = config.resolver.resolveRequest;

config.resolver.resolveRequest = (context, moduleName, platform) => {
  if (
    moduleName === "./privacy-provider" &&
    privacyProviderConsumers.has(context.originModulePath)
  ) {
    return { type: "sourceFile", filePath: privacyProviderFixture };
  }
  if (
    moduleName === "@/api/endpoints" &&
    context.originModulePath === settingsRoute
  ) {
    return {
      type: "sourceFile",
      filePath: path.resolve(__dirname, "harness/settings-endpoints.ts"),
    };
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

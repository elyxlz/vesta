// Metro only watches the project root by default; @vesta/core is a file:
// dependency living outside it, so the bundler must watch and resolve it.
const { getDefaultConfig } = require("expo/metro-config")
const path = require("path")

const config = getDefaultConfig(__dirname)
config.watchFolders = [path.resolve(__dirname, "../core")]
// Imports originating in ../core cannot discover dependencies installed in
// this app's sibling node_modules directory through normal hierarchical lookup.
// EAS uses that layout when it bundles the uploaded monorepo, so tell Metro
// where the mobile app's React and React Native dependencies live.
config.resolver.nodeModulesPaths = [path.resolve(__dirname, "node_modules")]
// Expo SDK 57 enables package exports by default (resolver.unstable_enablePackageExports),
// so @vesta/core's "./react" subpath export resolves at bundle time; no override needed.
module.exports = config

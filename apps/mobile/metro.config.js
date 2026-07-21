// Metro only watches the project root by default; @vesta/core is a file:
// dependency living outside it, so the bundler must watch and resolve it.
const { getDefaultConfig } = require("expo/metro-config")
const path = require("path")

const config = getDefaultConfig(__dirname)
config.watchFolders = [path.resolve(__dirname, "../core")]
// Expo SDK 57 enables package exports by default (resolver.unstable_enablePackageExports),
// so @vesta/core's "./react" subpath export resolves at bundle time; no override needed.
module.exports = config

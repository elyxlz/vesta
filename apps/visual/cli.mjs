#!/usr/bin/env node
import { mkdir } from "node:fs/promises";
import { RUNNERS } from "./platforms.mjs";
import { storeDirectory } from "./store.mjs";
import { serveCatalog, spawnCapture } from "./gallery/server.mjs";

const DEFAULT_PORT = 4173;

function usage() {
  console.log(`Usage:
  npm run visual                       Serve the gallery and open it
  npm run visual:serve -- [--port N] [--no-open]
  npm run visual:capture -- <runner> [--gentle]

Runners: ${Object.keys(RUNNERS).join(", ")}
`);
}

function parseArguments(values) {
  const [command = "serve", ...rest] = values;
  const options = {
    command,
    port: DEFAULT_PORT,
    open: true,
    gentle: false,
    runner: "",
  };
  for (let index = 0; index < rest.length; index += 1) {
    const argument = rest[index];
    if (argument === "--help") {
      usage();
      process.exit(0);
    }
    if (argument === "--no-open") options.open = false;
    else if (argument === "--gentle") options.gentle = true;
    else if (argument === "--port") {
      const port = Number(rest[index + 1]);
      if (!Number.isInteger(port) || port < 1 || port > 65_535) {
        throw new Error(`Invalid port: ${rest[index + 1]}`);
      }
      options.port = port;
      index += 1;
    } else if (!argument.startsWith("-") && !options.runner) {
      options.runner = argument;
    } else throw new Error(`Unknown argument: ${argument}`);
  }
  if (!["serve", "capture"].includes(command)) {
    throw new Error(`Unknown command: ${command}`);
  }
  if (command === "capture" && !RUNNERS[options.runner]) {
    throw new Error(
      `capture needs a runner: ${Object.keys(RUNNERS).join(", ")}`,
    );
  }
  return options;
}

async function main() {
  const options = parseArguments(process.argv.slice(2));
  await mkdir(storeDirectory, { recursive: true });
  if (options.command === "serve") {
    await serveCatalog(options.port, options.open);
    return;
  }
  const child = spawnCapture(options.runner, options.gentle);
  console.log(
    `Capturing ${options.runner}; log: .visual/capture-${options.runner}.log`,
  );
  process.exitCode = await new Promise((resolve) =>
    child.on("exit", (exitCode) => resolve(exitCode ?? 1)),
  );
}

main().catch((error) => {
  console.error(`\nVisual QA failed: ${error.message}`);
  process.exitCode = 1;
});

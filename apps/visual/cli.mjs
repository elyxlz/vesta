#!/usr/bin/env node
import { RUNNERS } from "./platforms.mjs";
import { serveCatalog, spawnCapture } from "./gallery/server.mjs";
import { referenceIndex } from "./references.mjs";
import { captureSelection } from "./selection.mjs";
import {
  comparePage,
  comparisonTargets,
  seedBaselines,
} from "./comparison.mjs";

const DEFAULT_PORT = 4173;

function usage() {
  console.log(`Usage:
  npm run visual                       Serve the gallery and open it
  npm run visual:serve -- [--port N] [--no-open]
  npm run visual:capture -- <runner> [--page settings] [--suite pages|states|all] [--gentle] [--all]
  node visual/cli.mjs refs [--page settings] [--platform web]  JSON references with local image paths
  node visual/cli.mjs compare [platform]  Compare saved captures; exit 1 if review is needed
  node visual/cli.mjs baseline [platform] Seed missing baselines from saved captures

Runners: ${Object.keys(RUNNERS).join(", ")}
Default suite: all (pages and detailed states). --all forces recapture.
`);
}

function parseArguments(values) {
  const [command, ...rest] =
    values[0] === undefined || values[0].startsWith("-")
      ? ["serve", ...values]
      : values;
  const options = {
    command,
    port: DEFAULT_PORT,
    open: true,
    gentle: false,
    all: false,
    runner: "",
    page: "",
    suite: "",
    platform: "",
  };
  for (let index = 0; index < rest.length; index += 1) {
    const argument = rest[index];
    if (argument === "--help") {
      usage();
      process.exit(0);
    }
    if (argument === "--no-open") options.open = false;
    else if (argument === "--gentle") options.gentle = true;
    else if (argument === "--all") options.all = true;
    else if (["--page", "--suite", "--platform"].includes(argument)) {
      const value = rest[++index];
      if (!value || value.startsWith("-"))
        throw new Error(`${argument} needs a value`);
      options[argument.slice(2)] = value;
    } else if (argument === "--port") {
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
  if (!["serve", "capture", "compare", "baseline", "refs"].includes(command)) {
    throw new Error(`Unknown command: ${command}`);
  }
  if (command === "capture" && !Object.hasOwn(RUNNERS, options.runner)) {
    throw new Error(
      `capture needs a runner: ${Object.keys(RUNNERS).join(", ")}`,
    );
  }
  return options;
}

async function main() {
  const options = parseArguments(process.argv.slice(2));
  const selection = captureSelection({
    VISUAL_SUITE: options.suite,
    VISUAL_PAGE: options.page,
  });
  if (options.command === "refs") {
    console.log(
      JSON.stringify(await referenceIndex(selection, options.platform)),
    );
    return;
  }
  if (options.command === "serve") {
    await serveCatalog(options.port, options.open);
    return;
  }
  if (options.command === "baseline" || options.command === "compare") {
    const targets = await comparisonTargets(
      options.platform || options.runner,
      selection,
    );
    if (!targets.length) throw new Error("No screenshots match the selection");
    if (options.command === "baseline") {
      console.log(`Seeded ${await seedBaselines(targets)} missing baselines.`);
      return;
    }
    const results = [];
    for (const { platform, name } of targets)
      results.push(await comparePage(platform, name));
    console.log(JSON.stringify({ results }));
    process.exitCode = results.some((result) => result.status !== "same")
      ? 1
      : 0;
    return;
  }
  const child = spawnCapture(
    options.runner,
    options.gentle,
    options.all,
    selection,
  );
  console.log(
    `Capturing ${options.runner}; log: .visual/capture-${options.runner}.log`,
  );
  process.exitCode = await new Promise((resolve, reject) => {
    child.on("error", reject);
    child.on("exit", (exitCode) => resolve(exitCode ?? 1));
  });
}

main().catch((error) => {
  console.error(`\nVisual QA failed: ${error.message}`);
  process.exitCode = 1;
});

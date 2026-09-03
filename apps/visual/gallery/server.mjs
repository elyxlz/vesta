import { execFile, spawn } from "node:child_process";
import { closeSync, mkdirSync, openSync } from "node:fs";
import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { RUNNERS, appsRoot } from "../platforms.mjs";
import { currentRunStatus } from "../run-status.mjs";
import { shotEntries, storeDirectory } from "../store.mjs";
import { galleryHtml } from "./page.mjs";
import { composeGallery } from "./view.mjs";

const galleryDirectory = path.dirname(fileURLToPath(import.meta.url));
const galleryAssets = ["styles.css", "client.js"];
const mimeTypes = new Map([
  [".css", "text/css; charset=utf-8"],
  [".html", "text/html; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".png", "image/png"],
  [".svg", "image/svg+xml"],
]);

export function safeStaticPath(pathname, baseDirectory) {
  const relative =
    pathname === "/" ? "index.html" : pathname.replace(/^\/+/, "");
  const target = path.resolve(baseDirectory, relative);
  const relation = path.relative(baseDirectory, target);
  if (relation.startsWith("..") || path.isAbsolute(relation)) return null;
  return target;
}

// RUNNERS is a plain object, so a bare `RUNNERS[name]` lookup would accept
// prototype keys ("constructor") from the URL.
export function isRunner(name) {
  return Object.hasOwn(RUNNERS, name);
}

// `all` retakes every shot; otherwise each runner skips the shots whose
// inputs have not changed since they were taken. The flag travels as an env
// var, the one carrier both the Playwright and the Maestro runners read.
export function captureCommand(runner, gentle, all = false) {
  if (!isRunner(runner)) throw new Error(`Unknown runner: ${runner}`);
  const definition = RUNNERS[runner];
  return {
    command: "npm",
    argumentsList: [
      "-w",
      definition.workspace,
      "run",
      definition.script,
      "--",
      ...definition.args,
      ...(gentle ? definition.gentleArgs : []),
    ],
    cwd: appsRoot,
    env: all ? { ...process.env, VISUAL_CAPTURE_ALL: "1" } : process.env,
  };
}

// A runner's plan: the units (flows or scenarios) a capture would retake,
// answered on stdout as the last line of JSON by the runner's own plan command,
// so the gallery and the capture decide freshness with one code path each.
const PLAN_TIMEOUT_MS = 120_000;

export function planCommand(runner, all = false) {
  if (!isRunner(runner)) throw new Error(`Unknown runner: ${runner}`);
  const { plan } = RUNNERS[runner];
  return {
    command: "node",
    argumentsList: [plan.script, ...plan.args],
    cwd: path.join(appsRoot, plan.directory),
    env: all ? { ...process.env, VISUAL_CAPTURE_ALL: "1" } : process.env,
  };
}

export function parsePlanOutput(stdout) {
  const lines = stdout.trim().split("\n").filter(Boolean);
  const last = lines[lines.length - 1];
  if (!last) throw new Error("the plan command printed nothing");
  const plan = JSON.parse(last);
  if (!Array.isArray(plan.units)) throw new Error("the plan carries no units");
  return plan;
}

function runPlan(runner, all) {
  const command = planCommand(runner, all);
  return new Promise((resolve) => {
    execFile(
      command.command,
      command.argumentsList,
      {
        cwd: command.cwd,
        env: command.env,
        timeout: PLAN_TIMEOUT_MS,
        maxBuffer: 16 * 1024 * 1024,
      },
      (error, stdout, stderr) => {
        try {
          if (error && !stdout.trim())
            throw new Error(stderr.trim() || error.message);
          resolve(parsePlanOutput(stdout));
        } catch (failure) {
          resolve({ runner, units: [], error: failure.message });
        }
      },
    );
  });
}

export async function collectPlans(all) {
  const entries = await Promise.all(
    Object.keys(RUNNERS).map(async (runner) => [
      runner,
      await runPlan(runner, all),
    ]),
  );
  return Object.fromEntries(entries);
}

// A capture is its own detached child, logged to the store, so the gallery keeps
// serving while it runs and a crash cannot take the server down.
export function spawnCapture(runner, gentle, all) {
  const plan = captureCommand(runner, gentle, all);
  mkdirSync(storeDirectory, { recursive: true });
  const logFile = openSync(
    path.join(storeDirectory, `capture-${runner}.log`),
    "w",
  );
  const child = spawn(plan.command, plan.argumentsList, {
    cwd: plan.cwd,
    env: plan.env,
    stdio: ["ignore", logFile, logFile],
  });
  closeSync(logFile);
  return child;
}

async function sendFile(response, target) {
  try {
    const info = await stat(target);
    if (!info.isFile()) throw new Error("Not a file");
    const content = await readFile(target);
    response.writeHead(200, {
      "Content-Type":
        mimeTypes.get(path.extname(target)) ?? "application/octet-stream",
      "Cache-Control": "no-store",
    });
    response.end(content);
  } catch {
    response.writeHead(404).end("Not found");
  }
}

function sendJson(response, status, payload) {
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
  });
  response.end(`${JSON.stringify(payload)}\n`);
}

function createCaptureRuns() {
  const idleRun = {
    running: false,
    startedAt: null,
    finishedAt: null,
    exitCode: null,
  };
  const runs = Object.fromEntries(
    Object.keys(RUNNERS).map((runner) => [runner, { ...idleRun }]),
  );
  const start = (runner, gentle, all) => {
    if (runs[runner].running) return false;
    const child = spawnCapture(runner, gentle, all);
    runs[runner] = {
      running: true,
      startedAt: new Date().toISOString(),
      finishedAt: null,
      exitCode: null,
    };
    const finish = (exitCode) => {
      runs[runner] = {
        ...runs[runner],
        running: false,
        finishedAt: new Date().toISOString(),
        exitCode,
      };
    };
    child.on("error", () => finish(1));
    child.on("exit", (code) => finish(code ?? 1));
    return true;
  };
  return { runs, start };
}

async function routeRequest(request, response, captureRuns) {
  const url = new URL(request.url ?? "/", "http://localhost");
  const pathname = decodeURIComponent(url.pathname);
  const [, head, second, ...rest] = pathname.split("/");
  if (pathname === "/status.json") {
    sendJson(response, 200, await currentRunStatus());
    return;
  }
  if (pathname === "/plan.json") {
    const all = url.searchParams.get("all") === "1";
    sendJson(response, 200, { plans: await collectPlans(all) });
    return;
  }
  if (pathname === "/shots.json") {
    sendJson(response, 200, {
      ...(await shotEntries()),
      runs: captureRuns.runs,
    });
    return;
  }
  if (head === "capture" && isRunner(second)) {
    if (request.method !== "POST") {
      response.writeHead(405).end("POST required");
      return;
    }
    const gentle = url.searchParams.get("gentle") !== "0";
    const all = url.searchParams.get("all") === "1";
    const started = captureRuns.start(second, gentle, all);
    sendJson(response, started ? 202 : 409, {
      started,
      run: captureRuns.runs[second],
    });
    return;
  }
  if (pathname === "/" || pathname === "/index.html") {
    try {
      const html = galleryHtml(await composeGallery());
      response.writeHead(200, {
        "Content-Type": "text/html; charset=utf-8",
        "Cache-Control": "no-store",
      });
      response.end(html);
    } catch (error) {
      response
        .writeHead(500)
        .end(`Could not compose the gallery: ${error.message}`);
    }
    return;
  }
  if (
    head === "gallery" &&
    galleryAssets.includes(second) &&
    rest.length === 0
  ) {
    await sendFile(response, path.join(galleryDirectory, second));
    return;
  }
  const baseDirectory =
    head === "reports" && isRunner(second)
      ? RUNNERS[second].reportDirectory
      : storeDirectory;
  const relative =
    baseDirectory === storeDirectory ? pathname : `/${rest.join("/")}`;
  const target = safeStaticPath(relative, baseDirectory);
  if (!target) {
    response.writeHead(403).end("Forbidden");
    return;
  }
  await sendFile(response, target);
}

// A throw inside the async router (a malformed %-escape, a runner spawn that
// fails) answers 500 instead of surfacing as an unhandled rejection that would
// take the whole gallery down.
export function handleRequest(request, response, captureRuns) {
  return routeRequest(request, response, captureRuns).catch((error) => {
    if (!response.headersSent) response.writeHead(500);
    response.end(`Gallery request failed: ${error.message}`);
  });
}

export async function serveCatalog(port, shouldOpen) {
  const captureRuns = createCaptureRuns();
  const server = createServer((request, response) => {
    void handleRequest(request, response, captureRuns);
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, "127.0.0.1", resolve);
  });
  const address = `http://127.0.0.1:${port}`;
  console.log(`\nVesta Apps QA: ${address}`);
  if (shouldOpen) {
    spawn(process.platform === "darwin" ? "open" : "xdg-open", [address], {
      stdio: "ignore",
    }).on("error", () => {});
  }
  await new Promise((resolve) => {
    const stop = () => server.close(resolve);
    process.once("SIGINT", stop);
    process.once("SIGTERM", stop);
  });
}

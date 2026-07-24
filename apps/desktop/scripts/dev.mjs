// Dev harness: vite dev server (http, port 1420) + electron pointed at it.
import { spawn } from "node:child_process";
import net from "node:net";
import { fileURLToPath } from "node:url";

const appsDir = fileURLToPath(new URL("../..", import.meta.url));
const desktopDir = fileURLToPath(new URL("..", import.meta.url));

// shell:true so `npm`/`npx` resolve to their .cmd shims on Windows.
const vite = spawn("npm", ["-w", "@vesta/web", "run", "dev"], {
  cwd: appsDir,
  env: { ...process.env, VESTA_DESKTOP_DEV: "1", HTTPS: "false" },
  stdio: "inherit",
  shell: true,
});

async function waitForPort(port, host, tries = 100) {
  for (let i = 0; i < tries; i++) {
    const ok = await new Promise((resolve) => {
      const socket = net.connect(port, host, () => {
        socket.destroy();
        resolve(true);
      });
      socket.on("error", () => resolve(false));
    });
    if (ok) return;
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(`vite dev server never came up on ${host}:${port}`);
}

await waitForPort(1420, "127.0.0.1");
const electron = spawn("npx", ["electron", "."], {
  cwd: desktopDir,
  env: { ...process.env, VESTA_DESKTOP_DEV: "1" },
  stdio: "inherit",
  shell: true,
});

const stop = () => {
  electron.kill();
  vite.kill();
};
electron.on("exit", stop);
process.on("SIGINT", stop);
process.on("SIGTERM", stop);

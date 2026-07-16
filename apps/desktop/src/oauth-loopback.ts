import http from "node:http";
import type { AddressInfo } from "node:net";

const servers = new Map<number, http.Server>();

const CALLBACK_PAGE =
  "<!doctype html><meta charset=utf-8><title>Vesta</title>" +
  "<body style='font-family:system-ui;padding:2rem'>Signed in. You can close this tab and return to Vesta.</body>";

/** Loopback redirect target for the native PKCE login (see apps/web/src/lib/pkce.ts). */
export function startLoopback(onUrl: (url: string) => void): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = http.createServer((req, res) => {
      res.writeHead(200, { "Content-Type": "text/html" });
      res.end(CALLBACK_PAGE);
      const { port } = server.address() as AddressInfo;
      onUrl(`http://127.0.0.1:${port}${req.url ?? "/"}`);
    });
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address() as AddressInfo;
      servers.set(port, server);
      resolve(port);
    });
  });
}

export function cancelLoopback(port: number): void {
  servers.get(port)?.close();
  servers.delete(port);
}

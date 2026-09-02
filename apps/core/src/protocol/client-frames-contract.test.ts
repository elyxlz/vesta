import { readFileSync, writeFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { clientContextFrame, encodeFrame, reauthFrame } from "./frames";

// The client-to-gateway half of the wire contract. This encoder writes the fixture (with
// REGEN_API_FIXTURES=1) and vestad's client_frames_from_the_typescript_encoder_parse test parses it
// with the production types, so a renamed field on either side fails CI. Every optional field is
// populated so the whole shape is pinned.
const FIXTURE = new URL("../../fixtures/client-frames.json", import.meta.url);

function fixtureContent(): string {
  const frames = {
    client_context: JSON.parse(
      encodeFrame(
        clientContextFrame({
          focused: true,
          client: "mobile",
          resync: false,
          viewing: "scout",
          device: { id: "device-1", descriptor: "Vesta on iPhone" },
          context: {
            timezone: "Europe/London",
            position: {
              latitude: 51.5074,
              longitude: -0.1278,
              accuracyM: 50,
              place: {
                city: "London",
                region: "England",
                country: "United Kingdom",
              },
            },
          },
        }),
      ),
    ) as unknown,
    reauth: JSON.parse(encodeFrame(reauthFrame("tok"))) as unknown,
  };
  return `${JSON.stringify(frames, null, 2)}\n`;
}

describe("client frame fixtures (parsed by vestad)", () => {
  it("match the committed fixture, regenerated with REGEN_API_FIXTURES=1", () => {
    const content = fixtureContent();
    if (process.env.REGEN_API_FIXTURES !== undefined) {
      writeFileSync(FIXTURE, content);
    }
    expect(readFileSync(FIXTURE, "utf8")).toBe(content);
  });
});

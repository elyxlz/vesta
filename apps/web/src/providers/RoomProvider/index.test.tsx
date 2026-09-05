import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";
import type { Room } from "@vesta/core";
import {
  GatewayContext,
  disconnectedValue,
  type GatewayContextValue,
} from "@/providers/GatewayProvider/context";
import { fakeAgentRow } from "@/test/fake-controller";
import { RoomProvider } from "./index";
import { useRoom } from "./context";

vi.mock("react-router-dom", () => ({
  Navigate: ({ to }: { to: string }) => <div data-testid="redirect">{to}</div>,
}));

const ROOMS: Room[] = [
  { id: "dm:ada", name: null, agents: ["ada"], createdAt: 1, lastMessageAt: 2 },
  {
    id: "peer-1",
    name: null,
    agents: ["ada", "nova"],
    createdAt: 1,
    lastMessageAt: null,
  },
  {
    id: "grp-1",
    name: "trip",
    agents: ["ada", "nova", "sol"],
    createdAt: 1,
    lastMessageAt: null,
  },
];

function Probe() {
  const { kind, label, agents, directAgent } = useRoom();
  return (
    <div data-testid="room">
      {[kind, label, agents.join("+"), directAgent?.name ?? "none"].join(" | ")}
    </div>
  );
}

function mount(
  roomId: string,
  gateway: Partial<GatewayContextValue> = {},
  fallback?: Room,
) {
  return render(
    <GatewayContext.Provider
      value={{
        ...disconnectedValue,
        agentsFetched: true,
        agents: [fakeAgentRow("ada"), fakeAgentRow("nova")],
        rooms: ROOMS,
        ...gateway,
      }}
    >
      <RoomProvider roomId={roomId} fallback={fallback}>
        <Probe />
      </RoomProvider>
    </GatewayContext.Provider>,
  );
}

afterEach(() => {
  cleanup();
});

describe("RoomProvider", () => {
  it.each([
    { roomId: "dm:ada", expected: "direct | ada | ada | ada" },
    { roomId: "peer-1", expected: "peer | ada & nova | ada+nova | none" },
    { roomId: "grp-1", expected: "group | trip | ada+nova+sol | none" },
  ])("resolves $roomId off the tree", ({ roomId, expected }) => {
    expect(mount(roomId).getByTestId("room").textContent).toBe(expected);
  });

  // A conversation that is gone (deleted elsewhere, or a stale link) sends the user home, but only
  // once the tree has actually loaded: an unsynced replica knows no rooms at all.
  it("redirects home when the loaded tree does not carry the room", () => {
    expect(mount("grp-gone").getByTestId("redirect").textContent).toBe("/");
  });

  it("renders nothing while the tree is still unknown", () => {
    const { queryByTestId } = mount("grp-gone", {
      agentsFetched: false,
      rooms: [],
    });
    expect(queryByTestId("redirect")).toBeNull();
    expect(queryByTestId("room")).toBeNull();
  });

  // A just-built agent has a page before the node mints its direct room; the caller hands the room
  // that page chats in, so the screen is reachable instead of bouncing home.
  it("serves the fallback room the tree does not carry yet", () => {
    const { queryByTestId, getByTestId } = mount(
      "dm:sol",
      { rooms: [] },
      {
        id: "dm:sol",
        name: null,
        agents: ["sol"],
        createdAt: 0,
        lastMessageAt: null,
      },
    );
    expect(queryByTestId("redirect")).toBeNull();
    expect(getByTestId("room").textContent).toBe("direct | sol | sol | none");
  });

  it("prefers the tree's own room over the fallback", () => {
    expect(
      mount(
        "dm:ada",
        {},
        {
          id: "dm:ada",
          name: null,
          agents: ["ada"],
          createdAt: 0,
          lastMessageAt: null,
        },
      ).getByTestId("room").textContent,
    ).toBe("direct | ada | ada | ada");
  });
});

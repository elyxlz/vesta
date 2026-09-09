import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { Room } from "@vesta/core";
import {
  GatewayContext,
  disconnectedValue,
  type GatewayContextValue,
} from "@/providers/GatewayProvider/context";
import { useDialogs } from "@/stores/use-dialogs";
import { fakeAgentRow } from "@/test/fake-controller";
import { ChatsIndex, ChatsLayout, ChatsRoom } from ".";

vi.mock("@/components/Navbar", () => ({ Navbar: () => null }));
vi.mock("@/components/StatusPill", () => ({ StatusPill: () => null }));
vi.mock("@/components/NewRoomDialog", () => ({ NewRoomDialog: () => null }));
vi.mock("@/components/Orb", () => ({ Orb: () => null }));
vi.mock("@/components/RoomPane", () => ({
  RoomPane: ({ roomId }: { roomId: string }) => <p>pane {roomId}</p>,
}));

const mobile = vi.hoisted(() => ({ value: false }));
vi.mock("@/hooks/use-mobile", () => ({ useIsMobile: () => mobile.value }));

const rooms: Room[] = [
  {
    id: "dm:luna",
    name: null,
    agents: ["luna"],
    createdAt: 1,
    lastMessageAt: 1_755_600_000,
  },
  {
    id: "grp-trip",
    name: "lisbon trip",
    agents: ["luna", "atlas"],
    createdAt: 1,
    lastMessageAt: 1_755_500_000,
  },
  {
    id: "peer-1",
    name: null,
    agents: ["atlas", "iris"],
    createdAt: 1,
    lastMessageAt: null,
  },
];

function renderAt(path: string) {
  const value: GatewayContextValue = {
    ...disconnectedValue,
    agentsFetched: true,
    agents: [fakeAgentRow("luna"), fakeAgentRow("atlas"), fakeAgentRow("iris")],
    rooms,
  };
  return render(
    <GatewayContext.Provider value={value}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="chats" element={<ChatsLayout />}>
            <Route index element={<ChatsIndex />} />
            <Route path=":roomId" element={<ChatsRoom />} />
          </Route>
          <Route path="chat/:roomId" element={<p>full page</p>} />
          <Route path="agent/:name/chat" element={<p>agent page</p>} />
        </Routes>
      </MemoryRouter>
    </GatewayContext.Provider>,
  );
}

afterEach(() => {
  cleanup();
  mobile.value = false;
  useDialogs.getState().setOpen("newRoom", false);
});

describe("ChatsLayout", () => {
  it("lists every room in order with its label and members", () => {
    renderAt("/chats");
    const links = screen.getAllByRole("link");
    expect(links.map((link) => link.getAttribute("aria-label"))).toEqual([
      "open luna chat",
      "open lisbon trip chat",
      "open atlas & iris chat",
    ]);
    expect(screen.getByText("luna, atlas")).toBeTruthy();
    expect(screen.getByText("atlas, iris")).toBeTruthy();
  });

  it("links a row to its selection inside the inbox at wide width", () => {
    renderAt("/chats");
    expect(
      screen
        .getByRole("link", { name: "open lisbon trip chat" })
        .getAttribute("href"),
    ).toBe("/chats/grp-trip");
    expect(screen.getByText("pick a conversation")).toBeTruthy();
  });

  it("opens the selected room beside the list", () => {
    renderAt("/chats/grp-trip");
    expect(screen.getByText("pane grp-trip")).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: "open lisbon trip chat" })
        .getAttribute("aria-current"),
    ).toBe("page");
  });

  it("opens the new group dialog from the header", () => {
    renderAt("/chats");
    fireEvent.click(screen.getByRole("button", { name: "new group" }));
    expect(useDialogs.getState().open.newRoom).toBe(true);
  });

  it("links a row to the full page at narrow width", () => {
    mobile.value = true;
    renderAt("/chats");
    expect(
      screen.getByRole("link", { name: "open luna chat" }).getAttribute("href"),
    ).toBe("/agent/luna/chat");
    expect(
      screen
        .getByRole("link", { name: "open lisbon trip chat" })
        .getAttribute("href"),
    ).toBe("/chat/grp-trip");
  });

  it("redirects a selected room to its full page at narrow width", () => {
    mobile.value = true;
    renderAt("/chats/grp-trip");
    expect(screen.getByText("full page")).toBeTruthy();
  });
});

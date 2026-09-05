import { describe, expect, it, vi } from "vitest";

import type { HttpClient } from "../transport/http";
import {
  fetchRoomHistory,
  roomHistoryPath,
  roomMessagesPath,
  roomSocketPath,
  roomsPath,
} from "./rooms";

describe("room paths", () => {
  it("addresses the room list, a room's history, its intake, and its socket", () => {
    expect(roomsPath()).toBe("/rooms");
    expect(roomHistoryPath("dm:scout")).toBe("/rooms/dm%3Ascout/history");
    expect(roomHistoryPath("dm:scout", 42)).toBe(
      "/rooms/dm%3Ascout/history?cursor=42",
    );
    expect(roomMessagesPath("dm:scout")).toBe("/rooms/dm%3Ascout/messages");
    expect(roomSocketPath("dm:scout")).toBe("/rooms/ws?room=dm%3Ascout");
  });
});

describe("fetchRoomHistory", () => {
  it("parses the page at the boundary and drops an event it cannot classify", async () => {
    const json = vi.fn().mockResolvedValue({
      events: [
        { type: "chat", id: 2, room: "dm:scout", sender: "scout", text: "hi" },
        { type: "chat", id: 3 },
      ],
      cursor: 1,
    });
    const http: HttpClient = { request: vi.fn(), json };
    const page = await fetchRoomHistory(http, "dm:scout", 7);

    expect(json).toHaveBeenCalledWith("/rooms/dm%3Ascout/history?cursor=7");
    expect(page.cursor).toBe(1);
    expect(page.events).toEqual([
      { type: "chat", id: 2, room: "dm:scout", sender: "scout", text: "hi" },
    ]);
  });
});

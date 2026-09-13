import { describe, expect, it, vi } from "vitest";

import type { HttpClient } from "../transport/http";
import {
  createRoom,
  fetchRoomHistory,
  roomAttachmentPath,
  roomAttachmentsPath,
  roomHistoryPath,
  roomMessagesPath,
  roomsPath,
  roomsSocketPath,
} from "./rooms";

describe("room paths", () => {
  it("addresses the room list, a room's history, and its intake, escaping the id", () => {
    expect(roomsPath()).toBe("/rooms");
    expect(roomHistoryPath("dm:scout")).toBe("/rooms/dm%3Ascout/history");
    expect(roomHistoryPath("dm:scout", 42)).toBe(
      "/rooms/dm%3Ascout/history?cursor=42",
    );
    expect(roomMessagesPath("dm:scout")).toBe("/rooms/dm%3Ascout/messages");
  });

  it("addresses the upload surface and one blob, leaving both query-free", () => {
    expect(roomAttachmentsPath()).toBe("/rooms/attachments");
    expect(roomAttachmentPath("a1b2c3")).toBe("/rooms/attachments/a1b2c3");
    expect(roomAttachmentPath("a1b2/c3")).toBe("/rooms/attachments/a1b2%2Fc3");
  });

  it("leaves the socket path query-free, since the session URL builder appends its own", () => {
    expect(roomsSocketPath()).toBe("/rooms/ws");
  });
});

describe("createRoom", () => {
  it("posts the name and the members, and answers the opened room", async () => {
    const room = {
      id: "grp-1",
      name: "Ops",
      agents: ["ada", "ben"],
      createdAt: 1_700_000_000,
      lastMessageAt: null,
    };
    const json = vi.fn().mockResolvedValue({ room });
    const http: HttpClient = { request: vi.fn(), json };

    const opened = await createRoom(http, "Ops", ["ada", "ben"]);

    const call = json.mock.calls[0];
    if (!call) throw new Error("no POST");
    expect(call[0]).toBe("/rooms");
    const init = call[1] as { method: string; body: string };
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({
      name: "Ops",
      agents: ["ada", "ben"],
    });
    expect(opened.room).toEqual(room);
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

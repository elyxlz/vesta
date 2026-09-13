import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  waitFor,
} from "@testing-library/react";

const navigate = vi.fn<(to: string) => Promise<void>>();
vi.mock("react-router-dom", () => ({
  useNavigate: () => navigate,
}));

vi.mock("@/api/client", () => ({
  httpClient: { json: vi.fn(), request: vi.fn() },
}));

import { httpClient } from "@/api/client";
import { ControllerContext } from "@/providers/ControllerProvider/context";
import {
  GatewayContext,
  disconnectedValue,
} from "@/providers/GatewayProvider/context";
import { useDialogs } from "@/stores/use-dialogs";
import { fakeAgentRow, fakeController, fakeTree } from "@/test/fake-controller";
import { NewRoomDialog } from "./index";

const OPENED = {
  room: {
    id: "grp-1",
    name: "trip",
    agents: ["ada"],
    createdAt: 1,
    lastMessageAt: null,
  },
};

const json = vi.mocked(httpClient.json);

function mount() {
  const fake = fakeController(fakeTree());
  const view = render(
    <ControllerContext.Provider value={fake.controller}>
      <GatewayContext.Provider
        value={{
          ...disconnectedValue,
          agentsFetched: true,
          agents: [fakeAgentRow("ada")],
        }}
      >
        <NewRoomDialog />
      </GatewayContext.Provider>
    </ControllerContext.Provider>,
  );
  return { ...view, fake };
}

beforeEach(() => {
  navigate.mockReset();
  navigate.mockResolvedValue(undefined);
  json.mockReset();
  json.mockResolvedValue(OPENED);
  useDialogs.getState().setOpen("newRoom", true);
});

afterEach(() => {
  cleanup();
  useDialogs.getState().setOpen("newRoom", false);
});

// The node answers the create before /sync carries the room, and the room route resolves off the
// tree: opening on the ack alone would land on a route that redirects home.
describe("NewRoomDialog", () => {
  it("opens the room only once the rooms delta carries it", async () => {
    const { getByLabelText, getByRole, getByText, fake } = mount();

    fireEvent.change(getByLabelText("group name"), {
      target: { value: "trip" },
    });
    fireEvent.click(getByRole("checkbox"));
    fireEvent.click(getByText("create"));

    await waitFor(() => {
      expect(json).toHaveBeenCalledWith("/rooms", expect.anything());
    });
    expect(navigate).not.toHaveBeenCalled();

    fake.emit({ type: "rooms", rooms: [OPENED.room] });

    await waitFor(() => {
      expect(navigate).toHaveBeenCalledWith("/chats/grp-1");
    });
  });

  // Closing the dialog during the settle window is the user leaving: the wait it left behind must
  // not steer the app into the room once the delta lands.
  it("opens nothing when the dialog closes while the create settles", async () => {
    const { getByLabelText, getByRole, getByText, fake } = mount();

    fireEvent.change(getByLabelText("group name"), {
      target: { value: "trip" },
    });
    fireEvent.click(getByRole("checkbox"));
    fireEvent.click(getByText("create"));

    await waitFor(() => {
      expect(json).toHaveBeenCalledWith("/rooms", expect.anything());
    });
    fireEvent.click(getByText("cancel"));

    await act(async () => {
      fake.emit({ type: "rooms", rooms: [OPENED.room] });
      await Promise.resolve();
    });

    expect(navigate).not.toHaveBeenCalled();
  });
});

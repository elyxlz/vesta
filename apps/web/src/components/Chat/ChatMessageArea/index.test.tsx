import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { createRef } from "react";
import { ChatMessageArea, type ChatScrollHandle } from "./index";

afterEach(cleanup);

function mount(direct: boolean) {
  return render(
    <ChatMessageArea
      scrollRef={createRef<ChatScrollHandle>()}
      loadMore={vi.fn()}
      hasMore={false}
      loadingMore={false}
      navbarHeight={0}
      chatMessages={[]}
      connected
      historyLoaded
      label="lisbon trip"
      direct={direct}
      showSenders={!direct}
      notAuthenticated={false}
      isTyping={false}
      isMobile={false}
      scrollLocked={false}
      onAtBottomChange={vi.fn()}
    />,
  );
}

// Only a direct room speaks for the one agent behind it. A peer or group room has no single agent
// setting anything up, so its empty conversation stays neutral.
describe("ChatMessageArea empty state", () => {
  it("names the agent in a direct room", () => {
    const { getByText } = mount(true);
    expect(getByText("lisbon trip is setting things up")).toBeTruthy();
  });

  it("stays neutral in a group room", () => {
    const { getByText, queryByText } = mount(false);
    expect(getByText("nothing here yet")).toBeTruthy();
    expect(queryByText("lisbon trip is setting things up")).toBeNull();
  });
});

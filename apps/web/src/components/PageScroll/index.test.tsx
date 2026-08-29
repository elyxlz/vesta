import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { PageScroll } from "./index";

describe("PageScroll", () => {
  afterEach(cleanup);

  it("renders its children", () => {
    render(
      <PageScroll>
        <p>hello</p>
      </PageScroll>,
    );
    expect(screen.getByText("hello")).toBeTruthy();
  });
});

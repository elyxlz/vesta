import { describe, expect, it } from "vitest";
import { stepChrome } from "./chrome";

describe("stepChrome", () => {
  it("gives the name step a heading and a continue action gated on validity", () => {
    const chrome = stepChrome({
      step: "name",
      nameValid: false,
      vibeReady: false,
      failed: false,
    });
    expect(chrome.heading?.title).toBe("new agent");
    expect(chrome.action).toEqual({
      kind: "submit-name",
      label: "continue",
      disabled: true,
    });
    expect(chrome.widthClass).toBe("w-[260px]");
  });

  it("enables the name action once the name is valid", () => {
    const chrome = stepChrome({
      step: "name",
      nameValid: true,
      vibeReady: false,
      failed: false,
    });
    expect(chrome.action?.disabled).toBe(false);
  });

  it("hides the heading and the action during the provider step", () => {
    const chrome = stepChrome({
      step: "provider",
      nameValid: true,
      vibeReady: false,
      failed: false,
    });
    expect(chrome.heading).toBeNull();
    expect(chrome.action).toBeNull();
  });

  it("gates the vibe continue on readiness and widens the step", () => {
    const chrome = stepChrome({
      step: "personality",
      nameValid: true,
      vibeReady: false,
      failed: false,
    });
    expect(chrome.heading?.title).toBe("pick a vibe");
    expect(chrome.action).toEqual({
      kind: "submit-vibe",
      label: "continue",
      disabled: true,
    });
    expect(chrome.widthClass).toBe("w-[672px]");
  });

  it("shows no action while creating and a retry after a failure", () => {
    const creating = stepChrome({
      step: "creating",
      nameValid: true,
      vibeReady: true,
      failed: false,
    });
    expect(creating.heading).toBeNull();
    expect(creating.action).toBeNull();
    const failed = stepChrome({
      step: "creating",
      nameValid: true,
      vibeReady: true,
      failed: true,
    });
    expect(failed.action).toEqual({
      kind: "retry",
      label: "try again",
      disabled: false,
    });
  });

  it("offers say hi on done", () => {
    const chrome = stepChrome({
      step: "done",
      nameValid: true,
      vibeReady: true,
      failed: false,
    });
    expect(chrome.action).toEqual({
      kind: "open-chat",
      label: "say hi",
      disabled: false,
    });
  });
});

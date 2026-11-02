import { describe, expect, it } from "vitest";
import { stripVoiceTags } from "./voice-tags";

describe("stripVoiceTags", () => {
  it.each<[string, string, string]>([
    ["drops a leading direction", "[laughs] No way.", "No way."],
    [
      "drops a mid-sentence direction",
      "Fine. [sighs] Friday then.",
      "Fine. Friday then.",
    ],
    ["drops a multi-word direction", "[calm, matter-of-fact] Done.", "Done."],
    [
      "keeps markdown link labels",
      "See [the docs](https://x.io).",
      "See [the docs](https://x.io).",
    ],
    [
      "keeps task checkboxes",
      "- [ ] todo\n- [x] done",
      "- [ ] todo\n- [x] done",
    ],
    ["keeps numeric citations", "As shown [1].", "As shown [1]."],
    [
      "keeps capitalised brackets",
      "Status: [WIP] draft",
      "Status: [WIP] draft",
    ],
    ["keeps line structure", "[excited] One\n\n[whispers] Two", "One\n\nTwo"],
    [
      "leaves text without tags untouched",
      "  indented  code ",
      "  indented  code ",
    ],
  ])("%s", (_name, input, expected) => {
    expect(stripVoiceTags(input)).toBe(expected);
  });
});

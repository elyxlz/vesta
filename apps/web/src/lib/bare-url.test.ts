import { describe, expect, it } from "vitest";
import { splitTextIntoLinks, type MdastNode } from "./bare-url";

const text = (value: string): MdastNode => ({ type: "text", value });
const link = (raw: string): MdastNode => ({
  type: "link",
  url: `https://${raw}`,
  children: [{ type: "text", value: raw }],
});

describe("splitTextIntoLinks", () => {
  it.each<[string, string, MdastNode[]]>([
    [
      "links a bare domain with a path",
      "see linkedin.com/in/x",
      [text("see "), link("linkedin.com/in/x")],
    ],
    ["links a github path", "github.com/a/b", [link("github.com/a/b")]],
    ["leaves a code filename alone", "open index.ts", [text("open index.ts")]],
    [
      "does not match a listed TLD inside a longer one",
      "example.community",
      [text("example.community")],
    ],
    [
      "does not take the domain out of an email",
      "mail me@example.com",
      [text("mail me@example.com")],
    ],
    [
      "excludes a trailing closing paren from the path",
      "(see docs.vesta.dev/app)",
      [text("(see "), link("docs.vesta.dev/app"), text(")")],
    ],
    [
      "keeps text on both sides of the link",
      "go to example.com now",
      [text("go to "), link("example.com"), text(" now")],
    ],
    [
      "links the product's own domain",
      "see vesta.run",
      [text("see "), link("vesta.run")],
    ],
    [
      "leaves an unlisted TLD alone",
      "see example.community",
      [text("see example.community")],
    ],
    [
      "does not re-link a scheme-prefixed url's host",
      "https://example.com",
      [text("https://example.com")],
    ],
  ])("%s", (_name, input, expected) => {
    expect(splitTextIntoLinks(input)).toEqual(expected);
  });
});

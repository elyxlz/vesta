import { ChatBubble } from "@/components/Chat/ChatBubble";
import { Orb } from "@/components/Orb";
import { orbColors, type OrbVisualState } from "@/components/Orb/styles";
import type { VestaEvent } from "@/lib/types";

const states: OrbVisualState[] = [
  "alive",
  "thinking",
  "booting",
  "authenticating",
  "starting",
  "stopping",
  "deleting",
  "dead",
  "loading",
];

const ts = "2026-04-19T12:34:00Z";

const mockChat: { label: string; events: VestaEvent[] }[] = [
  {
    label: "plain text",
    events: [
      { type: "user", text: "hey, what's up?", ts },
      { type: "chat", text: "all good — you?", ts },
    ],
  },
  {
    label: "newlines",
    events: [
      {
        type: "user",
        text: "line one\nline two\nline three",
        ts,
      },
      {
        type: "chat",
        text: "paragraph one.\n\nparagraph two with a gap.",
        ts,
      },
    ],
  },
  {
    label: "links",
    events: [
      {
        type: "user",
        text: "check https://anthropic.com and https://github.com/elyxlz/vesta",
        ts,
      },
      {
        type: "chat",
        text: "see [the docs](https://docs.anthropic.com) for details",
        ts,
      },
    ],
  },
  {
    label: "inline formatting",
    events: [
      {
        type: "user",
        text: "use **bold**, *italic*, ~~strike~~, and `inline code`",
        ts,
      },
      {
        type: "chat",
        text: "got it — **bold**, *italic*, ~~strike~~, `code`",
        ts,
      },
    ],
  },
  {
    label: "code block",
    events: [
      {
        type: "user",
        text: "show me a snippet",
        ts,
      },
      {
        type: "chat",
        text: "```ts\nfunction add(a: number, b: number) {\n  return a + b;\n}\n```",
        ts,
      },
    ],
  },
  {
    label: "lists",
    events: [
      {
        type: "user",
        text: "what are the steps?",
        ts,
      },
      {
        type: "chat",
        text: "1. first\n2. second\n3. third\n\n- bullet a\n- bullet b\n- bullet c",
        ts,
      },
    ],
  },
  {
    label: "headings + quote",
    events: [
      {
        type: "chat",
        text: "# Heading\n## Subheading\n\n> a blockquote\n\n---\n\nafter the rule",
        ts,
      },
    ],
  },
  {
    label: "table",
    events: [
      {
        type: "chat",
        text: "| name | role |\n|------|------|\n| ada  | eng  |\n| bob  | pm   |",
        ts,
      },
    ],
  },
  {
    label: "task list",
    events: [
      {
        type: "chat",
        text: "- [x] done\n- [ ] todo\n- [ ] also todo",
        ts,
      },
    ],
  },
  {
    label: "long text wrapping",
    events: [
      {
        type: "user",
        text: "this is a very long message meant to demonstrate how the chat bubble wraps long lines of text without breaking the layout, especially when there are no spaces in averyveryverylongunbrokenwordlikethisonewhichshouldstillwrapsomehow",
        ts,
      },
    ],
  },
  {
    label: "error",
    events: [{ type: "error", text: "something broke", ts }],
  },
  {
    label: "tool call",
    events: [
      {
        type: "tool_start",
        tool: "Read",
        input: '{"path":"/tmp/foo.txt"}',
        ts,
      },
    ],
  },
];

export function Debug() {
  return (
    <div className="flex flex-1 flex-col gap-12 overflow-y-auto p-8">
      <section className="flex flex-col gap-6">
        <h1 className="text-lg font-medium text-foreground">orb states</h1>
        <div className="grid grid-cols-3 gap-8 max-sm:grid-cols-2">
          {states.map((state) => {
            const [c1, c2, c3] = orbColors[state];
            return (
              <div key={state} className="flex flex-col items-center gap-3">
                <div className="h-[120px] w-[120px]">
                  <Orb state={state} size={120} />
                </div>
                <span className="text-sm font-medium text-foreground">
                  {state}
                </span>
                <div className="flex gap-1.5">
                  {[c1, c2, c3].map((c) => (
                    <div
                      key={c}
                      className="h-4 w-4 rounded-full border border-border"
                      style={{ backgroundColor: c }}
                    />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <section className="flex flex-col gap-6">
        <h1 className="text-lg font-medium text-foreground">chat bubbles</h1>
        <div className="flex flex-col gap-6 max-w-2xl">
          {mockChat.map(({ label, events }) => (
            <div key={label} className="flex flex-col gap-2">
              <span className="text-xs uppercase tracking-wide text-muted-foreground">
                {label}
              </span>
              <div className="flex flex-col gap-1.5 rounded-lg border border-border p-3">
                {events.map((event, i) => (
                  <ChatBubble key={i} event={event} />
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

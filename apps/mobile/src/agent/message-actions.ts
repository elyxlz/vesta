export type MessageActionId =
  | "reply"
  | "copy"
  | "edit-resend"
  | "read-aloud"
  | "share";

export function messageActionIds({
  user,
  canSpeak,
}: {
  user: boolean;
  canSpeak: boolean;
}): MessageActionId[] {
  const actions: MessageActionId[] = ["reply", "copy"];
  if (user) {
    actions.push("edit-resend");
  } else if (canSpeak) {
    actions.push("read-aloud");
  }
  actions.push("share");
  return actions;
}

export function quotedReply(text: string): string {
  const trimmed = text.trim();
  if (!trimmed) return "";
  return `${trimmed
    .split("\n")
    .map((line) => `> ${line}`)
    .join("\n")}\n\n`;
}

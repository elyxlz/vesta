// Delivery directions such as "[laughs]" or "[calm, dry]" are written for the TTS voice, which
// performs them without saying them. They are noise on screen, so displayed agent text drops
// them. Only lowercase word lists match, never a markdown link label ("[label](url)"), a task
// checkbox ("[ ]", "[x]") or a citation ("[1]").
const VOICE_TAG = /[ \t]*\[[a-z][a-z' ,-]{1,48}\](?!\()[ \t]*/g;

export function stripVoiceTags(text: string): string {
  return text
    .split("\n")
    .map((line) => {
      const stripped = line.replace(VOICE_TAG, " ");
      return stripped === line
        ? line
        : stripped.replace(/^ +| +$/g, "").replace(/ {2,}/g, " ");
    })
    .join("\n");
}

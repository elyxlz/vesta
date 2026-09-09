// Whose voice services a conversation uses: one agent's own. A room with no single agent on the
// roster (a group, or a direct room whose agent the tree has not carried yet) has no target, and
// nothing asks the node about voice without one, since `/agents//voice/tts/status` names no agent.
export function voiceTargetName(name: string): string | null {
  return name.length > 0 ? name : null;
}

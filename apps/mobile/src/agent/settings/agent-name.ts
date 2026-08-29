const AGENT_NAME_MAX_LENGTH = 32;

// Mirrors vestad's normalize_name so the form can preview and validate the
// canonical name before starting the restart-backed rename operation.
export function normalizeAgentName(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[\s_]/gu, "-")
    .replace(/[^a-z0-9-]/g, "")
    .replace(/^-+|-+$/g, "")
    .replace(/-+/g, "-")
    .slice(0, AGENT_NAME_MAX_LENGTH)
    .replace(/-+$/g, "");
}

export function agentRenameError(
  currentName: string,
  proposedName: string,
): string | null {
  const normalized = normalizeAgentName(proposedName);
  if (!normalized) return "Enter a name.";
  if (normalized === currentName) return "Choose a different name.";
  if (normalized !== "vesta" && normalized.includes("vesta")) {
    return 'Names cannot contain "vesta".';
  }
  return null;
}

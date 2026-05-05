export const MEMORY_PATH = "/root/agent/MEMORY.md";
export const SKILLS_PREFIX = "/root/agent/skills/";
export const DREAMER_PREFIX = "/root/agent/dreamer/";

export function isSimpleAllowed(path: string): boolean {
  if (path === MEMORY_PATH) return true;
  if (path.startsWith(SKILLS_PREFIX) && path.endsWith(".md")) return true;
  return false;
}

export function friendlyLabel(path: string): string {
  if (path === MEMORY_PATH) return "MEMORY.md";
  if (path.startsWith(SKILLS_PREFIX)) {
    return path.slice(SKILLS_PREFIX.length).split("/").join(" / ");
  }
  if (path.startsWith(DREAMER_PREFIX)) {
    const fname = path.slice(DREAMER_PREFIX.length);
    const parsed = parseDreamFilename(fname);
    if (parsed) {
      const date = new Intl.DateTimeFormat(undefined, {
        year: "numeric",
        month: "long",
        day: "numeric",
      }).format(parsed);
      const time = new Intl.DateTimeFormat(undefined, {
        hour: "numeric",
        minute: "2-digit",
      }).format(parsed);
      return `dream · ${date} · ${time}`;
    }
    return `dream · ${fname}`;
  }
  return path;
}

export function collectDreamPaths(
  entries: { path: string; is_dir: boolean }[],
): string[] {
  return entries
    .filter(
      (e) =>
        !e.is_dir &&
        e.path.startsWith(DREAMER_PREFIX) &&
        e.path.endsWith(".md") &&
        !e.path.slice(DREAMER_PREFIX.length).includes("/"),
    )
    .map((e) => e.path);
}

export function parseDreamFilename(fname: string): Date | null {
  const m = fname.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2})(\d{2})\.md$/);
  if (!m) return null;
  const [, y, mo, d, h, mi] = m;
  const date = new Date(
    Number(y),
    Number(mo) - 1,
    Number(d),
    Number(h),
    Number(mi),
  );
  return Number.isNaN(date.getTime()) ? null : date;
}

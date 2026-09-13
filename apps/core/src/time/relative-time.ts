// How long ago a conversation last spoke, in the coarse steps a list needs: anything older than a
// week reads better as a date than as a count of days. One wording for every client, so the same
// room reads the same on a phone and on a desktop.
export function relativeTime(epochSeconds: number, now = Date.now()): string {
  const mins = Math.floor((now - epochSeconds * 1000) / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${String(mins)}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${String(hours)}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${String(days)}d ago`;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
  }).format(epochSeconds * 1000);
}

// How long ago a conversation last spoke, in the coarse steps a list needs: anything older than a
// week reads better as a date than as a count of days.
export function relativeTime(epochSeconds: number, now = Date.now()): string {
  const mins = Math.floor((now - epochSeconds * 1000) / 60_000);
  if (mins < 1) return "now";
  if (mins < 60) return `${String(mins)}m`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${String(hours)}h`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${String(days)}d`;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
  }).format(epochSeconds * 1000);
}
